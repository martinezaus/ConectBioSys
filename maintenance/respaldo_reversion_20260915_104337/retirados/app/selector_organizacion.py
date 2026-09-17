"""Selector que mantiene Excel disponible mientras consulta la base externa."""
from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal as Signal, pyqtSlot as Slot
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QLabel, QPushButton
from app.api.organizaciones import obtener_organizaciones
from resources.config_path import cargar_config_conexion


class _Resultado(QObject):
    listo = Signal(object, str)


class _Carga(QRunnable):
    def __init__(self, config):
        super().__init__()
        self.config = dict(config)
        self.conexion = dict(cargar_config_conexion())
        self.resultado = _Resultado()

    def run(self):
        try:
            self.resultado.listo.emit(obtener_organizaciones(self.config, self.conexion), "")
        except Exception:
            self.resultado.listo.emit([], "No se pudo consultar la base externa. Podés exportar a Excel o volver a intentar.")


class SelectorOrganizacion(QWidget):
    seleccion_cambiada = Signal()

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = dict(config) if config else None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        fila = QHBoxLayout()
        fila.addWidget(QLabel("Organización:"))
        self.combo = QComboBox()
        self.combo.addItem("Solo Excel / organización no registrada", None)
        fila.addWidget(self.combo, 1)
        self.actualizar = QPushButton("Actualizar organizaciones")
        fila.addWidget(self.actualizar)
        layout.addLayout(fila)
        self.estado = QLabel()
        self.estado.setWordWrap(True)
        layout.addWidget(self.estado)
        self.combo.currentIndexChanged.connect(lambda index: self.seleccion_cambiada.emit())
        self.actualizar.clicked.connect(self.cargar)
        self.cargar()

    def cargar(self):
        self.combo.clear()
        self.combo.addItem("Solo Excel / organización no registrada", None)
        self.combo.setEnabled(False)
        if self.config is None:
            self.estado.setText("Este cliente trabaja solo con Excel. Podés activar una integración en Cliente e integración.")
            self.actualizar.setEnabled(False)
            return
        self.estado.setText("Consultando organizaciones… Excel está disponible.")
        self.actualizar.setEnabled(False)
        try:
            self._carga = _Carga(self.config)
        except Exception:
            self._recibir([], "No se pudo leer la configuración externa. Excel está disponible.")
            return
        self._carga.resultado.listo.connect(self._recibir)
        QThreadPool.globalInstance().start(self._carga)

    @Slot(object, str)
    def _recibir(self, organizaciones, error):
        for clave, nombre in organizaciones:
            self.combo.addItem(f"{nombre} (ID {clave})", clave)
        self.combo.setEnabled(bool(organizaciones))
        self.actualizar.setEnabled(True)
        self.estado.setText(error or ("Seleccioná la organización de estas marcaciones para habilitar el envío." if organizaciones else "No hay organizaciones registradas. Podés exportar a Excel."))
        self.seleccion_cambiada.emit()

    def configuracion_seleccionada(self):
        clave = self.combo.currentData()
        if clave == '__unica__' and self.config is not None and self.config.get('modo_organizacion') == 'unica':
            return dict(self.config)
        if clave is None or self.config is None or not self.config.get('columna_organizacion'):
            return None
        return dict(self.config, valor_organizacion=str(clave))

    def nombre_seleccionado(self):
        return self.combo.currentText()
