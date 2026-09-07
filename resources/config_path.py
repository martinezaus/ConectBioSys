import os
import sys
import shutil
import importlib.util

from resources.marcas_relojes import ADAPTERS

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

def get_config_mysql_path():
    base_dir = os.path.join(os.getenv("LOCALAPPDATA"), "ConectBioSync")
    os.makedirs(base_dir, exist_ok=True)
    destino = os.path.join(base_dir, "config_mysql.py")
    if not os.path.exists(destino):
        with open(destino, "w", encoding="utf-8") as f:
            f.write(
				'MYSQL_CONFIG = {\n'
				'    "host": "",\n'
				'    "puerto": 3306,\n'
				'    "usuario": "",\n'
				'    "password": "",\n'
				'    "base_datos": "",\n'
				'    "tabla_empleados": "empleados",\n'
				'}\n'
			)
    return destino

def cargar_config_mysql():
	ruta = get_config_mysql_path()
	spec = importlib.util.spec_from_file_location("config_mysql_runtime", ruta)
	modulo = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(modulo)
	return modulo.MYSQL_CONFIG

def guardar_config_mysql(config):
	ruta = get_config_mysql_path()
	contenido = (
		'MYSQL_CONFIG = {\n'
		f'    "host": {config["host"]!r},\n'
		f'    "puerto": {config["puerto"]!r},\n'
		f'    "usuario": {config["usuario"]!r},\n'
		f'    "password": {config["password"]!r},\n'
		f'    "base_datos": {config["base_datos"]!r},\n'
		f'    "tabla_empleados": {config["tabla_empleados"]!r},\n'
		'}\n'
	)
	with open(ruta, "w", encoding="utf-8") as f:
		f.write(contenido)