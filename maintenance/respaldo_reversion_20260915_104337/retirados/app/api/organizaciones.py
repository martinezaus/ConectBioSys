"""Organizaciones disponibles en la conexión externa configurada."""
from sqlalchemy import text
from resources.config_path import (
    cargar_config_empleados, normalizar_config_empleados,
    crear_engine_externo, cargar_config_conexion, _validar_identificador_sql,
)


def consultar_organizaciones(conexion, config):
    config = normalizar_config_empleados(config)
    if config.get("modo_organizacion") == "unica":
        return [("__unica__", "Sistema externo del cliente")]
    quote = conexion.dialect.identifier_preparer.quote
    def ident(value):
        return quote(_validar_identificador_sql(value))
    catalogo = config.get("tabla_catalogo_organizaciones", "")
    if catalogo:
        tabla = ident(catalogo)
        base = config.get("base_catalogo_organizaciones", "")
        if base:
            tabla = ident(base) + "." + tabla
        columna_id = ident(config.get("columna_id_catalogo", "id"))
        columna_nombre = ident(config.get("columna_nombre_catalogo", "nombre"))
        sql = f"SELECT {columna_id} AS id, {columna_nombre} AS nombre FROM {tabla} ORDER BY {columna_nombre}"
    else:
        # Sin catálogo nominal, mostrar los IDs realmente registrados en el vínculo.
        if not config['columna_organizacion']:
            return []
        tabla = ident(config['tabla_organizacion'] or config['tabla'])
        columna = ident(config['columna_organizacion'])
        sql = f"SELECT DISTINCT {columna} AS id FROM {tabla} WHERE {columna} IS NOT NULL ORDER BY {columna}"
    resultado = []
    vistos = set()
    for fila in conexion.execute(text(sql)).mappings():
        if fila['id'] is None:
            continue
        clave = str(fila['id']).strip()
        if not clave or clave in vistos:
            raise ValueError("El catálogo contiene identificadores de organización vacíos o repetidos.")
        vistos.add(clave)
        nombre = str(fila.get('nombre') or f"Organización {clave}")
        resultado.append((clave, nombre))
    return resultado


def obtener_organizaciones(config=None, config_conexion=None):
    config = cargar_config_empleados() if config is None else config
    engine = crear_engine_externo(cargar_config_conexion() if config_conexion is None else config_conexion)
    try:
        with engine.connect() as conexion:
            return consultar_organizaciones(conexion, config)
    finally:
        engine.dispose()


def validar_organizacion(conexion, config):
    if config.get('modo_organizacion') == 'unica':
        return
    valor = config.get('valor_organizacion', '')
    if not config.get('columna_organizacion') or not valor:
        raise ValueError("Seleccioná una organización disponible para enviar a la base de datos.")
    if str(valor) not in {clave for clave, nombre in consultar_organizaciones(conexion, config)}:
        raise ValueError("La organización seleccionada ya no está disponible. Actualizá la lista.")
