"""Operaciones sin widgets: descarga, respaldo, filtrado y Excel."""
from datetime import datetime, date, timedelta
from pathlib import Path
import os
import sqlite3
from contextlib import closing
import tempfile
from app.database.database import Database
from resources.config_path import crear_adaptador
from app.licencias import exigir_licencia
def rango_filtro(modo, desde=None, hasta=None, tarjeta=None, hoy=None):
    hoy=hoy or date.today()
    if modo==0:
        hasta=hoy.replace(day=1)-timedelta(days=1); desde=hasta.replace(day=1)
    elif modo==1: desde,hasta=hoy-timedelta(days=6),hoy
    elif modo not in (2,3): raise ValueError('Filtro desconocido.')
    if desde is None or hasta is None or desde>hasta: raise ValueError('El rango de fechas no es válido.')
    if modo==2 and not tarjeta: raise ValueError('Ingresá una tarjeta o ID de empleado.')
    return desde.isoformat(),hasta.isoformat(),tarjeta if modo==2 else None
def descargar(relojes,ruta,desde,hasta,tarjeta,progreso,cancelar):
    exigir_licencia()
    if not relojes: raise ValueError('No hay relojes configurados.')
    db=Database(ruta)
    guardadas=0; duplicadas=0; errores=[]
    for index,config in enumerate(relojes):
        cancelar(); adapter=None
        identificador=config['params']['dispositivo_id']
        progreso(int(index*100/len(relojes)),f'Conectando al reloj {identificador}…')
        try:
            adapter=crear_adaptador(config)
            if not adapter.conectar(): raise ConnectionError()
            lecturas=adapter.obtener_marcaciones(desde,hasta)
            nuevas=0; repetidas=0
            with closing(db.conectar()) as conexion, conexion:
                for lectura in lecturas:
                    cancelar()
                    if tarjeta is not None and str(lectura.reloj_user_id)!=str(tarjeta): continue
                    # Mantener la hora civil suministrada por el reloj (no zona del PC).
                    dt=lectura.timestamp.replace(tzinfo=None)
                    if not desde<=dt.date().isoformat()<=hasta: continue
                    cursor=conexion.execute('''INSERT INTO marcaciones
                        (dispositivo_id,empleado_id,fecha_hora,tipo_evento,metodo,fecha_descarga)
                        VALUES (?,?,?,?,?,datetime('now'))
                        ON CONFLICT(dispositivo_id,empleado_id,fecha_hora,tipo_evento) DO NOTHING''',
                        (lectura.dispositivo_id,str(lectura.reloj_user_id),dt.isoformat(sep=' '),lectura.tipo_evento,lectura.metodo))
                    nuevas+=cursor.rowcount; repetidas+=1-cursor.rowcount
            guardadas+=nuevas; duplicadas+=repetidas
        except Exception as exc:
            from app.trabajos import Cancelado
            if isinstance(exc,Cancelado): raise
            errores.append(f'Reloj {identificador}: {type(exc).__name__}. No se completó la descarga.')
        finally:
            if adapter is not None: adapter.desconectar()
    progreso(100,f'Guardadas: {guardadas}; ya existentes: {duplicadas}.')
    return {'guardadas':guardadas,'duplicadas':duplicadas,'errores':errores,
            'filas':db.obtener_marcaciones_filtradas(desde,hasta,tarjeta)}
def limpiar_reloj(config,ruta,progreso,cancelar):
    exigir_licencia()
    adapter=crear_adaptador(config)
    if not hasattr(adapter,'limpiar_buffer'): raise ValueError('Este modelo no admite limpieza desde la aplicación.')
    try:
        if not adapter.conectar(): raise ConnectionError()
        cancelar()
        # ZK mantiene el dispositivo deshabilitado durante lectura y borrado.
        lecturas=adapter.obtener_marcaciones('1970-01-01','2099-12-31')
        db=Database(ruta)
        with closing(db.conectar()) as conexion, conexion:
            for lectura in lecturas:
                cancelar()
                conexion.execute('''INSERT INTO marcaciones
                    (dispositivo_id,empleado_id,fecha_hora,tipo_evento,metodo,fecha_descarga)
                    VALUES (?,?,?,?,?,datetime('now')) ON CONFLICT(dispositivo_id,empleado_id,fecha_hora,tipo_evento) DO NOTHING''',
                    (lectura.dispositivo_id,str(lectura.reloj_user_id),lectura.timestamp.replace(tzinfo=None).isoformat(sep=' '),lectura.tipo_evento,lectura.metodo))
        cancelar()
        adapter.limpiar_buffer()
        return f'Buffer limpiado. {len(lecturas)} marcaciones respaldadas en la base local.'
    finally: adapter.desconectar()
def exportar_excel(filas,ruta,progreso,cancelar,mapa=None):
    from openpyxl import Workbook
    from openpyxl.worksheet.table import Table,TableStyleInfo
    ruta=Path(ruta)
    if ruta.suffix.lower()!='.xlsx': ruta=ruta.with_suffix('.xlsx')
    if not filas: raise ValueError('No hay filas seleccionadas.')
    if len(filas)>1048575: raise ValueError('La selección excede la capacidad de una hoja Excel.')
    wb=Workbook(); hoja=wb.active; hoja.title='Marcaciones'
    hoja.append(['Dispositivo','Tarjeta / ID reloj','Nombre','Fecha y hora','Tipo de evento','Método'])
    for i,fila in enumerate(filas,1):
        cancelar()
        dispositivo,tarjeta,fecha,tipo,metodo=fila
        hoja.append([str(dispositivo),str(tarjeta),(mapa or {}).get(str(tarjeta),''),datetime.fromisoformat(str(fecha)).replace(tzinfo=None),str(tipo),str(metodo)])
        for columna in (1,2,3,5,6): hoja.cell(i+1,columna).data_type='s'
        hoja.cell(i+1,4).number_format='dd/mm/yyyy hh:mm:ss'
        if i%500==0: progreso(i*100//len(filas),'Generando Excel…')
    tabla=Table(displayName='Marcaciones',ref=f'A1:F{len(filas)+1}')
    tabla.tableStyleInfo=TableStyleInfo(name='TableStyleMedium2',showRowStripes=True)
    hoja.add_table(tabla); hoja.freeze_panes='A2'
    for col,width in zip('ABCDEF',(18,22,32,24,20,18)): hoja.column_dimensions[col].width=width
    fd,temporal=tempfile.mkstemp(suffix='.xlsx',dir=ruta.parent);os.close(fd)
    try:
        wb.save(temporal); cancelar(); os.replace(temporal,ruta)
    finally:
        wb.close()
        if os.path.exists(temporal): os.unlink(temporal)
    return str(ruta)
