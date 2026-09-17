import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json
import tempfile
import threading
import unittest
from pathlib import Path
from datetime import date,datetime,timezone
from contextlib import ExitStack
from unittest.mock import patch,MagicMock
from PyQt6.QtCore import QEventLoop,QTimer
from PyQt6.QtWidgets import QApplication
from sqlalchemy import create_engine,text
from app import almacen,licencias,perfiles,servicios
from resources import config_path
from app.api import asistencias
from app.api.modelos import LecturaReloj

class NuevaVersionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{'LOCALAPPDATA':self.tmp.name});self.env.start()
        perfiles.activar_perfil(perfiles.crear_perfil('Prueba'))
    def tearDown(self):
        self.env.stop();self.tmp.cleanup()
    def test_config_migrates_without_executing_and_encrypts_secrets(self):
        raiz=perfiles.directorio_perfil();raiz.mkdir(parents=True)
        ruta=raiz/'config_conexion.py'
        cfg=dict(motor='mysql',host='localhost',puerto=3306,usuario='u',password='secreto-único',base_datos='bd')
        ruta.write_text('raise RuntimeError("NO EJECUTAR")\nCONEXION_CONFIG = '+repr(cfg),encoding='utf-8')
        self.assertEqual(config_path.cargar_config_conexion(),cfg)
        self.assertNotIn('secreto',ruta.read_text())
        config_path.guardar_config_conexion(dict(cfg,password='nuevo secreto'))
        self.assertEqual(config_path.cargar_config_conexion()['password'],'nuevo secreto')
        raw=(perfiles.raiz_datos()/'configuracion.db').read_bytes()
        self.assertNotIn(b'nuevo secreto',raw)
        self.assertNotIn('secreto-único'.encode(),raw)
    def test_tampered_encrypted_record_rejected(self):
        almacen.guardar('a',{'dato':1})
        with almacen.conectar() as db: db.execute("UPDATE ajustes SET valor=? WHERE clave='a'",(b'bad',))
        with self.assertRaises(Exception): almacen.leer('a')
    def test_activation_exact_anniversary_and_idempotent_across_profiles(self):
        payload=licencias.registrar_primera_activacion('Empresa')
        inicio=datetime.fromisoformat(payload['inicio'])
        self.assertEqual(payload['vencimiento'],licencias.aniversario(inicio).isoformat())
        perfiles.activar_perfil(perfiles.crear_perfil('Otra empresa'))
        self.assertEqual(licencias.registrar_primera_activacion('Otro'),payload)
        self.assertTrue(licencias.estado_licencia()[0])
        self.assertEqual(licencias.aniversario(datetime(2024,2,29,tzinfo=timezone.utc)),datetime(2025,2,28,tzinfo=timezone.utc))
    def test_code_renewal_and_replay(self):
        from tools.emitir_licencia import emitir
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        key=Ed25519PrivateKey.generate()
        payload=licencias.registrar_primera_activacion('Empresa')
        solicitud=json.loads(licencias.crear_solicitud('Empresa'))
        data=emitir(solicitud,'Empresa',key,datetime.fromisoformat(payload['vencimiento']))
        with patch.object(licencias,'_publica_emisor',return_value=key.public_key()):
            codigo='CBS1.'+licencias.b64(data)
            self.assertTrue(licencias.instalar_codigo(codigo)['programada'])
            with self.assertRaises(ValueError):licencias.instalar_codigo(codigo)
    def test_filter_boundaries(self):
        self.assertEqual(servicios.rango_filtro(0,hoy=date(2026,1,2))[:2],('2025-12-01','2025-12-31'))
        self.assertEqual(servicios.rango_filtro(1,hoy=date(2026,9,15))[:2],('2026-09-09','2026-09-15'))
        with self.assertRaises(ValueError):servicios.rango_filtro(2,date.today(),date.today(),'')
        with self.assertRaises(ValueError):servicios.rango_filtro(3,date(2026,9,3),date(2026,9,1))
    def test_excel_table_dates_and_formula_safety(self):
        from openpyxl import load_workbook
        ruta=Path(self.tmp.name)/'salida.xlsx'
        filas=[('1','001','2026-09-07 08:35:00','Entrada','huella')]
        servicios.exportar_excel(filas,ruta,lambda *a:None,lambda:None,{'001':'=1+1'})
        wb=load_workbook(ruta);ws=wb.active
        self.assertEqual(ws['B2'].value,'001')
        self.assertEqual(ws['C2'].data_type,'s')
        self.assertEqual(ws['D2'].value,datetime(2026,9,7,8,35))
        self.assertIn('Marcaciones',ws.tables);wb.close()
    def test_download_card_scope_duplicates_and_disconnect(self):
        adapter=MagicMock();adapter.conectar.return_value=True
        adapter.obtener_marcaciones.return_value=[LecturaReloj('93',datetime(2026,9,7,8,35),0,'1','huella'),LecturaReloj('94',datetime(2026,9,7,9),0,'1','huella')]
        ruta=Path(self.tmp.name)/'lecturas.db';config=[{'tipo':'zkteco','params':{'dispositivo_id':'1'}}]
        with patch.object(servicios,'exigir_licencia'),patch.object(servicios,'crear_adaptador',return_value=adapter):
            result=servicios.descargar(config,ruta,'2026-09-01','2026-09-30','93',lambda *a:None,lambda:None)
            self.assertEqual(result['guardadas'],1);self.assertEqual(len(result['filas']),1)
            result=servicios.descargar(config,ruta,'2026-09-01','2026-09-30','93',lambda *a:None,lambda:None)
            self.assertEqual(result['duplicadas'],1)
            self.assertEqual(adapter.desconectar.call_count,2)
    def test_buffer_never_clears_when_backup_fails(self):
        adapter=MagicMock();adapter.conectar.return_value=True;adapter.obtener_marcaciones.side_effect=RuntimeError('lectura fallida')
        with patch.object(servicios,'exigir_licencia'),patch.object(servicios,'crear_adaptador',return_value=adapter):
            with self.assertRaises(RuntimeError):servicios.limpiar_reloj({},Path(self.tmp.name)/'datos.db',lambda *a:None,lambda:None)
        adapter.limpiar_buffer.assert_not_called();adapter.desconectar.assert_called_once()
    def test_export_combined_datetime_resolved_id_and_no_repeat(self):
        engine=create_engine('sqlite:///:memory:')
        with engine.begin() as c:
            c.execute(text('CREATE TABLE empleados(id INTEGER PRIMARY KEY,n_reloj TEXT,nombre TEXT)'))
            c.execute(text("INSERT INTO empleados VALUES(92,'93','Persona')"))
            c.execute(text('CREATE TABLE destino(id INTEGER PRIMARY KEY,empleado INTEGER NOT NULL,momento DATETIME NOT NULL,tipo TEXT)'))
        config=dict(tabla='destino',columna_empleado='empleado',columna_fecha_hora='momento',columna_tipo='tipo',mapa_tipo={'Entrada':'IN'})
        empleados=dict(tabla='empleados',columna_id='n_reloj',columna_id_interno='id',columna_nombre='nombre',modo_organizacion='unica')
        with ExitStack() as stack:
            for nombre,valor in [('exigir_licencia',None),('integracion_habilitada',True),('crear_engine_externo',engine),('cargar_config_conexion',{}),('cargar_config_asistencias',config)]:stack.enter_context(patch.object(asistencias,nombre,return_value=valor))
            stack.enter_context(patch.object(engine,'dispose'))
            filas=[('1','93','2026-09-07 08:35:00','Entrada','huella')]
            self.assertEqual(asistencias.enviar_marcaciones(filas,empleados)[:2],(1,0))
            self.assertEqual(asistencias.enviar_marcaciones(filas,empleados)[:2],(0,1))
            with engine.connect() as c:
                row=c.execute(text('SELECT empleado,momento,tipo FROM destino')).one()
                self.assertEqual(row[0],92);self.assertIn('08:35:00',row[1]);self.assertEqual(row[2],'IN')
        engine.dispose()
    def test_driver_specific_options_without_connecting(self):
        cfg=dict(host='localhost',puerto=1234,usuario='u',password='p@:/',base_datos='base')
        for motor in ('mysql','postgresql','sqlserver','oracle'):
            engine=config_path.crear_engine_externo(dict(cfg,motor=motor))
            self.assertEqual(engine.url.password,'p@:/')
            if motor=='oracle':self.assertEqual(engine.url.query['service_name'],'base')
            if motor=='sqlserver':self.assertIn('driver',engine.url.query)
            engine.dispose()
    def test_qthread_runs_off_ui_thread_and_cleans_up(self):
        from app.trabajos import ControladorTrabajo
        app=QApplication.instance() or QApplication([])
        controller=ControladorTrabajo();loop=QEventLoop();results=[]
        controller.resultado.connect(lambda result:(results.append(result),loop.quit()))
        QTimer.singleShot(5000,loop.quit)
        ui=threading.get_ident()
        controller.iniciar(lambda p,c:threading.get_ident())
        loop.exec()
        self.assertEqual(len(results),1);self.assertNotEqual(ui,results[0]);self.assertFalse(controller.esta_ocupado())

if __name__=='__main__':unittest.main()
