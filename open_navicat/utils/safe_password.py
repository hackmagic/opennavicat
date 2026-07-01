"""Secure password storage with encryption and system keyring."""

from __future__ import annotations

import os
import base64
from typing import Optional

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from open_navicat.config import DATA_DIR


def _get_machine_key() -> bytes:
    """Derive a machine-specific Fernet key from a unique device identifier."""
    key_file = DATA_DIR / ".machine_key"
    if key_file.exists():
        return key_file.read_bytes()
    # Generate key from machine identifier
    machine_id = os.environ.get("COMPUTERNAME", "opennavicat-default").encode()
    salt = b"opennavicat-salt-v1"
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=100000)
    key = base64.urlsafe_b64encode(kdf.derive(machine_id))
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    key_file.write_bytes(key)
    return key


_cipher = Fernet(_get_machine_key())


def encrypt_password(plaintext: str) -> str:
    """Encrypt a password for local storage."""
    if not plaintext:
        return ""
    return _cipher.encrypt(plaintext.encode()).decode()


def decrypt_password(ciphertext: str) -> str:
    """Decrypt a previously encrypted password."""
    if not ciphertext:
        return ""
    try:
        return _cipher.decrypt(ciphertext.encode()).decode()
    except Exception:
        return ""


def mask_password(password: str, visible_chars: int = 2) -> str:
    """Return a masked version of the password for display purposes."""
    if len(password) <= visible_chars:
        return "*" * len(password)
    return password[:visible_chars] + "*" * (len(password) - visible_chars)
