import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import threading
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch,MagicMock
from PySide6.QtCore import QEventLoop,QTimer,Qt
from PySide6.QtWidgets import QApplication
from app.tareas import GestorTareas
from app.modelo_marcaciones import ModeloMarcaciones
from app.operaciones import descargar
from main import VentanaPrincipal,TablaMarcacionesDialog

class TareasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def wait_result(self,gestor,operacion):
        loop=QEventLoop(); resultados=[];errores=[];ticks=[]
        timer=QTimer();timer.setInterval(10);timer.timeout.connect(lambda:ticks.append(1));timer.start()
        gestor.resultado.connect(lambda r:(resultados.append(r),loop.quit()))
        gestor.error.connect(lambda e:(errores.append(e),loop.quit()))
        timeout=QTimer();timeout.setSingleShot(True);timeout.timeout.connect(loop.quit);timeout.start(3000)
        self.assertTrue(gestor.iniciar(operacion))
        self.assertFalse(gestor.iniciar(lambda p:'no debe ejecutarse'))
        loop.exec();timer.stop();timeout.stop()
        self.assertFalse(gestor.en_curso())
        return resultados,errores,ticks
    def test_ui_events_continue_during_work(self):
        ui=threading.get_ident();gestor=GestorTareas()
        result,error,ticks=self.wait_result(gestor,lambda p:(time.sleep(.2),threading.get_ident())[1])
        self.assertNotEqual(result[0],ui);self.assertFalse(error);self.assertGreater(len(ticks),2)
    def test_error_unblocks_and_releases_worker(self):
        gestor=GestorTareas();states=[];gestor.ocupado.connect(states.append)
        def fallar(p):raise RuntimeError('dato privado')
        result,error,_=self.wait_result(gestor,fallar)
        self.assertEqual(states,[True,False]);self.assertFalse(result);self.assertNotIn('dato privado',error[0])
        result,error,_=self.wait_result(gestor,lambda p:'recuperado')
        self.assertEqual(result,['recuperado'])
    def test_window_minimize_restore_and_buttons(self):
        with patch('main.Database'),patch('main.cargar_relojes',return_value=[]):
            ventana=VentanaPrincipal()
        ventana.show();self.app.processEvents()
        loop=QEventLoop();result=[]
        ventana._iniciar_tarea(lambda p:(time.sleep(.25),'ok')[1],lambda r:(result.append(r),loop.quit()))
        self.assertFalse(ventana.boton_exportar.isEnabled())
        self.assertFalse(ventana._iniciar_tarea(lambda p:'otra',lambda r:None))
        ventana.showMinimized();self.app.processEvents();ventana.showNormal()
        ventana.close();self.assertTrue(ventana.isVisible())
        timeout=QTimer();timeout.setSingleShot(True);timeout.timeout.connect(loop.quit);timeout.start(3000)
        loop.exec();timeout.stop()
        self.assertEqual(result,['ok']);self.assertTrue(ventana.boton_exportar.isEnabled());ventana.close()
    def test_large_table_selection_without_row_widgets(self):
        filas=[('1','93','2026-09-07 08:35:00','Entrada','huella')]*50000
        dialog=TablaMarcacionesDialog(filas)
        self.assertEqual(dialog.modelo.rowCount(),50000)
        self.assertIs(dialog.tabla.model(),dialog.modelo)
        dialog.modelo.setData(dialog.modelo.index(0,0),Qt.Unchecked,Qt.CheckStateRole)
        self.assertEqual(len(dialog.filas_seleccionadas()),49999)
        dialog._marcar_todo(False);self.assertEqual(dialog.filas_seleccionadas(),[])
        dialog._marcar_todo(True);self.assertEqual(len(dialog.filas_seleccionadas()),50000)
        dialog.close()
    def test_failed_device_read_always_disconnects(self):
        adapter=MagicMock();adapter.conectar.return_value=True;adapter.obtener_marcaciones.side_effect=RuntimeError()
        with patch('app.operaciones.crear_adaptador',return_value=adapter):
            resultado=descargar([{'params':{'dispositivo_id':'1'}}],'no_se_abre.db','2026-09-01','2026-09-02',lambda *a:None)
        self.assertEqual(resultado[:2],(0,0));self.assertTrue(resultado[2]);adapter.desconectar.assert_called_once()

    def test_download_keeps_time_and_skips_existing_rows(self):
        import tempfile,sqlite3
        from datetime import datetime
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as folder:
            ruta=str(Path(folder)/'marcaciones.db')
            with closing(sqlite3.connect(ruta)) as db, db:
                db.execute('CREATE TABLE marcaciones(dispositivo_id TEXT,empleado_id TEXT,fecha_hora TEXT,tipo_evento INTEGER,metodo TEXT,fecha_descarga TEXT,UNIQUE(dispositivo_id,empleado_id,fecha_hora,tipo_evento))')
            adapter=MagicMock();adapter.conectar.return_value=True
            adapter.obtener_marcaciones.return_value=[SimpleNamespace(dispositivo_id='1',reloj_user_id='93',timestamp=datetime(2026,9,7,8,35),tipo_evento=0,metodo='huella')]
            with patch('app.operaciones.crear_adaptador',return_value=adapter):
                args=([{'params':{'dispositivo_id':'1'}}],ruta,'2026-09-01','2026-09-30',lambda *a:None)
                self.assertEqual(descargar(*args)[:2],(1,0))
                self.assertEqual(descargar(*args)[:2],(0,1))
            with closing(sqlite3.connect(ruta)) as db, db:
                self.assertEqual(db.execute('SELECT fecha_hora FROM marcaciones').fetchone()[0],'2026-09-07 08:35:00')
    def test_excel_output_after_background_refactor(self):
        import tempfile
        from openpyxl import load_workbook
        from app.operaciones import exportar_excel
        from main import ENCABEZADOS_MARCACIONES
        with tempfile.TemporaryDirectory() as folder,patch('app.operaciones.obtener_mapa_empleados',return_value={'93':'Persona'}):
            ruta=Path(folder)/'salida.xlsx'
            exportar_excel([('1','93','2026-09-07 08:35:00','Entrada','huella')],ruta,ENCABEZADOS_MARCACIONES,lambda *a:None)
            wb=load_workbook(ruta)
            self.assertEqual(wb.active.cell(2,3).value,'Persona')
            self.assertEqual(wb.active.cell(2,4).value,'2026-09-07 08:35:00')
            wb.close()

if __name__=='__main__':unittest.main()
