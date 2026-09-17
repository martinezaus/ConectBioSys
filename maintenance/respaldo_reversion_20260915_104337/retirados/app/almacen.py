"""SQLite cifrado con DPAPI. Una conexión por operación, segura entre hilos."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from app.proteccion_windows import proteger, desproteger

@contextmanager
def conectar():
    from app.perfiles import raiz_datos
    ruta = raiz_datos() / 'configuracion.db'
    ruta.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(ruta, timeout=15)
    try:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE IF NOT EXISTS ajustes (clave TEXT PRIMARY KEY, valor BLOB NOT NULL)')
        db.commit()
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def leer(clave, defecto=None, db=None):
    if db is None:
        with conectar() as conexion: return leer(clave, defecto, conexion)
    fila = db.execute('SELECT valor FROM ajustes WHERE clave=?', (clave,)).fetchone()
    if fila is None: return defecto
    sobre = json.loads(desproteger(fila[0]))
    if sobre['clave'] != clave: raise ValueError('Registro cifrado incompatible.')
    return sobre['valor']

def guardar(clave, valor, db=None):
    if db is None:
        with conectar() as conexion: return guardar(clave, valor, conexion)
    contenido = proteger(json.dumps({'clave':clave,'valor':valor}, ensure_ascii=False).encode('utf-8'))
    db.execute('INSERT INTO ajustes VALUES (?,?) ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor', (clave,contenido))

def importar_literal(ruta, variable, defecto):
    import ast
    ruta = Path(ruta)
    if not ruta.exists(): return defecto
    for nodo in ast.parse(ruta.read_text(encoding='utf-8-sig')).body:
        if isinstance(nodo,ast.Assign) and any(isinstance(t,ast.Name) and t.id==variable for t in nodo.targets):
            return ast.literal_eval(nodo.value)
    raise ValueError(f'No se encontró {variable} en la configuración anterior.')
