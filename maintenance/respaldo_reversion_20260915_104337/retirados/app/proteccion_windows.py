"""Protección de secretos locales con DPAPI del usuario de Windows."""
import ctypes
from ctypes import wintypes
import os

class _Blob(ctypes.Structure):
    _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_ubyte))]

def _transformar(data, descifrar=False):
    if os.name != 'nt':
        raise RuntimeError('La protección de la instalación requiere Windows.')
    buffer = ctypes.create_string_buffer(data)
    entrada = _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    salida = _Blob()
    dll = ctypes.WinDLL('crypt32', use_last_error=True)
    funcion = dll.CryptUnprotectData if descifrar else dll.CryptProtectData
    funcion.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
    funcion.restype = wintypes.BOOL
    if not funcion(ctypes.byref(entrada), None, None, None, None, 1, ctypes.byref(salida)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(salida.pbData, salida.cbData)
    finally:
        liberar = ctypes.WinDLL('kernel32').LocalFree
        liberar.argtypes = [ctypes.c_void_p]
        liberar.restype = ctypes.c_void_p
        liberar(salida.pbData)

def proteger(data): return _transformar(data)
def desproteger(data): return _transformar(data, True)
