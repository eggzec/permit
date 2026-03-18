import uuid

import pytest
import uuid6

from app.domain.activation import ActivationCode


@pytest.mark.unit
def test_activation_code_generate_round_trips_uuid7():
    original = uuid6.uuid7()
    generated = ActivationCode.generate(original)

    assert generated.uuid == original, (
        "ActivationCode.generate must preserve the original UUID value"
    )
    assert generated.code.count("-") == 5, (
        "Generated activation code must contain six 5-char groups"
    )
    assert len(generated.code.replace("-", "")) == ActivationCode.LENGTH, (
        "Generated activation code must contain exactly 30 symbols"
    )


@pytest.mark.unit
def test_activation_code_generate_without_uuid_creates_uuid7():
    generated = ActivationCode.generate()
    assert generated.uuid.version == 7, (
        "ActivationCode.generate() must create a UUIDv7 when no UUID is passed"
    )


@pytest.mark.unit
def test_activation_code_rejects_invalid_length():
    with pytest.raises(ValueError, match="30 symbols"):
        ActivationCode(code="0" * 29)


@pytest.mark.unit
def test_activation_code_normalizes_input_format():
    original = uuid6.uuid7()
    canonical = ActivationCode.generate(original)
    compact = canonical.code.replace("-", "").lower()

    normalized = ActivationCode(code=compact)
    assert normalized.code == canonical.code, (
        "ActivationCode must normalize lowercase compact input to grouped format"
    )
    assert normalized.uuid == original, (
        "ActivationCode uuid property must decode normalized code correctly"
    )


@pytest.mark.unit
def test_activation_code_generate_rejects_non_uuid_input():
    with pytest.raises(TypeError, match="uuid cannot be of type"):
        ActivationCode.generate("not-a-uuid")


@pytest.mark.unit
def test_activation_code_generate_rejects_non_v7_uuid():
    with pytest.raises(TypeError, match="UUID version 7"):
        ActivationCode.generate(uuid.uuid4())
