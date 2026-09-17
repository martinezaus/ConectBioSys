"""Verificación offline. Este módulo nunca contiene la clave de emisión."""
import base64
import hashlib
import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import rsa, padding, ed25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from app.perfiles import raiz_datos
from app.proteccion_windows import proteger, desproteger

PRODUCTO = 'ConectBioSync'
AAD = b'ConectBioSync/licencia/v1'
MAX_ARCHIVO = 65536

def canonico(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')

def b64(data): return base64.b64encode(data).decode('ascii')
def unb64(value): return base64.b64decode(value, validate=True)

def escribir_atomico(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporal = path.with_suffix(path.suffix + '.tmp')
    temporal.write_bytes(data)
    temporal.replace(path)

def public_pem(key):
    return key.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)

def id_instalacion(key):
    return hashlib.sha256(public_pem(key)).hexdigest()

def _carpeta(): return raiz_datos() / 'licencia'

def _leer_blob(nombre):
    from app.almacen import leer, guardar
    clave = 'licencia/' + nombre
    valor = leer(clave)
    if valor is None:
        ruta = _carpeta() / nombre
        if ruta.exists():
            valor = b64(ruta.read_bytes())
            guardar(clave, valor)
    return unb64(valor) if valor is not None else None


def _guardar_blob(nombre, data):
    from app.almacen import guardar
    guardar('licencia/' + nombre, b64(data))


def _privada_instalacion():
    data = _leer_blob('instalacion.dpapi')
    if data is None:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        raw = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        data = proteger(raw)
        _guardar_blob('instalacion.dpapi', data)
    return serialization.load_pem_private_key(desproteger(data), password=None)


def crear_solicitud(cliente):
    if not cliente.strip():
        raise ValueError('Ingresá el nombre del cliente.')
    key = _privada_instalacion().public_key()
    return canonico({'version':1, 'producto':PRODUCTO, 'cliente':cliente.strip(),
                    'instalacion_id':id_instalacion(key), 'clave_publica':public_pem(key).decode('ascii')})

def _publica_emisor():
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
    ruta = base / 'resources' / 'license_public.pem'
    if not ruta.exists():
        raise ValueError('Esta distribución no tiene configurada la clave pública de licencias.')
    return serialization.load_pem_public_key(ruta.read_bytes())

def abrir_licencia(data, privada, emisor):
    if len(data) > MAX_ARCHIVO:
        raise ValueError('El archivo de licencia es demasiado grande.')
    sobre = json.loads(data)
    if sobre.get('version') != 1:
        raise ValueError('Formato de licencia no compatible.')
    firma = unb64(sobre.pop('firma'))
    emisor.verify(firma, canonico(sobre))
    secreto = privada.decrypt(unb64(sobre['clave']), padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
    payload = json.loads(AESGCM(secreto).decrypt(unb64(sobre['nonce']), unb64(sobre['datos']), AAD))
    if payload['producto'] != PRODUCTO or payload['instalacion_id'] != id_instalacion(privada.public_key()):
        raise ValueError('La licencia no corresponde a esta instalación.')
    if not isinstance(payload.get('cliente'), str) or not payload['cliente'].strip():
        raise ValueError('Cliente de licencia inválido.')
    inicio = datetime.fromisoformat(payload['inicio'])
    fin = datetime.fromisoformat(payload['vencimiento'])
    if inicio.tzinfo is None or fin.tzinfo is None or fin <= inicio:
        raise ValueError('Fechas de licencia inválidas.')
    return payload

def validar_vigencia(payload, ahora=None, ultimo=None):
    ahora = ahora or datetime.now(timezone.utc)
    if ultimo is not None and ahora.timestamp() + 300 < ultimo:
        raise ValueError('La fecha del equipo retrocedió. Corregí el reloj antes de continuar.')
    if ahora < datetime.fromisoformat(payload['inicio']):
        raise ValueError('La licencia todavía no está vigente.')
    if ahora >= datetime.fromisoformat(payload['vencimiento']):
        raise ValueError('La licencia venció. Importá la renovación anual.')

def _ultimo_control():
    data = _leer_blob('control.dpapi')
    return float(desproteger(data).decode('ascii')) if data else None


def _guardar_control(ahora):
    ultimo = _ultimo_control()
    _guardar_blob('control.dpapi', proteger(str(max(ahora.timestamp(), ultimo or 0)).encode('ascii')))


def aniversario(inicio):
    try: return inicio.replace(year=inicio.year + 1)
    except ValueError: return inicio.replace(year=inicio.year + 1, day=28)


def registrar_primera_activacion(cliente):
    """Una sola activación por instalación. No reinicia licencias existentes."""
    from app.almacen import conectar, leer, guardar
    cliente = cliente.strip()
    if not cliente: raise ValueError('Ingresá el titular de la licencia.')
    existente = _leer_blob('activa.cbslic')
    if existente is not None:
        raise ValueError('Esta instalación ya tiene una licencia. Importá una renovación.')
    key = _privada_instalacion()
    with conectar() as db:
        db.execute('BEGIN IMMEDIATE')
        anterior = leer('licencia/registro', db=db)
        if anterior is not None: return anterior
        ahora = datetime.now(timezone.utc)
        payload = dict(producto=PRODUCTO,cliente=cliente,instalacion_id=id_instalacion(key.public_key()),
                       inicio=ahora.isoformat(),vencimiento=aniversario(ahora).isoformat())
        guardar('licencia/registro', payload, db)
    _guardar_control(ahora)
    return payload


def _payload_actual():
    from app.almacen import leer
    data = _leer_blob('activa.cbslic')
    if data is not None:
        return abrir_licencia(data, _privada_instalacion(), _publica_emisor())
    payload = leer('licencia/registro')
    if payload is not None and payload['instalacion_id'] != id_instalacion(_privada_instalacion().public_key()):
        raise ValueError('El registro pertenece a otra instalación.')
    return payload


def instalar_licencia(ruta):
    with Path(ruta).open('rb') as f: return instalar_datos_licencia(f.read(MAX_ARCHIVO + 1))


def instalar_codigo(codigo):
    try:
        if len(codigo) > MAX_ARCHIVO * 2: raise ValueError()
        data = unb64(codigo.strip().removeprefix('CBS1.'))
    except Exception as exc:
        raise ValueError('Código de extensión inválido.') from exc
    return instalar_datos_licencia(data)


def instalar_datos_licencia(data):
    try:
        payload = abrir_licencia(data, _privada_instalacion(), _publica_emisor())
        ahora = datetime.now(timezone.utc)
        anterior = _payload_actual()
        pendiente = _leer_blob('renovacion.cbslic')
        limite = datetime.fromisoformat(anterior['vencimiento']) if anterior else None
        if pendiente:
            previa = abrir_licencia(pendiente, _privada_instalacion(), _publica_emisor())
            limite = max(limite or datetime.min.replace(tzinfo=timezone.utc), datetime.fromisoformat(previa['vencimiento']))
        if limite and datetime.fromisoformat(payload['vencimiento']) <= limite:
            raise ValueError('La renovación ya fue utilizada o no amplía la vigencia.')
        if ahora < datetime.fromisoformat(payload['inicio']):
            if anterior is None: raise ValueError('La licencia todavía no está vigente.')
            validar_vigencia(anterior, ahora, _ultimo_control())
            if datetime.fromisoformat(payload['inicio']) > datetime.fromisoformat(anterior['vencimiento']):
                raise ValueError('La renovación deja un período sin licencia.')
            _guardar_blob('renovacion.cbslic', data)
            return dict(payload, programada=True)
        validar_vigencia(payload, ahora, _ultimo_control())
    except ValueError: raise
    except Exception as exc:
        raise ValueError('Licencia inválida, alterada o emitida para otra instalación.') from exc
    _guardar_control(ahora)
    _guardar_blob('activa.cbslic', data)
    return payload


def estado_licencia():
    payload = None
    try:
        payload = _payload_actual()
        if payload is None: return False, 'Sin activar. Registrá la instalación para iniciar el primer año.', None
        ahora = datetime.now(timezone.utc)
        pendiente = _leer_blob('renovacion.cbslic')
        if pendiente:
            nuevo = abrir_licencia(pendiente, _privada_instalacion(), _publica_emisor())
            if ahora >= datetime.fromisoformat(nuevo['inicio']) and datetime.fromisoformat(nuevo['vencimiento']) > datetime.fromisoformat(payload['vencimiento']):
                validar_vigencia(nuevo, ahora, _ultimo_control())
                _guardar_blob('activa.cbslic', pendiente)
                payload = nuevo
        validar_vigencia(payload, ahora, _ultimo_control())
        _guardar_control(ahora)
        import math
        dias = math.ceil((datetime.fromisoformat(payload['vencimiento']) - ahora).total_seconds()/86400)
        return True, f"Activa — {dias} días restantes — vence {payload['vencimiento'][:10]} — {payload['cliente']}", payload
    except ValueError as exc:
        detalle = f" Vencimiento: {payload['vencimiento'][:10]}." if payload else ''
        return False, str(exc) + detalle, payload
    except Exception: return False, 'No se pudo validar la licencia de esta instalación.', None


def exigir_licencia():
    valida, mensaje, payload = estado_licencia()
    if not valida: raise ValueError(mensaje)
    return payload
