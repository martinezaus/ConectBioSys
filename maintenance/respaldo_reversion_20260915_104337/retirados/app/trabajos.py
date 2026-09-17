"""Controlador de trabajos. Las señales se entregan en el hilo de la UI."""
from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot
class Cancelado(Exception): pass
class Trabajo(QThread):
    progreso = pyqtSignal(int, str)
    resultado = pyqtSignal(object)
    error = pyqtSignal(str)
    def __init__(self, operacion, parent=None):
        super().__init__(parent)
        self.operacion = operacion
    def comprobar(self):
        if self.isInterruptionRequested(): raise Cancelado('Operación cancelada.')
    def run(self):
        try: self.resultado.emit(self.operacion(self.progreso.emit, self.comprobar))
        except Cancelado: self.error.emit('Operación cancelada.')
        except Exception as exc:
            # No mostrar DBAPI/SQL/credenciales en mensajes públicos.
            self.error.emit(f'No se pudo completar la operación ({type(exc).__name__}). Revisá la conexión, los permisos y el mapeo configurado.')
class ControladorTrabajo(QObject):
    progreso = pyqtSignal(int, str)
    resultado = pyqtSignal(object)
    error = pyqtSignal(str)
    ocupado = pyqtSignal(bool)
    def __init__(self,parent=None):
        super().__init__(parent)
        self._trabajo=None
        self._resultado=None
        self._error=None
    def iniciar(self,operacion):
        if self.esta_ocupado(): raise RuntimeError('Ya hay una operación en curso.')
        self._resultado=None; self._error=None
        self._trabajo=Trabajo(operacion,self)
        self._trabajo.progreso.connect(self.progreso)
        self._trabajo.resultado.connect(self._recibir)
        self._trabajo.error.connect(self._fallo)
        self._trabajo.finished.connect(self._terminado)
        self.ocupado.emit(True)
        self._trabajo.start()
    @pyqtSlot(object)
    def _recibir(self,resultado): self._resultado=resultado
    @pyqtSlot(str)
    def _fallo(self,error): self._error=error
    @pyqtSlot()
    def _terminado(self):
        trabajo=self._trabajo; self._trabajo=None
        trabajo.deleteLater()
        self.ocupado.emit(False)
        if self._error: self.error.emit(self._error)
        else: self.resultado.emit(self._resultado)
    def esta_ocupado(self): return self._trabajo is not None
    def cancelar(self):
        if self._trabajo: self._trabajo.requestInterruption()
