"""Contêiner da chave de cada certificado e SID do usuário (Frente C, 15/11/2026).

O evento 5061 do Windows traz o nome do contêiner da chave, não o certificado.
Para ligar um ao outro, a bandeja manda ao portal {sha256: contêiner}.

REGRA: ler o contêiner NUNCA abre a chave privada. Abrir gera 5058/5061 falso
e suja o próprio registro de uso. Por isso só se lê a propriedade
CERT_KEY_PROV_INFO_PROP_ID do certificado. Proibido aqui:
CryptAcquireCertificatePrivateKey, .PrivateKey, GetRSAPrivateKey, NCryptOpenKey
e certutil.
"""

from __future__ import annotations

import ctypes
import hashlib
import logging
from ctypes import wintypes

LOGGER = logging.getLogger(__name__)

CERT_KEY_PROV_INFO_PROP_ID = 2
TOKEN_QUERY = 0x0008
TOKEN_USER = 1


class _CertContext(ctypes.Structure):
    _fields_ = [("dwCertEncodingType", wintypes.DWORD), ("pbCertEncoded", ctypes.POINTER(ctypes.c_ubyte)),
                ("cbCertEncoded", wintypes.DWORD), ("pCertInfo", ctypes.c_void_p),
                ("hCertStore", ctypes.c_void_p)]


class _KeyProvInfo(ctypes.Structure):
    _fields_ = [("pwszContainerName", wintypes.LPWSTR)]  # só o primeiro campo interessa


def conteineres() -> dict[str, str]:
    """sha256 do DER (minúsculo) -> nome do contêiner, em CurrentUser\\My. `{}` se falhar."""
    loja = None
    crypt32 = None
    try:
        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        crypt32.CertOpenSystemStoreW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        crypt32.CertOpenSystemStoreW.restype = ctypes.c_void_p
        crypt32.CertEnumCertificatesInStore.argtypes = [ctypes.c_void_p, ctypes.POINTER(_CertContext)]
        crypt32.CertEnumCertificatesInStore.restype = ctypes.POINTER(_CertContext)
        crypt32.CertGetCertificateContextProperty.argtypes = [
            ctypes.POINTER(_CertContext), wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
        crypt32.CertGetCertificateContextProperty.restype = wintypes.BOOL
        crypt32.CertCloseStore.argtypes = [ctypes.c_void_p, wintypes.DWORD]
        crypt32.CertCloseStore.restype = wintypes.BOOL

        loja = crypt32.CertOpenSystemStoreW(None, "MY")
        if not loja:
            raise ctypes.WinError(ctypes.get_last_error())
        mapa: dict[str, str] = {}
        ctx = crypt32.CertEnumCertificatesInStore(loja, None)
        while ctx:  # o Enum libera o contexto anterior sozinho
            nome = _nome_do_conteiner(crypt32, ctx)
            if nome:
                c = ctx.contents
                der = ctypes.string_at(c.pbCertEncoded, c.cbCertEncoded)
                mapa[hashlib.sha256(der).hexdigest()] = nome
            ctx = crypt32.CertEnumCertificatesInStore(loja, ctx)
        return mapa
    except Exception:  # noqa: BLE001 — sem o mapa o uso fica sem resolver, mas a conferência segue
        LOGGER.exception("Contêineres das chaves: leitura falhou")
        return {}
    finally:
        if loja and crypt32 is not None:
            crypt32.CertCloseStore(loja, 0)


def _nome_do_conteiner(crypt32, ctx) -> str:
    """Propriedade 2 do certificado; certificado sem chave devolve ''."""
    tam = wintypes.DWORD(0)
    if not crypt32.CertGetCertificateContextProperty(ctx, CERT_KEY_PROV_INFO_PROP_ID, None, ctypes.byref(tam)):
        return ""
    buf = ctypes.create_string_buffer(tam.value)
    if not crypt32.CertGetCertificateContextProperty(ctx, CERT_KEY_PROV_INFO_PROP_ID, buf, ctypes.byref(tam)):
        return ""
    return _KeyProvInfo.from_buffer(buf).pwszContainerName or ""


def sid_atual() -> str:
    """SID do token do processo ('S-1-5-21-...'), ou '' em caso de falha."""
    token = wintypes.HANDLE()
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        adv = ctypes.WinDLL("advapi32", use_last_error=True)
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        k32.LocalFree.argtypes = [ctypes.c_void_p]
        adv.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
        adv.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                            ctypes.POINTER(wintypes.DWORD)]
        adv.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
        if not adv.OpenProcessToken(k32.GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(token)):
            raise ctypes.WinError(ctypes.get_last_error())
        tam = wintypes.DWORD(0)
        adv.GetTokenInformation(token, TOKEN_USER, None, 0, ctypes.byref(tam))  # só pede o tamanho
        buf = ctypes.create_string_buffer(tam.value)
        if not adv.GetTokenInformation(token, TOKEN_USER, buf, tam, ctypes.byref(tam)):
            raise ctypes.WinError(ctypes.get_last_error())
        sid_ptr = ctypes.c_void_p.from_buffer(buf).value  # TOKEN_USER começa pelo ponteiro do SID
        texto = wintypes.LPWSTR()
        if not adv.ConvertSidToStringSidW(sid_ptr, ctypes.byref(texto)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return texto.value or ""
        finally:
            k32.LocalFree(ctypes.cast(texto, ctypes.c_void_p))
    except Exception:  # noqa: BLE001
        LOGGER.exception("SID do usuário: leitura falhou")
        return ""
    finally:
        if token:
            ctypes.WinDLL("kernel32").CloseHandle(token)
