import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.operaciones import descargar, exportar_excel


class OperacionesTests(unittest.TestCase):
    def test_failed_device_read_always_disconnects(self):
        adapter = MagicMock()
        adapter.conectar.return_value = True
        adapter.obtener_marcaciones.side_effect = RuntimeError()
        with patch("app.operaciones.crear_adaptador", return_value=adapter):
            resultado = descargar(
                [{"params": {"dispositivo_id": "1"}}],
                "no_se_abre.db",
                "2026-09-01",
                "2026-09-02",
                lambda *args: None,
            )
        self.assertEqual(resultado[:2], (0, 0))
        self.assertTrue(resultado[2])
        adapter.desconectar.assert_called_once()

    def test_download_keeps_time_and_skips_existing_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            database_path = str(Path(folder) / "marcaciones.db")
            with closing(sqlite3.connect(database_path)) as database, database:
                database.execute(
                    "CREATE TABLE marcaciones ("
                    "dispositivo_id TEXT, empleado_id TEXT, fecha_hora TEXT, "
                    "tipo_evento INTEGER, metodo TEXT, fecha_descarga TEXT, "
                    "UNIQUE(dispositivo_id, empleado_id, fecha_hora, tipo_evento))"
                )
            adapter = MagicMock()
            adapter.conectar.return_value = True
            adapter.obtener_marcaciones.return_value = [
                SimpleNamespace(
                    dispositivo_id="1",
                    reloj_user_id="93",
                    timestamp=datetime(2026, 9, 7, 8, 35),
                    tipo_evento=0,
                    metodo="huella",
                )
            ]
            with patch("app.operaciones.crear_adaptador", return_value=adapter):
                args = (
                    [{"params": {"dispositivo_id": "1"}}],
                    database_path,
                    "2026-09-01",
                    "2026-09-30",
                    lambda *values: None,
                )
                self.assertEqual(descargar(*args)[:2], (1, 0))
                self.assertEqual(descargar(*args)[:2], (0, 1))
            with closing(sqlite3.connect(database_path)) as database:
                self.assertEqual(
                    database.execute("SELECT fecha_hora FROM marcaciones").fetchone()[0],
                    "2026-09-07 08:35:00",
                )

    def test_excel_output_contains_employee_name_and_timestamp(self):
        from openpyxl import load_workbook

        with tempfile.TemporaryDirectory() as folder, patch(
            "app.operaciones.obtener_mapa_empleados", return_value={"93": "Persona"}
        ):
            path = Path(folder) / "salida.xlsx"
            exportar_excel(
                [("1", "93", "2026-09-07 08:35:00", "Entrada", "huella")],
                path,
                ["Dispositivo", "Empleado", "Fecha y hora", "Tipo de evento", "Método"],
                lambda *args: None,
            )
            workbook = load_workbook(path)
            self.assertEqual(workbook.active.cell(2, 3).value, "Persona")
            self.assertEqual(workbook.active.cell(2, 4).value, "2026-09-07 08:35:00")
            workbook.close()


if __name__ == "__main__":
    unittest.main()
