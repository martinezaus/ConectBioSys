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
    """
    Todo adaptador de reloj debe heredar de esta clase e implementar los
    tres métodos abstractos. El ciclo de uso esperado es siempre:

        adapter = HikvisionAdapter(...)  # o ZKTecoAdapter(...)
        if adapter.conectar():
            marcaciones = adapter.obtener_marcaciones()
            ...
            adapter.desconectar()
    """

    # Identificador interno del dispositivo. Todos los adaptadores
    # concretos lo reciben por __init__ y lo guardan como self.dispositivo_id;
    # se declara acá solo como referencia de la interfaz.
    dispositivo_id: str

    @abstractmethod
    def conectar(self) -> bool:
        """
        Establece la conexión con el reloj físico.
        Devuelve True si la conexión fue exitosa, False en caso contrario.
        No debe lanzar excepciones por errores de red/autenticación
        esperables: esos casos deben loguearse y devolver False.
        """
        raise NotImplementedError

    @abstractmethod
    def obtener_marcaciones(
        self, desde: Optional[str] = None, hasta: Optional[str] = None
    ) -> List[LecturaReloj]:
        """
        Descarga las marcaciones del reloj y las devuelve como una lista de
        LecturaReloj ya normalizadas. Debe lanzar RuntimeError si se llama
        antes de conectar().
        """
        raise NotImplementedError

    @abstractmethod
    def desconectar(self) -> None:
        """
        Cierra la conexión con el reloj y libera cualquier recurso
        (sockets, sesiones HTTP, etc.). Debe ser seguro llamarlo aunque
        conectar() nunca se haya invocado o haya fallado.
        """
        raise NotImplementedError