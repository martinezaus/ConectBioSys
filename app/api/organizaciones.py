"""Catálogo de organizaciones y alcance de empleados mediante legajo."""
import re
from sqlalchemy import inspect, text
from resources.config_path import crear_engine_externo, _validar_identificador_sql


def id_organizacion(config):
    valor = config.get('organizacion_id')
    if valor is None:
        anterior = str(config.get('columna_condicion', '')).strip()
        match = re.fullmatch(r'(?:organizacion_id\s*=\s*)?[\'\"]?(\d+)[\'\"]?', anterior)
        valor = match.group(1) if match else None
    if valor is None or str(valor).strip() == '':
        raise ValueError('Seleccioná una organización en la configuración de empleados.')
    return str(valor)


def detectar_relacion(conexion, config):
    inspector = inspect(conexion)
    tabla = _validar_identificador_sql(config['tabla'])
    columnas = {c['name'] for c in inspector.get_columns(tabla)}
    if 'organizacion_id' in columnas:
        return {'tabla_relacion_organizacion': '', 'columna_empleado_relacion': ''}
    for candidata in ('legajo', 'legajos'):
        if inspector.has_table(candidata):
            columnas = {c['name'] for c in inspector.get_columns(candidata)}
            fk = next((c for c in ('empleados_id', 'empleado_id') if c in columnas), None)
            if fk and 'organizacion_id' in columnas:
                return {'tabla_relacion_organizacion': candidata, 'columna_empleado_relacion': fk}
    raise ValueError('No se encontró la relación de empleados con organizacion_id.')


def cargar_catalogo(config, conexion_config):
    engine = crear_engine_externo(conexion_config)
    try:
        with engine.connect() as conexion:
            inspector = inspect(conexion)
            tabla = next((t for t in ('organizaciones', 'organizacion') if inspector.has_table(t)), None)
            if tabla is None:
                raise ValueError('No existe una tabla organizaciones u organizacion.')
            columnas = {c['name'] for c in inspector.get_columns(tabla)}
            nombre = next((c for c in ('nombre', 'd_org') if c in columnas), None)
            if 'id' not in columnas or not nombre:
                raise ValueError('El catálogo requiere id y nombre o d_org.')
            quote = conexion.dialect.identifier_preparer.quote
            filas = conexion.execute(text(f'SELECT {quote("id")}, {quote(nombre)} FROM {quote(tabla)} ORDER BY {quote(nombre)}')).all()
            return [(str(i), str(n)) for i, n in filas if i is not None], detectar_relacion(conexion, config)
    finally:
        engine.dispose()


def filtro_organizacion(conexion, config):
    organizacion = id_organizacion(config)
    relacion = config if 'tabla_relacion_organizacion' in config else detectar_relacion(conexion, config)
    quote = conexion.dialect.identifier_preparer.quote
    tabla = quote(_validar_identificador_sql(config['tabla']))
    pk = quote(_validar_identificador_sql(config.get('columna_id_interno', 'id')))
    if relacion.get('tabla_relacion_organizacion'):
        legajo = quote(_validar_identificador_sql(relacion['tabla_relacion_organizacion']))
        fk = quote(_validar_identificador_sql(relacion['columna_empleado_relacion']))
        filtro = f'EXISTS (SELECT 1 FROM {legajo} org_scope WHERE org_scope.{fk} = {tabla}.{pk} AND org_scope.{quote("organizacion_id")} = :organizacion_id)'
    else:
        filtro = f'{tabla}.{quote("organizacion_id")} = :organizacion_id'
    return filtro, {'organizacion_id': organizacion}
