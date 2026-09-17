"""Runner de referencia. Solo los slots del controlador actualizan widgets."""
from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot

class Cancelado(Exception): pass

class Trabajo(QThread):
    progreso = pyqtSignal(int,str)
    resultado = pyqtSignal(object)
    error = pyqtSignal(str)
    cancelado = pyqtSignal()
    def __init__(self, operacion, parent=None):
        super().__init__(parent)
        self.operacion=operacion
    def comprobar_cancelacion(self):
        if self.isInterruptionRequested(): raise Cancelado()
    def run(self):
        try:
            # La operación crea y cierra sus conexiones en este hilo.
            value=self.operacion(self.progreso.emit,self.comprobar_cancelacion)
            self.resultado.emit(value)
        except Cancelado:
            self.cancelado.emit()
        except Exception:
            # El servicio debe guardar un código de diagnóstico, sin secretos.
            self.error.emit('La operación falló. Revisá la configuración y el registro de diagnóstico.')

class ControladorTrabajo(QObject):
    progreso = pyqtSignal(int,str)
    resultado = pyqtSignal(object)
    error = pyqtSignal(str)
    cancelado = pyqtSignal()
    ocupado = pyqtSignal(bool)
    def __init__(self,parent=None):
        super().__init__(parent)
        self._trabajo=None
    def iniciar(self,operacion):
        if self._trabajo is not None: raise RuntimeError('Ya hay una operación en curso.')
        worker=Trabajo(operacion,self)
        self._trabajo=worker
        worker.progreso.connect(self.progreso)
        worker.resultado.connect(self.resultado)
        worker.error.connect(self.error)
        worker.cancelado.connect(self.cancelado)
        worker.finished.connect(self._terminado)
        self.ocupado.emit(True)
        worker.start()
    def cancelar(self):
        if self._trabajo is not None: self._trabajo.requestInterruption()
    def esta_ocupado(self): return self._trabajo is not None
    @pyqtSlot()
    def _terminado(self):
        worker=self._trabajo
        self._trabajo=None
        worker.deleteLater()
        self.ocupado.emit(False)

# closeEvent: si esta_ocupado(), solicitar cancelación e ignorar el cierre hasta
# recibir ocupado(False). Nunca destruir QThread mientras siga ejecutándose.
# Cancelación cooperativa: no puede interrumpir una llamada DBAPI en curso;
# debe haber timeouts por driver. No usar terminate() ni processEvents() en bucles.
