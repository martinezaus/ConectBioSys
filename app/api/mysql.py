import pymysql
from resources.config_path import cargar_config_mysql


def obtener_empleados():
	"""Conecta a la base MySQL externa configurada por el usuario y devuelve
	todas las filas de la tabla de empleados que indicó."""
	config = cargar_config_mysql()

	if not config["host"] or not config["tabla_empleados"]:
		raise ValueError(
			"La conexión MySQL no está configurada. Andá a "
			"'Configurar relojes' > 'Configurar conexión MySQL'."
		)

	tabla = config["tabla_empleados"]
	# El nombre de tabla no se puede parametrizar con placeholders (?), así
	# que lo validamos a mano contra inyección SQL antes de usarlo en el f-string.
	if not tabla.replace("_", "").isalnum():
		raise ValueError(f"Nombre de tabla inválido: {tabla!r}")

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
			cursor.execute(f"SELECT * FROM `{tabla}`")
			return cursor.fetchall()
	finally:
		conexion.close()