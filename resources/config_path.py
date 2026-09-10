import os
import sys
import shutil
import importlib.util

from resources.marcas_relojes import ADAPTERS
from resources.db_engines import ENGINES
from sqlalchemy import create_engine

def get_config_relojes_path():
    """Devuelve la ruta persistente de config_relojes.py (fuera del .exe),
    creando una copia por defecto la primera vez que corre la app."""
    base_dir = os.path.join(os.getenv("LOCALAPPDATA"), "ConectBioSync")
    os.makedirs(base_dir, exist_ok=True)
    destino = os.path.join(base_dir, "config_relojes.py")

    if not os.path.exists(destino):
        if hasattr(sys, "_MEIPASS"):
            origen = os.path.join(sys._MEIPASS, "resources", "config_relojes.py")
        else:
            origen = os.path.join(os.path.dirname(__file__), "config_relojes.py")
        if os.path.exists(origen):
            shutil.copy(origen, destino)
        else:
            # No hay default empaquetado: creamos un archivo vacío válido
            with open(destino, "w", encoding="utf-8") as f:
                f.write('RELOJES = []\n')
    return destino

def cargar_relojes():
    """Lee resources/config_relojes.py desde la ruta persistente (AppData),
    no desde el bundle del .exe."""
    ruta = get_config_relojes_path()
    spec = importlib.util.spec_from_file_location("config_relojes_runtime", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo.RELOJES

def crear_adaptador(config_reloj):
	"""Instancia el adaptador correcto según el 'tipo' declarado en la config."""

	tipo = config_reloj["tipo"]
	clase = ADAPTERS.get(tipo)
	if clase is None:
		raise ValueError(f"Tipo de reloj desconocido: {tipo!r}")
	return clase(**config_reloj["params"])

# ---------- Conexión externa compartida (empleados + asistencias) ----------

def get_config_conexion_path():
	base_dir = os.path.join(os.getenv("LOCALAPPDATA"), "ConectBioSync")
	os.makedirs(base_dir, exist_ok=True)
	destino = os.path.join(base_dir, "config_conexion.py")
	if not os.path.exists(destino):
		with open(destino, "w", encoding="utf-8") as f:
			f.write(
				'CONEXION_CONFIG = {\n'
				'    "motor": "mysql",\n'
				'    "host": "",\n'
				'    "puerto": 3306,\n'
				'    "usuario": "",\n'
				'    "password": "",\n'
				'    "base_datos": "",\n'
				'    "archivo_sqlite": "",\n'
				'}\n'
			)
	return destino


def cargar_config_conexion():
	ruta = get_config_conexion_path()
	spec = importlib.util.spec_from_file_location("config_conexion_runtime", ruta)
	modulo = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(modulo)
	return modulo.CONEXION_CONFIG


def guardar_config_conexion(config):
	ruta = get_config_conexion_path()
	contenido = (
		'CONEXION_CONFIG = {\n'
		f'    "motor": {config["motor"]!r},\n'
		f'    "host": {config["host"]!r},\n'
		f'    "puerto": {config["puerto"]!r},\n'
		f'    "usuario": {config["usuario"]!r},\n'
		f'    "password": {config["password"]!r},\n'
		f'    "base_datos": {config["base_datos"]!r},\n'
		f'    "archivo_sqlite": {config["archivo_sqlite"]!r},\n'
		'}\n'
	)
	with open(ruta, "w", encoding="utf-8") as f:
		f.write(contenido)


def crear_engine_externo(config=None):
	"""Arma un engine de SQLAlchemy según el motor elegido por el usuario."""
	config = config or cargar_config_conexion()
	motor = config["motor"]
	info = ENGINES.get(motor)
	if info is None:
		raise ValueError(f"Motor de base de datos desconocido: {motor!r}")

	if motor == "sqlite":
		if not config["archivo_sqlite"]:
			raise ValueError("Falta indicar el archivo SQLite.")
		url = f"sqlite:///{config['archivo_sqlite']}"
	else:
		url = (
			f"{info['url_scheme']}://{config['usuario']}:{config['password']}"
			f"@{config['host']}:{config['puerto']}/{config['base_datos']}"
		)
	return create_engine(url, connect_args={"connect_timeout": 10} if motor != "sqlite" else {})


def _validar_identificador_sql(valor):
	"""Rechaza nombres de tabla/columna con caracteres peligrosos (inyección)."""
	if not valor or not valor.replace("_", "").isalnum():
		raise ValueError(f"Nombre de tabla/columna inválido: {valor!r}")
	return valor


# ---------- Mapeo de tabla: EMPLEADOS (lectura) ----------

def get_config_empleados_path():
	base_dir = os.path.join(os.getenv("LOCALAPPDATA"), "ConectBioSync")
	os.makedirs(base_dir, exist_ok=True)
	destino = os.path.join(base_dir, "config_tabla_empleados.py")
	if not os.path.exists(destino):
		with open(destino, "w", encoding="utf-8") as f:
			f.write(
				'TABLA_EMPLEADOS_CONFIG = {\n'
				'    "tabla": "empleados",\n'
				'    "columna_id": "",\n'
				'    "columna_nombre": "",\n'
				'    "columna_condicion": "",\n'
				'}\n'
			)
	return destino


def cargar_config_empleados():
	ruta = get_config_empleados_path()
	spec = importlib.util.spec_from_file_location("config_tabla_empleados_runtime", ruta)
	modulo = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(modulo)
	return modulo.TABLA_EMPLEADOS_CONFIG


def guardar_config_empleados(config):
	ruta = get_config_empleados_path()
	contenido = (
		'TABLA_EMPLEADOS_CONFIG = {\n'
		f'    "tabla": {config["tabla"]!r},\n'
		f'    "columna_id": {config["columna_id"]!r},\n'
		f'    "columna_nombre": {config["columna_nombre"]!r},\n'
		f'    "columna_condicion": {config["columna_condicion"]!r},\n'
		'}\n'
	)
	with open(ruta, "w", encoding="utf-8") as f:
		f.write(contenido)


# ---------- Mapeo de tabla: ASISTENCIAS (escritura) ----------

def get_config_asistencias_path():
	base_dir = os.path.join(os.getenv("LOCALAPPDATA"), "ConectBioSync")
	os.makedirs(base_dir, exist_ok=True)
	destino = os.path.join(base_dir, "config_tabla_asistencias.py")
	if not os.path.exists(destino):
		with open(destino, "w", encoding="utf-8") as f:
			f.write(
				'TABLA_ASISTENCIAS_CONFIG = {\n'
				'    "tabla": "asistencias",\n'
				'    "columna_empleado": "",\n'
				'    "columna_fecha": "",\n'
				'    "columna_hora": "",\n'
				'    "columna_tipo": "",\n'
				'    "columna_reloj": "",\n'
				'    "columna_c_ver": "",\n'
				'}\n'
			)
	return destino


def cargar_config_asistencias():
	ruta = get_config_asistencias_path()
	spec = importlib.util.spec_from_file_location("config_tabla_asistencias_runtime", ruta)
	modulo = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(modulo)
	return modulo.TABLA_ASISTENCIAS_CONFIG


def guardar_config_asistencias(config):
	ruta = get_config_asistencias_path()
	contenido = (
		'TABLA_ASISTENCIAS_CONFIG = {\n'
		f'    "tabla": {config["tabla"]!r},\n'
		f'    "columna_empleado": {config["columna_empleado"]!r},\n'
		f'    "columna_fecha": {config["columna_fecha"]!r},\n'
		f'    "columna_hora": {config["columna_hora"]!r},\n'
		f'    "columna_tipo": {config["columna_tipo"]!r},\n'
		f'    "columna_reloj": {config["columna_reloj"]!r},\n'
		f'    "columna_c_ver": {config["columna_c_ver"]!r},\n'
		'}\n'
	)
	with open(ruta, "w", encoding="utf-8") as f:
		f.write(contenido)
 