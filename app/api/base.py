"""
Interfaz común que deben implementar todos los adaptadores de relojes
biométricos (Hikvision, ZKTeco, y los que se agreguen a futuro).

Esto permite que el resto de la app (main.py, servicios de sincronización,
etc.) trate a cualquier reloj de la misma forma, sin importar el protocolo
real que use por debajo (HTTP/ISAPI, TCP nativo, etc.).
"""

from abc import ABC, abstractmethod
from typing import List, Optional

from .modelos import LecturaReloj


class RelojAdapter(ABC):

    dispositivo_id: str

    @abstractmethod
    def conectar(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def obtener_marcaciones(
        self, desde: Optional[str] = None, hasta: Optional[str] = None
    ) -> List[LecturaReloj]:
        raise NotImplementedError

    @abstractmethod
    def desconectar(self) -> None:
        """
        Cierra la conexión con el reloj y libera cualquier recurso
        (sockets, sesiones HTTP, etc.). Debe ser seguro llamarlo aunque
        conectar() nunca se haya invocado o haya fallado.
        """
        raise NotImplementedError