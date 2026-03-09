from __future__ import annotations

import hashlib
from datetime import datetime

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)
from uuid6 import uuid7

from app.core.exceptions import LicenseKeyGenerationError
from app.domain.license import LicenseFile, NodeLockedLicense
from app.services.license_gen import verify_license


@pytest.fixture
def sample_license(faker) -> NodeLockedLicense:
    """
    Provides a valid `NodeLockedLicense` instance for license-generation and verification tests.

    Scope: function — the license payload includes timestamped values and each test should receive its own independent model instance.

    Provides:
        A `NodeLockedLicense` model with realistic ids, timestamps, and a synthetic device fingerprint.

    Dependencies:
        faker: Supplies the generated fingerprint input.

    Teardown:
        None.

    Note:
        The fixture provides only the license data; each test still generates its own signing key pair.
    """
    now = datetime.now().timestamp()
    return NodeLockedLicense(
        id=uuid7(),
        vendor_id=uuid7(),
        client_id=uuid7(),
        expires_at=now + 3600,
        max_grace_secs=0,
        created_at=now,
        meta_data=None,
        device_fingerprint=(
            # TODO: this is fine for now but should be replaced with actual
            # device fingerprint using the appropriate class
            f"sha256:{hashlib.sha256(faker.binary(length=64)).hexdigest()}"
        ),
        session_limit=1,
    )


@pytest.mark.unit
def test_verify_license_accepts_matching_signature(
    sample_license: NodeLockedLicense,
) -> None:
    """
    Verifies that `app.services.license_gen.verify_license` accepts the signature produced for the same license payload and key pair.
    This matters because license verification is the integrity boundary for signed license files.

    Covers:
        - `app.domain.license.LicenseFile`
        - `app.services.license_gen.verify_license`

    Rationale:
        The test uses a real Ed25519 keypair and a real license signature so it documents the project-level signing and verification round trip. Historical third-party-coupled assertions were removed under REM-012.

    Fixtures:
        sample_license: Valid node-locked license model used to construct and verify the signature.
    """
    signer = Ed25519PrivateKey.generate()
    private_key_pem = signer.private_bytes(
        encoding=Encoding.PEM,
        format=PrivateFormat.PKCS8,
        encryption_algorithm=NoEncryption(),
    )
    public_key_pem = signer.public_key().public_bytes(
        encoding=Encoding.PEM, format=PublicFormat.SubjectPublicKeyInfo
    )
    license_file = LicenseFile(
        license_data=sample_license, private_key_pem=private_key_pem
    )

    verify_license(sample_license, license_file.signature, public_key_pem)


@pytest.mark.unit
def test_verify_license_rejects_tampered_signature(
    sample_license: NodeLockedLicense,
) -> None:
    """
    Verifies that `app.services.license_gen.verify_license` rejects a signature that has been tampered with after signing.
    This matters because the verification boundary must fail closed when license signatures are altered.

    Covers:
        - `app.domain.license.LicenseFile`
        - `app.services.license_gen.verify_license`

    Rationale:
        The test alters one character of a real signature so the failure is measured at the project verification boundary rather than on library internals. Historical third-party-coupled assertions were removed under REM-012.

    Fixtures:
        sample_license: Valid node-locked license model used to construct the original signature.
    """
    signer = Ed25519PrivateKey.generate()
    private_key_pem = signer.private_bytes(
        encoding=Encoding.PEM,
        format=PrivateFormat.PKCS8,
        encryption_algorithm=NoEncryption(),
    )
    public_key_pem = signer.public_key().public_bytes(
        encoding=Encoding.PEM, format=PublicFormat.SubjectPublicKeyInfo
    )
    signature = LicenseFile(
        license_data=sample_license, private_key_pem=private_key_pem
    ).signature
    tampered_signature = signature[:-1] + ("1" if signature[-1] != "1" else "2")

    with pytest.raises(
        LicenseKeyGenerationError, match="License signature verification failed"
    ):
        verify_license(sample_license, tampered_signature, public_key_pem)
