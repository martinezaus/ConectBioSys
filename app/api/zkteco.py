"""
Adaptador ZKTeco - protocolo nativo TCP (puerto 4370) vía librería pyzk.

Instalación: pip install pyzk
"""
import logging
from datetime import datetime, timedelta
from typing import List
from zk import ZK

from .base import RelojAdapter
from .modelos import LecturaReloj

log = logging.getLogger("marcaciones.zkteco")

class ZKTecoAdapter(RelojAdapter):

    # Mapeo de método de verificación que devuelve el reloj
    VERIFY_METHODS = {0: "clave", 1: "huella", 2: "tarjeta", 15: "rostro"}

    def __init__(self, ip: str, dispositivo_id: str, puerto: int,
                 comm_key: int = 0, timeout: int = 15, force_udp: bool = False):
        self.ip = ip
        self.dispositivo_id = dispositivo_id
        self.puerto = puerto
        self.comm_key = comm_key
        self.timeout = timeout
        self.force_udp = force_udp
        self._conn = None

    def conectar(self) -> bool:
        # from zk import ZK  # import local: quien no use ZKTeco no necesita pyzk instalado

        zk = ZK(
            self.ip,
            port=self.puerto,
            timeout=self.timeout,
            password=self.comm_key,
            force_udp=self.force_udp,
            ommit_ping=False,
        )
        try:
            self._conn = zk.connect()
            # Deshabilitar el dispositivo mientras leemos, para evitar que una
            # marcación en curso corrompa la sesión de lectura.
            self._conn.disable_device()
            log.info(f"[{self.dispositivo_id}] Conectado OK a {self.ip}:{self.puerto}")
            return True
        except Exception as e:
            log.error(f"[{self.dispositivo_id}] Error de conexión: {e}")
            return False
        
    def obtener_marcaciones(self, desde: Optional[str] = None, hasta: Optional[str] = None) -> List[LecturaReloj]:
        if self._conn is None:
            raise RuntimeError("Debe llamar a conectar() antes de obtener_marcaciones()")
        
        dt_hasta = self._a_datetime(hasta, fin_de_dia=True) if hasta else datetime.now()
        dt_desde = self._a_datetime(desde) if desde else dt_hasta - timedelta(days=7)

        marcaciones = []
        try:
            registros = self._conn.get_attendance()
            total_en_reloj = len(registros)
            for r in registros:
                if not (dt_desde <= r.timestamp <= dt_hasta):
                    continue

                marcaciones.append(
                        LecturaReloj(
                            reloj_user_id=str(r.user_id),
                            timestamp=r.timestamp,
                            tipo_evento=r.punch,
                            dispositivo_id=self.dispositivo_id,
                            metodo=self.VERIFY_METHODS.get(r.status, "desconocido"),
                        )
                )
            log.info(
                f"[{self.dispositivo_id}] {len(marcaciones)} marcaciones en rango "
                f"(de {total_en_reloj} totales en el reloj)"
            )
        except Exception as e:
            log.error(f"[{self.dispositivo_id}] Error leyendo marcaciones: {e}")
        return marcaciones
    

    @staticmethod
    def _a_datetime(valor, fin_de_dia=False):
        """Convierte 'YYYY-MM-DD' (o un datetime ya armado) a datetime."""
        if isinstance(valor, datetime):
            dt = valor
        else:
            dt = datetime.strptime(valor, "%Y-%m-%d")
        
        if fin_de_dia:
            dt = dt.replace(hour=23, minute=59, second=59)
        return dt

    def limpiar_buffer(self) -> None:
        """
        Borra las marcaciones DEL RELOJ. Usar solo después de confirmar que
        el guardado en la base de datos central fue exitoso.
        """
        if self._conn:
            self._conn.clear_attendance()
            log.info(f"[{self.dispositivo_id}] Buffer del reloj limpiado")

    def desconectar(self) -> None:
        if self._conn:
            try:
                self._conn.enable_device()
                self._conn.disconnect()
                log.info(f"[{self.dispositivo_id}] Desconectado")
            except Exception as e:
                log.warning(f"[{self.dispositivo_id}] Error al desconectar: {e}")