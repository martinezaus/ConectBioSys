"""Datos y serialización de configuración compartidos por la interfaz web."""

CAMPOS_POR_TIPO = {
    "zkteco": [
        ("ip", str, ""),
        ("dispositivo_id", str, ""),
        ("puerto", int, 4370),
        ("force_udp", bool, True),
    ],
    "hikvision": [
        ("ip", str, ""),
        ("dispositivo_id", str, ""),
        ("usuario", str, "admin"),
        ("password", str, ""),
        ("usar_https", bool, False),
    ],
}


def generar_config_relojes(relojes):
    """Serializa relojes a un archivo Python con la estructura de RELOJES."""
    lineas = [
        '"""',
        "Configuración de los relojes biométricos a conectar.",
        "",
        'Este archivo se genera desde la interfaz web. Cada entrada contiene',
        '"tipo" ("hikvision" o "zkteco") y los parámetros del adaptador.',
        '"""',
        "RELOJES = [",
    ]
    for reloj in relojes:
        lineas.append("\t{")
        lineas.append(f'\t\t"tipo": {reloj["tipo"]!r},')
        lineas.append('\t\t"params": {')
        for clave, valor in reloj["params"].items():
            lineas.append(f"\t\t\t{clave!r}: {valor!r},")
        lineas.append("\t\t},")
        lineas.append("\t},")
    lineas.extend(("]", ""))
    return "\n".join(lineas)
