"""Fernet encrypt/decrypt wrapper for storing secrets in the DB."""

from cryptography.fernet import Fernet

from app.config import settings

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        if not settings.fernet_key:
            raise RuntimeError("FERNET_KEY is not configured")
        _fernet = Fernet(settings.fernet_key.encode())
    return _fernet


def encrypt(plaintext: str) -> bytes:
    """Encrypt a string and return bytes suitable for LargeBinary column."""
    return _get_fernet().encrypt(plaintext.encode())


def decrypt(ciphertext: bytes) -> str:
    """Decrypt bytes from DB back to string."""
    return _get_fernet().decrypt(ciphertext).decode()


def encrypt_bytes(data: bytes) -> bytes:
    """Encrypt raw bytes (e.g. PFX certificate)."""
    return _get_fernet().encrypt(data)


def decrypt_bytes(ciphertext: bytes) -> bytes:
    """Decrypt raw bytes."""
    return _get_fernet().decrypt(ciphertext)
