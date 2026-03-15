import pytest
from app.internal import base32_crockford

@pytest.mark.unit
@pytest.mark.parametrize(
    "number, expected",
    [
        pytest.param(0, "0", id="zero"),
        pytest.param(1, "1", id="one"),
        pytest.param(31, "Z", id="max-single-char"),
        pytest.param(32, "10", id="base-rollover"),
        pytest.param(1234, "16J", id="large-integer"),
    ],
)
def test_encode_basic(number, expected):
    assert base32_crockford.encode(number) == expected

@pytest.mark.unit
@pytest.mark.parametrize(
    "number, checksum, expected",
    [
        pytest.param(0, True, "00", id="zero-with-checksum"),
        pytest.param(1234, True, "16JD", id="large-integer-with-checksum"),
    ],
)
def test_encode_with_checksum(number, checksum, expected):
    assert base32_crockford.encode(number, checksum=checksum) == expected

@pytest.mark.unit
@pytest.mark.parametrize(
    "number, split_length, expected",
    [
        pytest.param(1234567, 3, "15N-M7", id="split-length-3"),
        pytest.param(1234567, 1, "1-5-N-M-7", id="split-length-1"),
    ],
)
def test_encode_with_split_length(number, split_length, expected):
    assert base32_crockford.encode(number, split_length=split_length) == expected

@pytest.mark.unit
def test_encode_negative_raises():
    with pytest.raises(ValueError, match="is not a positive integer"):
        base32_crockford.encode(-1)

@pytest.mark.unit
def test_encode_negative_split_raises():
    with pytest.raises(ValueError, match="is not a positive integer"):
        base32_crockford.encode(1, split_length=-1)

@pytest.mark.unit
@pytest.mark.parametrize(
    "symbol_string, expected",
    [
        pytest.param("0", 0, id="zero"),
        pytest.param("16J", 1234, id="large-integer"),
        pytest.param("1-6-J", 1234, id="with-hyphens"),
    ],
)
def test_decode_basic(symbol_string, expected):
    assert base32_crockford.decode(symbol_string) == expected

@pytest.mark.unit
@pytest.mark.parametrize(
    "symbol_string, expected",
    [
        pytest.param("00", 0, id="zero-with-checksum"),
        pytest.param("16JD", 1234, id="large-integer-with-checksum"),
    ],
)
def test_decode_with_checksum(symbol_string, expected):
    assert base32_crockford.decode(symbol_string, checksum=True) == expected

@pytest.mark.unit
def test_decode_invalid_checksum_raises():
    with pytest.raises(ValueError, match="invalid check symbol"):
        base32_crockford.decode("16J6", checksum=True)

@pytest.mark.unit
@pytest.mark.parametrize(
    "symbol_string, expected",
    [
        pytest.param("1234-5678", "12345678", id="remove-hyphens"),
        pytest.param("IiLlOo", "111100", id="substitute-i-l-o"),
        pytest.param("abc", "ABC", id="to-uppercase"),
    ],
)
def test_normalize_basic(symbol_string, expected):
    assert base32_crockford.normalize(symbol_string) == expected

@pytest.mark.unit
def test_normalize_strict_raises():
    with pytest.raises(ValueError, match="requires normalization"):
        base32_crockford.normalize("IiLlOo", strict=True)

@pytest.mark.unit
def test_normalize_invalid_chars_raises():
    with pytest.raises(ValueError, match="contains invalid characters"):
        base32_crockford.normalize("U") # U is check-only or invalid depending on context, in normalize it fails regex

@pytest.mark.unit
def test_normalize_non_string_raises():
    with pytest.raises(TypeError, match="string is of invalid type"):
        base32_crockford.normalize(123)
