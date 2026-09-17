# Configuración de organizaciones

El cruce usa el número de tarjeta y, opcionalmente, una columna y un valor de organización en la tabla de empleados o en una tabla relacionada. La misma selección se aplica al envío de asistencias y a los nombres exportados a Excel.

En Configurar tabla de empleados:
- Número de tarjeta: n_reloj.
- ID interno: id.
- Columna de organización: nombre real del campo en la tabla de empleados (por ejemplo empresa_id).
- Valor de organización: valor que identifica la organización de las marcaciones.

Si la relación está en otra tabla, completar Tabla relacionada y Columna de empleado en esa tabla. Se comprueba la existencia de la relación sin duplicar empleados.

Dejar todos los campos de organización vacíos cuando no exista separación por organización. Las tarjetas deben ser únicas dentro del alcance configurado. No se elige arbitrariamente un empleado si hay duplicados.

Las configuraciones antiguas con una igualdad simple, como organizacion_id = 1, se interpretan al cargar. Al guardar se reemplaza la condición SQL por los campos separados. Otras expresiones antiguas producen un error para no perder silenciosamente el filtro.

La configuración actual utiliza una organización por exportación. No mezclar relojes de diferentes organizaciones en ese lote. Si un mismo reloj contiene personas de varias organizaciones con tarjetas repetidas, la marcación necesita un identificador adicional para distinguirlas.

Para múltiples organizaciones, la ampliación recomendada es crear perfiles de integración: organización, conexión, mapeo de empleados y relojes asociados. Un perfil puede exportar solo Excel y no requerir sistema web. La asociación de reloj a perfil permite seleccionar el destino automáticamente; todavía no está implementada.

Configuración verificada el 14/09/2026: tabla relacionada legajo, columna de empleado empleados_id, columna de organización organizacion_id y valor 1. Se resolvieron 118 tarjetas repetidas. La tarjeta 47 sigue siendo ambigua dentro de la organización 1 y se rechaza. No se modificó el esquema ni las asistencias remotas.
