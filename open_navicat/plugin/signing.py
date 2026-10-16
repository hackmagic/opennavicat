"""Ed25519 package signing.

Chain of trust, in one sentence: the manifest lists a sha256 for every file
in the package, the manifest is signed, therefore any change to any file
invalidates the signature.

Why sign the manifest and not the zip: a zip's central directory records
mtimes and ordering, so the same content packaged twice produces different
bytes.  The manifest is canonicalised (sorted keys, no whitespace) before
signing, so signatures are reproducible across machines and zip versions.

Keys are 32-byte Ed25519 keys, base64-encoded for transport.  The *private*
key never leaves the author's machine; only public keys are distributed, and
only public keys listed in ``plugin.trusted_keys`` (settings) will install a
package.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from open_navicat.errors import PluginSignatureError

__all__ = [
    "SIGNATURE_ALGORITHM",
    "generate_keypair",
    "sign_bytes",
    "verify_bytes",
    "public_key_fingerprint",
    "load_public_key",
    "load_private_key",
    "encode_public_key",
    "encode_private_key",
    "sha256_hex",
]

#: Recorded in every signature file so a future algorithm change is visible
#: rather than inferred.
SIGNATURE_ALGORITHM = "ed25519"


def _b64e(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _b64d(text: str) -> bytes:
    try:
        return base64.b64decode(text.strip().encode("ascii"), validate=True)
    except Exception as exc:  # binascii.Error, ValueError
        raise PluginSignatureError(f"invalid base64 key material: {exc}") from exc


def generate_keypair() -> tuple[str, str]:
    """Return ``(public_b64, private_b64)`` for a fresh keypair.

    The public half is safe to publish; the private half is what
    ``opennavicat plugin keygen`` writes to a file with a warning.
    """
    private = Ed25519PrivateKey.generate()
    return encode_public_key(private.public_key()), encode_private_key(private)


def load_private_key(text: str) -> Ed25519PrivateKey:
    """Decode a base64 private key (raw 32 bytes or PEM)."""
    text = text.strip()
    if text.startswith("-----BEGIN"):
        key = serialization.load_pem_private_key(text.encode("utf-8"), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise PluginSignatureError("PEM key is not Ed25519")
        return key
    raw = _b64d(text)
    try:
        return Ed25519PrivateKey.from_private_bytes(raw)
    except Exception as exc:
        raise PluginSignatureError("not a valid Ed25519 private key") from exc


def load_public_key(text: str) -> Ed25519PublicKey:
    """Decode a base64 public key (raw 32 bytes or PEM)."""
    text = text.strip()
    if text.startswith("-----BEGIN"):
        try:
            key = serialization.load_pem_public_key(text.encode("utf-8"))
        except Exception as exc:
            raise PluginSignatureError(f"unreadable PEM public key: {exc}") from exc
        if not isinstance(key, Ed25519PublicKey):
            raise PluginSignatureError("PEM key is not Ed25519")
        return key
    raw = _b64d(text)
    try:
        return Ed25519PublicKey.from_public_bytes(raw)
    except Exception as exc:
        raise PluginSignatureError("not a valid Ed25519 public key") from exc


def encode_public_key(key: Ed25519PublicKey) -> str:
    raw = key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return _b64e(raw)


def encode_private_key(key: Ed25519PrivateKey) -> str:
    raw = key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return _b64e(raw)


def _raw_public(key: Ed25519PublicKey) -> bytes:
    return key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def public_key_fingerprint(public_b64: str) -> str:
    """Stable short id for a public key, used in the trusted-key list.

    Displayed in the UI so a user can confirm "this is the key I imported"
    without comparing 44 base64 characters by eye.
    """
    digest = hashlib.sha256(_raw_public(load_public_key(public_b64))).hexdigest()
    return f"{digest[:8]}:{digest[8:12]}"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sign_bytes(payload: bytes, private_b64: str) -> str:
    """Detached Ed25519 signature over ``payload``, base64-encoded."""
    key = load_private_key(private_b64)
    return _b64e(key.sign(payload))


def verify_bytes(payload: bytes, signature_b64: str, public_b64: str) -> bool:
    """True when ``signature_b64`` is a valid signature over ``payload``.

    Never raises for a *bad signature* -- that is a normal answer and the
    caller reports it.  Only malformed key material or malformed base64
    signature text raises.
    """
    key = load_public_key(public_b64)
    try:
        raw = _b64d(signature_b64)
    except PluginSignatureError:
        return False
    try:
        key.verify(raw, payload)
    except InvalidSignature:
        return False
    return True
