
from datetime import datetime
from threading import Lock
from zoneinfo import ZoneInfo
from sqlalchemy import text
from app.api.empleados import resolver_id_empleado
from resources.config_path import (
	crear_engine_externo,
	cargar_config_asistencias,
	cargar_config_conexion,
	_validar_identificador_sql,
)

# Traducción de nuestro modelo interno al formato del sistema web.
_SEND_LOCK = Lock()

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
	"""fila = (dispositivo_id, numero_reloj, fecha_hora_str, tipo_evento_texto, metodo)
	tal como vienen de la consulta y exportación de marcaciones."""

	dispositivo_id, numero_reloj, fecha_hora_str, tipo_evento_texto, metodo = fila

	dt    = datetime.fromisoformat(str(fecha_hora_str))
	fecha = dt.strftime("%Y-%m-%d")
	hora  = dt.time().replace(tzinfo=None)
	tipo  = MAPA_TIPO.get(tipo_evento_texto, "E")

	try:
		reloj = int(dispositivo_id)
	except (TypeError, ValueError):
		reloj = None  # el sistema web tendrá que aceptar NULL o filtrarlo

	c_ver = MAPA_METODO_A_CVER.get(str(metodo).lower(), 3)  # 3 = Manual por defecto

	return numero_reloj, fecha, hora, tipo, reloj, c_ver

def enviar_marcaciones(filas):
	"""Inserta filas en la tabla de asistencias configurada. Devuelve
	(insertadas, duplicadas, errores, detalle_errores), donde detalle_errores trae el
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
	duplicada_sql = text(
        f'SELECT 1 FROM `{tabla}` '
        f'WHERE `{col_empleado}` = :empleado_id '
        f'AND `{col_fecha}` = :fecha '
        f'AND `{col_hora}` = :hora '
        f'AND `{col_tipo}` = :tipo '
        f'LIMIT 1 FOR UPDATE'
    )

	insertadas = 0
	duplicadas = 0
	errores = 0
	detalle_errores = []  # primeros N errores reales, para poder diagnosticar
	MAX_DETALLES = 15

	try:
		with _SEND_LOCK, engine.begin() as conexion:
			ids_empleados = {}
			for fila in filas:
				try:
					numero_reloj, fecha, hora, tipo, reloj, c_ver = _armar_valores(fila)
				except Exception as e:
					errores += 1
					if len(detalle_errores) < MAX_DETALLES:
						detalle_errores.append(f"{fila}: no se pudo interpretar la fila ({e})")
					continue
				try:
					with conexion.begin_nested():
						clave = str(numero_reloj).strip()
						if clave not in ids_empleados:
							ids_empleados[clave] = resolver_id_empleado(conexion, clave)
						empleado = ids_empleados[clave]
						valores = { "empleado_id": empleado, "fecha": fecha, "hora": hora, "tipo": tipo, "reloj": reloj, "c_ver": c_ver }
						if conexion.execute(duplicada_sql, valores).first():
							duplicadas += 1
							continue
						conexion.execute(sql, valores)
					insertadas += 1
				except Exception as e:
					errores += 1
					if len(detalle_errores) < MAX_DETALLES:
						detalle_errores.append(f"{fila}: {e}")
	finally:
		engine.dispose()

	return insertadas, duplicadas, errores, detalle_errores
