"""Fernet-based encryption for API key storage at rest."""

import base64
import hashlib

from cryptography.fernet import Fernet


def _derive_key(secret: str) -> bytes:
    """Derive a valid 32-byte Fernet key from the app secret key."""
    raw = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(raw)


def get_cipher() -> Fernet | None:
    """Return a Fernet cipher instance using the app secret key, or None if not configured."""
    from app.config import settings

    key = settings.app_secret_key
    if not key or key == "change-me-to-a-random-secret":
        return None
    return Fernet(_derive_key(key))


def encrypt_value(plaintext: str) -> str:
    """Encrypt a plaintext string. Returns the encrypted value as a base64 string."""
    cipher = get_cipher()
    if cipher is None:
        return plaintext  # fallback: store plaintext if no key configured
    return cipher.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_value(ciphertext: str) -> str:
    """Decrypt a ciphertext string. Returns the original plaintext."""
    try:
        cipher = get_cipher()
        if cipher is None:
            return ciphertext
        return cipher.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except Exception:
        # If decryption fails, return as-is (migration fallback for plaintext values)
        return ciphertext
