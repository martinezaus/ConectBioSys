import datetime
import sqlite3
from pathlib import Path

class Database:

	def __init__(self):
		self.ruta=Path("data/marcaciones.db")
		
		print("Base de datos:")

		print(self.ruta.resolve())

		self.ruta.parent.mkdir(parents=True, exist_ok=True)
		self.crear_tablas()
		
	def conectar(self):
		return sqlite3.connect(self.ruta)
	
	def crear_tablas(self):
		conexion=self.conectar()
		cursor = conexion.cursor()
		cursor.execute("""
			CREATE TABLE IF NOT EXISTS marcaciones (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				dispositivo_id TEXT NOT NULL,
				empleado_id TEXT NOT NULL,
				fecha_hora TEXT NOT NULL,
				tipo_evento INTEGER,
				metodo TEXT,
				enviado INTEGER DEFAULT 0,
				fecha_descarga TEXT
			)
		""")
		conexion.commit()
		conexion.close()

	def obtener_marcaciones_filtradas(self, desde, hasta, tarjeta=None):
		"""
		   Devuelve marcaciones entre 'desde' y 'hasta' (YYYY-MM-DD), opcionalmente
		   filtradas por número de tarjeta (empleado_id).
		"""

		conexion = self.conectar()
		cursor = conexion.cursor()
		
		if tarjeta:
			cursor.execute(
				"""
				    SELECT dispositivo_id, 
					       empleado_id, 
						   fecha_hora, 
						   CASE
						        WHEN tipo_evento = 0 THEN 'Entrada'
								WHEN tipo_evento = 1 THEN 'Salida'
								ELSE 'Otro'
							END AS tipo_evento, 
						   metodo
					FROM marcaciones
					WHERE date(fecha_hora) BETWEEN date(?) AND date(?)
					AND empleado_id = ?
				    ORDER BY fecha_hora
            """,
            (desde, hasta, tarjeta),
        
		)
		else:
			cursor.execute(
				"""
				    SELECT dispositivo_id, 
					       empleado_id, 
						   fecha_hora, 
						   CASE
						        WHEN tipo_evento = 0 THEN 'Entrada'
								WHEN tipo_evento = 1 THEN 'Salida'
								ELSE 'Otro'
							END AS tipo_evento,
							metodo
					FROM marcaciones
					WHERE date(fecha_hora) BETWEEN date(?) AND date(?)
					ORDER BY fecha_hora
				""",
				(desde, hasta),
		    
			)
		filas = cursor.fetchall()
		conexion.close()
		return filas

	def guardar_marcacion(self, dispositivo_id, empleado_id, fecha_hora, tipo_evento, metodo):

		conexion = self.conectar()
		cursor = conexion.cursor()
		cursor.execute("""
			INSERT INTO marcaciones (
				dispositivo_id,
				empleado_id,
				fecha_hora,
				tipo_evento,
				metodo,
				fecha_descarga
			)
			VALUES (?, ?, ?, ?, ?, datetime('now'))
		""", (
			dispositivo_id,
			empleado_id,
			fecha_hora,
			tipo_evento,
			metodo
		))

		conexion.commit()
		conexion.close()
		
	def obtener_todas_marcaciones(self, desde=None, hasta=None):
		"""
		    Devuelve todas las marcaciones guardadas. Si se pasan 'desde'/'hasta'
		    (YYYY-MM-DD), filtra por ese rango; si no, trae todo el histórico.
	    """
		anio_actual = datetime.date.today().year
		desde = desde or f"{anio_actual}-01-01"
		hasta = hasta or f"{anio_actual}-12-31"

		return self.obtener_marcaciones_filtradas(desde, hasta)



