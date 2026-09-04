import os
import importlib

from PySide6.QtWidgets import (
	QWidget,
	QVBoxLayout,
	QPushButton,
	QHBoxLayout,
	QMessageBox,
	QLineEdit,
	QDialog,
	QDialogButtonBox,
	QTableWidget,
	QTableWidgetItem,
	QCheckBox,
	QLabel,
	QComboBox,
	QFormLayout,
)

# Campos que necesita cada tipo de reloj: (nombre, tipo_de_dato, valor_por_defecto)
# Si agregás un adaptador nuevo, sumalo acá y el formulario lo va a mostrar solo.
CAMPOS_POR_TIPO = {
	"zkteco": [
		("ip", str, ""),
		("dispositivo_id", str, ""),
		("puerto", int, 4370),
		("force_udp", bool, True),
	],
	"hikvision": [
		("ip", str, ""),
		("dispositivo_id", str, ""),
		("usuario", str, "admin"),
		("password", str, ""),
		("usar_https", bool, False),
	],
}




def generar_config_relojes(relojes):
	"""Genera el texto de resources/config_relojes.py a partir de la lista de
	relojes (misma estructura que RELOJES: lista de {"tipo", "params"})."""
	lineas = [
		'"""',
		"Configuración de los relojes biométricos a conectar.",
		"",
		'Este archivo se genera automáticamente desde la pantalla "Configurar',
		'relojes" de la app. También podés editarlo a mano si preferís: cada',
		'entrada es un diccionario con "tipo" ("hikvision" o "zkteco") y los',
		"parámetros que necesita el __init__ del adaptador correspondiente.",
		'"""',
		"RELOJES = [",
	]
	for reloj in relojes:
		lineas.append("\t{")
		lineas.append(f'\t\t"tipo": {reloj["tipo"]!r},')
		lineas.append('\t\t"params": {')
		for clave, valor in reloj["params"].items():
			lineas.append(f"\t\t\t{clave!r}: {valor!r},")
		lineas.append("\t\t},")
		lineas.append("\t},")
	lineas.append("]")
	lineas.append("")
	return "\n".join(lineas)

class RelojFormDialog(QDialog):
	"""Formulario para dar de alta o editar un reloj. Los campos que se
	muestran dependen del tipo elegido (ver CAMPOS_POR_TIPO)."""

	def __init__(self, reloj=None, parent=None):
		super().__init__(parent)
		self.setWindowTitle("Reloj biométrico")
		self.resize(400, 250)
		self._campos_widgets = {}
		self._reloj_resultado = None

		layout = QVBoxLayout(self)

		fila_tipo = QHBoxLayout()
		fila_tipo.addWidget(QLabel("Tipo de reloj:"))
		self.combo_tipo = QComboBox()
		self.combo_tipo.addItems(list(CAMPOS_POR_TIPO.keys()))
		fila_tipo.addWidget(self.combo_tipo)
		layout.addLayout(fila_tipo)

		self.formulario_widget = QWidget()
		self.formulario_layout = QFormLayout()
		self.formulario_widget.setLayout(self.formulario_layout)
		layout.addWidget(self.formulario_widget)

		self.combo_tipo.currentTextChanged.connect(self._reconstruir_formulario)

		botones = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
		botones.accepted.connect(self._confirmar)
		botones.rejected.connect(self.reject)
		layout.addWidget(botones)

		if reloj:
			self.combo_tipo.setCurrentText(reloj["tipo"])
			self._reconstruir_formulario(reloj["tipo"], valores_iniciales=reloj["params"])
		else:
			self._reconstruir_formulario(self.combo_tipo.currentText())

	def _reconstruir_formulario(self, tipo, valores_iniciales=None):
		while self.formulario_layout.rowCount():
			self.formulario_layout.removeRow(0)
		self._campos_widgets = {}

		valores_iniciales = valores_iniciales or {}
		for nombre, tipo_dato, valor_por_defecto in CAMPOS_POR_TIPO[tipo]:
			valor = valores_iniciales.get(nombre, valor_por_defecto)
			if tipo_dato is bool:
				widget = QCheckBox()
				widget.setChecked(bool(valor))
			else:
				widget = QLineEdit()
				widget.setText(str(valor) if valor is not None else "")
			self.formulario_layout.addRow(nombre, widget)
			self._campos_widgets[nombre] = (widget, tipo_dato)

	def _confirmar(self):
		tipo = self.combo_tipo.currentText()
		params = {}
		for nombre, (widget, tipo_dato) in self._campos_widgets.items():
			if tipo_dato is bool:
				params[nombre] = widget.isChecked()
			elif tipo_dato is int:
				texto = widget.text().strip()
				if not texto.isdigit():
					QMessageBox.warning(self, "Dato inválido", f"'{nombre}' tiene que ser un número.")
					return
				params[nombre] = int(texto)
			else:
				texto = widget.text().strip()
				if not texto and nombre in ("ip", "dispositivo_id"):
					QMessageBox.warning(self, "Dato requerido", f"'{nombre}' es obligatorio.")
					return
				params[nombre] = texto

		self._reloj_resultado = {"tipo": tipo, "params": params}
		self.accept()

	def obtener_reloj(self):
		return self._reloj_resultado


class ConfiguracionRelojesDialog(QDialog):
	"""Pantalla para administrar la lista de relojes: agregar, editar,
	eliminar y guardar los cambios en resources/config_relojes.py."""

	def __init__(self, parent=None):
		super().__init__(parent)
		self.setWindowTitle("Configuración de relojes biométricos")
		self.resize(650, 400)
		self.relojes = self._cargar_relojes_actuales()

		layout = QVBoxLayout(self)
		layout.addWidget(QLabel("Relojes configurados. Agregá, editá o eliminá los que necesites."))

		self.tabla = QTableWidget()
		self.tabla.setColumnCount(4)
		self.tabla.setHorizontalHeaderLabels(["Tipo", "ID dispositivo", "IP", "Otros parámetros"])
		self.tabla.setEditTriggers(QTableWidget.NoEditTriggers)
		self.tabla.setSelectionBehavior(QTableWidget.SelectRows)
		layout.addWidget(self.tabla)
		self._refrescar_tabla()

		fila_botones = QHBoxLayout()
		self.boton_agregar = QPushButton("Agregar reloj")
		self.boton_editar = QPushButton("Editar")
		self.boton_eliminar = QPushButton("Eliminar")
		fila_botones.addWidget(self.boton_agregar)
		fila_botones.addWidget(self.boton_editar)
		fila_botones.addWidget(self.boton_eliminar)
		fila_botones.addStretch()
		layout.addLayout(fila_botones)

		self.boton_agregar.clicked.connect(self._agregar)
		self.boton_editar.clicked.connect(self._editar)
		self.boton_eliminar.clicked.connect(self._eliminar)

		botones = QDialogButtonBox()
		self.boton_guardar = botones.addButton("Guardar", QDialogButtonBox.AcceptRole)
		self.boton_cancelar = botones.addButton("Cancelar", QDialogButtonBox.RejectRole)
		botones.accepted.connect(self._guardar)
		botones.rejected.connect(self.reject)
		layout.addWidget(botones)

	def _cargar_relojes_actuales(self):
		try:
			import resources.config_relojes as modulo_config
			importlib.reload(modulo_config)
			return [dict(tipo=r["tipo"], params=dict(r["params"])) for r in modulo_config.RELOJES]
		except Exception:
			return []

	def _refrescar_tabla(self):
		self.tabla.setRowCount(len(self.relojes))
		for fila_idx, reloj in enumerate(self.relojes):
			params = reloj["params"]
			otros = ", ".join(
				f"{clave}={valor}" for clave, valor in params.items()
				if clave not in ("ip", "dispositivo_id")
			)
			self.tabla.setItem(fila_idx, 0, QTableWidgetItem(reloj["tipo"]))
			self.tabla.setItem(fila_idx, 1, QTableWidgetItem(str(params.get("dispositivo_id", ""))))
			self.tabla.setItem(fila_idx, 2, QTableWidgetItem(str(params.get("ip", ""))))
			self.tabla.setItem(fila_idx, 3, QTableWidgetItem(otros))
		self.tabla.resizeColumnsToContents()

	def _agregar(self):
		dialogo = RelojFormDialog(parent=self)
		if dialogo.exec() == QDialog.Accepted:
			self.relojes.append(dialogo.obtener_reloj())
			self._refrescar_tabla()

	def _editar(self):
		fila = self.tabla.currentRow()
		if fila < 0:
			QMessageBox.information(self, "Editar", "Seleccioná un reloj de la lista.")
			return
		dialogo = RelojFormDialog(reloj=self.relojes[fila], parent=self)
		if dialogo.exec() == QDialog.Accepted:
			self.relojes[fila] = dialogo.obtener_reloj()
			self._refrescar_tabla()

	def _eliminar(self):
		fila = self.tabla.currentRow()
		if fila < 0:
			QMessageBox.information(self, "Eliminar", "Seleccioná un reloj de la lista.")
			return
		reloj = self.relojes[fila]
		resp = QMessageBox.question(
			self, "Eliminar reloj",
			f"¿Eliminar el reloj {reloj['params'].get('dispositivo_id', '?')}?"
		)
		if resp == QMessageBox.Yes:
			del self.relojes[fila]
			self._refrescar_tabla()

	def _guardar(self):
		if not self.relojes:
			resp = QMessageBox.question(
				self, "Guardar sin relojes",
				"No hay relojes configurados. ¿Guardar igual una lista vacía?"
			)
			if resp != QMessageBox.Yes:
				return

		ids = [reloj["params"].get("dispositivo_id") for reloj in self.relojes]
		if len(ids) != len(set(ids)):
			QMessageBox.warning(
				self, "IDs repetidos",
				"Hay dos o más relojes con el mismo 'ID dispositivo'. Corregilo antes de guardar."
			)
			return

		try:
			ruta = self._ruta_config()
			contenido = generar_config_relojes(self.relojes)
			with open(ruta, "w", encoding="utf-8") as archivo:
				archivo.write(contenido)
		except Exception as e:
			QMessageBox.critical(self, "Error al guardar", f"No se pudo guardar la configuración:\n{e}")
			return

		self.accept()

	def _ruta_config(self):
		import resources.config_relojes as modulo_config
		return os.path.abspath(modulo_config.__file__)
