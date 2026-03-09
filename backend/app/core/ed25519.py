from __future__ import annotations

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    load_pem_private_key,
    load_pem_public_key,
)
from cryptography.utils import Buffer


__all__ = ["load_private_ed25519_key", "load_public_ed25519_key"]


def load_private_ed25519_key(
    pem: Buffer, password: bytes | None = None
) -> Ed25519PrivateKey:
    key = load_pem_private_key(pem, password=password)
    if not isinstance(key, Ed25519PrivateKey):
        raise TypeError("Provided key is not an Ed25519 private key")
    return key


def load_public_ed25519_key(pem: bytes) -> Ed25519PublicKey:
    key = load_pem_public_key(pem)
    if not isinstance(key, Ed25519PublicKey):
        raise TypeError("Provided key is not an Ed25519 public key")
    return key
