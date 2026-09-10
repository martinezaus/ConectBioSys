import datetime
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
	QInputDialog,
	QApplication,
	QDateEdit,
)

from PySide6.QtCore import QDate

from resources.config_path import (
	cargar_config_conexion,
	guardar_config_conexion,
	crear_engine_externo,
	cargar_config_empleados,
	guardar_config_empleados,
	cargar_config_asistencias,
	guardar_config_asistencias,
	cargar_relojes,
	get_config_relojes_path,
	crear_adaptador,
)
from resources.db_engines import ENGINES

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
		self.boton_limpiar_buffer = QPushButton("Limpiar buffer")

		fila_botones.addWidget(self.boton_agregar)
		fila_botones.addWidget(self.boton_editar)
		fila_botones.addWidget(self.boton_eliminar)
		fila_botones.addWidget(self.boton_limpiar_buffer)
		fila_botones.addStretch()
		layout.addLayout(fila_botones)

		self.boton_agregar.clicked.connect(self._agregar)
		self.boton_editar.clicked.connect(self._editar)
		self.boton_eliminar.clicked.connect(self._eliminar)
		self.boton_limpiar_buffer.clicked.connect(self.limpiar_buffer_relojes)
		self.boton_limpiar_buffer.setStyleSheet(
			"QPushButton { background-color: #c0392b; color: white; font-weight: bold; }"
			"QPushButton:hover { background-color: #a93226; }"
			"QPushButton:disabled { background-color: #7f8c8d; color: #dcdcdc; }"
		)

		self.boton_config_conexion = QPushButton("Configurar conexión a base de datos")
		self.boton_config_tabla_empleados = QPushButton("Configurar tabla de empleados")
		self.boton_config_tabla_asistencias = QPushButton("Configurar tabla de asistencias")
		layout.addWidget(self.boton_config_conexion)
		layout.addWidget(self.boton_config_tabla_empleados)
		layout.addWidget(self.boton_config_tabla_asistencias)

		self.boton_config_conexion.clicked.connect(self._abrir_config_conexion)
		self.boton_config_tabla_empleados.clicked.connect(self._abrir_config_tabla_empleados)
		self.boton_config_tabla_asistencias.clicked.connect(self._abrir_config_tabla_asistencias)

	def _cargar_relojes_actuales(self):
		try:
			return [dict(tipo=r["tipo"], params=dict(r["params"])) for r in cargar_relojes()]
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
			if self._guardar():
				self._refrescar_tabla()
			else:
				self.relojes.pop()

	def _editar(self):
		fila = self.tabla.currentRow()
		if fila < 0:
			QMessageBox.information(self, "Editar", "Seleccioná un reloj de la lista.")
			return
		reloj_anterior = self.relojes[fila]
		dialogo = RelojFormDialog(reloj=reloj_anterior, parent=self)
		if dialogo.exec() == QDialog.Accepted:
			self.relojes[fila] = dialogo.obtener_reloj()
			if self._guardar():
				self._refrescar_tabla()
			else:
				self.relojes[fila] = reloj_anterior

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
			if self._guardar():
				self._refrescar_tabla()
			else:
				self.relojes.insert(fila, reloj)

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

		return True

	def _ruta_config(self):
		return get_config_relojes_path()	

	def closeEvent(self, event):
		"""Cada alta/edición/baja se guarda al toque, así que no hay cambios
		pendientes que se puedan perder al cerrar: se cierra directamente."""
		self.accept()
		event.accept()

	def limpiar_buffer_relojes(self):
		""" Borra la memoria de marcaciones de cada reloj SIN descargarlas ni
		guardarlas antes. Operación irreversible. """

		aviso = QMessageBox(self)
		aviso.setIcon(QMessageBox.Warning)
		aviso.setWindowTitle("⚠ Limpiar buffer de relojes")
		aviso.setText("Esta acción va a BORRAR todas las marcaciones almacenadas en la "
					"memoria de cada reloj configurado, SIN descargarlas ni guardarlas "
					"primero.\n\nCualquier marcación que no hayas sincronizado antes se "
					"va a perder DEFINITIVAMENTE.\n\n¿Estás seguro de que querés continuar?"
		)
		aviso.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
		aviso.setDefaultButton(QMessageBox.Cancel)
		if aviso.exec() != QMessageBox.Yes:
			return
		
		texto, ok = QInputDialog.getText(
			self, "Confirmación final", "Para confirmar, escribí BORRAR (en mayúsculas) y aceptá:"
		)

		if not ok or texto.strip() != "BORRAR":
			return
		
		self.boton_limpiar_buffer.setEnabled(False)
		QApplication.processEvents()
		relojes_guardados = cargar_relojes()
		resultados = []
		for config_reloj in relojes_guardados:
			dispositivo_id = config_reloj["params"].get("dispositivo_id", "?")
			try:
				adapter = crear_adaptador(config_reloj)
			except ValueError as e:
				resultados.append(f"[{dispositivo_id}] Error de configuración: {e}")
				continue

			if not hasattr(adapter, "limpiar_buffer"):
				resultados.append(f"[{dispositivo_id}] No soporta limpiar buffer. Se omite.")
				continue

			if not adapter.conectar():
				resultados.append(f"[{dispositivo_id}] No se pudo conectar. Se omite.")
				continue

			try:
				adapter.limpiar_buffer()
				resultados.append(f"[{dispositivo_id}] Buffer limpiado correctamente.")
			except Exception as e:
				resultados.append(f"[{dispositivo_id}] Error al limpiar buffer: {e}")
			finally:
				adapter.desconectar()

		self.boton_limpiar_buffer.setEnabled(True)
		QMessageBox.information(self, "Limpieza finalizada", "\n".join(resultados) or "No hay relojes configurados.")

	def _abrir_config_conexion(self):
		ConfiguracionConexionDialog(parent=self).exec()

	def _abrir_config_tabla_empleados(self):
		ConfiguracionTablaEmpleadosDialog(parent=self).exec()

	def _abrir_config_tabla_asistencias(self):
		ConfiguracionTablaAsistenciasDialog(parent=self).exec()

class RangoFechasDialog(QDialog):
	"""Pide un rango 'desde'/'hasta' antes de exportar, para no traer
	todo el histórico de una sola vez."""

	def __init__(self, parent=None):
		super().__init__(parent)
		self.setWindowTitle("Elegir rango de fechas")

		layout = QVBoxLayout(self)
		layout.addWidget(QLabel("Elegí el rango de marcaciones a exportar:"))

		form = QFormLayout()
		hoy = QDate.currentDate()

		self.fecha_desde = QDateEdit(calendarPopup=True)
		self.fecha_desde.setDisplayFormat("yyyy-MM-dd")
		self.fecha_desde.setDate(hoy.addMonths(-1))

		self.fecha_hasta = QDateEdit(calendarPopup=True)
		self.fecha_hasta.setDisplayFormat("yyyy-MM-dd")
		self.fecha_hasta.setDate(hoy)

		form.addRow("Desde:", self.fecha_desde)
		form.addRow("Hasta:", self.fecha_hasta)
		layout.addLayout(form)

		botones = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
		botones.accepted.connect(self._validar)
		botones.rejected.connect(self.reject)
		layout.addWidget(botones)

	def _validar(self):
		if self.fecha_desde.date() > self.fecha_hasta.date():
			QMessageBox.warning(self, "Rango inválido", "'Desde' no puede ser posterior a 'Hasta'.")
			return
		self.accept()

	def obtener_rango(self):
		return (
			self.fecha_desde.date().toString("yyyy-MM-dd"),
			self.fecha_hasta.date().toString("yyyy-MM-dd"),
		)	

class ConfiguracionConexionDialog(QDialog):
	"""Elige el motor de base de datos y sus datos de conexión. Esta config
	es compartida entre la lectura de empleados y el envío de asistencias."""

	def __init__(self, parent=None):
		super().__init__(parent)
		self.setWindowTitle("Configurar conexión a base de datos")
		self.resize(420, 320)

		config_actual = cargar_config_conexion()

		layout = QVBoxLayout(self)
		form = QFormLayout()

		self.combo_motor = QComboBox()
		for clave, info in ENGINES.items():
			self.combo_motor.addItem(info["label"], clave)
		idx = self.combo_motor.findData(config_actual.get("motor", "mysql"))
		if idx >= 0:
			self.combo_motor.setCurrentIndex(idx)
		form.addRow("Motor:", self.combo_motor)

		self.campo_host = QLineEdit(config_actual.get("host", ""))
		self.campo_puerto = QLineEdit(str(config_actual.get("puerto") or ""))
		self.campo_usuario = QLineEdit(config_actual.get("usuario", ""))
		self.campo_password = QLineEdit(config_actual.get("password", ""))
		self.campo_password.setEchoMode(QLineEdit.Password)
		self.campo_base_datos = QLineEdit(config_actual.get("base_datos", ""))
		self.campo_archivo_sqlite = QLineEdit(config_actual.get("archivo_sqlite", ""))

		self.fila_host = form.addRow("Host / IP:", self.campo_host)
		self.fila_puerto = form.addRow("Puerto:", self.campo_puerto)
		self.fila_usuario = form.addRow("Usuario:", self.campo_usuario)
		self.fila_password = form.addRow("Contraseña:", self.campo_password)
		self.fila_base_datos = form.addRow("Base de datos:", self.campo_base_datos)
		self.fila_archivo = form.addRow("Archivo SQLite:", self.campo_archivo_sqlite)

		layout.addLayout(form)

		self.combo_motor.currentIndexChanged.connect(self._actualizar_campos_visibles)
		self._actualizar_campos_visibles()

		fila_botones = QHBoxLayout()
		self.boton_probar = QPushButton("Probar conexión")
		fila_botones.addWidget(self.boton_probar)
		fila_botones.addStretch()
		layout.addLayout(fila_botones)
		self.boton_probar.clicked.connect(self._probar_conexion)

		botones = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
		botones.accepted.connect(self._guardar)
		botones.rejected.connect(self.reject)
		layout.addWidget(botones)

	def _motor_actual(self):
		return self.combo_motor.currentData()

	def _actualizar_campos_visibles(self):
		info = ENGINES[self._motor_actual()]
		es_sqlite = info["requiere_archivo"]

		for widget in (self.campo_host, self.campo_puerto, self.campo_usuario,
					   self.campo_password, self.campo_base_datos):
			widget.setVisible(not es_sqlite)
		self.campo_archivo_sqlite.setVisible(es_sqlite)

		if not es_sqlite and not self.campo_puerto.text():
			self.campo_puerto.setText(str(info["puerto_default"]))

	def _armar_config(self):
		motor = self._motor_actual()
		info = ENGINES[motor]
		if info["requiere_archivo"]:
			if not self.campo_archivo_sqlite.text().strip():
				QMessageBox.warning(self, "Dato requerido", "Indicá la ruta del archivo SQLite.")
				return None
			return {
				"motor": motor, "host": "", "puerto": None, "usuario": "",
				"password": "", "base_datos": "",
				"archivo_sqlite": self.campo_archivo_sqlite.text().strip(),
			}

		puerto_texto = self.campo_puerto.text().strip()
		if not puerto_texto.isdigit():
			QMessageBox.warning(self, "Dato inválido", "El puerto tiene que ser un número.")
			return None
		return {
			"motor": motor,
			"host": self.campo_host.text().strip(),
			"puerto": int(puerto_texto),
			"usuario": self.campo_usuario.text().strip(),
			"password": self.campo_password.text(),
			"base_datos": self.campo_base_datos.text().strip(),
			"archivo_sqlite": "",
		}

	def _probar_conexion(self):
		config = self._armar_config()
		if config is None:
			return
		try:
			engine = crear_engine_externo(config)
			with engine.connect():
				pass
			QMessageBox.information(self, "Conexión OK", "La conexión se probó con éxito.")
		except Exception as e:
			QMessageBox.critical(self, "Error de conexión", f"No se pudo conectar:\n{e}")

	def _guardar(self):
		config = self._armar_config()
		if config is None:
			return
		try:
			guardar_config_conexion(config)
		except Exception as e:
			QMessageBox.critical(self, "Error al guardar", f"No se pudo guardar la configuración:\n{e}")
			return
		self.accept()

class ConfiguracionTablaEmpleadosDialog(QDialog):
	"""Define en qué tabla/columnas está el nombre de cada empleado, sobre
	la conexión ya configurada."""

	def __init__(self, parent=None):
		super().__init__(parent)
		self.setWindowTitle("Configurar tabla de empleados")
		self.resize(400, 220)

		config_actual = cargar_config_empleados()

		layout = QVBoxLayout(self)
		layout.addWidget(QLabel(
			"Usa la conexión configurada en 'Configurar conexión a base de datos'."
		))
		form = QFormLayout()

		self.campo_tabla = QLineEdit(config_actual.get("tabla", "empleados"))
		self.campo_tabla_organizacion = QLineEdit(config_actual.get("tabla_org", "empleados"))
		self.campo_columna_id = QLineEdit(config_actual.get("columna_id", ""))
		self.campo_columna_nombre = QLineEdit(config_actual.get("columna_nombre", ""))
		self.campo_columna_condicion = QLineEdit(config_actual.get("columna_condicion", ""))

		form.addRow("Tabla:", self.campo_tabla)
		form.addRow("Nombre Columna número tarjeta:", self.campo_columna_id)
		form.addRow("Nombre Columna apellido/nombre:", self.campo_columna_nombre)
		form.addRow("Nombre Columna condicion:", self.campo_columna_condicion)
		layout.addLayout(form)

		botones = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
		botones.accepted.connect(self._guardar)
		botones.rejected.connect(self.reject)
		layout.addWidget(botones)

	def _guardar(self):
		tabla = self.campo_tabla.text().strip()
		columna_id = self.campo_columna_id.text().strip()
		columna_nombre = self.campo_columna_nombre.text().strip()
		columna_condicion = self.campo_columna_condicion.text().strip()
		
		if not tabla or not columna_id or not columna_nombre:
			QMessageBox.warning(self, "Datos requeridos", "Completá los tres campos.")
			return
		try:
			guardar_config_empleados({
				"tabla": tabla,
				"columna_id": columna_id,
				"columna_nombre": columna_nombre,
				"columna_condicion": columna_condicion
			})
		except Exception as e:
			QMessageBox.critical(self, "Error al guardar", f"No se pudo guardar:\n{e}")
			return
		self.accept()

class ConfiguracionTablaAsistenciasDialog(QDialog):
	"""Define en qué tabla/columnas del sistema web hay que insertar las
	marcaciones, sobre la conexión ya configurada."""

	def __init__(self, parent=None):
		super().__init__(parent)
		self.setWindowTitle("Configurar tabla de asistencias")
		self.resize(420, 320)

		config_actual = cargar_config_asistencias()

		layout = QVBoxLayout(self)
		layout.addWidget(QLabel(
			"Usa la conexión configurada en 'Configurar conexión a base de datos'."
		))
		form = QFormLayout()

		self.campo_tabla = QLineEdit(config_actual.get("tabla", "asistencias"))
		self.campo_col_empleado = QLineEdit(config_actual.get("columna_empleado", ""))
		self.campo_col_fecha = QLineEdit(config_actual.get("columna_fecha", ""))
		self.campo_col_hora = QLineEdit(config_actual.get("columna_hora", ""))
		self.campo_col_tipo = QLineEdit(config_actual.get("columna_tipo", ""))
		self.campo_col_reloj = QLineEdit(config_actual.get("columna_reloj", ""))
		self.campo_col_c_ver = QLineEdit(config_actual.get("columna_c_ver", ""))

		form.addRow("Tabla:", self.campo_tabla)
		form.addRow("Nombre Columna empleado/Id:", self.campo_col_empleado)
		form.addRow("Nombre Columna fecha:", self.campo_col_fecha)
		form.addRow("Nombre Columna hora:", self.campo_col_hora)
		form.addRow("Nombre Columna tipo de asistencia:", self.campo_col_tipo)
		form.addRow("Nombre Columna número de dispositivo:", self.campo_col_reloj)
		form.addRow("Nombre Columna verificacion:", self.campo_col_c_ver)
		layout.addLayout(form)

		botones = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
		botones.accepted.connect(self._guardar)
		botones.rejected.connect(self.reject)
		layout.addWidget(botones)

	def _guardar(self):
		valores = {
			"tabla": self.campo_tabla.text().strip(),
			"columna_empleado": self.campo_col_empleado.text().strip(),
			"columna_fecha": self.campo_col_fecha.text().strip(),
			"columna_hora": self.campo_col_hora.text().strip(),
			"columna_tipo": self.campo_col_tipo.text().strip(),
			"columna_reloj": self.campo_col_reloj.text().strip(),
			"columna_c_ver": self.campo_col_c_ver.text().strip(),
		}
		if not all(valores.values()):
			QMessageBox.warning(self, "Datos requeridos", "Completá todos los campos.")
			return
		try:
			guardar_config_asistencias(valores)
		except Exception as e:
			QMessageBox.critical(self, "Error al guardar", f"No se pudo guardar:\n{e}")
			return
		self.accept()