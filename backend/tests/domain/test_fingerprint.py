import hashlib
import json

import pytest

from app.domain.fingerprint import Device


def _make_device(**overrides) -> Device:
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
    device = _make_device()
    payload = json.dumps(
        device.model_dump(exclude_computed_fields=True), sort_keys=True
    )
    expected = f"sha256:{hashlib.sha256(payload.encode()).hexdigest()}"

    assert device.fingerprint == expected, (
        "Device.fingerprint must be sha256 of sorted JSON over raw identifiers"
    )


@pytest.mark.unit
def test_device_fingerprint_is_cached_on_repeated_access():
    device = _make_device()
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
    device_a = _make_device(primary_disk_serial="disk-1")
    device_b = _make_device(primary_disk_serial="disk-2")

    assert device_a.fingerprint != device_b.fingerprint, (
        "Fingerprint must change when any hardware identifier changes"
    )
