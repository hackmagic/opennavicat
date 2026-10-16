"""Ed25519 signing: tamper detection, key handling and fingerprints."""

import pytest

from open_navicat.errors import PluginSignatureError
from open_navicat.plugin.manifest import canonical_manifest_bytes, parse_manifest
from open_navicat.plugin.signing import (
    generate_keypair,
    load_private_key,
    load_public_key,
    public_key_fingerprint,
    sha256_hex,
    sign_bytes,
    verify_bytes,
)

MESSAGE = b"the manifest bytes that get signed"


@pytest.fixture(scope="module")
def keypair():
    return generate_keypair()


class TestSignVerify:
    def test_roundtrip(self, keypair):
        pub, priv = keypair
        sig = sign_bytes(MESSAGE, priv)
        assert verify_bytes(MESSAGE, sig, pub) is True

    def test_tampered_payload_rejected(self, keypair):
        pub, priv = keypair
        sig = sign_bytes(MESSAGE, priv)
        assert verify_bytes(MESSAGE + b"!", sig, pub) is False

    def test_tampered_signature_rejected(self, keypair):
        pub, priv = keypair
        sig = sign_bytes(MESSAGE, priv)
        flipped = ("A" if sig[0] != "A" else "B") + sig[1:]
        assert verify_bytes(MESSAGE, flipped, pub) is False

    def test_wrong_key_rejected(self, keypair):
        pub, priv = keypair
        other_pub, _ = generate_keypair()
        sig = sign_bytes(MESSAGE, priv)
        assert verify_bytes(MESSAGE, sig, other_pub) is False

    def test_empty_payload_signs(self, keypair):
        pub, priv = keypair
        sig = sign_bytes(b"", priv)
        assert verify_bytes(b"", sig, pub) is True

    def test_bad_base64_signature_is_false_not_raise(self, keypair):
        # A corrupt signature file must read as "not verified", not crash the
        # installer with an unrelated decode error.
        pub, _ = keypair
        assert verify_bytes(MESSAGE, "!!!not base64!!!", pub) is False

    def test_bad_base64_key_raises(self):
        with pytest.raises(PluginSignatureError, match="invalid base64"):
            load_public_key("not base64 at all $$$")

    def test_wrong_length_key_raises(self):
        import base64

        short = base64.b64encode(b"too short").decode()
        with pytest.raises(PluginSignatureError, match="not a valid Ed25519"):
            load_public_key(short)

    def test_pem_roundtrip(self):
        from cryptography.hazmat.primitives import serialization

        _, priv = generate_keypair()
        pem = (
            load_private_key(priv)
            .private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
            .decode()
        )
        assert sign_bytes(MESSAGE, pem) == sign_bytes(MESSAGE, priv)

    def test_pem_public_key(self, keypair):
        from cryptography.hazmat.primitives import serialization

        pub, _ = keypair
        pem = (
            load_public_key(pub)
            .public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            .decode()
        )
        assert load_public_key(pem).public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        ) == load_public_key(pub).public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

    def test_pem_that_is_not_ed25519_rejected(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = (
            key.public_key()
            .public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            .decode()
        )
        with pytest.raises(PluginSignatureError, match="not Ed25519"):
            load_public_key(pem)

    def test_pem_that_is_not_a_key_rejected(self):
        with pytest.raises(PluginSignatureError, match="unreadable PEM"):
            load_public_key("-----BEGIN PUBLIC KEY-----\nZm9v\n-----END PUBLIC KEY-----")


class TestKeys:
    def test_keypair_is_base64_and_usable(self, keypair):
        pub, priv = keypair
        import base64

        assert base64.b64encode(base64.b64decode(pub)).decode() == pub
        assert base64.b64encode(base64.b64decode(priv)).decode() == priv
        assert len(base64.b64decode(pub)) == 32

    def test_keys_are_distinct(self):
        a_pub, a_priv = generate_keypair()
        b_pub, b_priv = generate_keypair()
        assert a_pub != b_pub
        assert a_priv != b_priv

    def test_fingerprint_stable_and_readable(self, keypair):
        pub, _ = keypair
        fp = public_key_fingerprint(pub)
        assert fp == public_key_fingerprint(pub)
        assert ":" in fp
        assert len(fp.split(":")[0]) == 8

    def test_fingerprint_differs_between_keys(self):
        a_pub, _ = generate_keypair()
        b_pub, _ = generate_keypair()
        assert public_key_fingerprint(a_pub) != public_key_fingerprint(b_pub)


class TestSha256:
    def test_digest_shape(self):
        assert sha256_hex(b"") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

    def test_digest_changes_with_input(self):
        assert sha256_hex(b"a") != sha256_hex(b"b")


class TestManifestSigning:
    def test_signature_covers_manifest_content(self, keypair):
        # The chain of trust: manifest bytes are signed, and the manifest
        # itself lists digests for every code file.  So changing one byte of
        # code changes a digest, changes the manifest, and breaks the sign.
        pub, priv = keypair
        m = parse_manifest({"id": "a.b", "version": "1.0.0", "entry_point": "m.C"})
        sig = sign_bytes(canonical_manifest_bytes(m), priv)
        assert verify_bytes(canonical_manifest_bytes(m), sig, pub) is True
        bumped = parse_manifest({"id": "a.b", "version": "1.0.1", "entry_point": "m.C"})
        assert verify_bytes(canonical_manifest_bytes(bumped), sig, pub) is False
