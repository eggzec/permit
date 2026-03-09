import uuid

import pytest
import uuid6

from app.domain.activation import ActivationCode


@pytest.mark.unit
def test_activation_code_generate_round_trips_uuid7():
    """
    Verifies that `app.domain.activation.ActivationCode.generate` preserves a
    supplied UUIDv7 and emits a grouped 30-symbol activation code. This matters
    because activation codes are a public representation of the underlying UUIDv7 identity.

    Covers:
        - `app.domain.activation.ActivationCode.generate`
        - `app.domain.activation.ActivationCode.uuid`

    Rationale:
        The test uses a real UUIDv7 because the contract is the round trip between the UUID and generated activation code.

    Fixtures:
        None.
    """
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
    """
    Verifies that `app.domain.activation.ActivationCode.generate` creates a UUIDv7 when no source UUID is supplied.
    This matters because callers rely on the helper to create new activation identities as well as encode existing ones.

    Covers:
        - `app.domain.activation.ActivationCode.generate`

    Rationale:
        The test asserts only the UUID version because that is the externally meaningful contract of the generated identifier.

    Fixtures:
        None.
    """
    generated = ActivationCode.generate()
    assert generated.uuid.version == 7, (
        "ActivationCode.generate() must create a UUIDv7 when no UUID is passed"
    )


@pytest.mark.unit
def test_activation_code_rejects_invalid_length():
    """
    Verifies that `app.domain.activation.ActivationCode` rejects code strings that do not contain the required 30 symbols.
    This matters because malformed activation codes should fail validation before decode logic runs.

    Covers:
        - `app.domain.activation.ActivationCode`

    Rationale:
        The failure is a direct model-construction contract, so a single invalid length case is sufficient.

    Fixtures:
        None.
    """
    with pytest.raises(ValueError, match="30 symbols"):
        ActivationCode(code="0" * 29)


@pytest.mark.unit
def test_activation_code_normalizes_input_format():
    """
    Verifies that `app.domain.activation.ActivationCode` normalizes lowercase compact input into the canonical grouped format.
    This matters because user-supplied activation codes may omit separators or use lowercase letters.

    Covers:
        - `app.domain.activation.ActivationCode`
        - `app.domain.activation.ActivationCode.uuid`

    Rationale:
        The test compares normalized input against a canonical generated code so the normalization contract is explicit.

    Fixtures:
        None.
    """
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
    """
    Verifies that `app.domain.activation.ActivationCode.generate` rejects non-UUID input types.
    This matters because callers should get a clear error instead of silent coercion when the API is misused.

    Covers:
        - `app.domain.activation.ActivationCode.generate`

    Rationale:
        This is a direct type-guard test with no fixtures or patches.

    Fixtures:
        None.
    """
    with pytest.raises(TypeError, match="uuid cannot be of type"):
        ActivationCode.generate("not-a-uuid")


@pytest.mark.unit
def test_activation_code_generate_rejects_non_v7_uuid():
    """
    Verifies that `app.domain.activation.ActivationCode.generate` rejects UUID values that are not version 7.
    This matters because the activation-code encoding contract is defined only for UUIDv7 inputs.

    Covers:
        - `app.domain.activation.ActivationCode.generate`

    Rationale:
        A UUIDv4 input is enough to prove the version guard on non-v7 identifiers.

    Fixtures:
        None.
    """
    with pytest.raises(TypeError, match="UUID version 7"):
        ActivationCode.generate(uuid.uuid4())
