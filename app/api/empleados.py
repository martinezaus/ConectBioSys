import pymysql
from sqlalchemy import text

from resources.config_path import (
	crear_engine_externo,
	cargar_config_empleados,
	cargar_config_conexion,
	_validar_identificador_sql,
)



def resolver_id_empleado(conexion, numero_reloj):
	"""Resuelve la tarjeta del dispositivo al ID relacional, sin asumir igualdad."""
	config = cargar_config_empleados()
	quote = conexion.dialect.identifier_preparer.quote
	tabla = quote(_validar_identificador_sql(config["tabla"]))
	tarjeta = quote(_validar_identificador_sql(config["columna_id"]))
	id_interno = quote(_validar_identificador_sql(config.get("columna_id_interno", "id")))
	ids = conexion.execute(
		text(f"SELECT {id_interno} FROM {tabla} WHERE {tarjeta} = :numero_reloj"),
		{"numero_reloj": numero_reloj},
	).scalars().fetchmany(2)
	if not ids:
		raise ValueError(f"No existe empleado con número de reloj {numero_reloj!r}")
	if len(ids) != 1 or ids[0] is None:
		raise ValueError(f"El número de reloj {numero_reloj!r} no identifica un empleado único con ID válido")
	return ids[0]


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