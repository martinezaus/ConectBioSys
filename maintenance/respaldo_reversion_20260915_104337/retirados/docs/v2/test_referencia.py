import ast
import sqlite3
import unittest
from pathlib import Path
from datetime import date,datetime,timezone,timedelta
from sqlalchemy import create_engine,text
from backend_referencia import Filtro,filtro_rapido,aniversario,Conexion,url_conexion,reflejar_destino,preparar_fila

class ReferenciaTests(unittest.TestCase):
    def test_schema(self):
        with sqlite3.connect(':memory:') as c:
            c.executescript(Path(__file__).with_name('schema.sql').read_text())
            self.assertEqual(c.execute('PRAGMA foreign_keys').fetchone()[0],1)
            self.assertTrue({'profiles','attendance','license_state','secrets','destination_mappings'}.issubset({r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}))
    def test_previous_month_leap_and_year_boundary(self):
        self.assertEqual(filtro_rapido('mes_anterior',date(2024,3,10)),Filtro(date(2024,2,1),date(2024,2,29)))
        self.assertEqual(filtro_rapido('mes_anterior',date(2026,1,2)),Filtro(date(2025,12,1),date(2025,12,31)))
    def test_seven_days_and_exclusive_end(self):
        f=filtro_rapido('ultimos_7',date(2026,9,15))
        self.assertEqual((f.hasta-f.desde).days+1,7)
        self.assertEqual(f.limites()[1],datetime(2026,9,16))
        with self.assertRaises(ValueError):Filtro(date(2026,9,15),date(2026,9,14)).limites()
    def test_anniversary(self):
        start=datetime(2024,2,29,12,tzinfo=timezone.utc)
        self.assertEqual(aniversario(start),datetime(2025,2,28,12,tzinfo=timezone.utc))
        with self.assertRaises(ValueError):aniversario(datetime(2026,1,1))
    def test_urls_preserve_password(self):
        for motor in ['mysql','postgresql','sqlserver','oracle']:
            cfg=Conexion(motor,host='localhost',port=1521,database='test',username='user',password='a@b:/?%',service_name='ORCL')
            url=url_conexion(cfg)
            self.assertEqual(url.password,cfg.password)
            if motor=='oracle':self.assertEqual(url.query['service_name'],'ORCL')
            if motor=='sqlserver':self.assertEqual(url.query['driver'],'ODBC Driver 18 for SQL Server')
    def test_reflection_and_mapping(self):
        engine=create_engine('sqlite:///:memory:')
        try:
            with engine.begin() as c:
                c.execute(text('CREATE TABLE destino(persona INTEGER, instante DATETIME, evento TEXT)'))
                mapping={'employee_id':'persona','occurred_at':'instante','event_type':'evento'}
                table=reflejar_destino(c,None,'destino',mapping)
                row=preparar_fila({'datetime_local':datetime(2026,9,7,8,35),'tarjeta':'093','reloj':'1','tipo':'entrada','metodo':'huella','id':'abc'},92,mapping,'combined',{'entrada':'E'})
                c.execute(table.insert(),[row])
                self.assertEqual(c.execute(text('SELECT persona FROM destino')).scalar_one(),92)
                with self.assertRaises(ValueError):reflejar_destino(c,None,'destino',{'a':'no_existe'})
        finally:engine.dispose()
    def test_reference_syntax(self):
        for name in ['ui_pyqt6.py','worker_pyqt6.py','backend_referencia.py']:
            ast.parse(Path(__file__).with_name(name).read_text(encoding='utf-8'))

if __name__=='__main__':unittest.main()
