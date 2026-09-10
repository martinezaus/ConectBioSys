"""Catálogo de motores de base de datos soportados por la app."""

ENGINES = {
	"mysql": {
		"label": "MySQL / MariaDB",
		"url_scheme": "mysql+pymysql",
		"requiere_puerto": True,
		"puerto_default": 3306,
		"requiere_archivo": False,
	},
	"postgresql": {
		"label": "PostgreSQL",
		"url_scheme": "postgresql+psycopg2",
		"requiere_puerto": True,
		"puerto_default": 5432,
		"requiere_archivo": False,
	},
	"sqlserver": {
		"label": "SQL Server",
		"url_scheme": "mssql+pyodbc",
		"requiere_puerto": True,
		"puerto_default": 1433,
		"requiere_archivo": False,
	},
	"sqlite": {
		"label": "SQLite (archivo local)",
		"url_scheme": "sqlite",
		"requiere_puerto": False,
		"puerto_default": None,
		"requiere_archivo": True,
	},
}