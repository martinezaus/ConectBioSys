import sys
import importlib
import datetime

from PySide6.QtWidgets import (
	QApplication,
	QMainWindow,
	QWidget,
	QVBoxLayout,
	QPushButton,
	QTextEdit,
	QHBoxLayout,
	QProgressBar,
	QMessageBox,
	QFileDialog,
	QInputDialog,
	QDialog,
	QDialogButtonBox,
	QTableWidget,
	QTableWidgetItem,
	QCheckBox,
	QLabel,
)
from PySide6.QtGui import QIcon
from openpyxl import Workbook

from app.database.database import Database
from resources.config_relojes import RELOJES
from resources.config_app import ESTILO_APP
from app.api.relojes import ConfiguracionRelojesDialog, RangoFechasDialog

from resources.config_path import cargar_relojes, crear_adaptador
from app.api.empleados import obtener_mapa_empleados

ENCABEZADOS_MARCACIONES = ["Dispositivo", "Empleado", "Fecha y hora", "Tipo de evento", "Método"]
RELOJES = cargar_relojes()


class TablaMarcacionesDialog(QDialog):
	"""Muestra una lista de marcaciones en una tabla con checkboxes para que el
	usuario elija cuáles exportar a Excel."""

	def __init__(self, filas, titulo="Marcaciones", parent=None):
		super().__init__(parent)
		self.setWindowTitle(titulo)
		self.resize(750, 500)
		self.filas = filas

		layout = QVBoxLayout()
		self.setLayout(layout)

		info = QLabel(f"{len(filas)} marcaciones encontradas. Tildá las que querés exportar.")
		layout.addWidget(info)

		fila_acciones = QHBoxLayout()
		self.boton_marcar_todo = QPushButton("Marcar todo")
		self.boton_desmarcar_todo = QPushButton("Desmarcar todo")
		fila_acciones.addWidget(self.boton_marcar_todo)
		fila_acciones.addWidget(self.boton_desmarcar_todo)
		fila_acciones.addStretch()
		layout.addLayout(fila_acciones)

		self.tabla = QTableWidget()
		self.tabla.setColumnCount(len(ENCABEZADOS_MARCACIONES) + 1)
		self.tabla.setHorizontalHeaderLabels(["", *ENCABEZADOS_MARCACIONES])
		self.tabla.setRowCount(len(filas))
		self.tabla.setEditTriggers(QTableWidget.NoEditTriggers)

		for fila_idx, fila in enumerate(filas):
			checkbox = QCheckBox()
			checkbox.setChecked(True)
			self.tabla.setCellWidget(fila_idx, 0, checkbox)
			for col_idx, valor in enumerate(fila, start=1):
				item = QTableWidgetItem(str(valor))
				self.tabla.setItem(fila_idx, col_idx, item)

		self.tabla.resizeColumnsToContents()
		layout.addWidget(self.tabla)

		self.boton_marcar_todo.clicked.connect(lambda: self._marcar_todo(True))
		self.boton_desmarcar_todo.clicked.connect(lambda: self._marcar_todo(False))

		botones = QDialogButtonBox()
		self.boton_exportar = botones.addButton("Exportar seleccionados", QDialogButtonBox.AcceptRole)
		self.boton_cerrar = botones.addButton("Cerrar", QDialogButtonBox.RejectRole)
		botones.accepted.connect(self.accept)
		botones.rejected.connect(self.reject)
		layout.addWidget(botones)

	def _marcar_todo(self, estado):
		for fila_idx in range(self.tabla.rowCount()):
			checkbox = self.tabla.cellWidget(fila_idx, 0)
			if checkbox is not None:
				checkbox.setChecked(estado)

	def filas_seleccionadas(self):
		"""Devuelve las filas originales (tuplas) cuyo checkbox quedó tildado."""
		seleccionadas = []
		for fila_idx, fila in enumerate(self.filas):
			checkbox = self.tabla.cellWidget(fila_idx, 0)
			if checkbox is not None and checkbox.isChecked():
				seleccionadas.append(fila)
		return seleccionadas


class VentanaPrincipal(QMainWindow):

	def __init__(self):
		super().__init__()

		self.db = Database()  # creo la base de datos
		self.setWindowTitle("ConectBioSync - Descarga de marcaciones de relojes biometricos")
		self.resize(800, 600)

		# Widget principal
		widget = QWidget()
		self.setCentralWidget(widget)

		# Layout
		layout = QVBoxLayout()
		widget.setLayout(layout)
		
		
		# Botón
		self.fila_botones = QHBoxLayout()
		self.boton_conectar = QPushButton("Mes Anterior")
		self.boton_conectar1 = QPushButton("Ultimo 7 dias")
		self.boton_conectar2 = QPushButton("Tarjeta")
		self.boton_exportar = QPushButton("Exportar")
		self.boton_configurar_relojes = QPushButton("Configurar relojes")

		self.fila_botones.addWidget(self.boton_conectar)
		self.fila_botones.addWidget(self.boton_conectar1)
		self.fila_botones.addWidget(self.boton_conectar2)
		self.fila_botones.addWidget(self.boton_exportar)
		self.fila_botones.addWidget(self.boton_configurar_relojes)

		layout.addLayout(self.fila_botones)


		self.barra_progreso = QProgressBar()
		self.barra_progreso.setVisible(False)   # oculta hasta que se necesite
		layout.addWidget(self.barra_progreso)

		# Área de mensajes
		self.area_mensajes = QTextEdit()
		self.area_mensajes.setReadOnly(True)
		layout.addWidget(self.area_mensajes)

		# Evento del botón
		self.boton_conectar.clicked.connect(self.conectar)
		self.boton_conectar1.clicked.connect(self.conectar_dias)
		self.boton_conectar2.clicked.connect(self.conectar_tarjeta)
		self.boton_exportar.clicked.connect(self.exportar)
		self.boton_configurar_relojes.clicked.connect(self.abrir_configuracion_relojes)

	def abrir_configuracion_relojes(self):
		""" Abre la pantalla de administración de relojes. Si el usuario guarda
		cambios, recarga RELOJES en memoria (no hace falta reiniciar la app). """
		dialogo = ConfiguracionRelojesDialog(parent=self)
		if dialogo.exec() == QDialog.Accepted:
			self._recargar_relojes()

	def _recargar_relojes(self): 
		global RELOJES
		try:
			RELOJES = cargar_relojes()
			self.mostrar_mensaje(f"Configuración de relojes actualizada ({len(RELOJES)} relojes).")
		except Exception as e:
			self.mostrar_mensaje(f"No se pudo recargar la configuración de relojes: {e}")

	def conectar(self):
		""" Conecta a los relojes y trae todas las marcaciones del mes anterior """
		desde, hasta = self.rango_mes_anterior()
		self._descargar_marcaciones(desde, hasta, self.boton_conectar)

	def conectar_dias(self):
		""" Conecta a los relojes y trae las marcaciones de los últimos 7 días,
		tomando la fecha de hoy como referencia """
		desde, hasta = self.rango_ultimos_dias(7)
		self._descargar_marcaciones(desde, hasta, self.boton_conectar1)

	def _descargar_marcaciones(self, desde, hasta, boton_disparador):
		"""Conecta a cada reloj configurado y descarga/guarda las marcaciones
		entre 'desde' y 'hasta' (inclusive). Es el motor común que usan los
		botones 'Mes Anterior' y 'Ultimo 7 dias'."""

		self.mostrar_mensaje(f"Iniciando conexión con los relojes ({desde} a {hasta})...")
		boton_disparador.setEnabled(False)
		self.barra_progreso.setVisible(True)

		total_guardadas = 0
		for config_reloj in RELOJES:
			dispositivo_id = config_reloj["params"].get("dispositivo_id", "?")
			try:
				adapter = crear_adaptador(config_reloj)
			except ValueError as e:
				self.mostrar_mensaje(f"[{dispositivo_id}] Error de configuración: {e}")
				continue

			self.mostrar_mensaje(f"[{dispositivo_id}] Conectando...")
			QApplication.processEvents()   # fuerza a refrescar la UI (ver nota abajo)
			if not adapter.conectar():
				self.mostrar_mensaje(f"[{dispositivo_id}] No se pudo conectar.")
				continue

			self.mostrar_mensaje(f"[{dispositivo_id}] Conexión establecida. Descargando marcaciones...")
			QApplication.processEvents()

			try:
				marcaciones = adapter.obtener_marcaciones(desde=desde, hasta=hasta)
			except Exception as e:
				self.mostrar_mensaje(f"[{dispositivo_id}] Error al obtener marcaciones: {e}")
				adapter.desconectar()
				continue

			self.mostrar_mensaje(f"[{dispositivo_id}] {len(marcaciones)} marcaciones descargadas. Guardando...")

			total = len(marcaciones)
			self.barra_progreso.setRange(0, max(total, 1))
			self.barra_progreso.setValue(0)

			guardadas_de_este_reloj = 0
			for i, lectura in enumerate(marcaciones, start=1):
				try:
					self.db.guardar_marcacion(
						lectura.dispositivo_id,
						lectura.reloj_user_id,
						lectura.timestamp.isoformat(sep=" "),
						lectura.tipo_evento,
						lectura.metodo,
					)
					guardadas_de_este_reloj += 1
				except Exception as e:
					self.mostrar_mensaje(f"[{dispositivo_id}] Error guardando una marcación: {e}")

				self.barra_progreso.setValue(i)
				if i % 200 == 0:   # refrescar la UI cada tanto, no en cada vuelta (sería lento)
					QApplication.processEvents()

			total_guardadas += guardadas_de_este_reloj
			self.mostrar_mensaje(f"[{dispositivo_id}] {guardadas_de_este_reloj} marcaciones guardadas en la base de datos.")

			adapter.desconectar()
			self.mostrar_mensaje(f"[{dispositivo_id}] Desconectado.")

			self.barra_progreso.setRange(0, 0)   # vuelve a indeterminado para el próximo reloj

		self.barra_progreso.setVisible(False)

		self.mostrar_mensaje(f"Listo. Total de marcaciones guardadas: {total_guardadas}.")
		boton_disparador.setEnabled(True)

	def conectar_tarjeta(self):
		""" Busca en la base de datos local las marcaciones de los últimos 30 días
		(tomando hoy como referencia) para el número de tarjeta ingresado, y las
		muestra en una tabla desde donde se pueden exportar. """
		tarjeta, ok = QInputDialog.getText(self, "Número de tarjeta", "Ingrese el número de tarjeta:")
		if not ok:
			return

		tarjeta = tarjeta.strip()
		if not tarjeta:
			QMessageBox.warning(self, "Dato requerido", "Debe ingresar un número de tarjeta.")
			return

		desde, hasta = self.rango_ultimos_dias(30)
		self.mostrar_mensaje(f"Buscando marcaciones de la tarjeta {tarjeta} ({desde} a {hasta})...")

		try:
			filas = self.obtener_marcaciones_por_tarjeta(tarjeta, desde, hasta)
		except Exception as e:
			self.mostrar_mensaje(f"Error al buscar marcaciones: {e}")
			return

		if not filas:
			self.mostrar_mensaje(f"No se encontraron marcaciones para la tarjeta {tarjeta}.")
			QMessageBox.information(self, "Tarjeta", "No hay marcaciones para esa tarjeta en los últimos 30 días.")
			return

		self.mostrar_mensaje(f"{len(filas)} marcaciones encontradas para la tarjeta {tarjeta}.")
		self._mostrar_y_exportar(filas, f"Marcaciones - Tarjeta {tarjeta}")

	def obtener_marcaciones_por_tarjeta(self, tarjeta, desde, hasta):
		if not hasattr(self.db, "obtener_marcaciones_por_tarjeta"):
			raise NotImplementedError(
				"Falta implementar 'obtener_marcaciones_por_tarjeta' en app/database/database.py"
			)
		return self.db.obtener_marcaciones_filtradas(desde, hasta, tarjeta=tarjeta)
	
	def exportar(self):
		""" Pide un rango de fechas, muestra en una tabla las marcaciones
			guardadas en ese rango y deja que el usuario elija cuáles exportar. """
		

		dialogo_rango = RangoFechasDialog(parent=self)
		if dialogo_rango.exec() != QDialog.Accepted:
			self.mostrar_mensaje("Exportación cancelada.")
			return
		
		desde, hasta = dialogo_rango.obtener_rango()
		self.mostrar_mensaje("Aguarde... buscando la información.")
		QApplication.processEvents()

		try:
			filas = self.obtener_todas_marcaciones(desde, hasta)
		except Exception as e:
			self.mostrar_mensaje(f"Error al leer la base de datos: {e}")
			return
		
		if not filas:
			self.mostrar_mensaje(f"No hay marcaciones guardadas entre {desde} y {hasta}.")
			QMessageBox.information(self, "Exportar", "No hay marcaciones guardadas en ese rango de fechas.")
			return
		
		self._mostrar_y_exportar(filas, f"Marcaciones ({desde} a {hasta})")

	def obtener_todas_marcaciones(self, desde=None, hasta=None):
		if not hasattr(self.db, "obtener_todas_marcaciones"):
			raise NotImplementedError(
				"Falta implementar 'obtener_todas_marcaciones' en app/database/database.py"
			)
		return self.db.obtener_todas_marcaciones(desde, hasta)

	def _mostrar_y_exportar(self, filas, titulo):
		"""Abre el diálogo de tabla con checkboxes y, si el usuario confirma,
		exporta a Excel las filas que quedaron tildadas."""


		
		dialogo = TablaMarcacionesDialog(filas, titulo, parent=self)
		if dialogo.exec() != QDialog.Accepted:
			self.mostrar_mensaje("Exportación cancelada.")
			return

		seleccionadas = dialogo.filas_seleccionadas()
		if not seleccionadas:
			QMessageBox.information(self, "Exportar", "No seleccionaste ninguna marcación.")
			return

		hoy = datetime.date.today().strftime("%Y-%m-%d")
		ruta_sugerida = f"marcaciones_{hoy}.xlsx"
		ruta, _ = QFileDialog.getSaveFileName(
			self, "Guardar archivo Excel", ruta_sugerida, "Excel (*.xlsx)"
		)

		if not ruta:
			self.mostrar_mensaje("Exportación cancelada.")
			return
		
		mapa_empleados = {}
		try:
			mapa_empleados = obtener_mapa_empleados()
			self.mostrar_mensaje(f"{len(mapa_empleados)} empleados encontrados en MySQL para hacer el cruce.")
			
		except Exception as e:
			self.mostrar_mensaje(f"No se pudo buscar nombres en MySQL, se exporta sin ese dato: {e}")
		
		wb = Workbook()
		hoja = wb.active
		hoja.title = "Marcaciones"
		# hoja.append(ENCABEZADOS_MARCACIONES)

		encabezados = list(ENCABEZADOS_MARCACIONES)
		indice_empleado = encabezados.index("Empleado")
		encabezados.insert(indice_empleado + 1, "Nombre")
		hoja.append(encabezados)

		for fila in seleccionadas:
			fila = list(fila)
			numero_tarjeta = str(fila[indice_empleado])
			nombre = mapa_empleados.get(numero_tarjeta, "")
			fila.insert(indice_empleado + 1, nombre)
			hoja.append(fila)

		# Ancho de columnas legible
		anchos = [15, 15, 20, 20, 15, 15]
		for i, ancho in enumerate(anchos, start=1):
			hoja.column_dimensions[hoja.cell(row=1, column=i).column_letter].width = ancho

		wb.save(ruta)
		self.mostrar_mensaje(f"Archivo exportado: {ruta} ({len(seleccionadas)} marcaciones).")
		QMessageBox.information(self, "Exportar", f"Se exportaron {len(seleccionadas)} marcaciones a:\n{ruta}")

	def mostrar_mensaje(self, mensaje):
		self.area_mensajes.append(mensaje)

	def rango_mes_anterior(self):
		"""Devuelve (desde, hasta) como 'YYYY-MM-DD' del mes calendario anterior."""
		hoy = datetime.date.today()
		primer_dia_mes_actual = hoy.replace(day=1)
		ultimo_dia_mes_anterior = primer_dia_mes_actual - datetime.timedelta(days=1)
		primer_dia_mes_anterior = ultimo_dia_mes_anterior.replace(day=1)
		return (
			primer_dia_mes_anterior.strftime("%Y-%m-%d"),
			ultimo_dia_mes_anterior.strftime("%Y-%m-%d"),
		)

	def rango_ultimos_dias(self, dias):
		"""Devuelve (desde, hasta) como 'YYYY-MM-DD' cubriendo los últimos
		'dias' días, tomando la fecha de hoy como referencia (hasta = hoy)."""
		hoy = datetime.date.today()
		desde = hoy - datetime.timedelta(days=dias)
		return desde.strftime("%Y-%m-%d"), hoy.strftime("%Y-%m-%d")


app = QApplication(sys.argv)
app.setWindowIcon(QIcon("resources/conectbiosync.ico"))
app.setStyleSheet(ESTILO_APP)
 
ventana = VentanaPrincipal()
ventana.show()
sys.exit(app.exec())