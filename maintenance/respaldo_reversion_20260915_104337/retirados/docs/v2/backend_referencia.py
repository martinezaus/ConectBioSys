"""Funciones de referencia para la propuesta v2. No reemplaza la app actual."""
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Literal
from sqlalchemy import URL, MetaData, Table, create_engine, literal, select

@dataclass(frozen=True)
class Filtro:
    desde: date
    hasta: date
    tarjeta: str | None = None
    def limites(self) -> tuple[datetime, datetime]:
        if self.hasta < self.desde:
            raise ValueError('La fecha hasta no puede ser anterior a desde.')
        return datetime.combine(self.desde,time.min), datetime.combine(self.hasta+timedelta(days=1),time.min)


def filtro_rapido(modo: Literal['mes_anterior','ultimos_7'], hoy: date) -> Filtro:
    if modo == 'mes_anterior':
        ultimo = hoy.replace(day=1)-timedelta(days=1)
        return Filtro(ultimo.replace(day=1),ultimo)
    if modo == 'ultimos_7':
        return Filtro(hoy-timedelta(days=6),hoy)  # siete fechas, incluyendo hoy
    raise ValueError('Filtro no reconocido.')


def aniversario(inicio: datetime) -> datetime:
    if inicio.tzinfo is None:
        raise ValueError('El registro debe tener zona horaria explícita.')
    try:
        return inicio.replace(year=inicio.year+1)
    except ValueError:
        return inicio.replace(year=inicio.year+1,day=28)

@dataclass(frozen=True)
class Conexion:
    motor: str
    host: str = ''
    port: int | None = None
    database: str = ''
    username: str = ''
    password: str = field(default='',repr=False)
    driver_odbc: str = 'ODBC Driver 18 for SQL Server'
    service_name: str = ''


def url_conexion(cfg: Conexion) -> URL:
    if cfg.motor == 'sqlite':
        if not cfg.database: raise ValueError('Indicá el archivo SQLite.')
        return URL.create('sqlite+pysqlite',database=cfg.database)
    drivers={'mysql':'mysql+pymysql','postgresql':'postgresql+psycopg2',
             'sqlserver':'mssql+pyodbc','oracle':'oracle+oracledb'}
    if cfg.motor not in drivers: raise ValueError('Motor no soportado.')
    if not cfg.host or not cfg.username: raise ValueError('Completá servidor y usuario.')
    if cfg.port is not None and not 1 <= cfg.port <= 65535: raise ValueError('Puerto inválido.')
    query={}
    if cfg.motor == 'sqlserver':
        query={'driver':cfg.driver_odbc,'Encrypt':'yes','TrustServerCertificate':'no'}
    if cfg.motor == 'oracle':
        if not cfg.service_name: raise ValueError('Oracle requiere Service Name.')
        query={'service_name':cfg.service_name}
    elif not cfg.database:
        raise ValueError('Indicá la base de datos.')
    return URL.create(drivers[cfg.motor],username=cfg.username,password=cfg.password,
                      host=cfg.host,port=cfg.port,database=None if cfg.motor=='oracle' else cfg.database,query=query)


def crear_engine(cfg: Conexion):
    options={}
    if cfg.motor == 'mysql': options={'connect_timeout':10,'read_timeout':30,'write_timeout':30}
    elif cfg.motor == 'postgresql': options={'connect_timeout':10,'options':'-c statement_timeout=30000'}
    elif cfg.motor == 'sqlserver': options={'timeout':10}
    elif cfg.motor == 'oracle': options={'tcp_connect_timeout':10}
    elif cfg.motor == 'sqlite': options={'timeout':5}
    return create_engine(url_conexion(cfg),pool_pre_ping=True,hide_parameters=True,connect_args=options)


def probar_conexion(cfg: Conexion):
    engine=crear_engine(cfg)
    try:
        with engine.connect() as connection:
            connection.execute(select(literal(1))).scalar_one()
        return 'Conexión exitosa'
    finally:
        engine.dispose()


def reflejar_destino(connection, schema: str | None, table: str, columns: dict[str,str]):
    destino=Table(table,MetaData(),schema=schema,autoload_with=connection,resolve_fks=False)
    if len(columns.values()) != len(set(columns.values())):
        raise ValueError('Dos campos de origen apuntan a la misma columna.')
    faltantes=set(columns.values())-set(destino.c.keys())
    if faltantes: raise ValueError(f'Columnas inexistentes: {sorted(faltantes)}')
    return destino


def preparar_fila(marca, empleado_externo, columns, datetime_mode, event_values):
    """marca contiene datetime_local ya normalizado; empleado_externo fue resuelto aparte."""
    dt=marca['datetime_local']
    if dt.tzinfo is not None:
        raise ValueError('Normalizá a hora local del destino antes de quitar la zona.')
    if marca['tipo'] not in event_values:
        raise ValueError('El evento no tiene equivalencia configurada; no se asume Entrada.')
    canonico={'employee_id':empleado_externo,'card_number':marca['tarjeta'],
              'device_id':marca['reloj'],'event_type':event_values[marca['tipo']],
              'method':marca['metodo'],'source_id':marca['id']}
    if datetime_mode=='combined': canonico['occurred_at']=dt
    elif datetime_mode=='split': canonico.update(date=dt.date(),time=dt.time())
    else: raise ValueError('Formato temporal de destino inválido.')
    return {destino:canonico[origen] for origen,destino in columns.items()}
