"""Compila el cliente; la herramienta de emisión y su clave privada quedan fuera."""
from pathlib import Path
import subprocess
import sys
raiz = Path(__file__).resolve().parents[1]
publica = raiz / 'resources' / 'license_public.pem'
if not publica.exists():
    raise SystemExit('Primero ejecutá tools/emitir_licencia.py inicializar.')
comando = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile', '--windowed',
           '--name', 'ConectBioSync', '--distpath', str(raiz / 'dist' / 'cliente'),
           '--workpath', str(raiz / 'build' / 'cliente'), '--specpath', str(raiz / 'build'),
           '--add-data', str(publica) + ';resources',
           '--exclude-module', 'PySide6', '--exclude-module', 'shiboken6',
           '--hidden-import', 'pymysql', '--hidden-import', 'psycopg2', '--hidden-import', 'pyodbc', '--hidden-import', 'oracledb',
           '--exclude-module', 'tools', '--exclude-module', 'tests',
           '--exclude-module', 'resources.config_relojes']
for nombre in ('isologo.ico', 'isologo.png'):
    archivo = raiz / 'resources' / nombre
    if archivo.exists(): comando += ['--add-data', str(archivo) + ';resources']
icono = raiz / 'resources' / 'isologo.ico'
if icono.exists(): comando += ['--icon', str(icono)]
comando.append(str(raiz / 'main.py'))
subprocess.run(comando, cwd=raiz, check=True)
