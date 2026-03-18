import hashlib
import json

import pytest

from app.domain.fingerprint import Device


def make_device(**overrides) -> Device:
    """
    Builds a `Device` model with stable test identifiers that can be selectively overridden.

    Used by:
        test_device_fingerprint_matches_sha256_of_sorted_json_payload - creates the baseline device used for canonical hashing.
        test_device_fingerprint_is_cached_on_repeated_access - creates the device whose computed fingerprint is read twice.
        test_device_fingerprint_changes_when_hardware_identity_changes - creates the two devices that differ by one hardware identifier.

    Args:
        overrides: Field replacements applied on top of the default hardware identifier set.

    Returns:
        Device: A `Device` instance with deterministic identifiers unless overridden by the caller.
    """
    data = {
        "cpu_id": "cpu-1",
        "motherboard_id": "mb-1",
        "motherboard_serial": "mb-serial-1",
        "machine_id": "machine-1",
        "primary_disk_serial": "disk-1",
    }
    data.update(overrides)
    return Device(**data)


@pytest.mark.unit
def test_device_fingerprint_matches_sha256_of_sorted_json_payload():
    """
    Purpose:
        Verifies that `app.domain.fingerprint.Device.fingerprint` is the SHA-256 digest of the sorted JSON payload of raw identifiers.
        This matters because license node-locking depends on a stable, deterministic device fingerprint contract.

    Covers:
        - `app.domain.fingerprint.Device`
        - `app.domain.fingerprint.Device.fingerprint`

    Rationale:
        The test recomputes the digest from the model dump so the fingerprint contract is explicit and independent of implementation shortcuts.

    Fixtures:
        None.
    """
    device = make_device()
    payload = json.dumps(
        device.model_dump(exclude_computed_fields=True), sort_keys=True
    )
    expected = f"sha256:{hashlib.sha256(payload.encode()).hexdigest()}"

    assert device.fingerprint == expected, (
        "Device.fingerprint must be sha256 of sorted JSON over raw identifiers"
    )


@pytest.mark.unit
def test_device_fingerprint_is_cached_on_repeated_access():
    """
    Purpose:
        Verifies that `app.domain.fingerprint.Device.fingerprint` remains stable and is cached across repeated access.
        This matters because repeated fingerprint reads should not recompute or drift within the same device instance.

    Covers:
        - `app.domain.fingerprint.Device.fingerprint`

    Rationale:
        The identity assertion documents the current cached-property behavior that the tests actually rely on.

    Fixtures:
        None.
    """
    device = make_device()
    first = device.fingerprint
    second = device.fingerprint

    assert first == second, (
        "Device.fingerprint must remain stable across repeated access"
    )
    assert first is second, (
        "Device.fingerprint should be served from cached_property on re-access"
    )


@pytest.mark.unit
def test_device_fingerprint_changes_when_hardware_identity_changes():
    """
    Purpose:
        Verifies that changing a hardware identifier changes `app.domain.fingerprint.Device.fingerprint`.
        This matters because node-locking must distinguish devices when any hardware identity input changes.

    Covers:
        - `app.domain.fingerprint.Device.fingerprint`

    Rationale:
        The test varies only one identifier so the fingerprint change is attributable to a single hardware field.

    Fixtures:
        None.
    """
    device_a = make_device(primary_disk_serial="disk-1")
    device_b = make_device(primary_disk_serial="disk-2")

    assert device_a.fingerprint != device_b.fingerprint, (
        "Fingerprint must change when any hardware identifier changes"
    )
