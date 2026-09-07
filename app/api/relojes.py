import datetime
import importlib
import pymysql

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
    get_config_relojes_path, 
    cargar_relojes, 
    crear_adaptador,
	cargar_config_mysql,
	guardar_config_mysql
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
RELOJES = cargar_relojes()

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

		self.boton_config_mysql = QPushButton("Configurar conexión MySQL")
		layout.addWidget(self.boton_config_mysql)
		self.boton_config_mysql.clicked.connect(self._abrir_config_mysql)


		botones = QDialogButtonBox()
		self.boton_guardar = botones.addButton("Guardar", QDialogButtonBox.AcceptRole)
		self.boton_cancelar = botones.addButton("Cancelar", QDialogButtonBox.RejectRole)
		botones.accepted.connect(self._guardar)
		botones.rejected.connect(self.reject)
		layout.addWidget(botones)

	def _cargar_relojes_actuales(self):
		try:
			ruta = get_config_relojes_path()
			spec = importlib.util.spec_from_file_location("config_relojes_runtime", ruta)
			modulo_config = importlib.util.module_from_spec(spec)
			spec.loader.exec_module(modulo_config)
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
		return get_config_relojes_path()
	

	def sincronizacion_completa(self):
		resp = QMessageBox.question(
			        self, "Sincronización completa",
					   	  "Esto va a descargar TODO el historial de cada reloj (puede tardar "
						  "varios minutos) y, si se guarda todo correctamente, va a BORRAR "
						  "las marcaciones de la memoria del reloj.\n\n"
						  "¿Confirmás que querés continuar?"
			    )
		if resp != QMessageBox.Yes:
			return
		
		# Rango bien amplio para traer todo lo que tenga el reloj en memoria.
		desde = "2000-01-01"
		hasta = datetime.date.today().strftime("%Y-%m-%d")
		self._descargar_marcaciones(desde, hasta, self.boton_sync_completa, limpiar_buffer_si_ok=True)
		
	
	def limpiar_buffer_relojes(self):
		""" Borra la memoria de marcaciones de cada reloj SIN descargarlas ni
			guardarlas antes. Operación irreversible: cualquier marcación que no
			se haya guardado previamente en la base se pierde para siempre. """
		
		aviso = QMessageBox(self)
		aviso.setIcon(QMessageBox.Warning)
		aviso.setWindowTitle("⚠ Limpiar buffer de relojes")
		aviso.setText(
			"Esta acción va a BORRAR todas las marcaciones almacenadas en la "
			"memoria de cada reloj configurado, SIN descargarlas ni guardarlas "
			"primero.\n\n"
			"Cualquier marcación que no hayas sincronizado antes se va a perder "
			"DEFINITIVAMENTE.\n\n"
			"¿Estás seguro de que querés continuar?"
			)
		aviso.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
		aviso.setDefaultButton(QMessageBox.Cancel)
		if aviso.exec() != QMessageBox.Yes:
			self.mostrar_mensaje("Limpieza de buffer cancelada.")
			return
		
		texto, ok = QInputDialog.getText(
			self, "Confirmación final", "Para confirmar, escribí BORRAR (en mayúsculas) y aceptá:"
		)

		if not ok or texto.strip() != "BORRAR":
			self.mostrar_mensaje("Limpieza de buffer cancelada (confirmación incorrecta).")
			return
		
		self.mostrar_mensaje("Iniciando limpieza de buffer en los relojes...")
		self.boton_limpiar_buffer.setEnabled(False)
		QApplication.processEvents()

		for config_reloj in RELOJES:
			dispositivo_id = config_reloj["params"].get("dispositivo_id", "?")
			try:
				adapter = crear_adaptador(config_reloj)
			except ValueError as e:
				self.mostrar_mensaje(f"[{dispositivo_id}] Error de configuración: {e}")
				continue

			if not hasattr(adapter, "limpiar_buffer"):
				self.mostrar_mensaje(f"[{dispositivo_id}] Este tipo de reloj no soporta limpiar buffer. Se omite.")
				continue

			self.mostrar_mensaje(f"[{dispositivo_id}] Conectando...")
			QApplication.processEvents()
			if not adapter.conectar():
				self.mostrar_mensaje(f"[{dispositivo_id}] No se pudo conectar. Se omite.")
				continue

			try:
				adapter.limpiar_buffer()
				self.mostrar_mensaje(f"[{dispositivo_id}] Buffer limpiado correctamente.")
			except Exception as e:
				self.mostrar_mensaje(f"[{dispositivo_id}] Error al limpiar buffer: {e}")
			finally:
				adapter.desconectar()

		self.mostrar_mensaje("Limpieza de buffer finalizada.")
		self.boton_limpiar_buffer.setEnabled(True)

	def _abrir_config_mysql(self):
		dialogo = ConfiguracionMySQLDialog(parent=self)
		dialogo.exec()


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


class ConfiguracionMySQLDialog(QDialog):
	"""Formulario para configurar la conexión a la base MySQL externa donde
	vive la tabla de empleados, con botón para probar antes de guardar."""

	def __init__(self, parent=None):
		super().__init__(parent)
		self.setWindowTitle("Configurar conexión MySQL")
		self.resize(400, 300)

		config_actual = cargar_config_mysql()

		layout = QVBoxLayout(self)
		form = QFormLayout()

		self.campo_host = QLineEdit(config_actual.get("host", ""))
		self.campo_puerto = QLineEdit(str(config_actual.get("puerto", 3306)))
		self.campo_usuario = QLineEdit(config_actual.get("usuario", ""))
		self.campo_password = QLineEdit(config_actual.get("password", ""))
		self.campo_password.setEchoMode(QLineEdit.Password)
		self.campo_base_datos = QLineEdit(config_actual.get("base_datos", ""))
		self.campo_tabla = QLineEdit(config_actual.get("tabla_empleados", "empleados"))

		form.addRow("Host / IP:", self.campo_host)
		form.addRow("Puerto:", self.campo_puerto)
		form.addRow("Usuario:", self.campo_usuario)
		form.addRow("Contraseña:", self.campo_password)
		form.addRow("Base de datos:", self.campo_base_datos)
		form.addRow("Tabla de empleados:", self.campo_tabla)
		layout.addLayout(form)

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

	def _armar_config(self):
		puerto_texto = self.campo_puerto.text().strip()
		if not puerto_texto.isdigit():
			QMessageBox.warning(self, "Dato inválido", "El puerto tiene que ser un número.")
			return None
		return {
			"host": self.campo_host.text().strip(),
			"puerto": int(puerto_texto),
			"usuario": self.campo_usuario.text().strip(),
			"password": self.campo_password.text(),
			"base_datos": self.campo_base_datos.text().strip(),
			"tabla_empleados": self.campo_tabla.text().strip(),
		}

	def _probar_conexion(self):
		config = self._armar_config()
		if config is None:
			return
		try:
			
			conexion = pymysql.connect(
				host=config["host"], port=config["puerto"],
				user=config["usuario"], password=config["password"],
				database=config["base_datos"], connect_timeout=8,
			)
			conexion.close()
			QMessageBox.information(self, "Conexión OK", "La conexión a MySQL se probó con éxito.")
		except Exception as e:
			QMessageBox.critical(self, "Error de conexión", f"No se pudo conectar:\n{e}")

	def _guardar(self):
		config = self._armar_config()
		if config is None:
			return
		try:
			guardar_config_mysql(config)
		except Exception as e:
			QMessageBox.critical(self, "Error al guardar", f"No se pudo guardar la configuración:\n{e}")
			return
		self.accept()	