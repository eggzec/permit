from __future__ import annotations

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from app.core.ed25519 import load_private_ed25519_key, load_public_ed25519_key


@pytest.mark.unit
def test_load_private_ed25519_key_returns_private_key() -> None:
    """
    Verifies that `app.core.ed25519.load_private_ed25519_key` accepts a
    PEM-encoded Ed25519 private key and returns the expected key type. This
    matters because license signing and verification depend on loading the
    correct asymmetric key material.

    Covers:
        - `app.core.ed25519.load_private_ed25519_key`

    Rationale:
        The test uses real generated key material because the loader contract is defined by accepted and rejected key types.

    Fixtures:
        None.
    """
    private_key = Ed25519PrivateKey.generate()
    private_key_pem = private_key.private_bytes(
        encoding=Encoding.PEM,
        format=PrivateFormat.PKCS8,
        encryption_algorithm=NoEncryption(),
    )
    loaded_private_key = load_private_ed25519_key(private_key_pem)

    assert isinstance(loaded_private_key, Ed25519PrivateKey), (
        f"Expected Ed25519PrivateKey, got {type(loaded_private_key)}"
    )


@pytest.mark.unit
def test_load_private_ed25519_key_rejects_rsa_private_key() -> None:
    """
    Verifies that `app.core.ed25519.load_private_ed25519_key` rejects PEM data
    for a non-Ed25519 private key. This matters because callers should fail fast
    when they provide the wrong key type for Ed25519 operations.

    Covers:
        - `app.core.ed25519.load_private_ed25519_key`

    Rationale:
        A real RSA key is used so the failure documents the public loader contract rather than a mocked type check.

    Fixtures:
        None.
    """
    rsa_private_key = rsa.generate_private_key(
        public_exponent=65537, key_size=2048
    )
    rsa_private_key_pem = rsa_private_key.private_bytes(
        encoding=Encoding.PEM,
        format=PrivateFormat.PKCS8,
        encryption_algorithm=NoEncryption(),
    )

    with pytest.raises(TypeError, match="not an Ed25519 private key"):
        load_private_ed25519_key(rsa_private_key_pem)


@pytest.mark.unit
def test_load_public_ed25519_key_returns_public_key() -> None:
    """
    Verifies that `app.core.ed25519.load_public_ed25519_key` accepts a
    PEM-encoded Ed25519 public key and returns the expected key type. This
    matters because license verification depends on loading the correct public
    key material.

    Covers:
        - `app.core.ed25519.load_public_ed25519_key`

    Rationale:
        The test generates a real Ed25519 keypair and round-trips only the public key because that is the public contract of the loader.

    Fixtures:
        None.
    """
    public_key_pem = (
        Ed25519PrivateKey
        .generate()
        .public_key()
        .public_bytes(
            encoding=Encoding.PEM, format=PublicFormat.SubjectPublicKeyInfo
        )
    )
    loaded_public_key = load_public_ed25519_key(public_key_pem)

    assert isinstance(loaded_public_key, Ed25519PublicKey), (
        f"Expected Ed25519PublicKey, got {type(loaded_public_key)}"
    )


@pytest.mark.unit
def test_load_public_ed25519_key_rejects_rsa_public_key() -> None:
    """
    Verifies that `app.core.ed25519.load_public_ed25519_key` rejects PEM data
    for a non-Ed25519 public key. This matters because callers must not
    accidentally verify signatures with incompatible key material.

    Covers:
        - `app.core.ed25519.load_public_ed25519_key`

    Rationale:
        A real RSA public key is used so the failure path reflects the same key-type mismatch production code would encounter.

    Fixtures:
        None.
    """
    rsa_public_key_pem = (
        rsa
        .generate_private_key(public_exponent=65537, key_size=2048)
        .public_key()
        .public_bytes(
            encoding=Encoding.PEM, format=PublicFormat.SubjectPublicKeyInfo
        )
    )

    with pytest.raises(TypeError, match="not an Ed25519 public key"):
        load_public_ed25519_key(rsa_public_key_pem)
