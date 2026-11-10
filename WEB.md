# ConectBioSync en la red local

La interfaz web se ejecuta en el equipo Windows que tiene acceso a los relojes. El servidor local queda disponible en `https://localhost:8083/ConectBioSync`; las conexiones TCP/HTTP a Hikvision y ZKTeco se originan en ese equipo.

## Iniciar

Instalá las dependencias del proyecto y ejecutá:

```powershell
python webapp.py
```

En el primer inicio, el servidor crea automáticamente dos perfiles: **admin**, con acceso a toda la aplicación y a Configuración, y **operador**, sin acceso a Configuración. Muestra las contraseñas iniciales en la consola una sola vez; guardalas para entregarlas a cada persona. La configuración queda en `%LOCALAPPDATA%\ConectBioSync\web_auth.json`; las contraseñas se almacenan como hashes, no como texto. En los siguientes inicios se reutilizan automáticamente. Al actualizar una instalación existente, se conserva el acceso de administrador y se genera el perfil operador en el siguiente arranque.

El servidor escucha únicamente en `127.0.0.1:8083` y crea un certificado HTTPS local temporal por defecto. El navegador puede mostrar una advertencia porque ese certificado no está emitido por una autoridad de confianza. Para usar un certificado propio, configurá las rutas de ambos archivos antes de iniciarlo:

```powershell
$env:CONNECTBIOSYNC_TLS_CERT = "C:\ruta\localhost.crt"
$env:CONNECTBIOSYNC_TLS_KEY = "C:\ruta\localhost.key"
```

También podés definir `CONNECTBIOSYNC_SECRET_KEY`, `CONNECTBIOSYNC_USERNAME`, `CONNECTBIOSYNC_PASSWORD`, `CONNECTBIOSYNC_OPERATOR_USERNAME` y `CONNECTBIOSYNC_OPERATOR_PASSWORD` como variables de entorno. Las cookies seguras permanecen habilitadas por defecto.

Si perdiste la contraseña generada, detené el servidor y eliminá `%LOCALAPPDATA%\ConectBioSync\web_auth.json`; al volver a iniciar se generarán credenciales nuevas y se mostrarán en la consola.

## Restablecimiento por correo

Un administrador puede configurar o cambiar SMTP desde **Configuración → Restablecimiento de clave** sin reiniciar el servidor. Puede guardar servidor, puerto, cifrado, remitente y credenciales, probar la conexión sin enviar un correo y quitar la clave guardada. Cada cuenta debe tener un correo válido en **Administración → Usuarios**. La configuración se conserva en `smtp_config.json` dentro de `%LOCALAPPDATA%\ConectBioSync`; en Docker queda en `data/config/ConectBioSync` y está excluida del repositorio. También se admiten variables de entorno como valores iniciales:

```powershell
$env:CONNECTBIOSYNC_SMTP_HOST = "smtp.example.com"
$env:CONNECTBIOSYNC_SMTP_PORT = "587"
$env:CONNECTBIOSYNC_SMTP_USERNAME = "cuenta@example.com"
$env:CONNECTBIOSYNC_SMTP_PASSWORD = "<clave SMTP o de aplicación>"
$env:CONNECTBIOSYNC_SMTP_FROM = "cuenta@example.com"
$env:CONNECTBIOSYNC_SMTP_STARTTLS = "1"
```

Para un servidor que exige TLS implícito (normalmente puerto `465`), configurá `CONNECTBIOSYNC_SMTP_SSL=1` y `CONNECTBIOSYNC_SMTP_STARTTLS=0`. Mantené las credenciales SMTP fuera del repositorio. Si falla el envío, se cancela el restablecimiento y se conserva la clave anterior.

Abrí `https://localhost:8083/ConectBioSync` en el navegador del mismo equipo.

## Datos y configuración

- La base local de marcaciones es `data/marcaciones.db` dentro del proyecto; se puede cambiar mediante `CONNECTBIOSYNC_DATABASE` usando una ruta absoluta.
- La configuración de relojes y de las bases externas se guarda en el perfil de Windows del usuario que ejecuta el servidor. Ejecutá el servidor bajo una cuenta de Windows persistente que tenga acceso a esa configuración y a los relojes.
- En **Configuración**, cargá el JSON actual, editá los valores y guardá. Las contraseñas de relojes y de la base externa no se muestran; dejá el campo correspondiente vacío para conservar el valor guardado. La configuración de reloj admite `hikvision` y `zkteco`.
- Solo el perfil **admin** puede ver o modificar la configuración; el servidor también bloquea esas rutas para el perfil **operador**.
- En **Usuarios**, un administrador puede crear cuentas, declarar su correo, cambiar su nombre o perfil, activarlas/desactivarlas, restablecer claves y eliminarlas. Las claves iniciales se generan aleatoriamente y se muestran una sola vez. Las claves restablecidas se envían por correo; al ingresar, el usuario debe cambiarlas antes de continuar. Los cambios de nombre, perfil, estado o clave invalidan las sesiones anteriores del usuario. Siempre debe quedar al menos un administrador activo.
- Compartí cada contraseña únicamente con la persona autorizada para ese perfil.
