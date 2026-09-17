> Actualización: ya existe una implementación en el proyecto. Consultar `GUIA_CLIENTES_Y_LICENCIAS.md` en la raíz para el comportamiento integrado y sus límites. Este documento conserva la propuesta de diseño; sus ejemplos no son la aplicación ejecutable.

# Propuesta v2 — PyQt6, SQLite y servicios de asistencia

## Alcance y estado de esta entrega

Se entrega la estructura modular detallada solicitada, acompañada de esquema SQL y código de referencia. No es una migración ya integrada ni un nuevo instalador. El proyecto actual usa PySide6; no se deben importar PySide6 y PyQt6 en el mismo proceso. Las vistas de referencia usan exclusivamente PyQt6. El ejecutable de la iteración anterior tiene pendiente resolver su prueba de arranque y no se considera validado para esta versión.

Archivos de esta propuesta:
- `schema.sql`: esquema nuevo, comprobable sobre SQLite vacío. No ejecutar directamente sobre la base productiva.
- `backend_referencia.py`: filtros, año calendario, construcción de URL, conexión, reflexión y transformación de filas.
- `worker_pyqt6.py`: ejecución QThread, señales, cancelación cooperativa y ciclo de vida.
- `ui_pyqt6.py`: vistas nativas y señales para conectar a los controladores; no realiza operaciones externas por sí sola.

## Reglas adoptadas

1. Cada empresa es un perfil local, independiente de que contrate un sistema web. La integración externa comienza desactivada y Excel funciona sin configurarla.
2. Tarjeta/usuario del reloj e ID relacional externo son identificadores distintos. Resolver por organización y tarjeta, o por una equivalencia explícita. Nunca reemplazar un ID desconocido por la tarjeta.
3. La primera activación es una acción explícita de registro local: concede un año desde ese instante. Abrir la aplicación, cambiar perfil o reinstalar una actualización no renueva el plazo.
4. Se define un año como aniversario calendario en UTC, con 29/02 → 28/02 cuando corresponde. No equivale siempre a 365 días. Vencimiento exclusivo: `ahora >= vence` implica Vencida.
5. Últimos siete días significa siete fechas incluyendo hoy: desde hoy−6 hasta hoy. Si el negocio requiere siete días completos excluyendo hoy, cambia únicamente la política del servicio de filtros.
6. Fechas visibles inclusive; internamente usar intervalo `[desde 00:00, día siguiente de hasta 00:00)` para incluir segundos y microsegundos del último día.
7. Con licencia vencida siguen disponibles consulta y exportación Excel del histórico. Se bloquean nuevas descargas, envíos y limpieza de dispositivos.

## Estructura objetivo

```text
conectbiosync/
  bootstrap.py                    # configuración de logging e inicialización
  app.py                          # QApplication PyQt6 e inyección de dependencias
  domain/
    models.py                     # Profile, Device, Attendance, DateFilter, ExportReport
    errors.py                     # errores seguros para mostrar al usuario
    policies.py                   # filtros, zonas horarias y vencimiento
  data/
    sqlite_factory.py             # una conexión local por trabajo
    migrations/                   # schema_version y migraciones transaccionales
    profile_repository.py
    device_repository.py
    config_repository.py
    attendance_repository.py
    license_repository.py
    export_repository.py
  security/
    secret_store.py               # AES-GCM; claves envueltas con DPAPI en SQLite
    license_tokens.py             # verificación de extensiones firmadas
  adapters/
    base.py                       # contrato de reloj y capacidades
    zkteco.py                     # reutilizar pyzk; comm_key y TCP/UDP
    hikvision.py                  # reutilizar ISAPI; capacidades por modelo
  services/
    config_service.py
    download_service.py
    connection_factory.py         # SQLAlchemy + estrategias por dialecto
    schema_service.py             # esquemas, tablas y tipos de columnas
    employee_resolver.py          # tarjeta + organización → ID relacional
    organization_service.py       # catálogo externo opcional
    export_service.py             # lotes y control de resultado incierto
    excel_service.py              # openpyxl, formato y escritura temporal
    license_service.py
    device_maintenance_service.py # borrado explícito y auditado
  controllers/
    task_controller.py            # QThread + señales
    configuration_controller.py
    attendance_controller.py
    license_controller.py
  ui/
    main_window.py                # perfil, resultados, progreso y cancelar
    configuration_tabs.py         # relojes, conexión, mapeo, licencia
    filters_panel.py
    attendance_model.py           # QAbstractTableModel, paginación
    export_dialog.py
  tests/
    unit/
    integration/
    ui/
```

Dependencia unidireccional: UI → controladores → servicios → repositorios/adaptadores. El dominio no importa Qt. Los servicios no importan widgets ni muestran QMessageBox.

## Capa de datos: SQLite como fuente de configuración

`schema.sql` define perfiles, dispositivos, conexiones externas, secretos cifrados, mapeos versionados, marcaciones, lotes/items de exportación, licencia y auditoría. La configuración deja de ejecutarse como módulos Python.

Usar una base local central con `profile_id` y dispositivos con UUID interno. `device_code` puede repetirse entre clientes, pero no dentro del mismo perfil. Toda consulta de marcaciones debe restringirse al perfil activo mediante JOIN con devices. El ID interno del dispositivo forma parte de la huella de duplicados.

Crear conexiones SQLite dentro de cada hilo. Activar `foreign_keys`, `busy_timeout` y WAL; las escrituras se ejecutan en transacciones cortas. WAL no permite varios escritores simultáneos: serializar modificaciones de configuración y registro de licencia. No mantener transacciones SQLite abiertas mientras se consulta un reloj o servidor SQL.

La huella de una marcación utiliza identificador original del evento si es estable, junto al dispositivo; si no existe, SHA-256 de dispositivo, tarjeta, fecha original normalizada, evento y método. Conservar el timestamp original, zona horaria y timestamp local. El UTC puede ser nulo para horas ambiguas que requieran revisión. No convertir un datetime sin zona usando la zona implícita del PC.

Las credenciales se guardan en `secrets`, nunca dentro de options_json, logs, URLs impresas o repr de DTO. La clave AES se guarda como BLOB envuelto por Windows DPAPI en encryption_keys; el nonce y ciphertext se guardan en secrets. Usar como AAD identificador del secreto, perfil y propósito. Una codificación Base64 no cifra. Un hash simple no permite recuperar una contraseña ni impide alterar un estado de licencia si el atacante también puede cambiar el hash.

Contratos de repositorio:

```python
class AttendanceRepository:
    def save_batch(self, profile_id, events) -> SaveReport: ...
    def query_page(self, profile_id, filter, cursor, limit=500) -> Page: ...
    def iterate_filtered(self, profile_id, filter, batch_size=1000): ...

class ConfigRepository:
    def load_profile_snapshot(self, profile_id) -> ProfileSnapshot: ...
    def save_connection(self, profile_id, public_config, encrypted_secret): ...
    def save_mapping(self, mapping) -> int: ...  # nueva revisión
```

## Configuración: pestañas y validaciones

### Relojes

Listado por perfil y formulario de IP/hostname, puerto, ID del dispositivo, marca, modelo, protocolo, usuario y secreto. Para ZK la clave de comunicación puede ser numérica; para Hikvision se utiliza usuario/contraseña. Los campos y protocolos permitidos dependen de la marca. Incluir timeout y zona horaria.

Capacidades del adaptador: `supports_server_filter`, `supports_card_filter`, `supports_clear_attendance`. No asumir que todos los modelos Hikvision tienen una API de borrado. No usar un reset de fábrica para implementar Limpiar Buffer.

`DeviceMaintenanceService.clear_attendance(device_id, confirmation)` comprueba licencia, capacidad, respaldo local confirmado y ausencia de otro trabajo sobre el dispositivo. La UI muestra nombre/IP/alcance, pide confirmación con No como predeterminado y después ejecuta el servicio en QThread. Se audita el resultado real, y siempre se desconecta/restaura el dispositivo en finally. No borrar usuarios, rostros ni huellas. Si no hay soporte, ocultar o deshabilitar el botón con una explicación.

### Base externa

| Motor | Dialecto | Detalle específico |
|---|---|---|
| MySQL/MariaDB | mysql+pymysql | timeout de conexión, lectura y escritura |
| PostgreSQL | postgresql+psycopg2 | connect_timeout y statement_timeout |
| SQL Server | mssql+pyodbc | driver ODBC instalado, autenticación y TLS |
| Oracle | oracle+oracledb | Service Name; thin/thick según despliegue |
| SQLite externo | sqlite+pysqlite | archivo destino; no usar la base interna como destino |

SQLAlchemy abstrae el SQL, pero cada motor necesita su DBAPI/driver y opciones de timeout/TLS. No se puede enviar `connect_timeout` indiscriminadamente a todos. La fábrica usa URL.create para contraseñas con caracteres especiales y `select(literal(1))` para la prueba, incluida la sintaxis Oracle. La prueba es de conexión, no de permiso para insertar.

Los timeouts de consulta deben completarse en la estrategia de cada driver: ODBC cursor.timeout y Oracle call_timeout, además del timeout de conexión. Se valida su soporte con las versiones instaladas. La referencia incluye creación de conexiones, no todas las variantes de autenticación de cada proveedor.

### Mapeo dinámico

Cargar esquemas, tablas y columnas mediante reflexión SQLAlchemy, en segundo plano. No interpolar SQL recibido del usuario. Seleccionar columnas entre las realmente existentes y comprobar tipos y nulabilidad.

Campos canónicos: employee_id, card_number, occurred_at, date, time, device_id, event_type, method y source_id. Permitir timestamp combinado o fecha/hora separados. Oracle no tiene un TIME independiente equivalente a todos los otros motores: si se mapea una hora a texto, exigir y registrar una conversión explícita; por defecto usar timestamp combinado.

Guardar equivalencias de eventos, por ejemplo Entrada → E, Salida → S. Un evento desconocido no se convierte silenciosamente en Entrada. Verificar columnas NOT NULL no mapeadas y sin default/identidad antes del primer envío.

El resolver de empleados admite:
- columna de organización en empleados;
- relación intermedia configurada, como legajo.empleados_id → empleados.id;
- destino sin organizaciones, elegido expresamente;
- identificación por tarjeta solo si el destino define expresamente esa semántica.

Para el sistema del proyecto: la pertenencia se consulta con EXISTS sobre legajo; así varios legajos no duplican empleados. El catálogo de nombres se configura por separado: en la base personal se observó organizacion(id, d_org). Otras instalaciones pueden utilizar nombre u otra columna.

Si se repite una tarjeta en la organización seleccionada, no elegir el primer resultado. Registrar error de esa marcación. La organización escogida y la revisión de mapeo se congelan para todo el lote.

## Descarga y consulta

La pantalla ofrece Origen (Reloj / Base local), filtro, fechas, tarjeta, dispositivos y acciones. Los cuatro filtros se convierten al mismo DTO Filtro. La tarjeta se trata como texto para conservar ceros iniciales.

Flujo del DownloadService:
1. Validar licencia, perfil, dispositivos y rango.
2. Capturar configuración inmutable del trabajo; bloquear cambio de perfil mientras está activo.
3. Abrir el adaptador en el hilo trabajador.
4. Aplicar filtros en el reloj si los admite. Si no, descargar y filtrar localmente, informándolo en el progreso.
5. Guardar por lotes en SQLite, diferenciando nuevas, duplicadas y rechazadas.
6. Desconectar en finally, incluso cuando falle la conexión parcialmente.
7. Emitir resumen; no ocultar una excepción de descarga devolviendo una lista vacía.

La consulta local utiliza el mismo rango, pero no requiere licencia vigente ni conexión externa. Reemplazar la comprobación actual de un método inexistente en el filtro por tarjeta por el contrato real del repositorio.

## Exportación

### Excel

ExcelService recibe un snapshot de los IDs seleccionados o un filtro estable. Usa openpyxl en el hilo trabajador, encabezados claros, fecha y hora como valores tipados, formato de tabla, fila superior inmovilizada y ancho de columnas razonable. Evitar que tarjetas o textos que empiezan por =, +, - o @ se interpreten como fórmulas; escribir esos campos como texto explícito. Tarjetas con ceros iniciales permanecen texto.

Crear primero un archivo temporal en el directorio elegido y reemplazar el destino solo al terminar. Si el usuario cancela, eliminar únicamente ese temporal. En grandes volúmenes, dividir hojas respetando el límite de Excel e informar el total. Con cero filas, mostrar un aviso y no crear una tabla inválida.

### SQL externo

ExportService comprueba licencia e integración, refleja destino, valida mapeo y resuelve empleados. Usa `connection.execute(table.insert(), rows)` con objetos Python tipados. Nunca concatenar valores dentro del SQL. Mantener lotes acotados y transacciones independientes de SQLite.

Diferenciar nuevas, omitidas por duplicado, rechazadas y resultado incierto. Una caída después del COMMIT remoto y antes de registrar éxito local no demuestra que el envío falló. SQLite y la base remota no comparten una transacción atómica.

Solución preferida: columna source_id externa con restricción UNIQUE y una identidad estable por marcación. Si el cliente no permite esa columna, guardar un registro local de envíos y usar una clave natural acordada para conciliación. No prometer entrega exactamente una vez sin una restricción/idempotencia externa. Un estado uncertain se concilia antes de reintentar; no se reenvía ciegamente.

No asumir que todos los drivers soportan savepoints de la misma manera. Validar previamente las filas y usar una estrategia de transacción probada por motor.

## Licencia: primera activación y extensión

Cambiar la política anterior: el año inicial se calcula al registrar, no al generar un archivo del emisor. El registro inicial se realiza en una transacción SQLite BEGIN IMMEDIATE:

```text
registrar(cliente, reloj_utc):
    si existe license_state:
        devolver estado existente; NO cambiar registered_at ni expires_at
    registered_at = reloj_utc.now()
    expires_at = aniversario(registered_at)
    estado = {installation_id, cliente, registered_at, expires_at,
              last_seen_utc, used_extension_ids: []}
    cifrar estado autenticado y persistirlo como un único registro
    COMMIT
```

La activación inicial no depende de MySQL ni de contratar el sistema web. Al utilizar una sola instalación con varios perfiles, el plazo pertenece a la instalación, no se reinicia al agregar una empresa.

La extensión es un token firmado por el proveedor, no una contraseña universal incluida en el código. Formato sugerido: `CBS1.<payload_base64url>.<firma_base64url>`. Payload: versión, producto, instalación, extension_id único, issued_at y extensión autorizada en años o vencimiento autorizado. La app contiene solo la clave pública. Permitir pegar el código y opcionalmente importar un archivo equivalente.

En una transacción: verificar firma/producto/instalación, verificar que extension_id no esté consumido, calcular `base = max(vencimiento_actual, ahora_utc)` y el nuevo aniversario, actualizar el estado cifrado y registrar el ID usado dentro de ese mismo estado. No guardar la lista antirrepetición solamente en una tabla editable sin autenticación.

Indicador UI calculado a partir del estado validado: Sin registrar, Activa, Vencida o Inválida; vencimiento local legible; días restantes = ceil(max(0, diferencia_en_segundos)/86400). Actualizar cada minuto y volver a validar al iniciar cada operación protegida. Si se requiere corte estricto de una descarga larga al vencer, comprobar también entre lotes.

Toda la configuración y estado persistente reside en SQLite, incluidos los BLOB cifrados y la clave envuelta por DPAPI. No almacenar la clave AES en texto plano ni una clave de firma privada en el cliente.

Límite importante: una primera activación gratuita/local puede volver a concederse si alguien borra toda la identidad y base de la instalación. El cifrado no impide eliminar o restaurar una copia antigua. Para impedir reactivaciones tras reinstalar y detectar retrocesos de tiempo con garantía, hace falta un registro de activaciones/tiempo en un servidor. La solución offline puede detectar retrocesos respecto a last_seen_utc, pero no garantizar lo que ocurrió fuera del estado local. No ocultar esta limitación en el diseño comercial.

## Controladores e hilos

El archivo worker_pyqt6.py usa QThread y pyqtSignal. Su operación recibe callbacks de progreso y cancelación y devuelve DTO, no widgets ni conexiones vivas. La UI actualiza tablas, barras y QMessageBox en slots del hilo principal. Mantener referencias al QThread hasta finished; pedir interrupción y cerrar recursos cooperativamente.

Al cerrar la ventana con una operación activa, solicitar cancelación e ignorar momentáneamente closeEvent. Cerrar cuando el trabajador termine. No usar terminate() ni wait() prolongado en la UI. Cada llamada de red debe tener timeout: la cancelación no interrumpe una función DBAPI bloqueada.

Conexión representativa del controlador:

```python
self.tabs.probar_bd.connect(self.probar_conexion)
self.trabajo.progreso.connect(self.mostrar_progreso)
self.trabajo.resultado.connect(self.mostrar_resultado)
self.trabajo.error.connect(self.mostrar_error)  # QMessageBox en el hilo principal

@pyqtSlot(dict)
def probar_conexion(self, valores):
    config = Conexion(**valores)
    self.trabajo.iniciar(lambda progreso, cancelar: probar_conexion(config))
```

El ejemplo de runner devuelve un mensaje público genérico; la implementación final debe mapear errores de validación, timeout, driver ausente, permisos y mapeo a códigos seguros, evitando exponer parámetros SQL o secretos en excepciones.

## Migración desde el repositorio actual

| Actual | Destino |
|---|---|
| main.py monolítico | main_window + controladores + servicios |
| PySide6 / Signal | PyQt6 / pyqtSignal, enums PyQt6, un solo binding |
| config_*.py y perfiles.json | repositorios SQLite y secrets cifrados |
| app/database/database.py | repositorio de marcaciones con profile_id y migraciones |
| app/api/zkteco.py, hikvision.py | adaptadores con capacidades y errores explícitos |
| app/api/asistencias.py | employee_resolver + ExportService + mapeo reflejado |
| app/licencias.py | LicenseService con registro inicial y extensiones en SQLite |
| herramientas del emisor | conservar separadas, solo para generar extensiones firmadas |

Respaldar SQLite mediante su backup API, no copiar únicamente el archivo principal mientras WAL está activo. Leer configuraciones antiguas como datos de asignaciones literales con ast.literal_eval; no ejecutar archivos arbitrarios para migrarlos. Las configuraciones no literales deben revisarse y no descartarse silenciosamente. Migrar secretos en una transacción; comprobar recuentos/huellas de marcaciones antes de retirar el lector anterior. Mantener el respaldo para rollback.

Las licencias antiguas vigentes requieren una regla de migración: conservar el vencimiento ya concedido; no regalar otro año por actualizar la aplicación. El año desde registro aplica a instalaciones que aún no fueron activadas.

## Verificación y criterios de aceptación

- Perfil nuevo: no solicita ni crea conexión externa; Excel disponible.
- Mes anterior cruza enero/diciembre y febrero bisiesto correctamente.
- Últimos 7 días contiene exactamente 7 fechas.
- Tarjeta + rango conserva ceros iniciales y excluye registros fuera del rango.
- Tarjeta 93 → empleado 92 dentro de su organización; otra organización no se mezcla.
- Borrado solicita confirmación y nunca llama al adaptador si se cancela o no tiene capacidad.
- Una segunda activación no cambia el vencimiento; el mismo token no extiende dos veces.
- Código alterado, vencido o de otra instalación rechazado; renovación vigente y vencida probadas.
- Trabajos lentos no bloquean GUI; cerrar/cancelar no destruye un QThread activo.
- Excel conserva fechas y tarjetas, no ejecuta fórmulas y no deja archivos finales incompletos.
- Transacciones fallidas no se marcan como confirmadas; estado incierto no se reintenta a ciegas.
- Pruebas reales separadas contra MySQL, PostgreSQL, SQL Server y Oracle; compilar SQL no equivale a probar sus drivers.
- Instalador probado en Windows limpio: drivers requeridos, Qt, cifrado y ausencia de secretos del proveedor.

## Referencias técnicas

- [QThread y afinidad de QObject](https://doc.qt.io/qt-6/threads-qobject.html)
- [QThread](https://doc.qt.io/qt-6/qthread.html)
- [SQLAlchemy URL.create](https://docs.sqlalchemy.org/en/20/core/engines.html#creating-urls-programmatically)
- [Reflexión de tablas](https://docs.sqlalchemy.org/en/20/core/reflection.html)
- [SQL Server / pyodbc](https://docs.sqlalchemy.org/en/20/dialects/mssql.html#hostname-connections)
- [Oracle / python-oracledb](https://docs.sqlalchemy.org/en/20/dialects/oracle.html)
