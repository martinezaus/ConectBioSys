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

    reloj_user_id: str
    timestamp: datetime
    tipo_evento: int
    dispositivo_id: str
    metodo: str