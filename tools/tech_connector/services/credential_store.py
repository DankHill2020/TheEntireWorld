"""Operating-system protected credential persistence for desktop clients."""

from __future__ import annotations

import ctypes
import hashlib
import os
import stat
from ctypes import wintypes
from pathlib import Path


class CredentialStoreUnavailable(RuntimeError):
    """Raised when the host has no supported protected credential facility."""


class _DataBlob(ctypes.Structure):
    _fields_ = (("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte)))


def _blob(data: bytes):
    buffer = ctypes.create_string_buffer(data)
    value = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    return value, buffer


class WindowsDpapiCredentialStore:
    """Persist small secrets encrypted for the current Windows user."""

    _ENTROPY = b"the_entire_world.tech_connector.credentials.v1"
    _UI_FORBIDDEN = 0x01

    def __init__(self, root: str | Path) -> None:
        if os.name != "nt":
            raise CredentialStoreUnavailable("Windows DPAPI is unavailable on this platform")
        self.root = Path(root).expanduser() / "credentials"

    def _path(self, key: str) -> Path:
        normalized = str(key or "").strip()
        if not normalized:
            raise ValueError("credential key is required")
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        return self.root / f"{digest}.credential"

    def _protect(self, value: bytes) -> bytes:
        source, source_buffer = _blob(value)
        entropy, entropy_buffer = _blob(self._ENTROPY)
        destination = _DataBlob()
        crypt32 = ctypes.windll.crypt32
        if not crypt32.CryptProtectData(
            ctypes.byref(source),
            "Tech Connector credential",
            ctypes.byref(entropy),
            None,
            None,
            self._UI_FORBIDDEN,
            ctypes.byref(destination),
        ):
            raise ctypes.WinError()
        try:
            return ctypes.string_at(destination.pbData, destination.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(destination.pbData)
            del source_buffer, entropy_buffer

    def _unprotect(self, value: bytes) -> bytes:
        source, source_buffer = _blob(value)
        entropy, entropy_buffer = _blob(self._ENTROPY)
        destination = _DataBlob()
        crypt32 = ctypes.windll.crypt32
        if not crypt32.CryptUnprotectData(
            ctypes.byref(source),
            None,
            ctypes.byref(entropy),
            None,
            None,
            self._UI_FORBIDDEN,
            ctypes.byref(destination),
        ):
            raise ctypes.WinError()
        try:
            return ctypes.string_at(destination.pbData, destination.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(destination.pbData)
            del source_buffer, entropy_buffer

    def load(self, key: str) -> str:
        path = self._path(key)
        try:
            protected = path.read_bytes()
        except FileNotFoundError:
            return ""
        return self._unprotect(protected).decode("utf-8")

    def save(self, key: str, value: str) -> None:
        text = str(value or "")
        if not text:
            self.delete(key)
            return
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(key)
        temporary = path.with_suffix(".credential.tmp")
        temporary.write_bytes(self._protect(text.encode("utf-8")))
        _restrict_to_current_user(temporary)
        temporary.replace(path)
        _restrict_to_current_user(path)

    def delete(self, key: str) -> None:
        try:
            self._path(key).unlink()
        except FileNotFoundError:
            pass


class UnavailableCredentialStore:
    """Non-persistent adapter that refuses to risk plaintext secret storage."""

    def load(self, key: str) -> str:
        return ""

    def save(self, key: str, value: str) -> None:
        if str(value or ""):
            raise CredentialStoreUnavailable(
                "No supported operating-system credential store is available"
            )

    def delete(self, key: str) -> None:
        return None


def default_credential_store(app_data_root: str | Path):
    if os.name == "nt":
        return WindowsDpapiCredentialStore(app_data_root)
    return UnavailableCredentialStore()


def _restrict_to_current_user(path: Path) -> None:
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
