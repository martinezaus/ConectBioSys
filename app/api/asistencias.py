
from datetime import datetime
from sqlalchemy import text
from resources.config_path import (
	crear_engine_externo,
	cargar_config_asistencias,
	cargar_config_conexion,
	_validar_identificador_sql,
)

# Traducción de nuestro modelo interno al formato del sistema web.
MAPA_TIPO = {"Entrada": "E", "Salida": "S"}

MAPA_METODO_A_CVER = {
	"huella": 1,
	"rostro": 15,
	"tarjeta": 3,
	"clave": 3,
	"desconocido": 3,
	"sin_clasificar": 3,
	"entrada": 3, "salida": 3, "inicio_pausa": 3,
	"fin_pausa": 3, "entrada_extra": 3, "salida_extra": 3,
}


def _armar_valores(fila):
	"""fila = (dispositivo_id, empleado_id, fecha_hora_str, tipo_evento_texto, metodo)
	tal como vienen de la tabla de exportación en main.py."""

	dispositivo_id, empleado_id, fecha_hora_str, tipo_evento_texto, metodo = fila

	dt    = datetime.fromisoformat(str(fecha_hora_str))
	fecha = dt.strftime("%Y-%m-%d")
	hora  = dt.strftime("%H:%M:%S")
	tipo  = MAPA_TIPO.get(tipo_evento_texto, "E")

	try:
		reloj = int(dispositivo_id)
	except (TypeError, ValueError):
		reloj = None  # el sistema web tendrá que aceptar NULL o filtrarlo

	c_ver = MAPA_METODO_A_CVER.get(str(metodo).lower(), 3)  # 3 = Manual por defecto

	return empleado_id, fecha, hora, tipo, reloj, c_ver

def enviar_marcaciones(filas):
	"""Inserta filas en la tabla de asistencias configurada. Devuelve
	(insertadas, errores, detalle_errores), donde detalle_errores trae el
	motivo real de los primeros errores (para poder diagnosticarlos)."""

	config_tabla = cargar_config_asistencias()
	tabla        = _validar_identificador_sql(config_tabla["tabla"])
	col_empleado = _validar_identificador_sql(config_tabla["columna_empleado"])
	col_fecha    = _validar_identificador_sql(config_tabla["columna_fecha"])
	col_hora     = _validar_identificador_sql(config_tabla["columna_hora"])
	col_tipo     = _validar_identificador_sql(config_tabla["columna_tipo"])
	col_reloj    = _validar_identificador_sql(config_tabla["columna_reloj"])
	col_c_ver    = _validar_identificador_sql(config_tabla["columna_c_ver"])

	engine = crear_engine_externo(cargar_config_conexion())

	sql = text(
        f'INSERT INTO `{tabla}` '
        f'(`{col_empleado}`, `{col_fecha}`, `{col_hora}`, `{col_tipo}`, `{col_reloj}`, `{col_c_ver}`) '
        f'VALUES (:empleado_id, :fecha, :hora, :tipo, :reloj, :c_ver)'
    )

	insertadas = 0
	errores = 0
	detalle_errores = []  # primeros N errores reales, para poder diagnosticar
	MAX_DETALLES = 15

	with engine.begin() as conexion:
		for fila in filas:
			try:
				empleado, fecha, hora, tipo, reloj, c_ver = _armar_valores(fila)
			except Exception as e:
				errores += 1
				if len(detalle_errores) < MAX_DETALLES:
					detalle_errores.append(f"{fila}: no se pudo interpretar la fila ({e})")
				continue
			try:
				with conexion.begin_nested():
					conexion.execute(sql, 
			 		                 { "empleado_id": empleado, "fecha": fecha, "hora": hora, "tipo": tipo, "reloj": reloj, "c_ver": c_ver, }
									)
				insertadas += 1
			except Exception as e:
				errores += 1
				if len(detalle_errores) < MAX_DETALLES:
					detalle_errores.append(f"{fila}: {e}")

	return insertadas, errores, detalle_errores