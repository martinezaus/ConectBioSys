"""
Configuración de los relojes biométricos a conectar.

Este archivo se genera automáticamente desde la pantalla "Configurar
relojes" de la app. También podés editarlo a mano si preferís: cada
entrada es un diccionario con "tipo" ("hikvision" o "zkteco") y los
parámetros que necesita el __init__ del adaptador correspondiente.
"""

RELOJES = [
	{
		"tipo": 'zkteco',
		"params": {
			'ip': '192.168.100.20',
			'dispositivo_id': '1',
			'puerto': 4370,
			'force_udp': True,
		},
	},
	{
		"tipo": 'zkteco',
		"params": {
			'ip': '192.168.100.21',
			'dispositivo_id': '2',
			'puerto': 4370,
			'force_udp': True,
		},
	},
	{
		"tipo": 'hikvision',
		"params": {
			'ip': '10.10.81.2',
			'dispositivo_id': '3',
			'usuario': 'admin',
			'password': 'halvear2026',
			'usar_https': False,
		},
	},
	{
		"tipo": 'hikvision',
		"params": {
			'ip': '10.10.81.3',
			'dispositivo_id': '4',
			'usuario': 'admin',
			'password': 'halvear2026',
			'usar_https': False,
		},
	},
]
