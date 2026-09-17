"""Ejecución de una operación de E/S fuera del hilo de los widgets."""
from PySide6.QtCore import QObject, QThread, Signal, Slot


class _Trabajo(QThread):
    progreso = Signal(int, str)

    def __init__(self, operacion, parent):
        super().__init__(parent)
        self.operacion = operacion
        self.valor = None
        self.error = None

    def run(self):
        try:
            self.valor = self.operacion(self.progreso.emit)
        except Exception as exc:
            self.error = f'{type(exc).__name__}: no se pudo completar la operación. Revisá la conexión, los permisos y la configuración.'


class GestorTareas(QObject):
    progreso = Signal(int, str)
    ocupado = Signal(bool)
    resultado = Signal(object)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._trabajo = None

    def en_curso(self):
        return self._trabajo is not None

    def iniciar(self, operacion):
        if self.en_curso():
            return False
        trabajo = _Trabajo(operacion, self)
        self._trabajo = trabajo
        trabajo.progreso.connect(self.progreso)
        trabajo.finished.connect(self._terminado)
        self.ocupado.emit(True)
        trabajo.start()
        return True

    @Slot()
    def _terminado(self):
        trabajo = self._trabajo
        valor, error = trabajo.valor, trabajo.error
        self._trabajo = None
        trabajo.deleteLater()
        self.ocupado.emit(False)
        if error:
            self.error.emit(error)
        else:
            self.resultado.emit(valor)
