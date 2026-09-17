"""Operaciones largas sin referencias a widgets."""
import os
import sqlite3
import tempfile
from pathlib import Path
from contextlib import closing
from openpyxl import Workbook
from resources.config_path import crear_adaptador, crear_engine_externo
from app.api.empleados import obtener_mapa_empleados


def descargar(relojes, ruta_db, desde, hasta, progreso):
    guardadas = 0
    repetidas = 0
    errores = []
    for config in relojes:
        identificador = config['params'].get('dispositivo_id', '?')
        adapter = None
        try:
            progreso(-1, f'[{identificador}] Conectando al reloj…')
            adapter = crear_adaptador(config)
            if not adapter.conectar():
                raise ConnectionError('No se pudo conectar al reloj.')
            lecturas = adapter.obtener_marcaciones(desde=desde, hasta=hasta)
            nuevas = 0
            duplicadas = 0
            with closing(sqlite3.connect(ruta_db, timeout=15)) as conexion, conexion:
                for i, lectura in enumerate(lecturas, 1):
                    cursor = conexion.execute('''INSERT INTO marcaciones
                        (dispositivo_id, empleado_id, fecha_hora, tipo_evento, metodo, fecha_descarga)
                        VALUES (?, ?, ?, ?, ?, datetime('now'))
                        ON CONFLICT(dispositivo_id, empleado_id, fecha_hora, tipo_evento) DO NOTHING''',
                        (lectura.dispositivo_id, lectura.reloj_user_id, lectura.timestamp.isoformat(sep=' '), lectura.tipo_evento, lectura.metodo))
                    nuevas += cursor.rowcount
                    duplicadas += 1 - cursor.rowcount
                    if i % 200 == 0:
                        progreso(i * 100 // len(lecturas), f'[{identificador}] Guardando {i}/{len(lecturas)}…')
            guardadas += nuevas
            repetidas += duplicadas
            progreso(100, f'[{identificador}] Guardadas: {nuevas}. Ya existentes: {duplicadas}.')
        except Exception as exc:
            errores.append(f'[{identificador}] Falló la descarga ({type(exc).__name__}).')
        finally:
            if adapter is not None:
                try: adapter.desconectar()
                except Exception: errores.append(f'[{identificador}] No se pudo cerrar la conexión.')
    return guardadas, repetidas, errores


def exportar_excel(filas, ruta, encabezados, progreso):
    try:
        progreso(-1, 'Consultando nombres de empleados…')
        mapa = obtener_mapa_empleados()
    except Exception:
        mapa = {}
        progreso(-1, 'No se pudieron consultar los nombres. Se exportan las tarjetas sin ese dato.')
    wb = Workbook()
    hoja = wb.active
    hoja.title = 'Marcaciones'
    encabezados = list(encabezados)
    indice = encabezados.index('Empleado')
    encabezados.insert(indice + 1, 'Nombre')
    hoja.append(encabezados)
    for i, fila in enumerate(filas, 1):
        valores = list(fila)
        valores.insert(indice + 1, mapa.get(str(valores[indice]), ''))
        hoja.append(valores)
        if i % 500 == 0:
            progreso(i * 100 // len(filas), f'Generando Excel: {i}/{len(filas)}…')
    for i, ancho in enumerate((15, 15, 25, 22, 20, 15), 1):
        hoja.column_dimensions[hoja.cell(1, i).column_letter].width = ancho
    ruta = Path(ruta)
    fd, temporal = tempfile.mkstemp(suffix='.xlsx', dir=ruta.parent)
    os.close(fd)
    try:
        progreso(-1, 'Guardando archivo Excel…')
        wb.save(temporal)
        os.replace(temporal, ruta)
    finally:
        wb.close()
        if os.path.exists(temporal): os.unlink(temporal)
    return str(ruta)


def probar_conexion(config, progreso):
    engine = crear_engine_externo(config)
    try:
        with engine.connect(): pass
        return 'La conexión se probó con éxito.'
    finally:
        engine.dispose()


def limpiar_buffers(relojes, progreso):
    resultados = []
    for config in relojes:
        identificador = config['params'].get('dispositivo_id', '?')
        adapter = None
        try:
            progreso(-1, f'[{identificador}] Limpiando buffer…')
            adapter = crear_adaptador(config)
            if not hasattr(adapter, 'limpiar_buffer'):
                resultados.append(f'[{identificador}] No soporta limpiar buffer. Se omite.')
                continue
            if not adapter.conectar(): raise ConnectionError()
            adapter.limpiar_buffer()
            resultados.append(f'[{identificador}] Buffer limpiado correctamente.')
        except Exception as exc:
            resultados.append(f'[{identificador}] No se pudo limpiar ({type(exc).__name__}).')
        finally:
            if adapter is not None:
                try: adapter.desconectar()
                except Exception: resultados.append(f'[{identificador}] No se pudo cerrar la conexión.')
    return '\n'.join(resultados) or 'No hay relojes configurados.'
