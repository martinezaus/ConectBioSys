"""
Modelos de datos comunes para los adaptadores de relojes biométricos.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class LecturaReloj:
    """
    Representa una marcación individual normalizada, sin importar de qué
    marca de reloj provenga. Todos los adaptadores (Hikvision, ZKTeco, etc.)
    deben devolver instancias de esta clase desde obtener_marcaciones().
    """

    # ID de empleado/usuario tal como lo reporta el propio reloj (string,
    # puede venir con ceros a la izquierda u otros formatos según la marca).
    reloj_user_id: str

    # Fecha y hora de la marcación.
    timestamp: datetime

    # Código de tipo de evento normalizado. Convención usada por los
    # adaptadores actuales: 0 = entrada, 1 = salida. Algunos relojes
    # (ZKTeco) pueden reportar otros códigos según su propio firmware
    # (r.punch), en cuyo caso ese valor se pasa tal cual.
    tipo_evento: int

    # Identificador interno del dispositivo (el que usa la app para saber
    # de qué reloj físico vino el dato, no un ID del fabricante).
    dispositivo_id: str

    # Método de verificación usado por el empleado: "huella", "tarjeta",
    # "rostro", "clave", o el string que determine el mapeo del adaptador
    # ("sin_clasificar" / "desconocido" si el reloj no informa un método
    # reconocido).
    metodo: str