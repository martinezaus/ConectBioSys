import pymysql
from resources.config_path import cargar_config_mysql


def obtener_mapa_empleados():
	"""Conecta a la base MySQL externa y devuelve un diccionario
	{numero_tarjeta: nombre_completo} para buscar nombres por tarjeta."""
	config = cargar_config_mysql()

	if not config["host"] or not config["tabla_empleados"]:
		raise ValueError(
			"La conexión MySQL no está configurada. Andá a "
			"'Configurar relojes' > 'Configurar conexión MySQL'."
		)

	tabla = config["tabla_empleados"]
	columna_id = config["columna_id"]
	columna_nombre = config["columna_nombre"]

	# Nombres de tabla/columna no se pueden parametrizar con placeholders (?),
	# así que los validamos a mano contra inyección SQL.
	for valor in (tabla, columna_id, columna_nombre):
		if not valor.replace("_", "").isalnum():
			raise ValueError(f"Nombre de tabla/columna inválido: {valor!r}")

	conexion = pymysql.connect(
		host=config["host"],
		port=int(config["puerto"]),
		user=config["usuario"],
		password=config["password"],
		database=config["base_datos"],
		cursorclass=pymysql.cursors.DictCursor,
		connect_timeout=10,
	)
	try:
		with conexion.cursor() as cursor:
			cursor.execute(f"SELECT `{columna_id}`, `{columna_nombre}` FROM `{tabla}`")
			filas = cursor.fetchall()
			return {str(fila[columna_id]): fila[columna_nombre] for fila in filas}
	finally:
		conexion.close()