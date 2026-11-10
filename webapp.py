"""Interfaz web de ConectBioSync para uso en la red local."""
import io
import json
import logging
import os
import re
import secrets
import smtplib
import ssl
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from werkzeug.exceptions import NotFound
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.serving import run_simple

from app.api.asistencias import enviar_marcaciones
from app.api.organizaciones import cargar_catalogo
from app.database.database import Database
from app.api.configuracion_relojes import CAMPOS_POR_TIPO, generar_config_relojes
from app.operaciones import descargar, exportar_excel, limpiar_buffers, probar_conexion
from resources.config_path import (
    cargar_config_asistencias,
    cargar_config_conexion,
    cargar_config_empleados,
    cargar_relojes,
    crear_engine_externo,
    guardar_config_asistencias,
    guardar_config_conexion,
    guardar_config_empleados,
    get_config_relojes_path,
    _validar_identificador_sql,
)
from resources.db_engines import ENGINES

ENCABEZADOS = ["Dispositivo", "Empleado", "Fecha y hora", "Tipo de evento", "Método"]
QUERY_PAGE_SIZE = 20
ROOT = Path(__file__).resolve().parent
SERVER_PATH = "/ConectBioSync"
AUTH_CONFIG_PATH = (
    Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    / "ConectBioSync"
    / "web_auth.json"
)


SMTP_CONFIG_PATH = AUTH_CONFIG_PATH.with_name("smtp_config.json")
SMTP_TLS_MODES = {"none", "starttls", "ssl"}


def _smtp_defaults_from_env():
    try:
        port = int(os.environ.get("CONNECTBIOSYNC_SMTP_PORT", "587"))
    except ValueError:
        port = 587
    use_ssl = os.environ.get("CONNECTBIOSYNC_SMTP_SSL", "0") == "1"
    use_starttls = os.environ.get("CONNECTBIOSYNC_SMTP_STARTTLS", "1") == "1"
    tls_mode = "ssl" if use_ssl else "starttls" if use_starttls else "none"
    return {
        "host": os.environ.get("CONNECTBIOSYNC_SMTP_HOST", "").strip(),
        "port": port,
        "username": os.environ.get("CONNECTBIOSYNC_SMTP_USERNAME", "").strip(),
        "password": os.environ.get("CONNECTBIOSYNC_SMTP_PASSWORD", ""),
        "sender": os.environ.get("CONNECTBIOSYNC_SMTP_FROM", "").strip(),
        "tls_mode": tls_mode,
    }


def _load_smtp_config():
    try:
        saved = json.loads(SMTP_CONFIG_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _smtp_defaults_from_env()
    except (OSError, json.JSONDecodeError):
        logging.getLogger(__name__).exception("No se pudo leer la configuración SMTP persistida.")
        return _smtp_defaults_from_env()
    try:
        if not isinstance(saved, dict):
            raise ValueError("SMTP config must be an object")
        return {
            "host": str(saved.get("host", "")).strip(),
            "port": int(saved.get("port", 587)),
            "username": str(saved.get("username", "")).strip(),
            "password": str(saved.get("password", "")),
            "sender": str(saved.get("sender", "")).strip(),
            "tls_mode": str(saved.get("tls_mode", "starttls")),
        }
    except (TypeError, ValueError, AttributeError):
        logging.getLogger(__name__).exception("La configuración SMTP persistida es inválida.")
        return _smtp_defaults_from_env()


def _normalize_smtp_config(data, existing=None, clear_password=False):
    if not isinstance(data, dict):
        raise ValueError("La configuración SMTP no es válida.")
    existing = existing or {}
    host = str(data.get("host", "")).strip()
    sender = str(data.get("sender", "")).strip()
    username = str(data.get("username", "")).strip()
    raw_password = data.get("password", "")
    if not isinstance(raw_password, str):
        raise ValueError("La contraseña SMTP no es válida.")
    password = raw_password or ("" if clear_password else existing.get("password", ""))
    if isinstance(data.get("port"), bool):
        raise ValueError("El puerto SMTP debe ser numérico.")
    try:
        port = int(data.get("port", 587))
    except (TypeError, ValueError):
        raise ValueError("El puerto SMTP debe ser numérico.")
    tls_mode = data.get("tls_mode")
    if not host or len(host) > 253 or any(char.isspace() for char in host):
        raise ValueError("Ingresá un servidor SMTP válido.")
    if not 1 <= port <= 65535:
        raise ValueError("El puerto SMTP debe estar entre 1 y 65535.")
    if len(sender) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", sender):
        raise ValueError("Ingresá un correo remitente válido.")
    if tls_mode not in SMTP_TLS_MODES:
        raise ValueError("Elegí un modo de cifrado SMTP válido.")
    if bool(username) != bool(password):
        raise ValueError("Completá juntos el usuario y la contraseña SMTP, o dejá ambos vacíos.")
    return {
        "host": host,
        "port": port,
        "username": username,
        "password": password,
        "sender": sender,
        "tls_mode": tls_mode,
    }


def _public_smtp_config(config):
    return {
        "host": config.get("host", ""),
        "port": config.get("port", 587),
        "username": config.get("username", ""),
        "sender": config.get("sender", ""),
        "tls_mode": config.get("tls_mode", "starttls"),
        "password_configured": bool(config.get("password")),
    }


def _save_smtp_config(config):
    path = SMTP_CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as config_file:
            json.dump(config, config_file, indent=2)
            config_file.write("\n")
            config_file.flush()
            os.fsync(config_file.fileno())
        if os.name != "nt":
            os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        if os.name != "nt":
            os.chmod(path, 0o600)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise RuntimeError("No se pudo guardar la configuración SMTP local.") from exc


def _open_smtp_connection(config):
    if not config.get("host") or not config.get("sender"):
        raise RuntimeError("Completá el servidor SMTP y el correo remitente.")
    if config.get("tls_mode") not in SMTP_TLS_MODES:
        raise RuntimeError("El modo de cifrado SMTP no es válido.")
    if bool(config.get("username")) != bool(config.get("password")):
        raise RuntimeError("Configurá juntos el usuario y la contraseña SMTP.")
    server = None
    try:
        if config["tls_mode"] == "ssl":
            server = smtplib.SMTP_SSL(
                config["host"], int(config["port"]), timeout=15,
                context=ssl.create_default_context(),
            )
        else:
            server = smtplib.SMTP(config["host"], int(config["port"]), timeout=15)
        server.ehlo()
        if config["tls_mode"] == "starttls":
            server.starttls(context=ssl.create_default_context())
            server.ehlo()
        if config.get("username"):
            server.login(config["username"], config["password"])
        return server
    except Exception:
        if server is not None:
            server.close()
        raise


def _test_smtp_connection(config):
    server = _open_smtp_connection(config)
    try:
        return "Conexión SMTP y autenticación correctas. No se envió ningún correo."
    finally:
        try:
            server.quit()
        except (OSError, smtplib.SMTPException):
            server.close()


def _configuracion_entorno():
    return {
        "SECRET_KEY": os.environ.get("CONNECTBIOSYNC_SECRET_KEY"),
        "WEB_USERNAME": os.environ.get("CONNECTBIOSYNC_USERNAME"),
        "WEB_PASSWORD": os.environ.get("CONNECTBIOSYNC_PASSWORD"),
        "OPERATOR_USERNAME": os.environ.get("CONNECTBIOSYNC_OPERATOR_USERNAME"),
        "OPERATOR_PASSWORD": os.environ.get("CONNECTBIOSYNC_OPERATOR_PASSWORD"),
        "SESSION_COOKIE_SECURE": os.environ.get("CONNECTBIOSYNC_COOKIE_SECURE", "1") != "0",
    }


def _guardar_configuracion_auth(path, config):
    temporary_path = path.with_suffix(".json.tmp")
    try:
        with temporary_path.open("w", encoding="utf-8") as auth_file:
            json.dump(config, auth_file, indent=2)
            auth_file.write("\n")
            auth_file.flush()
            os.fsync(auth_file.fileno())
        os.replace(temporary_path, path)
    except OSError as exc:
        temporary_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"No se pudo guardar la configuración de acceso en {path}. "
            "Verificá los permisos del directorio."
        ) from exc


def _enviar_clave_temporal(email, username, password, smtp_config=None):
    config = smtp_config or _load_smtp_config()
    message = EmailMessage()
    message["Subject"] = "Restablecimiento de clave de ConectBioSync"
    message["From"] = config["sender"]
    message["To"] = email
    message.set_content(
        f"Hola {username},\n\n"
        "El administrador restableció tu clave de ConectBioSync.\n"
        f"Tu clave temporal es: {password}\n\n"
        "Al iniciar sesión, el sistema te pedirá que la cambies antes de continuar.\n"
        "No compartas este mensaje y elimina el correo después de cambiar la clave.\n"
    )

    try:
        server = _open_smtp_connection(config)
        with server:
            server.send_message(message)
    except RuntimeError:
        raise
    except (OSError, smtplib.SMTPException) as exc:
        raise RuntimeError(
            "No se pudo enviar la clave temporal por correo. "
            "Verificá la configuración SMTP y volvé a intentarlo."
        ) from exc


def _cargar_o_crear_configuracion_auth(initial):
    path = AUTH_CONFIG_PATH
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        path.parent.mkdir(parents=True, exist_ok=True)
        admin_password = "h81m-vg4"
        operator_password = initial.get("OPERATOR_PASSWORD") or secrets.token_urlsafe(24)
        config = {
            "secret_key": initial.get("SECRET_KEY") or secrets.token_hex(32),
            "username": initial.get("WEB_USERNAME") or "admin",
            "password_hash": generate_password_hash(admin_password),
            "operator_username": initial.get("OPERATOR_USERNAME") or "operador",
            "operator_password_hash": generate_password_hash(operator_password),
            "users": [
                {
                    "username": initial.get("WEB_USERNAME") or "admin",
                    "role": "admin",
                    "password_hash": generate_password_hash(admin_password),
                    "email": "",
                    "enabled": True,
                    "auth_version": 0,
                    "must_change_password": False,
                },
                {
                    "username": initial.get("OPERATOR_USERNAME") or "operador",
                    "role": "operator",
                    "password_hash": generate_password_hash(operator_password),
                    "email": "",
                    "enabled": True,
                    "auth_version": 0,
                    "must_change_password": False,
                },
            ],
        }
        try:
            with path.open("x", encoding="utf-8") as auth_file:
                json.dump(config, auth_file, indent=2)
                auth_file.write("\n")
                auth_file.flush()
                os.fsync(auth_file.fileno())
        except FileExistsError:
            return _cargar_o_crear_configuracion_auth(initial)
        if not initial.get("OPERATOR_PASSWORD"):
            print(
                "\nCredenciales iniciales de ConectBioSync "
                "(solo se mostrarán esta vez):\n"
                f"Administrador: {config['username']}"
                + f"\nOperador: {config['operator_username']}"
                + (f" / {operator_password}" if not initial.get("OPERATOR_PASSWORD") else "")
                + f"\nConfiguración: {path}\n"
            )
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"No se pudo leer la configuración de acceso en {path}. "
            "Verificá sus permisos y que el archivo JSON sea válido."
        ) from exc

    if not isinstance(config, dict) or not all(
        config.get(key) for key in ("secret_key", "username", "password_hash")
    ):
        raise RuntimeError(
            f"La configuración de acceso en {path} está incompleta. "
            "Corregila o eliminá el archivo para generar credenciales nuevas."
        )
    if not config.get("operator_password_hash"):
        operator_password = initial.get("OPERATOR_PASSWORD") or secrets.token_urlsafe(24)
        config["operator_username"] = config.get("operator_username") or "operador"
        config["operator_password_hash"] = generate_password_hash(operator_password)
        try:
            temporary_path = path.with_suffix(".json.tmp")
            with temporary_path.open("w", encoding="utf-8") as auth_file:
                json.dump(config, auth_file, indent=2)
                auth_file.write("\n")
                auth_file.flush()
                os.fsync(auth_file.fileno())
            os.replace(temporary_path, path)
        except OSError as exc:
            raise RuntimeError(
                f"No se pudo guardar el perfil de operador en {path}. "
                "Verificá los permisos del directorio."
            ) from exc
        if not initial.get("OPERATOR_PASSWORD"):
            print(
                "\nSe creó el perfil de operador de ConectBioSync. "
                "Guardá esta contraseña: no se volverá a mostrar.\n"
                f"Usuario: {config['operator_username']}\n"
                f"Contraseña: {operator_password}\n"
                f"Configuración: {path}\n"
            )
    if not isinstance(config.get("users"), list):
        config["users"] = [
            {
                "username": config["username"],
                "role": "admin",
                "password_hash": config["password_hash"],
                "email": "",
                "enabled": True,
                "auth_version": 0,
                "must_change_password": False,
            },
            {
                "username": config["operator_username"],
                "role": "operator",
                "password_hash": config["operator_password_hash"],
                "email": "",
                "enabled": True,
                "auth_version": 0,
                "must_change_password": False,
            },
        ]
        _guardar_configuracion_auth(path, config)
    if not config["users"] or any(
        not isinstance(user, dict)
        or not all(user.get(key) for key in ("username", "role", "password_hash"))
        or user.get("role") not in ("admin", "operator")
        for user in config["users"]
    ):
        raise RuntimeError(
            f"La lista de usuarios en {path} es inválida. "
            "Corregí la configuración antes de iniciar el servidor."
        )
    protected_admin_username = config.get("protected_admin_username") or config["username"]
    protected_admin = next(
        (user for user in config["users"] if user["username"].casefold() == protected_admin_username.casefold()),
        None,
    )
    if protected_admin is None or protected_admin["role"] != "admin":
        raise RuntimeError("La cuenta administradora protegida no existe o no tiene perfil admin.")
    auth_changed = config.get("protected_admin_username") != protected_admin_username
    config["protected_admin_username"] = protected_admin_username
    for user in config["users"]:
        is_protected = user["username"].casefold() == protected_admin_username.casefold()
        if user.get("protected", False) != is_protected:
            user["protected"] = is_protected
            auth_changed = True
    if auth_changed:
        _guardar_configuracion_auth(path, config)
    return {
        "SECRET_KEY": config["secret_key"],
        "WEB_USERNAME": config["username"],
        "WEB_PASSWORD_HASH": config["password_hash"],
        "OPERATOR_USERNAME": config["operator_username"],
        "OPERATOR_PASSWORD_HASH": config["operator_password_hash"],
        "USERS": config["users"],
        "PROTECTED_ADMIN_USERNAME": protected_admin_username,
    }


def create_app(overrides=None, database=None):
    app = Flask(__name__)
    initial_config = _configuracion_entorno()
    if overrides:
        initial_config.update(overrides)
    test_or_explicit_users = bool(overrides and overrides.get("WEB_USERNAME"))
    missing_auth_config = (
        not initial_config.get("SECRET_KEY")
        or not initial_config.get("WEB_USERNAME")
        or not (initial_config.get("WEB_PASSWORD") or initial_config.get("WEB_PASSWORD_HASH"))
        or not initial_config.get("OPERATOR_USERNAME")
        or not (
            initial_config.get("OPERATOR_PASSWORD")
            or initial_config.get("OPERATOR_PASSWORD_HASH")
        )
    )
    if missing_auth_config or not test_or_explicit_users:
        persisted_config = _cargar_o_crear_configuracion_auth(initial_config)
        for key, value in persisted_config.items():
            if not initial_config.get(key):
                initial_config[key] = value
        if not (overrides and overrides.get("WEB_USERNAME")):
            initial_config["USERS"] = persisted_config["USERS"]
    if not initial_config.get("USERS"):
        initial_config["USERS"] = [
            {
                "username": initial_config["WEB_USERNAME"],
                "role": "admin",
                "password_hash": initial_config.get("WEB_PASSWORD_HASH")
                or generate_password_hash(str(initial_config["WEB_PASSWORD"])),
                "email": "",
                "enabled": True,
                "auth_version": 0,
                "must_change_password": False,
            },
            {
                "username": initial_config["OPERATOR_USERNAME"],
                "role": "operator",
                "password_hash": initial_config.get("OPERATOR_PASSWORD_HASH")
                or generate_password_hash(str(initial_config["OPERATOR_PASSWORD"])),
                "email": "",
                "enabled": True,
                "auth_version": 0,
                "must_change_password": False,
            },
        ]
    if not initial_config.get("PROTECTED_ADMIN_USERNAME"):
        initial_config["PROTECTED_ADMIN_USERNAME"] = next(
            user["username"] for user in initial_config["USERS"] if user["role"] == "admin"
        )
    for user in initial_config["USERS"]:
        user["protected"] = user["username"].casefold() == initial_config["PROTECTED_ADMIN_USERNAME"].casefold()
    app.config.update(initial_config)
    app.config["SMTP_CONFIG"] = _load_smtp_config()
    app.smtp_lock = threading.RLock()
    app.config["USERS"] = [dict(user) for user in app.config["USERS"]]
    usernames = set()
    for user in app.config["USERS"]:
        username = user.get("username")
        if (
            not isinstance(username, str)
            or not re.fullmatch(r"[A-Za-z0-9_.@-]{3,50}", username)
            or user.get("role") not in ("admin", "operator")
            or not isinstance(user.get("password_hash"), str)
            or not isinstance(user.get("email", ""), str)
            or not isinstance(user.get("enabled", True), bool)
            or isinstance(user.get("auth_version", 0), bool)
            or not isinstance(user.get("auth_version", 0), int)
            or user.get("auth_version", 0) < 0
            or not isinstance(user.get("must_change_password", False), bool)
            or username.casefold() in usernames
        ):
            raise RuntimeError("La lista de usuarios configurada contiene datos inválidos.")
        usernames.add(username.casefold())
    if not any(
        user["role"] == "admin" and user.get("enabled", True)
        for user in app.config["USERS"]
    ):
        raise RuntimeError("Debe existir al menos un administrador activo.")
    app.account_lock = threading.RLock()
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,
    )
    db_path = os.environ.get("CONNECTBIOSYNC_DATABASE", str(ROOT / "data" / "marcaciones.db"))
    app.database = database or Database(db_path)
    app.jobs = {}
    app.queries = {}
    app.state_lock = threading.Lock()
    app.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="conectbiosync")
    app.export_dir = Path(tempfile.gettempdir()) / "ConectBioSync-exports"
    app.export_dir.mkdir(parents=True, exist_ok=True)

    def csrf_token():
        token = session.get("_csrf_token")
        if not token:
            token = secrets.token_urlsafe(32)
            session["_csrf_token"] = token
        return token

    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.before_request
    def protect_routes():
        if request.endpoint == "static":
            return None
        if request.endpoint not in ("login", "login_post") and not session.get("authenticated"):
            if request.path.startswith("/api/"):
                return jsonify(error="Iniciá sesión para continuar."), 401
            return redirect(url_for("login"))
        if (
            session.get("role") != "admin"
            and request.endpoint in {
                "settings",
                "organizations",
                "save_settings",
                "test_connection",
                "test_smtp_connection",
                "list_users",
                "manage_users",
            }
        ):
            return jsonify(error="Solo el perfil administrador puede acceder a la configuración."), 403
        if session.get("authenticated"):
            with app.account_lock:
                account = next(
                    (
                        user for user in app.config["USERS"]
                        if user["username"].casefold() == str(session.get("username", "")).casefold()
                    ),
                    None,
                )
            if (
                account is None
                or not account.get("enabled", True)
                or account["role"] != session.get("role")
                or int(account.get("auth_version", 0)) != session.get("auth_version", 0)
            ):
                session.clear()
                if request.path.startswith("/api/"):
                    return jsonify(error="Tu sesión ya no es válida. Iniciá sesión nuevamente."), 401
                return redirect(url_for("login"))
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            provided = request.headers.get("X-CSRF-Token") or request.form.get("_csrf_token", "")
            expected = session.get("_csrf_token", "")
            if not expected or not secrets.compare_digest(provided, expected):
                if request.path.startswith("/api/"):
                    return jsonify(error="La sesión expiró. Recargá la página e intentá de nuevo."), 400
                abort(400, "Token de formulario inválido.")
        if (
            session.get("authenticated")
            and session.get("must_change_password")
            and request.endpoint not in ("change_password", "change_password_post", "logout")
        ):
            if request.path.startswith("/api/"):
                return jsonify(error="Cambiá tu clave temporal antes de continuar."), 403
            return redirect(url_for("change_password"))
        return None

    def owner_key():
        if "owner_key" not in session:
            session["owner_key"] = secrets.token_urlsafe(24)
        return session["owner_key"]

    def json_object():
        data = request.get_json(silent=True)
        return data if isinstance(data, dict) else None

    def run_job(job_id, operation):
        def report(percent, message):
            with app.state_lock:
                job = app.jobs[job_id]
                job["progress"] = percent
                job["message"] = str(message)

        try:
            result = operation(report)
            with app.state_lock:
                job = app.jobs[job_id]
                job["status"] = "completed"
                job["result"] = result
                job["progress"] = 100
                if not job["message"]:
                    job["message"] = "Tarea completada."
        except Exception as exc:
            app.logger.exception("Falló una tarea web de ConectBioSync (%s).", job_id)
            with app.state_lock:
                job = app.jobs[job_id]
                job["status"] = "error"
                job["error"] = (
                    f"No se pudo completar la operación ({type(exc).__name__}). "
                    "Revisá la conexión, los permisos y la configuración."
                )

    def start_job(kind, operation):
        job_id = uuid.uuid4().hex
        with app.state_lock:
            app.jobs[job_id] = {
                "owner": owner_key(),
                "kind": kind,
                "status": "running",
                "progress": -1,
                "message": "Iniciando…",
                "error": None,
                "result": None,
                "created": datetime.now().timestamp(),
            }
        app.executor.submit(run_job, job_id, operation)
        return job_id

    def get_owned_job(job_id):
        with app.state_lock:
            job = app.jobs.get(job_id)
            if job is None or job["owner"] != owner_key():
                abort(404)
            return dict(job)

    def clean_expired_state():
        cutoff = datetime.now().timestamp() - 3600
        with app.state_lock:
            for key in [k for k, value in app.jobs.items()
                        if value["created"] < cutoff and value["status"] != "running"]:
                job = app.jobs.pop(key)
                if job["kind"] == "export" and job["result"]:
                    try:
                        Path(job["result"]).unlink(missing_ok=True)
                    except OSError:
                        app.logger.exception("No se pudo eliminar una exportación temporal.")
            for key in [k for k, value in app.queries.items() if value["created"] < cutoff]:
                app.queries.pop(key)

    @app.get("/login")
    def login():
        if session.get("authenticated"):
            return redirect(url_for("index"))
        return render_template("login.html")

    @app.post("/login")
    def login_post():
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        with app.account_lock:
            accounts = [dict(user) for user in app.config["USERS"] if user.get("enabled", True)]
        for account in accounts:
            if (
                secrets.compare_digest(username.casefold(), account["username"].casefold())
                and check_password_hash(account["password_hash"], password)
            ):
                session.clear()
                session["authenticated"] = True
                session["username"] = account["username"]
                session["role"] = account["role"]
                session["auth_version"] = int(account.get("auth_version", 0))
                session["must_change_password"] = bool(account.get("must_change_password", False))
                csrf_token()
                return redirect(url_for("index"))
        flash("Usuario o contraseña incorrectos.", "error")
        return render_template("login.html"), 401

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/change-password", methods=["GET", "POST"])
    def change_password():
        if request.method == "POST":
            return change_password_post()
        return render_template("change_password.html", csrf=csrf_token())

    def change_password_post():
        current_password = request.form.get("current_password", "")
        password = request.form.get("password", "")
        confirmation = request.form.get("confirmation", "")
        with app.account_lock:
            current_account = next(
                (user for user in app.config["USERS"] if user["username"].casefold() == session.get("username", "").casefold()),
                None,
            )
            if current_account is None or not check_password_hash(current_account["password_hash"], current_password):
                return render_template(
                    "change_password.html", csrf=csrf_token(),
                    error="La clave actual es incorrecta.",
                ), 403
        if len(password) < 12 or len(password) > 256:
            return render_template(
                "change_password.html",
                csrf=csrf_token(),
                error="La nueva clave debe tener entre 12 y 256 caracteres.",
            ), 400
        if not secrets.compare_digest(password, confirmation):
            return render_template(
                "change_password.html",
                csrf=csrf_token(),
                error="Las claves no coinciden.",
            ), 400
        with app.account_lock:
            users = [dict(user) for user in app.config["USERS"]]
            account = next(
                user for user in users
                if user["username"].casefold() == session["username"].casefold()
            )
            account["password_hash"] = generate_password_hash(password)
            account["must_change_password"] = False
            account["auth_version"] = int(account.get("auth_version", 0)) + 1
            _persist_users(users)
            app.config["USERS"] = users
            session["auth_version"] = account["auth_version"]
            session["must_change_password"] = False
        flash("La clave se cambió correctamente.", "success")
        return redirect(url_for("index"))

    @app.get("/")
    def index():
        clean_expired_state()
        count = app.database.obtener_todas_marcaciones(
            date.today().replace(day=1).isoformat(), date.today().isoformat()
        )
        return render_template(
            "index.html",
            user=session.get("username", ""),
            is_admin=session.get("role") == "admin",
            today=date.today().isoformat(),
            month_count=len(count),
            csrf=csrf_token(),
        )

    @app.get("/api/status")
    def status():
        return jsonify(
            configured_clocks=len(cargar_relojes()),
        )

    @app.get("/api/users")
    def list_users():
        with app.account_lock:
            users = [
                {
                    "username": user["username"],
                    "role": user["role"],
                    "email": user.get("email", ""),
                    "enabled": user.get("enabled", True),
                    "protected": user.get("protected", False),
                }
                for user in app.config["USERS"]
            ]
        return jsonify(users=users)

    @app.post("/api/users")
    def manage_users():
        data = json_object()
        if data is None:
            return jsonify(error="El cuerpo de la solicitud no es válido."), 400
        action = data.get("action")
        try:
            with app.account_lock:
                previous_users = [dict(user) for user in app.config["USERS"]]
                users = [dict(user) for user in previous_users]
                result = _manage_users(users, data, session.get("username"), app.config["PROTECTED_ADMIN_USERNAME"])
                if action == "reset_password":
                    _persist_users(users)
                    try:
                        _enviar_clave_temporal(
                            result["email"],
                            result["username"],
                            result["temporary_password"],
                            dict(app.config["SMTP_CONFIG"]),
                        )
                    except Exception as send_error:
                        try:
                            _persist_users(previous_users)
                        except Exception as rollback_error:
                            app.logger.exception(
                                "No se pudo revertir el restablecimiento de clave."
                            )
                            raise RuntimeError(
                                "Falló el correo y no se pudo revertir el restablecimiento. "
                                "Contactá al administrador del sistema."
                            ) from rollback_error
                        raise RuntimeError(
                            "No se envió el correo; el restablecimiento de clave fue cancelado."
                        ) from send_error
                    result["message"] = (
                        f"Se envió una clave temporal a {result['email']}. "
                        "El usuario deberá cambiarla al iniciar sesión."
                    )
                    result.pop("email")
                else:
                    _persist_users(users)
                app.config["USERS"] = users
            if result.get("acting_user_changed", False):
                session.clear()
            return jsonify(result)
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        except Exception as exc:
            app.logger.exception("No se pudo administrar los usuarios.")
            return jsonify(error=f"No se pudieron guardar los usuarios ({type(exc).__name__})."), 500

    def _persist_users(users):
        auth_path = AUTH_CONFIG_PATH
        try:
            config = json.loads(auth_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            app.logger.exception("No se pudo leer la configuración persistente de usuarios.")
            raise RuntimeError("No se pudo leer la configuración persistente de acceso.") from exc
        config["users"] = users
        protected_name = config.get("protected_admin_username") or config.get("username")
        admin = next(
            (user for user in users if user["username"].casefold() == protected_name.casefold()),
            None,
        )
        if admin is None or admin["role"] != "admin" or not admin.get("enabled", True):
            raise RuntimeError("La cuenta administradora protegida no está disponible.")
        config["username"] = admin["username"]
        config["password_hash"] = admin["password_hash"]
        operator = next((user for user in users if user["role"] == "operator"), None)
        if operator:
            config["operator_username"] = operator["username"]
            config["operator_password_hash"] = operator["password_hash"]
        _guardar_configuracion_auth(auth_path, config)

    def _manage_users(users, data, acting_username, protected_admin_username):
        action = data.get("action")
        if action == "create":
            username = _validate_username(data.get("username"))
            role = data.get("role")
            if role not in ("admin", "operator"):
                raise ValueError("Elegí un perfil válido.")
            if any(user["username"].casefold() == username.casefold() for user in users):
                raise ValueError("Ya existe un usuario con ese nombre.")
            temporary_password = secrets.token_urlsafe(18)
            users.append(
                {
                    "username": username,
                    "role": role,
                    "password_hash": generate_password_hash(temporary_password),
                    "email": _validate_email(data.get("email")),
                    "enabled": True,
                    "auth_version": 0,
                    "must_change_password": True,
                }
            )
            return {
                "message": "Usuario creado.",
                "temporary_password": temporary_password,
                "username": username,
            }

        target_name = _validate_username(data.get("target_username"))
        target = next(
            (user for user in users if user["username"].casefold() == target_name.casefold()),
            None,
        )
        if target is None:
            raise ValueError("No existe el usuario indicado.")
        if target["username"].casefold() == protected_admin_username.casefold():
            raise ValueError("La cuenta administradora protegida solo puede cambiar su propia clave desde Cambiar clave.")

        if action == "reset_password":
            email = _validate_email(target.get("email", ""))
            temporary_password = secrets.token_urlsafe(18)
            target["password_hash"] = generate_password_hash(temporary_password)
            target["auth_version"] = int(target.get("auth_version", 0)) + 1
            target["must_change_password"] = True
            return {
                "message": "Se envió una clave temporal por correo.",
                "temporary_password": temporary_password,
                "username": target["username"],
                "email": email,
                "acting_user_changed": (
                    target["username"].casefold() == str(acting_username).casefold()
                ),
            }

        if action == "update":
            new_username = _validate_username(data.get("username"))
            role = data.get("role")
            enabled = data.get("enabled")
            email = _validate_email(data.get("email"))
            if role not in ("admin", "operator"):
                raise ValueError("Elegí un perfil válido.")
            if not isinstance(enabled, bool):
                raise ValueError("El estado activo debe ser verdadero o falso.")
            if any(
                user is not target and user["username"].casefold() == new_username.casefold()
                for user in users
            ):
                raise ValueError("Ya existe un usuario con ese nombre.")
            target.update(username=new_username, role=role, email=email, enabled=enabled)
        elif action == "delete":
            users.remove(target)
        else:
            raise ValueError("La operación de usuarios no es válida.")

        active_admins = [
            user for user in users if user["role"] == "admin" and user.get("enabled", True)
        ]
        if not active_admins:
            raise ValueError("Debe quedar al menos un administrador activo.")
        return {
            "message": "Usuario actualizado." if action == "update" else "Usuario eliminado.",
            "acting_user_changed": (
                target_name.casefold() == str(acting_username).casefold()
                and (
                    action == "delete"
                    or target["username"].casefold() != target_name.casefold()
                    or target["role"] != "admin"
                    or not target["enabled"]
                )
            ),
        }

    def _validate_username(value):
        if not isinstance(value, str):
            raise ValueError("Ingresá un nombre de usuario.")
        username = value.strip()
        if not re.fullmatch(r"[A-Za-z0-9_.@-]{3,50}", username):
            raise ValueError(
                "El usuario debe tener entre 3 y 50 caracteres: letras, números, punto, guion, guion bajo o @."
            )
        return username

    def _validate_email(value):
        if not isinstance(value, str):
            raise ValueError("Ingresá un correo electrónico válido para el usuario.")
        email = value.strip()
        if len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            raise ValueError("Ingresá un correo electrónico válido para el usuario.")
        return email

    @app.post("/api/download")
    def download():
        data = json_object()
        if data is None:
            return jsonify(error="El cuerpo de la solicitud no es válido."), 400
        period = data.get("period")
        today = date.today()
        if period == "previous_month":
            end = today.replace(day=1) - timedelta(days=1)
            start = end.replace(day=1)
        elif period == "last_7_days":
            start, end = today - timedelta(days=7), today
        elif period == "custom":
            try:
                start = date.fromisoformat(str(data.get("since", "")))
                end = date.fromisoformat(str(data.get("until", "")))
            except (TypeError, ValueError):
                return jsonify(error="Ingresá un rango de fechas válido."), 400
            if start > end:
                return jsonify(error="La fecha inicial debe ser anterior o igual a la fecha final."), 400
        else:
            return jsonify(error="Seleccioná un período de descarga válido."), 400
        clocks = cargar_relojes()
        if not clocks:
            return jsonify(error="No hay relojes configurados."), 400
        job_id = start_job(
            "download",
            lambda progress: descargar(
                clocks, str(app.database.ruta.resolve()), start.isoformat(), end.isoformat(), progress
            ),
        )
        return jsonify(job_id=job_id, since=start.isoformat(), until=end.isoformat()), 202

    @app.post("/api/query")
    def query_records():
        data = json_object()
        if data is None:
            return jsonify(error="El cuerpo de la solicitud no es válido."), 400
        since, until = data.get("since", ""), data.get("until", "")
        try:
            start, end = date.fromisoformat(since), date.fromisoformat(until)
        except (TypeError, ValueError):
            return jsonify(error="Ingresá fechas válidas."), 400
        if start > end:
            return jsonify(error="La fecha inicial debe ser anterior a la final."), 400
        card = str(data.get("card", "")).strip()
        rows = app.database.obtener_marcaciones_filtradas(since, until, tarjeta=card or None)
        query_id = uuid.uuid4().hex
        with app.state_lock:
            app.queries[query_id] = {
                "owner": owner_key(),
                "rows": rows,
                "created": datetime.now().timestamp(),
            }
        return jsonify(query_id=query_id, total=len(rows), page_size=QUERY_PAGE_SIZE, rows=rows[:QUERY_PAGE_SIZE])

    @app.get("/api/query/<query_id>")
    def query_page(query_id):
        try:
            offset = max(0, int(request.args.get("offset", "0")))
        except ValueError:
            return jsonify(error="Página inválida."), 400
        with app.state_lock:
            result = app.queries.get(query_id)
            if result is None or result["owner"] != owner_key():
                abort(404)
            rows = result["rows"]
        return jsonify(rows=rows[offset:offset + QUERY_PAGE_SIZE], total=len(rows), offset=offset, page_size=QUERY_PAGE_SIZE)

    def selected_rows(data, query_id):
        with app.state_lock:
            result = app.queries.get(query_id)
            if result is None or result["owner"] != owner_key():
                abort(404)
            rows = result["rows"]
        indices = data.get("indices", [])
        if not isinstance(indices, list) or len(indices) > len(rows):
            abort(400, "La selección de marcaciones no es válida.")
        for index in indices:
            if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(rows):
                abort(400, "La selección contiene una fila no válida.")
        if data.get("all") is True:
            excluded = set(indices)
            return [row for index, row in enumerate(rows) if index not in excluded]
        return [rows[index] for index in indices]

    @app.post("/api/export")
    def export():
        data = json_object()
        if data is None:
            return jsonify(error="El cuerpo de la solicitud no es válido."), 400
        try:
            rows = selected_rows(data, str(data.get("query_id", "")))
        except (TypeError, ValueError):
            return jsonify(error="La selección de marcaciones no es válida."), 400
        if not rows:
            return jsonify(error="Seleccioná al menos una marcación."), 400
        path = app.export_dir / f"{uuid.uuid4().hex}.xlsx"

        def make_export(progress):
            exportar_excel(rows, path, ENCABEZADOS, progress)
            return str(path)

        job_id = start_job("export", make_export)
        return jsonify(job_id=job_id), 202

    @app.post("/api/send")
    def send_records():
        data = json_object()
        if data is None:
            return jsonify(error="El cuerpo de la solicitud no es válido."), 400
        try:
            rows = selected_rows(data, str(data.get("query_id", "")))
        except (TypeError, ValueError):
            return jsonify(error="La selección de marcaciones no es válida."), 400
        if not rows:
            return jsonify(error="Seleccioná al menos una marcación."), 400
        return jsonify(job_id=start_job("send", lambda progress: enviar_marcaciones(rows))), 202

    @app.get("/api/jobs/<job_id>")
    def job_status(job_id):
        job = get_owned_job(job_id)
        result = job["result"]
        if job["kind"] == "export":
            result = {"download_url": url_for("download_export", job_id=job_id)} if result else None
        return jsonify(
            status=job["status"],
            kind=job["kind"],
            progress=job["progress"],
            message=job["message"],
            error=job["error"],
            result=result,
        )

    @app.get("/api/jobs/<job_id>/file")
    def download_export(job_id):
        job = get_owned_job(job_id)
        if job["kind"] != "export" or job["status"] != "completed" or not job["result"]:
            abort(404)
        path = Path(job["result"])
        try:
            contents = path.read_bytes()
            path.unlink()
        except OSError:
            app.logger.exception("No se pudo leer el archivo Excel de la tarea %s.", job_id)
            return jsonify(error="No se pudo leer el archivo exportado."), 500
        return send_file(
            io.BytesIO(contents),
            as_attachment=True,
            download_name=f"marcaciones_{date.today().isoformat()}.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @app.post("/api/clean-buffers")
    def clear_buffers():
        data = json_object()
        if data is None:
            return jsonify(error="El cuerpo de la solicitud no es válido."), 400
        if data.get("confirmation") != "BORRAR":
            return jsonify(error="Escribí BORRAR para confirmar la limpieza irreversible."), 400
        clocks = cargar_relojes()
        if not clocks:
            return jsonify(error="No hay relojes configurados."), 400
        return jsonify(job_id=start_job("clean", lambda progress: limpiar_buffers(clocks, progress))), 202

    @app.get("/api/settings")
    def settings():
        connection = dict(cargar_config_conexion())
        connection["password_configured"] = bool(connection.get("password"))
        connection["password"] = ""
        clocks = cargar_relojes()
        safe_clocks = []
        for clock in clocks:
            item = {"tipo": clock["tipo"], "params": dict(clock["params"])}
            if "password" in item["params"]:
                item["params"]["password"] = ""
            safe_clocks.append(item)
        return jsonify(
            engines={key: value["label"] for key, value in ENGINES.items()},
            clocks=safe_clocks,
            connection=connection,
            employees=cargar_config_empleados(),
            assistances=cargar_config_asistencias(),
            smtp=_public_smtp_config(app.config["SMTP_CONFIG"]),
        )

    @app.post("/api/settings/schema")
    def settings_schema():
        data = json_object()
        if data is None or not isinstance(data.get("connection"), dict):
            return jsonify(error="Indicá los datos de conexión para consultar las tablas."), 400
        engine = None
        try:
            connection = _connection_config(data["connection"])
            engine = crear_engine_externo(connection)
            from sqlalchemy import inspect
            inspector = inspect(engine)
            tables = []
            for table_name in inspector.get_table_names():
                tables.append({"name": table_name, "columns": [column["name"] for column in inspector.get_columns(table_name)]})
            return jsonify(tables=tables)
        except (KeyError, TypeError, ValueError) as exc:
            return jsonify(error=str(exc)), 400
        except Exception as exc:
            app.logger.exception("No se pudo consultar el esquema de la base de datos.")
            return jsonify(error=f"No se pudo consultar el esquema ({type(exc).__name__})."), 400
        finally:
            if engine is not None:
                engine.dispose()
    @app.get("/api/settings/organizations")
    def organizations():
        try:
            rows, relationship = cargar_catalogo(cargar_config_empleados(), cargar_config_conexion())
        except Exception as exc:
            app.logger.exception("No se pudo consultar el catálogo de organizaciones.")
            return jsonify(error=f"No se pudieron cargar organizaciones ({type(exc).__name__})."), 400
        return jsonify(rows=rows, relationship=relationship)

    @app.post("/api/settings")
    def save_settings():
        data = json_object()
        if data is None:
            return jsonify(error="El cuerpo de la solicitud no es válido."), 400
        section = data.get("section")
        try:
            _save_settings(data, section)
        except (KeyError, TypeError, ValueError) as exc:
            return jsonify(error=str(exc)), 400
        except Exception as exc:
            app.logger.exception("No se pudo guardar la configuración web.")
            return jsonify(error=f"No se pudo guardar la configuración ({type(exc).__name__})."), 500
        return jsonify(message="Configuración guardada.")

    @app.post("/api/settings/test-connection")
    def test_connection():
        data = json_object()
        if data is None:
            return jsonify(error="El cuerpo de la solicitud no es válido."), 400
        connection = data.get("connection")
        if not isinstance(connection, dict):
            return jsonify(error="La configuración de conexión no es válida."), 400
        try:
            connection = _connection_config(connection)
        except (KeyError, TypeError, ValueError) as exc:
            return jsonify(error=str(exc)), 400
        return jsonify(
            job_id=start_job(
                "test_connection",
                lambda progress: probar_conexion(connection, progress),
            )
        ), 202

    @app.post("/api/settings/test-smtp")
    def test_smtp_connection():
        data = json_object()
        if data is None:
            return jsonify(error="El cuerpo de la solicitud no es válido."), 400
        with app.smtp_lock:
            current = dict(app.config["SMTP_CONFIG"])
        try:
            config = _normalize_smtp_config(
                data.get("smtp"), current, bool(data.get("clear_password", False))
            )
            message = _test_smtp_connection(config)
        except (KeyError, TypeError, ValueError, RuntimeError) as exc:
            return jsonify(error=str(exc)), 400
        except (OSError, smtplib.SMTPException) as exc:
            return jsonify(
                error=f"No se pudo conectar o autenticar con SMTP ({type(exc).__name__})."
            ), 400
        return jsonify(message=message)

    def _connection_config(connection):
        motor = connection.get("motor")
        if motor not in ENGINES:
            raise ValueError("Motor de base de datos no soportado.")
        current = cargar_config_conexion()
        same_target = all(
            connection.get(key) == current.get(key)
            for key in ("motor", "host", "puerto", "usuario", "base_datos", "archivo_sqlite")
        )
        password = connection.get("password") or (
            current.get("password", "") if same_target else ""
        )
        if ENGINES[motor]["requiere_archivo"]:
            sqlite_file = str(connection.get("archivo_sqlite", "")).strip()
            if not sqlite_file:
                raise ValueError("Indicá la ruta del archivo SQLite.")
            return {
                "motor": motor, "host": "", "puerto": None, "usuario": "",
                "password": "", "base_datos": "", "archivo_sqlite": sqlite_file,
            }
        if isinstance(connection.get("puerto"), bool):
            raise ValueError("El puerto debe ser numérico.")
        try:
            port = int(connection.get("puerto"))
        except (TypeError, ValueError):
            raise ValueError("El puerto debe ser numérico.")
        host = str(connection.get("host", "")).strip()
        username = str(connection.get("usuario", "")).strip()
        database_name = str(connection.get("base_datos", "")).strip()
        if not host or not username or not database_name or not 1 <= port <= 65535:
            raise ValueError("Completá host, puerto, usuario y base de datos.")
        return {
            "motor": motor, "host": host, "puerto": port, "usuario": username,
            "password": password, "base_datos": database_name, "archivo_sqlite": "",
        }

    def _save_settings(data, section):
        if not isinstance(data, dict):
            raise ValueError("Formato de configuración inválido.")
        if section == "smtp":
            with app.smtp_lock:
                config = _normalize_smtp_config(
                    data.get("smtp"),
                    app.config["SMTP_CONFIG"],
                    bool(data.get("clear_password", False)),
                )
                _save_smtp_config(config)
                app.config["SMTP_CONFIG"] = config
            return
        if section == "clocks":
            clocks = data.get("clocks")
            if not isinstance(clocks, list):
                raise ValueError("La lista de relojes no es válida.")


            old_by_id = {
                str(clock["params"].get("dispositivo_id")): clock
                for clock in cargar_relojes()
            }
            validated = []
            ids = set()
            for clock in clocks:
                if not isinstance(clock, dict) or clock.get("tipo") not in CAMPOS_POR_TIPO:
                    raise ValueError("Tipo de reloj no soportado.")
                kind = clock["tipo"]
                values = clock.get("params")
                if not isinstance(values, dict):
                    raise ValueError("Los parámetros del reloj no son válidos.")
                params = {}
                for name, field_type, default in CAMPOS_POR_TIPO[kind]:
                    value = values.get(name, default)
                    if field_type is bool:
                        if not isinstance(value, bool):
                            raise ValueError(f"El campo {name} debe ser verdadero o falso.")
                    elif field_type is int:
                        if isinstance(value, bool):
                            raise ValueError(f"El campo {name} debe ser un número.")
                        try:
                            value = int(value)
                        except (TypeError, ValueError):
                            raise ValueError(f"El campo {name} debe ser un número.")
                        if name == "puerto" and not 1 <= value <= 65535:
                            raise ValueError("El puerto debe estar entre 1 y 65535.")
                    else:
                        value = str(value).strip()
                        if name in ("ip", "dispositivo_id") and not value:
                            raise ValueError(f"El campo {name} es obligatorio.")
                    params[name] = value
                device_id = str(params["dispositivo_id"])
                if device_id in ids:
                    raise ValueError("Hay más de un reloj con el mismo ID de dispositivo.")
                ids.add(device_id)
                old = old_by_id.get(device_id)
                if params.get("password") == "" and old and old["tipo"] == kind:
                    params["password"] = old["params"].get("password", "")
                validated.append({"tipo": kind, "params": params})
            config_path = Path(get_config_relojes_path())
            temp_path = config_path.with_suffix(config_path.suffix + ".tmp")
            try:
                temp_path.write_text(generar_config_relojes(validated), encoding="utf-8")
                os.replace(temp_path, config_path)
            finally:
                temp_path.unlink(missing_ok=True)
            return

        if section == "connection":
            connection = data.get("connection")
            if not isinstance(connection, dict):
                raise ValueError("La configuración de conexión no es válida.")
            guardar_config_conexion(_connection_config(connection))
            return

        if section == "employees":
            employees = data.get("employees")
            if not isinstance(employees, dict):
                raise ValueError("La configuración de empleados no es válida.")
            employee_config = {
                "tabla": str(employees.get("tabla", "")).strip(),
                "columna_id": str(employees.get("columna_id", "")).strip(),
                "columna_id_interno": str(employees.get("columna_id_interno", "")).strip(),
                "columna_nombre": str(employees.get("columna_nombre", "")).strip(),
                "organizacion_id": str(employees.get("organizacion_id", "")).strip(),
            }
            if not all(employee_config.values()):
                raise ValueError("Completá todos los campos de empleados y elegí una organización.")
            for key in ("tabla", "columna_id", "columna_id_interno", "columna_nombre"):
                _validar_identificador_sql(employee_config[key])
            organizations, relation = cargar_catalogo(employee_config, cargar_config_conexion())
            if employee_config["organizacion_id"] not in {identifier for identifier, _ in organizations}:
                raise ValueError("La organización seleccionada no existe en el catálogo.")
            guardar_config_empleados({**employee_config, **relation})
            return

        if section == "assistances":
            assistances = data.get("assistances")
            if not isinstance(assistances, dict):
                raise ValueError("La configuración de asistencias no es válida.")
            fields = (
                "tabla", "columna_empleado", "columna_fecha", "columna_hora",
                "columna_tipo", "columna_reloj", "columna_c_ver",
            )
            assistance_config = {key: str(assistances.get(key, "")).strip() for key in fields}
            if not all(assistance_config.values()):
                raise ValueError("Completá todos los campos de la tabla de asistencias.")
            for value in assistance_config.values():
                _validar_identificador_sql(value)
            guardar_config_asistencias(assistance_config)
            return

        raise ValueError("Elegí qué sección de configuración guardar.")

    return app


def create_server_application(app=None):
    """Monta la aplicación bajo el prefijo público solicitado."""
    return DispatcherMiddleware(
        NotFound(),
        {SERVER_PATH: app or create_app()},
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    certificate = os.environ.get("CONNECTBIOSYNC_TLS_CERT")
    private_key = os.environ.get("CONNECTBIOSYNC_TLS_KEY")
    if bool(certificate) != bool(private_key):
        raise RuntimeError(
            "Configurá juntos CONNECTBIOSYNC_TLS_CERT y CONNECTBIOSYNC_TLS_KEY, "
            "o dejá ambos sin definir para usar un certificado local temporal."
        )
    ssl_context = (certificate, private_key) if certificate else "adhoc"
    port = int(os.environ.get("PORT", "8083"))
    logging.info("ConectBioSync estará disponible en https://localhost:%s%s", port, SERVER_PATH)
    run_simple(
        "127.0.0.1",
        port,
        create_server_application(),
        ssl_context=ssl_context,
        use_reloader=False,
        threaded=True,
    )
