import unittest
from unittest.mock import patch
from sqlalchemy import create_engine, text
from app.api import empleados
from resources.config_path import normalizar_config_empleados

class OrganizacionTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')
        self.config = {'tabla':'empleados','columna_id':'n_reloj','columna_nombre':'nombre','columna_condicion':'organizacion_id = 1'}
        with self.engine.begin() as c:
            c.execute(text('CREATE TABLE empleados(id INTEGER, n_reloj TEXT, nombre TEXT, organizacion_id TEXT)'))
            c.execute(text("INSERT INTO empleados VALUES (92,'93','A','1'),(501,'93','B','2'),(10,'10','C','1')"))
        self.mock = patch.object(empleados,'cargar_config_empleados',side_effect=lambda:self.config)
        self.mock.start()
    def tearDown(self):
        self.mock.stop()
        self.engine.dispose()
    def test_legacy_filter_resolves_repeated_card(self):
        with self.engine.connect() as c:
            self.assertEqual(empleados.resolver_id_empleado(c,'93'),92)
            self.config.update(columna_organizacion='organizacion_id',valor_organizacion='2')
            self.assertEqual(empleados.resolver_id_empleado(c,'93'),501)
    def test_optional_filter_and_missing_card(self):
        self.config['columna_condicion']=''
        with self.engine.connect() as c:
            self.assertEqual(empleados.resolver_id_empleado(c,'10'),10)
            with self.assertRaises(ValueError): empleados.resolver_id_empleado(c,'93')
            with self.assertRaises(ValueError): empleados.resolver_id_empleado(c,'999')
    def test_excel_uses_same_scope(self):
        with patch.object(empleados,'crear_engine_externo',return_value=self.engine), patch.object(empleados,'cargar_config_conexion',return_value={}):
            self.assertEqual(empleados.obtener_mapa_empleados(),{'93':'A','10':'C'})
    def test_duplicate_inside_organization_rejected(self):
        with self.engine.begin() as c:
            c.execute(text("INSERT INTO empleados VALUES (502,'93','D','1')"))
            with self.assertRaises(ValueError): empleados.resolver_id_empleado(c,'93')
    def test_parameterized_value(self):
        self.config.update(columna_organizacion='organizacion_id',valor_organizacion="1 OR 1=1")
        with self.engine.connect() as c:
            with self.assertRaises(ValueError): empleados.resolver_id_empleado(c,'93')
    def test_custom_column_and_saved_configuration(self):
        from tempfile import TemporaryDirectory
        from resources import config_path
        with self.engine.begin() as c:
            c.execute(text('ALTER TABLE empleados RENAME COLUMN organizacion_id TO empresa_codigo'))
            self.config.update(columna_organizacion='empresa_codigo', valor_organizacion='2')
            self.assertEqual(empleados.resolver_id_empleado(c,'93'),501)
        with TemporaryDirectory() as folder:
            path = str(__import__('pathlib').Path(folder) / 'config.py')
            with patch.dict(__import__('os').environ, {'LOCALAPPDATA':folder}):
                config_path.guardar_config_empleados(self.config)
                saved = config_path.cargar_config_empleados()
                self.assertEqual(saved['columna_organizacion'], 'empresa_codigo')
                self.assertEqual(saved['valor_organizacion'], '2')
                self.assertNotIn('columna_condicion', saved)

    def test_related_table_and_multiple_legajos(self):
        self.config.update(tabla_organizacion='legajo', columna_empleado_organizacion='empleados_id')
        with self.engine.begin() as c:
            c.execute(text('ALTER TABLE empleados DROP COLUMN organizacion_id'))
            c.execute(text('CREATE TABLE legajo (empleados_id INTEGER, organizacion_id INTEGER)'))
            c.execute(text('INSERT INTO legajo VALUES (92,1),(92,1),(501,2),(10,1)'))
            self.assertEqual(empleados.resolver_id_empleado(c,'93'),92)
            self.config.update(columna_organizacion='organizacion_id',valor_organizacion='2')
            self.assertEqual(empleados.resolver_id_empleado(c,'93'),501)
        with patch.object(empleados,'crear_engine_externo',return_value=self.engine), patch.object(empleados,'cargar_config_conexion',return_value={}):
            self.assertEqual(empleados.obtener_mapa_empleados(),{'93':'B'})

    def test_migration_and_validation(self):
        cfg=normalizar_config_empleados({'columna_condicion':"empresa_id = 'ABC'"})
        self.assertEqual((cfg['columna_organizacion'],cfg['valor_organizacion']),('empresa_id','ABC'))
        for cfg in [{'columna_condicion':'organizacion_id = 1 OR 1=1'}, {'columna_organizacion':'empresa_id'}, {'valor_organizacion':'1'}]:
            with self.assertRaises(ValueError): normalizar_config_empleados(cfg)
        self.assertEqual(normalizar_config_empleados({'columna_organizacion':'org','valor_organizacion':0})['valor_organizacion'],'0')

if __name__ == '__main__': unittest.main()
