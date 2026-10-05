from __future__ import annotations

import base64
import ctypes
import os
import uuid
from ctypes import wintypes
from pathlib import Path


class SecretStoreUnavailable(RuntimeError):
    pass


class SecretNotFound(KeyError):
    pass


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


class WindowsDPAPISecretStore:
    def __init__(self, home: Path):
        if os.name != "nt":
            raise SecretStoreUnavailable("Windows DPAPI is available only on Windows")
        self.root = home / "secrets"
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _blob(data: bytes) -> tuple[_DATA_BLOB, ctypes.Array[ctypes.c_char]]:
        buffer = ctypes.create_string_buffer(data)
        blob = _DATA_BLOB(
            len(data),
            ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)),
        )
        return blob, buffer

    @staticmethod
    def _protect(data: bytes) -> bytes:
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        source, source_buffer = WindowsDPAPISecretStore._blob(data)
        _ = source_buffer
        output = _DATA_BLOB()
        if not crypt32.CryptProtectData(
            ctypes.byref(source),
            "Homuncula",
            None,
            None,
            None,
            0x1,
            ctypes.byref(output),
        ):
            raise ctypes.WinError()
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            kernel32.LocalFree(output.pbData)

    @staticmethod
    def _unprotect(data: bytes) -> bytes:
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        source, source_buffer = WindowsDPAPISecretStore._blob(data)
        _ = source_buffer
        output = _DATA_BLOB()
        if not crypt32.CryptUnprotectData(
            ctypes.byref(source),
            None,
            None,
            None,
            None,
            0x1,
            ctypes.byref(output),
        ):
            raise ctypes.WinError()
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            kernel32.LocalFree(output.pbData)

    def put(self, value: str) -> str:
        secret_ref = "sec_" + uuid.uuid4().hex
        protected = self._protect(value.encode("utf-8"))
        encoded = base64.urlsafe_b64encode(protected)
        (self.root / secret_ref).write_bytes(encoded)
        return secret_ref

    def get(self, secret_ref: str) -> str:
        if not secret_ref.startswith("sec_") or "/" in secret_ref or "\\" in secret_ref:
            raise SecretNotFound(secret_ref)
        path = self.root / secret_ref
        if not path.exists():
            raise SecretNotFound(secret_ref)
        protected = base64.urlsafe_b64decode(path.read_bytes())
        return self._unprotect(protected).decode("utf-8")

    def delete(self, secret_ref: str) -> None:
        path = self.root / secret_ref
        if not path.exists():
            raise SecretNotFound(secret_ref)
        path.unlink()

    def list_refs(self) -> list[str]:
        return sorted(path.name for path in self.root.glob("sec_*") if path.is_file())


class MemorySecretStore:
    def __init__(self):
        self.values: dict[str, str] = {}

    def put(self, value: str) -> str:
        secret_ref = "sec_" + uuid.uuid4().hex
        self.values[secret_ref] = value
        return secret_ref

    def get(self, secret_ref: str) -> str:
        try:
            return self.values[secret_ref]
        except KeyError as exc:
            raise SecretNotFound(secret_ref) from exc

    def delete(self, secret_ref: str) -> None:
        try:
            del self.values[secret_ref]
        except KeyError as exc:
            raise SecretNotFound(secret_ref) from exc

    def list_refs(self) -> list[str]:
        return sorted(self.values)
