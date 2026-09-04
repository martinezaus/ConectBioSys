"""
Adaptador Hikvision - protocolo ISAPI (HTTP REST + autenticación Digest).

Instalación: pip install requests
"""

import logging
from datetime import datetime, timedelta
from typing import List, Optional
from requests.auth import HTTPDigestAuth
import urllib3
import uuid
from .base import RelojAdapter
from .modelos import LecturaReloj

log = logging.getLogger("marcaciones.hikvision")


class HikvisionAdapter(RelojAdapter):

    # Estado de asistencia que devuelve el equipo, si está configurado en
    # modo "time attendance".
    ATTENDANCE_MAP = {
        "checkIn": "entrada",
        "checkOut": "salida",
        "breakOut": "inicio_pausa",
        "breakIn": "fin_pausa",
        "overtimeIn": "entrada_extra",
        "overtimeOut": "salida_extra",
    }

    def __init__(self, ip: str, dispositivo_id: str, usuario: str, password: str,
                 puerto: int = 80, usar_https: bool = False, timeout: int = 15):
        self.ip = ip
        self.dispositivo_id = dispositivo_id
        self.usuario = usuario
        self.password = password
        self.puerto = puerto
        self.usar_https = usar_https
        self.timeout = timeout
        self._session = None

    @property
    def _base_url(self) -> str:
        esquema = "https" if self.usar_https else "http"
        return f"{esquema}://{self.ip}:{self.puerto}"
    
    def conectar(self) -> bool:
        import requests
        from requests.auth import HTTPDigestAuth

        # ISAPI de Hikvision requiere Digest Auth, no Basic. Con Basic el
        # dispositivo responde 401 + XML "invalidOperation" en vez de un
        # 401 estándar pidiendo digest.
        self._session = requests.Session()
        self._session.auth = HTTPDigestAuth(self.usuario, self.password)

        try:
            headers_init = {
                "Accept": "application/xml"
            }
            resp = self._session.get(
                f"{self._base_url}/ISAPI/System/deviceInfo",
                headers=headers_init,
                timeout=self.timeout,
                verify=False,
            )

            if resp.status_code == 200:
                log.info(f"[{self.dispositivo_id}] Conectado OK a {self.ip}:{self.puerto}")
                return True

            log.error(f"[{self.dispositivo_id}] Respuesta inesperada: HTTP {resp.status_code} - {resp.text}")
            return False
        except Exception as e:
            log.error(f"[{self.dispositivo_id}] Error de conexión: {e}")
            return False


    def obtener_marcaciones(self, desde: Optional[str] = None, hasta: Optional[str] = None) -> List[LecturaReloj]:
        if self._session is None:
            raise RuntimeError("Debe llamar a conectar() antes de obtener_marcaciones()")

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        search_id = str(uuid.uuid4())

        # Formato ISO estricto sin microsegundos requerido por Hikvision
        if hasta is None:
            hasta = datetime.now().astimezone().replace(microsecond=0).isoformat()
        if desde is None:
            desde = (datetime.now() - timedelta(days=7)).astimezone().replace(microsecond=0).isoformat()

        marcaciones = []
        posicion = 0
        tamano_pagina = 30
        MAX_PAGINAS = 2000  # salvavidas: evita loop infinito si el equipo nunca devuelve NO MATCH

        for _ in range(MAX_PAGINAS):
            # Estructura JSON exacta exigida por ISAPI: nodo raíz AcsEventCond,
            # con startTime/endTime al mismo nivel (sin Filter anidado) y
            # major/minor obligatorios (0/0 = todos los eventos).
            body = {
                "AcsEventCond": {
                    "searchID": search_id,
                    "searchResultPosition": posicion,
                    "maxResults": tamano_pagina,
                    "major": 0,
                    "minor": 0,
                    "startTime": desde,
                    "endTime": hasta,
                }
            }

            try:
                # Reseteamos el auth ANTES de cada pedido: requests cachea el nonce
                # del desafío Digest anterior y lo reutiliza preventivamente para
                # ahorrarse el round-trip. Hikvision rechaza nonces reusados con
                # 401, así que forzamos un handshake Digest completo y nuevo en
                # cada request (a costa de un pedido extra por vuelta, aceptable
                # para un job de background).
                self._session.auth = HTTPDigestAuth(self.usuario, self.password)

                # Cambiamos obligatoriamente la URL de destino al formato JSON
                url_endpoint = f"{self._base_url}/ISAPI/AccessControl/AcsEvent?format=json"
                
                headers_json = {
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                }

                # Enviamos el payload nativo usando el parámetro json= de requests
                resp = self._session.post(
                    url_endpoint, 
                    json=body,
                    headers=headers_json,
                    timeout=self.timeout,
                    verify=False,
                )

                if resp.status_code != 200:
                    log.error(f"[{self.dispositivo_id}] Error en respuesta del reloj: HTTP {resp.status_code}")
                    print(f"Cuerpo del error {resp.status_code}: {resp.text}")
                    break

                data = resp.json()

                # Accedemos de forma segura a la lista de eventos según el mapa de Hikvision
                search_desc = data.get("AcsEvent", {})
                total = search_desc.get("totalMatches", 0)
                estado_busqueda = search_desc.get("responseStatusStrg", "")
                info_list = search_desc.get("InfoList", [])

                log.debug(
                    f"[{self.dispositivo_id}] pagina pos={posicion} "
                    f"status={estado_busqueda} total={total} recibidos={len(info_list)}"
                )

                for ev in info_list:
                    # Buscamos el ID del empleado en las variantes posibles de Hikvision
                    empleado = ev.get("employeeNoString") or ev.get("employeeNo")
                    # Descartamos eventos sin un ID de empleado numérico limpio:
                    # tarjetas no enroladas, eventos de sistema/puerta, etc. pueden
                    # traer basura binaria en este campo en vez de un número real.
                    if not empleado or not str(empleado).strip().isdigit():
                        continue
                        
                    estado = ev.get("attendanceStatus", "")
                    time_str = ev.get("time")
                    
                    if time_str:
                        marcaciones.append(
                            LecturaReloj(
                                reloj_user_id=str(empleado),
                                timestamp=datetime.fromisoformat(time_str),
                                tipo_evento=1 if estado == "checkOut" else 0,
                                dispositivo_id=self.dispositivo_id,
                                metodo=self.ATTENDANCE_MAP.get(estado, "sin_clasificar"),
                            )
                        )

                # Cortamos SOLO cuando el equipo confirma que no hay más resultados.
                # "totalMatches" no es confiable en páginas tempranas (puede venir en
                # 0 mientras el equipo todavía arma la búsqueda), así que no lo usamos
                # como condición de corte. Nos guiamos por responseStatusStrg.
                if estado_busqueda == "NO MATCH":
                    break
                if estado_busqueda not in ("MORE",) and not info_list:
                    # Firmware que no informa "MORE"/"NO MATCH": si no vino status
                    # reconocido y la página vino vacía, asumimos fin de búsqueda.
                    break

                posicion += tamano_pagina

            except Exception as e:
                log.error(f"[{self.dispositivo_id}] Error leyendo o parseando eventos: {e}")
                break

        log.info(f"[{self.dispositivo_id}] {len(marcaciones)} marcaciones descargadas")
        return marcaciones

    def desconectar(self) -> None:
        if self._session:
            self._session.close()
            log.info(f"[{self.dispositivo_id}] Desconectado")