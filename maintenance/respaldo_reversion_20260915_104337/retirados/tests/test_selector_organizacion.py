import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import sqlite3
import unittest
from datetime import time
from unittest.mock import patch
from sqlalchemy import create_engine, text
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QThreadPool
from app.api.organizaciones import consultar_organizaciones
from app.api import asistencias
from resources.config_path import normalizar_config_empleados
from main import TablaMarcacionesDialog

class SelectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.license_patch=patch('main.estado_licencia',return_value=(True,'OK',{}))
        self.license_patch.start()
        self.addCleanup(self.license_patch.stop)
        self.cfg=normalizar_config_empleados({'tabla':'empleados','columna_id':'n_reloj','columna_nombre':'nombre','columna_condicion':'organizacion_id=1'})
    def dialog(self, rows=None, error=None):
        with patch('app.selector_organizacion.cargar_config_conexion',return_value={}), patch('main.integracion_habilitada',return_value=True), patch('main.estado_licencia',return_value=(True,'OK',{})), patch('main.cargar_config_empleados',return_value=self.cfg), patch('app.selector_organizacion.obtener_organizaciones',return_value=rows or [],side_effect=error):
            d=TablaMarcacionesDialog([(1,'93','2026-09-07 08:35:00','Entrada','huella')])
            QThreadPool.globalInstance().waitForDone(2000)
            self.app.processEvents()
        return d
    def test_selection_controls_destination(self):
        d=self.dialog([('1','Organización A'),('2','Organización B')])
        self.assertTrue(d.boton_enviar_mysql.isHidden())
        self.assertFalse(d.boton_exportar_excel.isHidden())
        d._elegir_mysql()
        self.assertIsNone(d.destino)
        d.selector_organizacion.combo.setCurrentIndex(2)
        self.assertFalse(d.boton_enviar_mysql.isHidden())
        self.assertEqual(d.selector_organizacion.configuracion_seleccionada()['valor_organizacion'],'2')
        self.assertEqual(self.cfg['valor_organizacion'],'1')
        d.selector_organizacion.combo.setCurrentIndex(0)
        self.assertTrue(d.boton_enviar_mysql.isHidden())
        d.close()
    def test_excel_only_never_loads_connection(self):
        with patch('main.integracion_habilitada',return_value=False), patch('app.selector_organizacion.cargar_config_conexion') as connection, patch('main.cargar_config_empleados') as mapping:
            d=TablaMarcacionesDialog([])
            self.assertTrue(d.boton_enviar_mysql.isHidden())
            connection.assert_not_called()
            mapping.assert_not_called()
            d.close()

    def test_empty_and_unavailable_keep_excel(self):
        for error in [None,RuntimeError('offline')]:
            d=self.dialog(error=error)
            self.assertTrue(d.boton_enviar_mysql.isHidden())
            self.assertFalse(d.boton_exportar_excel.isHidden())
            self.assertIsNone(d.selector_organizacion.configuracion_seleccionada())
            d._elegir_excel()
            self.assertEqual(d.destino,'excel')
            d.close()

class CatalogoTests(unittest.TestCase):
    def setUp(self):
        self.engine=create_engine('sqlite:///:memory:')
        self.cfg=normalizar_config_empleados({'tabla':'empleados','columna_id':'n_reloj','columna_nombre':'nombre','columna_condicion':'organizacion_id=1','tabla_catalogo_organizaciones':'organizaciones'})
        with self.engine.begin() as c:
            c.execute(text('CREATE TABLE organizaciones(id INTEGER, nombre TEXT)'))
            c.execute(text("INSERT INTO organizaciones VALUES(1,'A'),(2,'B')"))
            c.execute(text('CREATE TABLE empleados(id INTEGER, n_reloj TEXT, nombre TEXT, organizacion_id INTEGER)'))
            c.execute(text("INSERT INTO empleados VALUES (92,'93','Uno',1),(501,'93','Dos',2)"))
            c.execute(text('CREATE TABLE asistencias(empleados_id INTEGER, fecha TEXT, hora TEXT, tipo TEXT, reloj INTEGER, c_ver INTEGER)'))
        self.tabla={'tabla':'asistencias',**{'columna_'+k:v for k,v in [('empleado','empleados_id'),('fecha','fecha'),('hora','hora'),('tipo','tipo'),('reloj','reloj'),('c_ver','c_ver')]}}
    def tearDown(self): self.engine.dispose()
    def test_named_catalog_and_registered_ids(self):
        with self.engine.connect() as c:
            self.assertEqual(consultar_organizaciones(c,self.cfg),[('1','A'),('2','B')])
            cfg=dict(self.cfg,tabla_catalogo_organizaciones='')
            self.assertEqual(consultar_organizaciones(c,cfg),[('1','Organización 1'),('2','Organización 2')])
    def test_integration_off_and_license_missing_block_before_connection(self):
        with patch.object(asistencias,'exigir_licencia',side_effect=ValueError('Vencida')),patch.object(asistencias,'crear_engine_externo') as engine:
            with self.assertRaises(ValueError):asistencias.enviar_marcaciones([],self.cfg)
            engine.assert_not_called()
        with patch.object(asistencias,'exigir_licencia'),patch.object(asistencias,'integracion_habilitada',return_value=False),patch.object(asistencias,'crear_engine_externo') as engine:
            with self.assertRaises(ValueError):asistencias.enviar_marcaciones([],self.cfg)
            engine.assert_not_called()

    def test_selected_scope_and_removed_organization(self):
        sqlite3.register_adapter(time,lambda t:t.isoformat())
        filas=[(1,'93','2026-09-07 08:35:00','Entrada','huella')]
        cfg=dict(self.cfg,valor_organizacion='2')
        with patch.object(self.engine,'dispose'), patch.object(asistencias,'exigir_licencia'), patch.object(asistencias,'integracion_habilitada',return_value=True), patch.object(asistencias,'crear_engine_externo',return_value=self.engine),patch.object(asistencias,'cargar_config_conexion',return_value={}),patch.object(asistencias,'cargar_config_asistencias',return_value=self.tabla):
            self.assertEqual(asistencias.enviar_marcaciones(filas,cfg)[:2],(1,0))
            with self.engine.begin() as c:
                self.assertEqual(c.execute(text('SELECT empleados_id FROM asistencias')).scalar_one(),501)
                c.execute(text('DELETE FROM organizaciones WHERE id=2'))
            with self.assertRaises(ValueError): asistencias.enviar_marcaciones(filas,cfg)
            with self.engine.connect() as c:
                self.assertEqual(c.execute(text('SELECT COUNT(*) FROM asistencias')).scalar_one(),1)

if __name__=='__main__':unittest.main()
