import contextlib
import io
import json
import os
import re
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from werkzeug.test import Client
from werkzeug.security import generate_password_hash
from werkzeug.wrappers import Response

from app.database.database import Database
from webapp import SERVER_PATH, create_app, create_server_application


class WebAppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp.name) / "marcaciones.db")
        connection = sqlite3.connect(self.database.ruta)
        with connection:
            connection.execute(
                "INSERT INTO marcaciones "
                "(dispositivo_id, empleado_id, fecha_hora, tipo_evento, metodo) "
                "VALUES (?, ?, ?, ?, ?)",
                ("reloj-1", "tarjeta-93", "2026-10-05 08:35:00", 0, "huella"),
            )
        connection.close()
        self.auth_path = Path(self.temp.name) / "web_auth.json"
        self.auth_path.write_text(
            json.dumps(
                {
                    "secret_key": "test-persisted-secret",
                    "username": "admin",
                    "password_hash": generate_password_hash("test-password"),
                    "operator_username": "operador",
                    "operator_password_hash": generate_password_hash("operator-password"),
                }
            ),
            encoding="utf-8",
        )
        self.auth_path_patcher = patch("webapp.AUTH_CONFIG_PATH", self.auth_path)
        self.auth_path_patcher.start()
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-session-secret",
                "WEB_USERNAME": "admin",
                "WEB_PASSWORD": "test-password",
                "OPERATOR_USERNAME": "operador",
                "OPERATOR_PASSWORD": "operator-password",
                "SESSION_COOKIE_SECURE": False,
            },
            database=self.database,
        )
        for user in self.app.config["USERS"]:
            user["email"] = f"{user['username']}@example.com"
        self.client = self.app.test_client()
        self.server_client = Client(create_server_application(self.app), Response)

    def tearDown(self):
        self.app.executor.shutdown(wait=True)
        self.auth_path_patcher.stop()
        self.temp.cleanup()

    def token(self, response):
        match = re.search(rb'name="_csrf_token" value="([^"]+)"', response.data)
        if match:
            return match.group(1).decode()
        match = re.search(rb"window\.CSRF_TOKEN = \"([^\"]+)\"", response.data)
        self.assertIsNotNone(match)
        return match.group(1).decode()

    def login(self):
        response = self.client.get("/login")
        return self.client.post(
            "/login",
            data={
                "_csrf_token": self.token(response),
                "username": "admin",
                "password": "test-password",
            },
            follow_redirects=True,
        )

    def test_routes_require_login(self):
        self.assertEqual(self.client.get("/").status_code, 302)
        response = self.client.get("/api/status")
        self.assertEqual(response.status_code, 401)

    def test_operator_cannot_view_settings_or_call_settings_endpoints(self):
        operator_client = self.app.test_client()
        login_page = operator_client.get("/login")
        response = operator_client.post(
            "/login",
            data={
                "_csrf_token": self.token(login_page),
                "username": "operador",
                "password": "operator-password",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b'id="settings"', response.data)

        csrf = self.token(response)
        endpoints = (
            ("GET", "/api/settings", None),
            ("GET", "/api/settings/organizations", None),
            ("POST", "/api/settings", {"section": "clocks"}),
            ("POST", "/api/settings/test-connection", {"connection": {}}),
        )
        for method, path, payload in endpoints:
            with self.subTest(method=method, path=path):
                result = operator_client.open(
                    path,
                    method=method,
                    json=payload,
                    headers={"X-CSRF-Token": csrf},
                )
                self.assertEqual(result.status_code, 403)
                self.assertIn("administrador", result.get_json()["error"])

    def test_admin_can_view_settings(self):
        response = self.login()
        self.assertIn(b'id="settings"', response.data)

    def test_admin_can_create_users_and_only_temporary_password_is_returned(self):
        self.login()
        created = self.client.post(
            "/api/users",
            json={
                "action": "create",
                "username": "nuevo.operador",
                "email": "nuevo@example.com",
                "role": "operator",
            },
            headers={"X-CSRF-Token": self.token(self.client.get("/"))},
        )
        self.assertEqual(created.status_code, 200)
        result = created.get_json()
        self.assertEqual(result["username"], "nuevo.operador")
        self.assertTrue(result["temporary_password"])

        listed = self.client.get("/api/users")
        self.assertEqual(listed.status_code, 200)
        self.assertNotIn("password_hash", json.dumps(listed.get_json()))
        stored = json.loads(self.auth_path.read_text(encoding="utf-8"))
        account = next(user for user in stored["users"] if user["username"] == "nuevo.operador")
        self.assertNotIn(result["temporary_password"], json.dumps(stored))

        new_user = self.app.test_client()
        page = new_user.get("/login")
        response = new_user.post(
            "/login",
            data={
                "_csrf_token": self.token(page),
                "username": "nuevo.operador",
                "password": result["temporary_password"],
            },
        )
        self.assertEqual(response.status_code, 302)
        forced = new_user.get("/")
        self.assertEqual(forced.status_code, 302)
        self.assertTrue(forced.headers["Location"].endswith("/change-password"))
        change_page = new_user.get("/change-password")
        changed = new_user.post(
            "/change-password",
            data={
                "_csrf_token": self.token(change_page),
                "password": "operator-new-password",
                "confirmation": "operator-new-password",
            },
        )
        self.assertEqual(changed.status_code, 302)
        self.assertEqual(new_user.get("/api/status").status_code, 200)

    def test_admin_can_reset_password_and_old_sessions_are_revoked(self):
        self.login()
        operator_client = self.app.test_client()
        page = operator_client.get("/login")
        operator_client.post(
            "/login",
            data={
                "_csrf_token": self.token(page),
                "username": "operador",
                "password": "operator-password",
            },
        )
        with patch("webapp._enviar_clave_temporal") as send_email:
            reset = self.client.post(
                "/api/users",
                json={"action": "reset_password", "target_username": "operador"},
                headers={"X-CSRF-Token": self.token(self.client.get("/"))},
            )
        self.assertEqual(reset.status_code, 200)
        temporary_password = send_email.call_args.args[2]
        self.assertEqual(send_email.call_args.args[0], "operador@example.com")
        self.assertNotIn("temporary_password", reset.get_json())
        self.assertEqual(operator_client.get("/api/status").status_code, 401)

        new_operator = self.app.test_client()
        page = new_operator.get("/login")
        response = new_operator.post(
            "/login",
            data={
                "_csrf_token": self.token(page),
                "username": "operador",
                "password": temporary_password,
            },
        )
        self.assertEqual(response.status_code, 302)
        forced = new_operator.get("/")
        self.assertTrue(forced.headers["Location"].endswith("/change-password"))
        change_page = new_operator.get("/change-password")
        changed = new_operator.post(
            "/change-password",
            data={
                "_csrf_token": self.token(change_page),
                "password": "operator-new-password",
                "confirmation": "operator-new-password",
            },
        )
        self.assertEqual(changed.status_code, 302)
        self.assertEqual(new_operator.get("/api/status").status_code, 200)

    def test_email_failure_rolls_back_password_reset(self):
        self.login()
        operator_client = self.app.test_client()
        page = operator_client.get("/login")
        operator_client.post(
            "/login",
            data={
                "_csrf_token": self.token(page),
                "username": "operador",
                "password": "operator-password",
            },
        )
        before = json.loads(self.auth_path.read_text(encoding="utf-8"))
        with patch("webapp._enviar_clave_temporal", side_effect=RuntimeError("SMTP unavailable")):
            response = self.client.post(
                "/api/users",
                json={"action": "reset_password", "target_username": "operador"},
                headers={"X-CSRF-Token": self.token(self.client.get("/"))},
            )
        self.assertEqual(response.status_code, 500)
        self.assertIn("restablecimiento de clave fue cancelado", response.get_json()["error"])
        after = json.loads(self.auth_path.read_text(encoding="utf-8"))
        self.assertEqual(
            next(user for user in before["users"] if user["username"] == "operador"),
            next(user for user in after["users"] if user["username"] == "operador"),
        )
        self.assertEqual(operator_client.get("/api/status").status_code, 200)

    def test_admin_can_reset_own_password_and_reauthenticate(self):
        self.login()
        with patch("webapp._enviar_clave_temporal") as send_email:
            reset = self.client.post(
                "/api/users",
                json={"action": "reset_password", "target_username": "admin"},
                headers={"X-CSRF-Token": self.token(self.client.get("/"))},
            )
        self.assertEqual(reset.status_code, 200)
        result = reset.get_json()
        self.assertTrue(result["acting_user_changed"])
        self.assertEqual(send_email.call_args.args[0], "admin@example.com")
        self.assertNotIn("temporary_password", result)
        self.assertEqual(self.client.get("/api/users").status_code, 401)

        new_admin = self.app.test_client()
        page = new_admin.get("/login")
        response = new_admin.post(
            "/login",
            data={
                "_csrf_token": self.token(page),
                "username": "admin",
                "password": send_email.call_args.args[2],
            },
        )
        self.assertEqual(response.status_code, 302)
        forced = new_admin.get("/")
        self.assertTrue(forced.headers["Location"].endswith("/change-password"))
        change_page = new_admin.get("/change-password")
        changed = new_admin.post(
            "/change-password",
            data={
                "_csrf_token": self.token(change_page),
                "password": "admin-new-password",
                "confirmation": "admin-new-password",
            },
        )
        self.assertEqual(changed.status_code, 302)
        self.assertEqual(new_admin.get("/api/users").status_code, 200)

    def test_admin_can_manage_admin_but_last_active_admin_is_protected(self):
        self.login()
        token = self.token(self.client.get("/"))
        last_admin = self.client.post(
            "/api/users",
            json={
                "action": "update",
                "target_username": "admin",
                "username": "admin",
                "role": "operator",
                "enabled": True,
            },
            headers={"X-CSRF-Token": token},
        )
        self.assertEqual(last_admin.status_code, 400)
        self.assertIn("al menos un administrador", last_admin.get_json()["error"])

        create_admin = self.client.post(
            "/api/users",
            json={
                "action": "create",
                "username": "admin.respaldo",
                "email": "admin-backup@example.com",
                "role": "admin",
            },
            headers={"X-CSRF-Token": token},
        )
        self.assertEqual(create_admin.status_code, 200)
        disable_admin = self.client.post(
            "/api/users",
            json={
                "action": "update",
                "target_username": "admin",
                "username": "administrador",
                "role": "operator",
                "enabled": False,
            },
            headers={"X-CSRF-Token": token},
        )
        self.assertEqual(disable_admin.status_code, 200)
        self.assertTrue(disable_admin.get_json()["acting_user_changed"])
        self.assertEqual(self.client.get("/api/users").status_code, 401)
        stored = json.loads(self.auth_path.read_text(encoding="utf-8"))
        self.assertEqual(stored["username"], "admin.respaldo")

    def test_deleting_last_active_admin_is_rejected(self):
        self.login()
        response = self.client.post(
            "/api/users",
            json={"action": "delete", "target_username": "admin"},
            headers={"X-CSRF-Token": self.token(self.client.get("/"))},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("al menos un administrador", response.get_json()["error"])

    def test_admin_can_delete_admin_when_another_admin_remains(self):
        self.login()
        token = self.token(self.client.get("/"))
        created = self.client.post(
            "/api/users",
            json={
                "action": "create",
                "username": "admin.respaldo",
                "email": "admin-backup@example.com",
                "role": "admin",
            },
            headers={"X-CSRF-Token": token},
        )
        self.assertEqual(created.status_code, 200)
        deleted = self.client.post(
            "/api/users",
            json={"action": "delete", "target_username": "admin"},
            headers={"X-CSRF-Token": token},
        )
        self.assertEqual(deleted.status_code, 200)
        self.assertTrue(deleted.get_json()["acting_user_changed"])
        self.assertEqual(self.client.get("/api/users").status_code, 401)
        saved = json.loads(self.auth_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["username"], "admin.respaldo")

    def test_server_mounts_app_at_requested_path(self):
        login_page = self.server_client.get(f"{SERVER_PATH}/login")
        self.assertEqual(login_page.status_code, 200)
        self.assertIn(
            f"{SERVER_PATH}/static/web.css",
            login_page.get_data(as_text=True),
        )
        login = self.server_client.post(
            f"{SERVER_PATH}/login",
            data={
                "_csrf_token": self.token(login_page),
                "username": "admin",
                "password": "test-password",
            },
        )
        self.assertEqual(login.status_code, 302)
        self.assertTrue(login.headers["Location"].startswith(SERVER_PATH))
        dashboard = self.server_client.get(f"{SERVER_PATH}/")
        self.assertEqual(dashboard.status_code, 200)
        html = dashboard.get_data(as_text=True)
        self.assertIn(f'window.APP_ROOT = "{SERVER_PATH}"', html)
        self.assertIn(f"{SERVER_PATH}/static/web.js", html)
        self.assertEqual(self.server_client.get(f"{SERVER_PATH}/api/status").status_code, 200)
        base_url = self.server_client.get(SERVER_PATH)
        self.assertEqual(base_url.status_code, 308)
        self.assertTrue(base_url.headers["Location"].endswith(f"{SERVER_PATH}/"))
        self.assertEqual(self.server_client.get(f"{SERVER_PATH}/").status_code, 200)
        self.assertEqual(self.server_client.get("/").status_code, 404)

    def test_login_and_search_require_csrf(self):
        page = self.login()
        self.assertEqual(page.status_code, 200)
        csrf = self.token(page)
        denied = self.client.post(
            "/api/query",
            json={"since": "2026-10-01", "until": "2026-10-31"},
        )
        self.assertEqual(denied.status_code, 400)
        found = self.client.post(
            "/api/query",
            json={"since": "2026-10-01", "until": "2026-10-31", "card": "tarjeta-93"},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(found.status_code, 200)
        payload = found.get_json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["rows"][0][1], "tarjeta-93")

    def test_invalid_date_range_is_rejected(self):
        page = self.login()
        response = self.client.post(
            "/api/query",
            json={"since": "2026-11-01", "until": "2026-10-01"},
            headers={"X-CSRF-Token": self.token(page)},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("anterior", response.get_json()["error"])

    def test_query_pages_are_bound_to_authenticated_session(self):
        page = self.login()
        response = self.client.post(
            "/api/query",
            json={"since": "2026-10-01", "until": "2026-10-31"},
            headers={"X-CSRF-Token": self.token(page)},
        )
        query_id = response.get_json()["query_id"]
        other = self.app.test_client()
        self.assertEqual(other.get(f"/api/query/{query_id}").status_code, 401)

    def test_settings_do_not_return_saved_passwords(self):
        page = self.login()
        with (
            patch("webapp.cargar_config_conexion", return_value={"password": "db-secret"}),
            patch("webapp.cargar_relojes", return_value=[
                {"tipo": "hikvision", "params": {"dispositivo_id": "1", "password": "clock-secret"}}
            ]),
            patch("webapp.cargar_config_empleados", return_value={}),
            patch("webapp.cargar_config_asistencias", return_value={}),
        ):
            response = self.client.get("/api/settings")
        self.assertEqual(response.status_code, 200)
        payload = json.dumps(response.get_json())
        self.assertNotIn("db-secret", payload)
        self.assertNotIn("clock-secret", payload)

    def test_clock_configuration_can_be_saved_without_database_mappings(self):
        page = self.login()
        config_path = Path(self.temp.name) / "config_relojes.py"
        with (
            patch("webapp.cargar_relojes", return_value=[]),
            patch("webapp.get_config_relojes_path", return_value=str(config_path)),
        ):
            response = self.client.post(
                "/api/settings",
                json={
                    "section": "clocks",
                    "clocks": [{
                        "tipo": "zkteco",
                        "params": {
                            "ip": "192.168.1.20",
                            "dispositivo_id": "reloj-1",
                            "puerto": 4370,
                            "force_udp": True,
                        },
                    }],
                },
                headers={"X-CSRF-Token": self.token(page)},
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("'dispositivo_id': 'reloj-1'", config_path.read_text(encoding="utf-8"))

    def test_json_endpoints_reject_non_object_payloads(self):
        page = self.login()
        response = self.client.post(
            "/api/query",
            json=[],
            headers={"X-CSRF-Token": self.token(page)},
        )
        self.assertEqual(response.status_code, 400)

    def test_export_runs_as_background_job_and_downloads(self):
        page = self.login()
        query = self.client.post(
            "/api/query",
            json={"since": "2026-10-01", "until": "2026-10-31"},
            headers={"X-CSRF-Token": self.token(page)},
        ).get_json()
        with patch(
            "webapp.exportar_excel",
            side_effect=lambda rows, path, headers, progress: (
                Path(path).write_bytes(b"xlsx"),
                str(path),
            )[1],
        ):
            response = self.client.post(
                "/api/export",
                json={"query_id": query["query_id"], "indices": [0]},
                headers={"X-CSRF-Token": self.token(page)},
            )
            job_id = response.get_json()["job_id"]
            for _ in range(50):
                status = self.client.get(f"/api/jobs/{job_id}").get_json()
                if status["status"] != "running":
                    break
                time.sleep(0.02)
            self.assertEqual(status["status"], "completed")
            download = self.client.get(status["result"]["download_url"])
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.data, b"xlsx")

    def test_first_start_creates_and_persists_random_credentials(self):
        auth_path = Path(self.temp.name) / "first-start" / "web_auth.json"
        with (
            patch("webapp.AUTH_CONFIG_PATH", auth_path),
            patch.dict(os.environ, {}, clear=True),
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            first_app = create_app(database=self.database)
            try:
                credentials = output.getvalue()
                admin_password = re.search(r"Administrador: admin / (\S+)", credentials).group(1)
                operator_password = re.search(r"Operador: operador / (\S+)", credentials).group(1)
                config = json.loads(auth_path.read_text(encoding="utf-8"))
                self.assertEqual(config["username"], "admin")
                self.assertEqual(config["operator_username"], "operador")
                self.assertNotIn(admin_password, auth_path.read_text(encoding="utf-8"))
                self.assertNotIn(operator_password, auth_path.read_text(encoding="utf-8"))
                admin_client = first_app.test_client()
                page = admin_client.get("/login")
                response = admin_client.post(
                    "/login",
                    data={
                        "_csrf_token": self.token(page),
                        "username": "admin",
                        "password": admin_password,
                    },
                )
                self.assertEqual(response.status_code, 302)
                operator_client = first_app.test_client()
                page = operator_client.get("/login")
                response = operator_client.post(
                    "/login",
                    data={
                        "_csrf_token": self.token(page),
                        "username": "operador",
                        "password": operator_password,
                    },
                )
                self.assertEqual(response.status_code, 302)
            finally:
                first_app.executor.shutdown(wait=True)

            second_app = create_app(database=self.database)
            try:
                self.assertEqual(second_app.config["WEB_USERNAME"], "admin")
                second_client = second_app.test_client()
                page = second_client.get("/login")
                response = second_client.post(
                    "/login",
                    data={
                        "_csrf_token": self.token(page),
                        "username": "admin",
                        "password": admin_password,
                    },
                )
                self.assertEqual(response.status_code, 302)
                self.assertEqual(output.getvalue(), credentials)
            finally:
                second_app.executor.shutdown(wait=True)


if __name__ == "__main__":
    unittest.main()
