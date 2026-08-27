from __future__ import annotations

import json
from datetime import datetime

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)
from pydantic import ValidationError
from uuid6 import uuid7

from app.domain.license import BaseLicense, LicenseFile, NodeLockedLicense


def build_base_license(faker, **overrides) -> BaseLicense:
    """
    Builds a valid `BaseLicense` payload that callers can override for focused test scenarios.

    Used by:
        test_base_license_canonical_json_is_sorted - creates the baseline license model for canonical serialization.
        test_base_license_rejects_expiry_before_creation - supplies a valid payload before one temporal field is invalidated.
        test_node_locked_license_requires_positive_session_limit - seeds the node-locked license builder.

    Args:
        faker: `Faker` session fixture used to generate metadata values.
        overrides: Field replacements applied on top of the default base-license payload.

    Returns:
        BaseLicense: A valid base-license model unless the caller intentionally overrides a field into an invalid state.
    """
    now = datetime.now().timestamp()
    payload = {
        "id": uuid7(),
        "vendor_id": uuid7(),
        "client_id": uuid7(),
        "expires_at": now + 3600,
        "max_grace_secs": 0,
        "created_at": now,
        "meta_data": {faker.word(): faker.word(), faker.word(): faker.word()},
    }
    payload.update(overrides)
    return BaseLicense(**payload)


def build_node_locked_license(faker, **overrides) -> NodeLockedLicense:
    """
    Builds a valid `NodeLockedLicense` model that callers can override for targeted validation cases.

    Used by:
        test_node_locked_license_requires_positive_session_limit - creates the baseline payload before invalidating the session limit.
        test_license_file_rejects_non_ed25519_private_key - provides a valid license payload for signature-construction validation.

    Args:
        faker: `Faker` session fixture used to generate metadata and fingerprint values.
        overrides: Field replacements applied on top of the default node-locked payload.

    Returns:
        NodeLockedLicense: A valid node-locked license model unless the caller intentionally overrides a field into an invalid state.
    """
    payload = build_base_license(faker).model_dump()
    payload.update({
        "device_fingerprint": faker.sha256(raw_output=False),
        "session_limit": 1,
    })
    payload.update(overrides)
    return NodeLockedLicense(**payload)


@pytest.mark.unit
def test_base_license_canonical_json_is_sorted(faker) -> None:
    """
    Verifies that `app.domain.license.BaseLicense.canonical_json` sorts keys and matches the model dump serialization.
    This matters because signature generation depends on a stable canonical license representation.

    Covers:
        - `app.domain.license.BaseLicense`
        - `app.domain.license.BaseLicense.canonical_json`

    Rationale:
        The expected JSON is recomputed from the model dump so the canonicalization contract is explicit.

    Fixtures:
        faker: Session-scoped `Faker` instance used to generate metadata values.
    """
    license_model = build_base_license(faker)
    canonical_json = license_model.canonical_json()
    expected_json = json.dumps(
        license_model.model_dump(), sort_keys=True, default=str
    )

    assert canonical_json == expected_json, (
        f"Expected canonical JSON '{expected_json}', got '{canonical_json}'"
    )


@pytest.mark.unit
def test_base_license_rejects_expiry_before_creation(faker) -> None:
    """
    Verifies that `app.domain.license.BaseLicense` rejects payloads whose expiry precedes creation time.
    This matters because licenses with inverted temporal bounds should never be considered valid.

    Covers:
        - `app.domain.license.BaseLicense`

    Rationale:
        The test overrides only the temporal fields of an otherwise valid payload so the validation failure is isolated.

    Fixtures:
        faker: Session-scoped `Faker` instance used to generate a valid baseline payload.
    """
    now = datetime.now().timestamp()
    with pytest.raises(
        ValidationError, match="expiry date cannot be before creation date"
    ):
        build_base_license(faker, created_at=now, expires_at=now - 1)


@pytest.mark.unit
def test_node_locked_license_requires_positive_session_limit(faker) -> None:
    """
    Verifies that `app.domain.license.NodeLockedLicense` rejects non-positive session limits.
    This matters because node-locked licensing uses the session limit as an enforced capacity constraint.

    Covers:
        - `app.domain.license.NodeLockedLicense`

    Rationale:
        The test mutates only the session-limit field of an otherwise valid payload so the model validation rule stays isolated.

    Fixtures:
        faker: Session-scoped `Faker` instance used to generate a valid baseline payload.
    """
    with pytest.raises(ValidationError, match="session_limit"):
        build_node_locked_license(faker, session_limit=0)


@pytest.mark.unit
def test_license_file_rejects_non_ed25519_private_key(faker) -> None:
    """
    Verifies that `app.domain.license.LicenseFile` rejects signature construction with a non-Ed25519 private key.
    This matters because license signing must fail fast when callers provide incompatible key material.

    Covers:
        - `app.domain.license.LicenseFile`

    Rationale:
        A real RSA key is used so the failure documents the public key-type contract rather than a mocked branch.

    Fixtures:
        faker: Session-scoped `Faker` instance used to generate the valid license payload.
    """
    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    rsa_private_key_pem = rsa_key.private_bytes(
        encoding=Encoding.PEM,
        format=PrivateFormat.PKCS8,
        encryption_algorithm=NoEncryption(),
    )

    with pytest.raises(TypeError, match="Ed25519 private key"):
        LicenseFile(
            license_data=build_node_locked_license(faker),
            private_key_pem=rsa_private_key_pem,
        )
