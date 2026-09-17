# Uso de la versión integrada

La aplicación ahora utiliza PyQt6. Los cambios están integrados en el código fuente; el Setup.exe existente no corresponde a esta actualización.

## Ejecutar

Desde la carpeta del proyecto, en PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

El entorno virtual de este proyecto ya tiene instalados PyQt6 y el controlador Oracle.

## Primera puesta en marcha

1. Seleccionar o crear el cliente. Cada cliente conserva sus relojes, configuración y marcaciones.
2. Entrar en **Licencia**, indicar el titular y pulsar **Registrar primera activación: 1 año**. El vencimiento es el aniversario del registro, a la misma hora UTC. Para el 29 de febrero se usa el 28 de febrero siguiente. Repetir el registro o cambiar de cliente no concede otro año. Las licencias anteriores se conservan.
3. En **Configuraciones**, agregar relojes ZKTeco o Hikvision. Configurar IP, puerto, ID, modelo opcional, comunicación y credenciales. ZK permite TCP/UDP mediante `force_udp` y clave `comm_key`; Hikvision utiliza ISAPI y permite HTTP/HTTPS.
4. Si el cliente necesita exportar a otro sistema, habilitarlo en **Cliente e integración**. Sin integración, descarga y Excel funcionan sin configurar servidores ni tablas.
5. Elegir origen y filtro: mes anterior, últimos siete días incluyendo hoy, tarjeta con rango, o rango personalizado. Descargar o consultar; luego seleccionar filas y destino.

## Configuración externa

La conexión utiliza SQLAlchemy con MySQL/MariaDB, PostgreSQL, SQL Server, Oracle o SQLite. El botón **Probar conexión** ejecuta una consulta en segundo plano. Los controladores tienen tiempos de espera específicos. SQL Server necesita el driver ODBC indicado instalado en Windows (por defecto ODBC Driver 18) y un certificado válido. En Oracle el campo base/servicio corresponde al Service Name.

En el mapeo de empleados:

- Tarjeta/número de reloj: por ejemplo `n_reloj`.
- ID interno: por ejemplo `id`.
- Organización: directa o mediante una tabla relacionada, por ejemplo `legajo.empleados_id` y `legajo.organizacion_id`.
- Catálogo: tabla `organizacion` con sus columnas de ID y nombre, configurables.
- Un sistema sin organizaciones puede utilizar el modo **Única**. Con catálogo, el envío se habilita al seleccionar una organización registrada.

En el mapeo de asistencias:

- Indicar tabla y esquema opcional.
- Mapear empleado al ID relacional, por ejemplo `empleados_id`; la aplicación resuelve la tarjeta al ID real dentro de la organización.
- Completar **FechaHora combinada** o bien fecha y hora separadas. Si está completa la combinada, tiene prioridad.
- Tipo, dispositivo y verificación son opcionales si el destino los admite vacíos o tiene valores predeterminados.
- Los valores por evento se configuran como JSON, por ejemplo `{"Entrada":"E","Salida":"S","Evento 2":"P"}`. Un evento sin mapeo se omite con explicación; nunca se convierte automáticamente en Entrada.

Los nombres y tipos se comprueban mediante reflexión de la tabla. Una columna obligatoria sin mapeo produce error. Oracle no tiene un tipo TIME independiente: utilizar una columna DATETIME/DATE combinada o un campo de texto para la hora, según el esquema del cliente.

Las inserciones de un lote están dentro de una transacción. Los errores de validación de una persona se informan y esa fila se omite; un fallo SQL revierte el lote. Se comprueba si una fila con los mismos valores ya existe antes de insertarla. Para evitar duplicados entre instalaciones concurrentes se necesita una restricción UNIQUE en la base externa. Una pérdida de conexión durante el commit exige comprobar el destino antes de reenviar.

## Limpieza del reloj

Seleccionar un único reloj ZK y pulsar **Limpiar buffer**. La aplicación solicita confirmación, descarga todas las marcaciones y confirma su guardado local antes de borrarlas del equipo. Si falla la lectura o el respaldo, no ejecuta el borrado. No borra personas ni huellas. El adaptador Hikvision no expone una limpieza verificada y muestra que la operación no está disponible.

## Almacenamiento y actualización

`%LOCALAPPDATA%\ConectBioSync\configuracion.db` contiene perfiles, configuración y estado de licencia como registros cifrados con Windows DPAPI, vinculados al usuario Windows. SQLite abre una conexión independiente por operación. Las contraseñas no se escriben en texto plano.

Los archivos de configuración Python anteriores se importan al acceder a cada sección, mediante análisis de literales; no se ejecuta su código. Se guarda una copia cifrada del contenido original dentro de SQLite y se reemplaza el archivo anterior por un aviso de migración. `perfiles.json` se importa una sola vez. Los archivos antiguos de licencia cifrada se importan conservando su vencimiento. La clave privada del emisor permanece en `.license-issuer` y no se modifica.

El histórico mantiene sus ubicaciones anteriores y sus registros. Abrir la base no elimina duplicados ni borra marcaciones. Respaldar tanto el histórico como configuracion.db; para copiar una base abierta se debe usar la API de backup de SQLite o cerrar primero la aplicación. DPAPI requiere el mismo usuario Windows: copiar únicamente el archivo a otro equipo no permite descifrarlo. La recuperación o traslado de instalación requiere un procedimiento del proveedor.

La protección offline detecta alteraciones de los registros y retrocesos del reloj respecto al último control. No puede impedir por sí sola que alguien borre completamente todos los datos y simule una instalación nueva; para esa garantía se necesita un servidor de activación.

## Renovaciones: herramienta exclusiva del proveedor

El cliente guarda su solicitud `.cbsreq`. La herramienta de emisión mantiene la firma y el cifrado existentes. Para renovar anticipadamente, usar el vencimiento actual exacto como inicio; si ya venció, omitir inicio para comenzar ahora.

```powershell
.\.venv\Scripts\python.exe tools\emitir_licencia.py emitir solicitud.cbsreq --cliente "Empresa" --salida renovacion.cbslic --codigo renovacion.txt --inicio "2027-09-15T15:00:00+00:00"
```

El cliente puede importar `.cbslic` o pegar el contenido de `renovacion.txt`. Una renovación futura queda programada. Se rechazan códigos que no amplían la vigencia, repetidos o de otra instalación. No distribuir la herramienta ni la clave privada.

## Módulos y validación

- `app/almacen.py`: SQLite cifrado y lectura segura de archivos heredados.
- `resources/config_path.py`: acceso a configuración y motores SQLAlchemy.
- `app/database/database.py`: histórico y consulta por rango.
- `app/licencias.py`: registro anual y renovaciones firmadas/cifradas.
- `app/servicios.py`: descarga, respaldo y Excel con tabla, fechas reales y tarjetas como texto.
- `app/trabajos.py`: QThread, señales y control de vida del trabajo.
- `app/filtros.py`, `app/api/relojes.py`, `app/dialogos_cliente.py`, `main.py`: interfaz integrada.
- `app/api/asistencias.py`: reflexión, resolución de empleados e inserción.

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

Las pruebas utilizan SQLite temporal y adaptadores simulados. Cubren cifrado, migración, renovación, filtros, Excel, QThread, aislamiento entre clientes, respaldo fallido y tarjeta 93 resuelta al empleado 92. También se verificó la apertura de las ventanas PyQt6. Las conexiones a relojes reales y a servidores MySQL/PostgreSQL/SQL Server/Oracle deben validarse con el equipo de cada cliente; no se ejecutaron escrituras ni limpiezas en dispositivos o bases productivas durante esta implementación.

Para construir un ejecutable nuevo, usar `tools/compilar.py`. Se actualizó para excluir PySide6 e incluir los drivers dinámicos; el ejecutable no se recompiló en esta actualización.
