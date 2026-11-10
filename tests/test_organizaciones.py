import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from sqlalchemy import create_engine,text
from app.api import empleados,organizaciones
from resources import config_path

class OrganizacionTests(unittest.TestCase):
    def setUp(self):
        self.engine=create_engine('sqlite:///:memory:')
        self.config={'tabla':'empleados','columna_id':'n_reloj','columna_id_interno':'id','columna_nombre':'nombre','organizacion_id':'1'}
        with self.engine.begin() as c:
            c.execute(text('CREATE TABLE empleados(id INTEGER,n_reloj TEXT,nombre TEXT)'))
            c.execute(text("INSERT INTO empleados VALUES (92,'93','Persona A'),(501,'93','Persona B')"))
            c.execute(text('CREATE TABLE legajo(empleados_id INTEGER,organizacion_id INTEGER)'))
            c.execute(text('INSERT INTO legajo VALUES (92,1),(92,1),(501,2)'))
            c.execute(text('CREATE TABLE organizacion(id INTEGER,d_org TEXT)'))
            c.execute(text("INSERT INTO organizacion VALUES (1,'Empresa A'),(2,'Empresa B')"))
    def tearDown(self):self.engine.dispose()
    def test_repeated_card_scoped_by_legajo(self):
        with patch.object(empleados,'cargar_config_empleados',return_value=self.config),self.engine.connect() as c:
            self.assertEqual(empleados.resolver_id_empleado(c,'93'),92)
            self.config['organizacion_id']='2'
            self.assertEqual(empleados.resolver_id_empleado(c,'93'),501)
            self.config['organizacion_id']='3'
            with self.assertRaises(ValueError):empleados.resolver_id_empleado(c,'93')
    def test_duplicate_within_same_organization_is_rejected(self):
        with self.engine.begin() as c:c.execute(text('INSERT INTO legajo VALUES (501,1)'))
        with patch.object(empleados,'cargar_config_empleados',return_value=self.config),self.engine.connect() as c:
            with self.assertRaises(ValueError):empleados.resolver_id_empleado(c,'93')
    def test_excel_applies_same_filter(self):
        with patch.object(empleados,'cargar_config_empleados',return_value=self.config),patch.object(empleados,'cargar_config_conexion',return_value={}),patch.object(empleados,'crear_engine_externo',return_value=self.engine),patch.object(self.engine,'dispose'):
            self.assertEqual(empleados.obtener_mapa_empleados(),{'93':'Persona A'})
    def test_catalog_names_and_relationship(self):
        with patch.object(organizaciones,'crear_engine_externo',return_value=self.engine),patch.object(self.engine,'dispose'):
            filas,relacion=organizaciones.cargar_catalogo(self.config,{})
            self.assertEqual(filas,[('1','Empresa A'),('2','Empresa B')])
            self.assertEqual(relacion,{'tabla_relacion_organizacion':'legajo','columna_empleado_relacion':'empleados_id'})
    def test_save_roundtrip_and_legacy_id(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(config_path,'get_config_empleados_path',return_value=str(Path(tmp)/'empleados.py')):
            config_path.guardar_config_empleados(self.config)
            self.assertEqual(config_path.cargar_config_empleados()['organizacion_id'],'1')
            self.assertNotIn('columna_condicion',config_path.cargar_config_empleados())
        self.assertEqual(organizaciones.id_organizacion({'columna_condicion':'organizacion_id = 2'}),'2')
        self.assertEqual(organizaciones.id_organizacion({'columna_condicion':'1'}),'1')
        with self.assertRaises(ValueError):organizaciones.id_organizacion({'columna_condicion':'1 OR 1=1'})
    def test_direct_organization_column(self):
        with self.engine.begin() as c:
            c.execute(text('ALTER TABLE empleados ADD COLUMN organizacion_id INTEGER'))
            c.execute(text('UPDATE empleados SET organizacion_id=CASE id WHEN 92 THEN 1 ELSE 2 END'))
        with patch.object(empleados,'cargar_config_empleados',return_value=self.config),self.engine.connect() as c:
            self.assertEqual(empleados.resolver_id_empleado(c,'93'),92)
if __name__=='__main__':unittest.main()
