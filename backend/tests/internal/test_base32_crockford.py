import pytest

from app.internal import base32_crockford


@pytest.mark.unit
@pytest.mark.parametrize(
    "number, expected",
    [
        pytest.param(0, "0", id="zero"),
        pytest.param(1, "1", id="one"),
        pytest.param(31, "Z", id="max_single_char"),
        pytest.param(32, "10", id="base_rollover"),
        pytest.param(1234, "16J", id="large_integer"),
    ],
)
def test_encode_basic(number, expected):
    """
    Purpose:
        Verifies that `app.internal.base32_crockford.encode` returns the expected Crockford representation for basic integer inputs.
        This matters because activation and license code generation depend on deterministic base-32 encoding.

    Covers:
        - `app.internal.base32_crockford.encode`

    Rationale:
        A small parametrized set is enough here because the contract under test is the explicit mapping for representative integers.

    Fixtures:
        None.

    Parametrize:
        number: Integer input to encode.
        expected: Expected Crockford-encoded string.
        Cases:
            - <id="zero"> — the zero value encodes to the single zero symbol.
            - <id="one"> — a single-digit positive integer remains a single symbol.
            - <id="max_single_char"> — the maximum one-symbol value maps to `Z`.
            - <id="base_rollover"> — the first rollover to two symbols is encoded correctly.
            - <id="large_integer"> — a larger multi-symbol number encodes deterministically.
    """
    encoded = base32_crockford.encode(number)
    assert encoded == expected, (
        f"Expected encode({number}) to return '{expected}', got '{encoded}'"
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "number, checksum, expected",
    [
        pytest.param(0, True, "00", id="zero_with_checksum"),
        pytest.param(1234, True, "16JD", id="large_integer_with_checksum"),
    ],
)
def test_encode_with_checksum(number, checksum, expected):
    """
    Purpose:
        Verifies that `app.internal.base32_crockford.encode` appends the expected checksum symbol when checksum mode is enabled.
        This matters because checksum-bearing activation and license codes rely on deterministic check-symbol generation.

    Covers:
        - `app.internal.base32_crockford.encode`

    Rationale:
        The parametrized cases document the public checksum contract directly from representative values.

    Fixtures:
        None.

    Parametrize:
        number: Integer input to encode.
        checksum: Whether checksum mode is enabled.
        expected: Expected encoded output including the checksum symbol.
        Cases:
            - <id="zero_with_checksum"> — zero includes the expected checksum suffix.
            - <id="large_integer_with_checksum"> — a multi-symbol integer includes the expected checksum suffix.
    """
    encoded = base32_crockford.encode(number, checksum=checksum)
    assert encoded == expected, (
        f"Expected encode({number}, checksum={checksum}) to return '{expected}', got '{encoded}'"
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "number, split_length, expected",
    [
        pytest.param(1234567, 3, "15N-M7", id="split_length_3"),
        pytest.param(1234567, 1, "1-5-N-M-7", id="split_length_1"),
    ],
)
def test_encode_with_split_length(number, split_length, expected):
    """
    Purpose:
        Verifies that `app.internal.base32_crockford.encode` inserts hyphen separators at the requested split length.
        This matters because human-facing codes are grouped for readability and must preserve deterministic formatting.

    Covers:
        - `app.internal.base32_crockford.encode`

    Rationale:
        The grouped outputs are asserted directly because separator placement is part of the public formatting contract.

    Fixtures:
        None.

    Parametrize:
        number: Integer input to encode.
        split_length: Group size to insert between separators.
        expected: Expected grouped encoded output.
        Cases:
            - <id="split_length_3"> — groups a multi-symbol output into chunks of three.
            - <id="split_length_1"> — inserts separators between every symbol.
    """
    encoded = base32_crockford.encode(number, split_length=split_length)
    assert encoded == expected, (
        f"Expected encode({number}, split_length={split_length}) to return '{expected}', got '{encoded}'"
    )


@pytest.mark.unit
def test_encode_negative_raises():
    """
    Purpose:
        Verifies that `app.internal.base32_crockford.encode` rejects negative integers.
        This matters because the encoding contract is defined only for non-negative values.

    Covers:
        - `app.internal.base32_crockford.encode`

    Rationale:
        A single negative case is sufficient because the validation rule is not data-dependent beyond sign.

    Fixtures:
        None.
    """
    with pytest.raises(ValueError, match="is not a positive integer"):
        base32_crockford.encode(-1)


@pytest.mark.unit
def test_encode_negative_split_raises():
    """
    Purpose:
        Verifies that `app.internal.base32_crockford.encode` rejects a negative split length.
        This matters because grouping configuration should fail fast when it is not a positive integer.

    Covers:
        - `app.internal.base32_crockford.encode`

    Rationale:
        The split-length validation is a direct input guard and does not require multiple cases here.

    Fixtures:
        None.
    """
    with pytest.raises(ValueError, match="is not a positive integer"):
        base32_crockford.encode(1, split_length=-1)


@pytest.mark.unit
@pytest.mark.parametrize(
    "symbol_string, expected",
    [
        pytest.param("0", 0, id="zero"),
        pytest.param("16J", 1234, id="large_integer"),
        pytest.param("1-6-J", 1234, id="with_hyphens"),
    ],
)
def test_decode_basic(symbol_string, expected):
    """
    Purpose:
        Verifies that `app.internal.base32_crockford.decode` parses basic Crockford strings and grouped input correctly.
        This matters because human-entered codes may include separators while still needing to decode to the same integer.

    Covers:
        - `app.internal.base32_crockford.decode`

    Rationale:
        The parametrized cases cover plain, grouped, and multi-symbol inputs that represent the documented decode boundary.

    Fixtures:
        None.

    Parametrize:
        symbol_string: Input string to decode.
        expected: Expected decoded integer.
        Cases:
            - <id="zero"> — decodes the zero symbol.
            - <id="large_integer"> — decodes a multi-symbol string.
            - <id="with_hyphens"> — ignores grouping separators during decode.
    """
    decoded = base32_crockford.decode(symbol_string)
    assert decoded == expected, (
        f"Expected decode('{symbol_string}') to return {expected}, got {decoded}"
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "symbol_string, expected",
    [
        pytest.param("00", 0, id="zero_with_checksum"),
        pytest.param("16JD", 1234, id="large_integer_with_checksum"),
    ],
)
def test_decode_with_checksum(symbol_string, expected):
    """
    Purpose:
        Verifies that `app.internal.base32_crockford.decode` accepts valid checksum-bearing strings when checksum mode is enabled.
        This matters because checksum-validated codes must round-trip from their public representation.

    Covers:
        - `app.internal.base32_crockford.decode`

    Rationale:
        The test asserts representative checksum-valid inputs directly because the external contract is the accepted string form.

    Fixtures:
        None.

    Parametrize:
        symbol_string: Input string including a checksum symbol.
        expected: Expected decoded integer.
        Cases:
            - <id="zero_with_checksum"> — decodes the minimal checksum-bearing string.
            - <id="large_integer_with_checksum"> — decodes a multi-symbol checksum-bearing string.
    """
    decoded = base32_crockford.decode(symbol_string, checksum=True)
    assert decoded == expected, (
        f"Expected decode('{symbol_string}', checksum=True) to return {expected}, got {decoded}"
    )


@pytest.mark.unit
def test_decode_invalid_checksum_raises():
    """
    Purpose:
        Verifies that `app.internal.base32_crockford.decode` rejects an input whose checksum symbol does not match the payload.
        This matters because checksum validation is the integrity check for human-entered codes.

    Covers:
        - `app.internal.base32_crockford.decode`

    Rationale:
        One invalid checksum case is sufficient because the contract is simply that mismatched checksums fail.

    Fixtures:
        None.
    """
    with pytest.raises(ValueError, match="invalid check symbol"):
        base32_crockford.decode("16J6", checksum=True)


@pytest.mark.unit
@pytest.mark.parametrize(
    "symbol_string, expected",
    [
        pytest.param("1234-5678", "12345678", id="remove_hyphens"),
        pytest.param("IiLlOo", "111100", id="substitute_i_l_o"),
        pytest.param("abc", "ABC", id="to_uppercase"),
    ],
)
def test_normalize_basic(symbol_string, expected):
    """
    Purpose:
        Verifies that `app.internal.base32_crockford.normalize` removes separators, uppercases symbols, and substitutes ambiguous characters.
        This matters because human-entered codes must normalize into the canonical alphabet before decode.

    Covers:
        - `app.internal.base32_crockford.normalize`

    Rationale:
        The cases document the supported normalization behaviors directly from representative inputs.

    Fixtures:
        None.

    Parametrize:
        symbol_string: Raw input string to normalize.
        expected: Expected canonical normalized output.
        Cases:
            - <id="remove_hyphens"> — strips grouping separators.
            - <id="substitute_i_l_o"> — substitutes ambiguous Crockford characters.
            - <id="to_uppercase"> — uppercases alphabetic input.
    """
    normalized = base32_crockford.normalize(symbol_string)
    assert normalized == expected, (
        f"Expected normalize('{symbol_string}') to return '{expected}', got '{normalized}'"
    )


@pytest.mark.unit
def test_normalize_strict_raises():
    """
    Purpose:
        Verifies that `app.internal.base32_crockford.normalize` rejects inputs that would require normalization when strict mode is enabled.
        This matters because strict callers may require already-canonical code strings.

    Covers:
        - `app.internal.base32_crockford.normalize`

    Rationale:
        The chosen input exercises the normalization path that strict mode is meant to forbid.

    Fixtures:
        None.
    """
    with pytest.raises(ValueError, match="requires normalization"):
        base32_crockford.normalize("IiLlOo", strict=True)


@pytest.mark.unit
def test_normalize_invalid_chars_raises():
    """
    Purpose:
        Verifies that `app.internal.base32_crockford.normalize` rejects strings containing invalid characters.
        This matters because invalid symbols should fail before decode and checksum logic consume them.

    Covers:
        - `app.internal.base32_crockford.normalize`

    Rationale:
        A single invalid-character example is sufficient because the rule being exercised is the input alphabet guard.

    Fixtures:
        None.
    """
    with pytest.raises(ValueError, match="contains invalid characters"):
        base32_crockford.normalize(
            "U"
        )  # U is check-only or invalid depending on context, in normalize it fails regex


@pytest.mark.unit
def test_normalize_non_string_raises():
    """
    Purpose:
        Verifies that `app.internal.base32_crockford.normalize` rejects non-string input types.
        This matters because the normalizer contract is defined only for string inputs.

    Covers:
        - `app.internal.base32_crockford.normalize`

    Rationale:
        The non-string guard is a direct type contract with no additional setup needed.

    Fixtures:
        None.
    """
    with pytest.raises(TypeError, match="string is of invalid type"):
        base32_crockford.normalize(123)
