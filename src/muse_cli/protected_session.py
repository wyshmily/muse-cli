"""Read a Windows-user DPAPI cookie jar without writing plaintext credentials."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path


def load_windows_session(path):
    from .gateway import AuthError
    if os.name != 'nt':
        raise AuthError('DPAPI sessions require the Windows user that saved them')

    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]

    data = Path(path).read_bytes()
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    result = Blob()
    decrypt = ctypes.WinDLL('crypt32', use_last_error=True).CryptUnprotectData
    decrypt.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                       ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    decrypt.restype = wintypes.BOOL
    if not decrypt(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise AuthError('Could not decrypt the local Windows session')
    free = ctypes.WinDLL('kernel32').LocalFree
    free.argtypes = [ctypes.c_void_p]
    free.restype = ctypes.c_void_p
    try:
        jar = json.loads(ctypes.string_at(result.data, result.size))
    finally:
        ctypes.memset(result.data, 0, result.size)
        free(result.data)
    cookies = [c for c in jar if c.get('domain', '').lstrip('.') == 'muse.ai'
               or c.get('domain', '').endswith('.muse.ai')]
    if not any(c.get('name') == 'hatch_sess' for c in cookies):
        raise AuthError('Protected session does not contain a Muse login')
    return '; '.join(c['name'] + '=' + c['value'] for c in cookies)
