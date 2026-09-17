"""Herramienta del proveedor. No distribuir junto con la aplicación."""
import argparse
import getpass
import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa, padding
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from app.licencias import PRODUCTO, AAD, MAX_ARCHIVO, canonico, b64, public_pem, id_instalacion, escribir_atomico
from app.proteccion_windows import proteger, desproteger

RAIZ = Path(__file__).resolve().parents[1]
PRIVADA = RAIZ / '.license-issuer' / 'emisor.dpapi'
PUBLICA = RAIZ / 'resources' / 'license_public.pem'

def inicializar():
    if PRIVADA.exists() or PUBLICA.exists():
        raise ValueError('Ya existe una clave. No se reemplaza para conservar las licencias emitidas.')
    key = ed25519.Ed25519PrivateKey.generate()
    raw = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    escribir_atomico(PRIVADA, proteger(raw))
    escribir_atomico(PUBLICA, public_pem(key.public_key()))

def siguiente_anio(inicio):
    try:
        return inicio.replace(year=inicio.year + 1)
    except ValueError:
        return inicio.replace(year=inicio.year + 1, day=28)

def emitir(solicitud, cliente, key, inicio=None):
    if solicitud.get('version') != 1 or solicitud.get('producto') != PRODUCTO:
        raise ValueError('Solicitud no compatible.')
    publica = serialization.load_pem_public_key(solicitud['clave_publica'].encode('ascii'))
    if not isinstance(publica, rsa.RSAPublicKey) or publica.key_size < 2048 or publica.key_size > 4096:
        raise ValueError('Clave de instalación inválida.')
    if solicitud['instalacion_id'] != id_instalacion(publica) or not cliente.strip():
        raise ValueError('Solicitud o cliente inválido.')
    inicio = inicio or datetime.now(timezone.utc)
    if inicio.tzinfo is None:
        raise ValueError('La fecha de inicio requiere zona horaria.')
    payload = {'producto':PRODUCTO, 'cliente':cliente.strip(), 'instalacion_id':solicitud['instalacion_id'],
               'inicio':inicio.isoformat(), 'vencimiento':siguiente_anio(inicio).isoformat()}
    secreto = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(12)
    sobre = {'version':1, 'clave':b64(publica.encrypt(secreto, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))),
             'nonce':b64(nonce), 'datos':b64(AESGCM(secreto).encrypt(nonce, canonico(payload), AAD))}
    sobre['firma'] = b64(key.sign(canonico(sobre)))
    return canonico(sobre)

def main():
    parser = argparse.ArgumentParser(description='Emisor de licencias anuales ConectBioSync')
    sub = parser.add_subparsers(dest='accion', required=True)
    sub.add_parser('inicializar')
    em = sub.add_parser('emitir')
    em.add_argument('solicitud', type=Path)
    em.add_argument('--cliente', required=True)
    em.add_argument('--salida', required=True, type=Path)
    em.add_argument('--codigo', type=Path, help='Guardar también un código de extensión CBS1 para pegar en la aplicación.')
    em.add_argument('--inicio', help='Inicio ISO 8601 con zona; por defecto ahora. Para renovar anticipadamente usar el vencimiento actual.')
    bak = sub.add_parser('respaldar-clave')
    bak.add_argument('salida', type=Path)
    restore = sub.add_parser('restaurar-clave')
    restore.add_argument('respaldo', type=Path)
    args = parser.parse_args()
    try:
        if args.accion == 'inicializar':
            inicializar()
            print('Clave privada protegida con Windows. Clave pública lista para compilar la aplicación.')
            return
        if args.accion == 'restaurar-clave':
            if PRIVADA.exists():
                raise ValueError('Ya existe una clave privada local; no se reemplaza.')
            password = getpass.getpass('Contraseña del respaldo: ')
            key = serialization.load_pem_private_key(args.respaldo.read_bytes(), password=password.encode())
            if not isinstance(key, ed25519.Ed25519PrivateKey):
                raise ValueError('Clave de emisión no compatible.')
            publica = public_pem(key.public_key())
            if PUBLICA.exists() and PUBLICA.read_bytes() != publica:
                raise ValueError('El respaldo no corresponde a la clave pública de esta distribución.')
            raw = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
            escribir_atomico(PRIVADA, proteger(raw))
            escribir_atomico(PUBLICA, publica)
            print('Clave de emisión restaurada y protegida para este usuario de Windows.')
            return
        raw = desproteger(PRIVADA.read_bytes())
        key = serialization.load_pem_private_key(raw, password=None)
        if args.accion == 'respaldar-clave':
            password = getpass.getpass('Contraseña para cifrar el respaldo: ')
            if len(password) < 12 or password != getpass.getpass('Repetir contraseña: '):
                raise ValueError('Usá una contraseña de al menos 12 caracteres y confirmala.')
            data = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.BestAvailableEncryption(password.encode()))
            with args.salida.open('xb') as f: f.write(data)
            print('Respaldo cifrado creado. Guardalo separado del código y de la contraseña.')
            return
        with args.solicitud.open('rb') as f: data = f.read(MAX_ARCHIVO + 1)
        if len(data) > MAX_ARCHIVO: raise ValueError('Solicitud demasiado grande.')
        inicio = datetime.fromisoformat(args.inicio) if args.inicio else None
        licencia = emitir(json.loads(data), args.cliente, key, inicio)
        with args.salida.open('xb') as f: f.write(licencia)
        if args.codigo:
            with args.codigo.open('x', encoding='ascii') as f: f.write('CBS1.' + b64(licencia))
        print('Licencia anual creada:', args.salida)
    except Exception as exc:
        parser.exit(1, f'Error: {exc}\n')

if __name__ == '__main__': main()
