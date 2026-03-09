from __future__ import annotations

import base58
from cryptography.exceptions import InvalidSignature

from app.core.ed25519 import load_public_ed25519_key
from app.core.exceptions import LicenseKeyGenerationError
from app.domain.license import BaseLicense


__all__ = ["verify_license"]


def verify_license(
    lic: BaseLicense, signature: str, public_key_pem: bytes
) -> None:
    payload = lic.canonical_json().encode()
    sig_bytes = base58.b58decode(signature.encode())
    public_key = load_public_ed25519_key(public_key_pem)
    try:
        public_key.verify(sig_bytes, payload)
    except InvalidSignature as exc:
        # TODO: this should throw validation error instead of generation error
        raise LicenseKeyGenerationError(
            "License signature verification failed"
        ) from exc
