from sqlalchemy import text
from resources.config_path import crear_engine_externo, cargar_config_empleados, cargar_config_conexion, _validar_identificador_sql
from app.api.organizaciones import filtro_organizacion


def resolver_id_empleado(conexion, numero_reloj):
    """La tarjeta identifica al empleado únicamente dentro de la organización."""
    config = cargar_config_empleados()
    quote = conexion.dialect.identifier_preparer.quote
    tabla = quote(_validar_identificador_sql(config['tabla']))
    tarjeta = quote(_validar_identificador_sql(config['columna_id']))
    pk = quote(_validar_identificador_sql(config.get('columna_id_interno', 'id')))
    filtro, params = filtro_organizacion(conexion, config)
    params['numero_reloj'] = str(numero_reloj).strip()
    ids = conexion.execute(text(f'SELECT {pk} FROM {tabla} WHERE {tarjeta} = :numero_reloj AND {filtro}'), params).scalars().fetchmany(2)
    if not ids:
        raise ValueError(f'No existe empleado con tarjeta {numero_reloj!r} en la organización seleccionada.')
    if len(ids) != 1 or ids[0] is None:
        raise ValueError(f'La tarjeta {numero_reloj!r} está repetida dentro de la organización seleccionada.')
    return ids[0]


def obtener_mapa_empleados():
    config = cargar_config_empleados()
    engine = crear_engine_externo(cargar_config_conexion())
    try:
        with engine.connect() as conexion:
            quote = conexion.dialect.identifier_preparer.quote
            tabla = quote(_validar_identificador_sql(config['tabla']))
            tarjeta = quote(_validar_identificador_sql(config['columna_id']))
            nombre = quote(_validar_identificador_sql(config['columna_nombre']))
            filtro, params = filtro_organizacion(conexion, config)
            filas = conexion.execute(text(f'SELECT {tarjeta}, {nombre} FROM {tabla} WHERE {filtro}'), params)
            mapa = {}
            for numero, apellido in filas:
                if numero is None: continue
                clave = str(numero).strip()
                if clave in mapa:
                    raise ValueError(f'La tarjeta {clave!r} está repetida dentro de la organización seleccionada.')
                mapa[clave] = apellido
            return mapa
    finally:
        engine.dispose()
