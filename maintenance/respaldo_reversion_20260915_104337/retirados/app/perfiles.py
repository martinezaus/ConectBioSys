"""Perfiles locales aislados; no dependen de un servidor de personal."""
import json
import os
import uuid
from pathlib import Path


def raiz_datos():
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'ConectBioSync'


def _guardar(registro):
    from app.almacen import guardar
    guardar('perfiles', registro)


def cargar_perfiles():
    from app.almacen import leer
    registro = leer('perfiles')
    if registro is not None:
        return registro
    ruta = raiz_datos() / 'perfiles.json'
    if ruta.exists():
        registro = json.loads(ruta.read_text(encoding='utf-8'))
        if not any(p['id'] == registro['activo'] for p in registro['perfiles']):
            raise ValueError('El perfil activo no existe.')
        _guardar(registro)
        return registro
    # Conservar las configuraciones existentes sin copiarlas a otros clientes.
    registro = {'activo':'default', 'perfiles':[{'id':'default', 'nombre':'Cliente principal',
                'integracion':(raiz_datos() / 'config_conexion.py').exists()}]}
    _guardar(registro)
    return registro


def perfil_actual():
    registro = cargar_perfiles()
    return next(dict(p) for p in registro['perfiles'] if p['id'] == registro['activo'])


def directorio_perfil():
    identificador = perfil_actual()['id']
    if identificador == 'default':
        return raiz_datos()
    uuid.UUID(identificador)  # El ID nunca se interpreta como una ruta libre.
    return raiz_datos() / 'perfiles' / identificador


def crear_perfil(nombre):
    nombre = nombre.strip()
    if not nombre:
        raise ValueError('Ingresá el nombre del cliente.')
    registro = cargar_perfiles()
    perfil = {'id':str(uuid.uuid4()), 'nombre':nombre, 'integracion':False}
    registro['perfiles'].append(perfil)
    _guardar(registro)
    return perfil['id']


def activar_perfil(identificador):
    registro = cargar_perfiles()
    if not any(p['id'] == identificador for p in registro['perfiles']):
        raise ValueError('Perfil inexistente.')
    registro['activo'] = identificador
    _guardar(registro)


def configurar_perfil(nombre, integracion):
    nombre = nombre.strip()
    if not nombre:
        raise ValueError('Ingresá el nombre del cliente.')
    registro = cargar_perfiles()
    for p in registro['perfiles']:
        if p['id'] == registro['activo']:
            p.update(nombre=nombre, integracion=bool(integracion))
    _guardar(registro)


def integracion_habilitada():
    return perfil_actual()['integracion']


def ruta_marcaciones():
    actual = perfil_actual()
    if actual.get('ruta_marcaciones'):
        ruta = Path(actual['ruta_marcaciones'])
        if not ruta.exists():
            raise FileNotFoundError(f'No se encuentra el histórico del cliente: {ruta}')
        return ruta
    if actual['id'] == 'default':
        # Compatibilidad con la ubicación usada por las versiones anteriores.
        import sys
        base = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1]
        anterior = base / 'data' / 'marcaciones.db'
        if anterior.exists():
            registro = cargar_perfiles()
            for p in registro['perfiles']:
                if p['id'] == 'default': p['ruta_marcaciones'] = str(anterior.resolve())
            _guardar(registro)
            return anterior
    return directorio_perfil() / 'data' / 'marcaciones.db'
