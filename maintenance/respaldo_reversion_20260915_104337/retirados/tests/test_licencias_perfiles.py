import json
import os
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch
from cryptography.hazmat.primitives.asymmetric import rsa, ed25519
from cryptography.exceptions import InvalidSignature
from app import licencias
from app import perfiles
from app.proteccion_windows import proteger, desproteger
from tools.emitir_licencia import emitir, siguiente_anio

class LicenciasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.device = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.issuer = ed25519.Ed25519PrivateKey.generate()
        cls.request = {'version':1,'producto':licencias.PRODUCTO,'instalacion_id':licencias.id_instalacion(cls.device.public_key()),'clave_publica':licencias.public_pem(cls.device.public_key()).decode()}
        cls.start = datetime(2026,9,14,12,tzinfo=timezone.utc)
    def payload(self):
        data=emitir(self.request,'Empresa A',self.issuer,self.start)
        return licencias.abrir_licencia(data,self.device,self.issuer.public_key())
    def test_encrypted_roundtrip(self):
        data=emitir(self.request,'Empresa A',self.issuer,self.start)
        self.assertNotIn(b'Empresa A',data)
        payload=licencias.abrir_licencia(data,self.device,self.issuer.public_key())
        self.assertEqual(payload['vencimiento'],'2027-09-14T12:00:00+00:00')
        licencias.validar_vigencia(payload,self.start)
    def test_tampering_wrong_issuer_wrong_installation(self):
        data=emitir(self.request,'Empresa A',self.issuer,self.start)
        modified=json.loads(data);modified['datos']='AAAA'
        with self.assertRaises(InvalidSignature):licencias.abrir_licencia(licencias.canonico(modified),self.device,self.issuer.public_key())
        with self.assertRaises(InvalidSignature):licencias.abrir_licencia(data,self.device,ed25519.Ed25519PrivateKey.generate().public_key())
        other=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        with self.assertRaises(ValueError):licencias.abrir_licencia(data,other,self.issuer.public_key())
    def test_expiration_future_and_clock_rollback(self):
        payload=self.payload()
        for now,last in [(self.start-timedelta(seconds=1),None),(siguiente_anio(self.start),None),(self.start,self.start.timestamp()+600)]:
            with self.assertRaises(ValueError):licencias.validar_vigencia(payload,now,last)
        self.assertEqual(siguiente_anio(datetime(2024,2,29,tzinfo=timezone.utc)).day,28)
    def test_dpapi_and_activation_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{'LOCALAPPDATA':tmp}), patch.object(licencias,'_publica_emisor',return_value=self.issuer.public_key()):
            self.assertEqual(desproteger(proteger(b'secreto')),b'secreto')
            self.assertFalse(licencias.estado_licencia()[0])
            req=json.loads(licencias.crear_solicitud('Cliente'))
            key=licencias._privada_instalacion()
            self.assertEqual(req['instalacion_id'],licencias.id_instalacion(key.public_key()))
            start=datetime.now(timezone.utc)-timedelta(seconds=1)
            archivo=Path(tmp)/'activa.cbslic'
            archivo.write_bytes(emitir(req,'Cliente',self.issuer,start))
            licencias.instalar_licencia(archivo)
            self.assertTrue(licencias.estado_licencia()[0])
            renewal=Path(tmp)/'renovacion.cbslic'
            renewal.write_bytes(emitir(req,'Cliente',self.issuer,siguiente_anio(start)))
            self.assertTrue(licencias.instalar_licencia(renewal)['programada'])
            self.assertTrue(licencias.estado_licencia()[0])
            archivo.write_text('{}')
            with self.assertRaises(ValueError):licencias.instalar_licencia(archivo)
            self.assertTrue(licencias.estado_licencia()[0])
    def test_scheduled_renewal_activates_at_boundary(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'LOCALAPPDATA':tmp}),patch.object(licencias,'_publica_emisor',return_value=self.issuer.public_key()):
            request=json.loads(licencias.crear_solicitud('Cliente'))
            start=datetime.now(timezone.utc)-timedelta(seconds=1)
            license_file=Path(tmp)/'first.cbslic'
            license_file.write_bytes(emitir(request,'Cliente',self.issuer,start))
            licencias.instalar_licencia(license_file)
            renewal=Path(tmp)/'renewal.cbslic'
            renewal.write_bytes(emitir(request,'Cliente',self.issuer,siguiente_anio(start)))
            licencias.instalar_licencia(renewal)
            class Future(datetime):
                @classmethod
                def now(cls,tz=None):return siguiente_anio(start)+timedelta(seconds=1)
            with patch.object(licencias,'datetime',Future):
                valid,_,payload=licencias.estado_licencia()
                self.assertTrue(valid)
                self.assertEqual(payload['inicio'],siguiente_anio(start).isoformat())

    def test_missing_license_blocks_operations(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'LOCALAPPDATA':tmp}):
            with self.assertRaises(ValueError):licencias.exigir_licencia()

class PerfilesTests(unittest.TestCase):
    def test_isolation_and_excel_default(self):
        from resources.config_path import guardar_relojes,cargar_relojes
        from app.database.database import Database
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{'LOCALAPPDATA':tmp}):
            self.assertFalse(perfiles.integracion_habilitada())
            uno=perfiles.crear_perfil('Empresa A')
            dos=perfiles.crear_perfil('Empresa B')
            perfiles.activar_perfil(uno)
            guardar_relojes([{'tipo':'zkteco','params':{'dispositivo_id':'1'}}])
            db1=Database()
            db1.guardar_marcacion('1','93','2026-09-07 08:35:00',0,'huella')
            perfiles.configurar_perfil('Empresa A',True)
            perfiles.activar_perfil(dos)
            self.assertFalse(perfiles.integracion_habilitada())
            self.assertEqual(cargar_relojes(),[])
            db2=Database()
            self.assertEqual(db2.obtener_todas_marcaciones('2026-09-01','2026-09-30'),[])
            self.assertNotEqual(db1.ruta,db2.ruta)
            self.assertFalse((perfiles.directorio_perfil()/'config_conexion.py').exists())
            perfiles.activar_perfil(uno)
            self.assertTrue(perfiles.integracion_habilitada())
            self.assertEqual(len(cargar_relojes()),1)
            self.assertEqual(len(db1.obtener_todas_marcaciones('2026-09-01','2026-09-30')),1)
    def test_legacy_configuration_preserved(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'LOCALAPPDATA':tmp}):
            root=perfiles.raiz_datos();root.mkdir()
            original=root/'config_conexion.py';original.write_text('legacy')
            self.assertTrue(perfiles.integracion_habilitada())
            self.assertEqual(perfiles.directorio_perfil(),root)
            self.assertEqual(original.read_text(),'legacy')

if __name__=='__main__':unittest.main()
