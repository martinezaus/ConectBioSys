from pathlib import Path
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QLineEdit, QCheckBox,
    QPlainTextEdit, QDialogButtonBox, QLabel, QPushButton, QFileDialog, QMessageBox)
from app.perfiles import perfil_actual, configurar_perfil
from app.licencias import estado_licencia, crear_solicitud, instalar_licencia, registrar_primera_activacion, instalar_codigo

class PerfilDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Cliente e integración')
        self.resize(500, 220)
        perfil = perfil_actual()
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.nombre = QLineEdit(perfil['nombre'])
        self.integracion = QCheckBox('Usar un sistema externo de administración del personal')
        self.integracion.setChecked(perfil['integracion'])
        form.addRow('Cliente:', self.nombre)
        form.addRow(self.integracion)
        layout.addLayout(form)
        aviso = QLabel('Sin integración, solo necesitás configurar los relojes y activar la licencia. Podés descargar y exportar a Excel. Cada cliente tiene sus propios relojes y marcaciones.')
        aviso.setWordWrap(True)
        layout.addWidget(aviso)
        botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        botones.accepted.connect(self.guardar)
        botones.rejected.connect(self.reject)
        layout.addWidget(botones)
    def guardar(self):
        try:
            configurar_perfil(self.nombre.text(), self.integracion.isChecked())
            self.accept()
        except Exception as exc:
            QMessageBox.warning(self, 'Configuración', str(exc))

class LicenciaDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Activación y renovación anual')
        self.resize(540, 260)
        layout = QVBoxLayout(self)
        self.estado = QLabel()
        self.estado.setWordWrap(True)
        layout.addWidget(self.estado)
        self.cliente = QLineEdit(perfil_actual()['nombre'])
        form = QFormLayout()
        form.addRow('Titular de la licencia:', self.cliente)
        layout.addLayout(form)
        activar = QPushButton('Registrar primera activación: 1 año')
        self.boton_registrar = activar
        activar.clicked.connect(self.registrar)
        layout.addWidget(activar)
        self.codigo = QPlainTextEdit()
        self.codigo.setPlaceholderText('Pegá el código de extensión recibido del proveedor')
        self.codigo.setMaximumHeight(80)
        layout.addWidget(self.codigo)
        extender = QPushButton('Aplicar código de extensión')
        extender.clicked.connect(self.extender)
        layout.addWidget(extender)
        texto = QLabel('Para renovar: guardá la solicitud y enviala al proveedor.\nDespués de abonar, importá el archivo o pegá el código recibido.\nLa renovación se realiza importando un nuevo archivo anual.')
        texto.setWordWrap(True)
        layout.addWidget(texto)
        solicitud = QPushButton('Guardar solicitud de licencia')
        solicitud.clicked.connect(self.solicitar)
        layout.addWidget(solicitud)
        importar = QPushButton('Importar licencia o renovación')
        importar.clicked.connect(self.importar)
        layout.addWidget(importar)
        cerrar = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        cerrar.button(QDialogButtonBox.StandardButton.Close).setText('Cerrar')
        cerrar.rejected.connect(self.reject)
        layout.addWidget(cerrar)
        self.actualizar()
    def actualizar(self):
        valida, mensaje, payload = estado_licencia()
        self.estado.setText(mensaje)
        self.estado.setStyleSheet('color: #176b31;' if valida else 'color: #9c310d;')
        self.boton_registrar.setEnabled(payload is None)
    def solicitar(self):
        ruta, _ = QFileDialog.getSaveFileName(self, 'Guardar solicitud', 'solicitud.cbsreq', 'Solicitud ConectBioSync (*.cbsreq)')
        if not ruta: return
        try:
            Path(ruta).write_bytes(crear_solicitud(self.cliente.text()))
            QMessageBox.information(self, 'Solicitud guardada', 'Enviá este archivo al proveedor para recibir tu licencia anual.')
        except Exception as exc:
            QMessageBox.warning(self, 'Solicitud', str(exc))
    def importar(self):
        ruta, _ = QFileDialog.getOpenFileName(self, 'Importar licencia', '', 'Licencia ConectBioSync (*.cbslic)')
        if not ruta: return
        try:
            payload = instalar_licencia(ruta)
            self.actualizar()
            QMessageBox.information(self, 'Licencia importada', f"{'Renovación programada' if payload.get('programada') else 'Licencia activada'}. Vencimiento: {payload['vencimiento'][:10]}.")
        except Exception as exc:
            QMessageBox.warning(self, 'No se pudo activar', str(exc))

    def registrar(self):
        try:
            registrar_primera_activacion(self.cliente.text())
            self.actualizar()
        except Exception as exc: QMessageBox.warning(self, 'Registro', str(exc))
    def extender(self):
        try:
            instalar_codigo(self.codigo.toPlainText())
            self.codigo.clear()
            self.actualizar()
        except Exception as exc: QMessageBox.warning(self, 'Extensión', str(exc))
