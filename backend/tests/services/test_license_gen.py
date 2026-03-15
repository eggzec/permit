from __future__ import annotations

import hashlib
from datetime import datetime

import base58
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)
from faker import Faker
from pydantic import ValidationError
from uuid6 import uuid7

from app.core.ed25519 import load_public_ed25519_key
from app.core.exceptions import LicenseKeyGenerationError
from app.domain.license import BaseLicense, LicenseFile, NodeLockedLicense
from app.services.license_gen import (
    ACTIVATION_CODE_PATTERN,
    ALPHABET,
    gen_activation_code,
    verify_license,
)


fake = Faker()

# ---------------------------------------------------------------------------
# Module-scoped fixtures — pure in-memory, safe to share across tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def sample_license():
    """A valid NodeLockedLicense instance for use in signature tests."""
    now = datetime.now().timestamp()
    return NodeLockedLicense(
        id=uuid7(),
        vendor_id=uuid7(),
        client_id=uuid7(),
        expires_at=now + 3600,
        max_grace_secs=0,
        created_at=now,
        meta_data=None,
        device_fingerprint=f"sha256:{hashlib.sha256(fake.binary(length=64)).hexdigest()}",
        session_limit=1,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_valid_signature_passes(sample_license: NodeLockedLicense):
    signer = Ed25519PrivateKey.generate()
    payload = sample_license.canonical_json().encode()
    sig_bytes = signer.sign(payload)
    sig_b58 = base58.b58encode(sig_bytes).decode()
    pub_pem = signer.public_key().public_bytes(
        encoding=Encoding.PEM, format=PublicFormat.SubjectPublicKeyInfo
    )
    # Must not raise
    verify_license(sample_license, sig_b58, pub_pem)


@pytest.mark.unit
def test_tampered_signature_raises(sample_license: NodeLockedLicense):
    signer = Ed25519PrivateKey.generate()
    payload = sample_license.canonical_json().encode()
    sig_bytes = signer.sign(payload)
    sig_b58 = base58.b58encode(sig_bytes).decode()
    pub_pem = signer.public_key().public_bytes(
        encoding=Encoding.PEM, format=PublicFormat.SubjectPublicKeyInfo
    )
    tampered = sig_b58[:-1] + ("1" if sig_b58[-1] != "1" else "2")

    with pytest.raises(LicenseKeyGenerationError):
        verify_license(sample_license, tampered, pub_pem)


@pytest.mark.unit
def test_rejects_non_ed25519_key(sample_license: NodeLockedLicense):
    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    rsa_pem = rsa_key.private_bytes(
        encoding=Encoding.PEM,
        format=PrivateFormat.PKCS8,
        encryption_algorithm=NoEncryption(),
    )
    with pytest.raises((ValidationError, TypeError)):
        LicenseFile(license_data=sample_license, private_key_pem=rsa_pem)


@pytest.mark.unit
def test_matches_pattern():
    code = gen_activation_code()
    assert ACTIVATION_CODE_PATTERN.match(code), (
        f"Code {code!r} does not match required pattern XXXX-XXXX-XXXX-XXXX"
    )


@pytest.mark.unit
def test_length_is_19_characters():
    code = gen_activation_code()
    assert len(code) == 19, (
        f"Expected 19 characters (16 + 3 dashes), got {len(code)}"
    )


@pytest.mark.unit
def test_has_four_segments():
    code = gen_activation_code()
    segments = code.split("-")
    assert len(segments) == 4, (
        f"Expected 4 dash-separated segments, got {len(segments)}"
    )


@pytest.mark.unit
def test_each_segment_has_four_characters():
    code = gen_activation_code()
    for i, segment in enumerate(code.split("-")):
        assert len(segment) == 4, (
            f"Segment {i} has {len(segment)} chars, expected 4"
        )


@pytest.mark.unit
def test_uses_only_valid_crockford_alphabet():
    code = gen_activation_code()
    raw = code.replace("-", "")
    invalid = [c for c in raw if c not in ALPHABET]
    assert not invalid, (
        f"Code contains characters outside Crockford alphabet: {invalid}"
    )


@pytest.mark.unit
def test_batch_is_statistically_unique():
    """100 codes generated in one call must all be distinct."""
    codes = [gen_activation_code() for _ in range(100)]
    assert len(set(codes)) == 100, "All 100 generated codes must be unique"


@pytest.mark.unit
def test_license_expiry_validation_raises():
    """BaseLicense should raise ValueError if expires_at <= created_at."""
    now = datetime.now().timestamp()
    with pytest.raises(ValidationError, match="expiry date cannot be before"):
        BaseLicense(
            id=uuid7(),
            vendor_id=uuid7(),
            client_id=uuid7(),
            expires_at=now - 3600,  # Expired in past
            max_grace_secs=0,
            created_at=now,
            meta_data=None,
        )


@pytest.mark.unit
def test_load_public_ed25519_key_raises_for_rsa_key():
    """load_public_ed25519_key should raise TypeError for non-Ed25519 keys."""
    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub_pem = rsa_key.public_key().public_bytes(
        encoding=Encoding.PEM, format=PublicFormat.SubjectPublicKeyInfo
    )
    with pytest.raises(TypeError, match="not an Ed25519 public key"):
        load_public_ed25519_key(pub_pem)


@pytest.mark.unit
def test_license_file_signature_generation(sample_license):
    """LicenseFile should generate a valid base58 signature."""
    signer = Ed25519PrivateKey.generate()
    priv_pem = signer.private_bytes(
        encoding=Encoding.PEM,
        format=PrivateFormat.PKCS8,
        encryption_algorithm=NoEncryption(),
    )

    lf = LicenseFile(license_data=sample_license, private_key_pem=priv_pem)
    sig = lf.signature
    assert sig, "Signature must not be empty"
    # Basic base58 character set check
    assert all(
        c in "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
        for c in sig
    )
