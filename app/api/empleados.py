import pymysql
from sqlalchemy import text

from resources.config_path import (
	crear_engine_externo,
	cargar_config_empleados,
	cargar_config_conexion,
	_validar_identificador_sql,
)



def obtener_mapa_empleados():
	"""Devuelve un diccionario {numero_tarjeta: nombre_completo}."""
	config_tabla = cargar_config_empleados()

	tabla = _validar_identificador_sql(config_tabla["tabla"])
	columna_id = _validar_identificador_sql(config_tabla["columna_id"])
	columna_nombre = _validar_identificador_sql(config_tabla["columna_nombre"])
	columna_condicion = _validar_identificador_sql(config_tabla["columna_condicion"])

	engine = crear_engine_externo(cargar_config_conexion())
	with engine.connect() as conexion:
		resultado = conexion.execute(
			text(f'SELECT "{columna_id}" AS id, "{columna_nombre}" AS nombre FROM "{tabla}" WHERE "{columna_condicion}"')
		)
		return {str(fila.id).strip(): fila.nombre for fila in resultado}