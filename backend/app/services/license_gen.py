from __future__ import annotations

import re
import secrets

import base58
from cryptography.exceptions import InvalidSignature

from app.core.ed25519 import load_public_ed25519_key
from app.core.exceptions import LicenseKeyGenerationError
from app.domain.license import BaseLicense
from app.internal import base32_crockford


__all__ = [
    "ACTIVATION_CODE_PATTERN",
    "ALPHABET",
    "MAX_RETRIES",
    "gen_activation_code",
    "verify_license",
]

ALPHABET = base32_crockford.SYMBOLS
ACTIVATION_CODE_PATTERN = re.compile(r"^([A-Z0-9]{4}-){3}[A-Z0-9]{4}$")
MAX_RETRIES = 5


def verify_license(
    lic: BaseLicense, signature: str, public_key_pem: bytes
) -> None:
    payload = lic.canonical_json().encode()
    sig_bytes = base58.b58decode(signature.encode())
    public_key = load_public_ed25519_key(public_key_pem)
    try:
        public_key.verify(sig_bytes, payload)
    except InvalidSignature as exc:
        raise LicenseKeyGenerationError(
            "License signature verification failed"
        ) from exc


def _generate_raw_code() -> str:
    """Generate a raw 16-character Crockford base32 string (80 bits).

    Returns:
        str: A 16-character base32 encoded string.
    """
    # 80 bits = 10 bytes. 16 symbols * 5 bits = 80 bits.
    val = secrets.randbits(80)
    # Ensure it's exactly 16 chars by zero-padding if necessary
    return base32_crockford.encode(val).zfill(16)


def gen_activation_code() -> str:
    """Generate a unique 19-character activation code (XXXX-XXXX-XXXX-XXXX).

    Returns:
        str: A formatted activation code.
    """
    raw = _generate_raw_code()
    # Format with dashes
    formatted = "-".join(raw[i : i + 4] for i in range(0, 16, 4))
    return formatted
