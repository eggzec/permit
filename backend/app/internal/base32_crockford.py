"""
base32-crockford
================

A Python module implementing the alternate base32 encoding as described
by Douglas Crockford at: http://www.crockford.com/wrmg/base32.html.

He designed the encoding to:

   * Be human and machine readable
   * Be compact
   * Be error resistant
   * Be pronounceable

It uses a symbol set of 10 digits and 22 letters, excluding I, L O and
U. Decoding is not case sensitive, and 'i' and 'l' are converted to '1'
and 'o' is converted to '0'. Encoding uses only upper-case characters.

Hyphens may be present in symbol strings to improve readability, and
are removed when decoding.

A check symbol can be appended to a symbol string to detect errors
within the string.

This code is licensed under the BSD-3 clause
Copyright (c) 2015, Jason Bittel <jason.bittel@gmail.com>
Copyright (c) 2026, M Laraib Ali <laraibg786@outlook.com>
"""

import re


__all__ = ["decode", "encode", "normalize"]


# The encoded symbol space does not include I, L, O or U
SYMBOLS = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
# These five symbols are exclusively for checksum values
CHECK_SYMBOLS = "*~$=U"

ENCODE_SYMBOLS = dict(enumerate(SYMBOLS + CHECK_SYMBOLS))
DECODE_SYMBOLS = {ch: i for i, ch in ENCODE_SYMBOLS.items()}
NORMALIZE_MAP = str.maketrans("IiLlOo", "111100")
VALID_SYMBOLS = re.compile(f"^[{SYMBOLS}]+[{re.escape(CHECK_SYMBOLS)}]?$")

BASE = len(SYMBOLS)
CHECK_BASE = len(SYMBOLS + CHECK_SYMBOLS)


def encode(
    number: int | str, *, checksum: bool = False, split_length: int = 0
) -> str:
    """Encode an integer into a symbol string.

    Args:
        - number: Integer value to encode (must be non-negative)
        - checksum: If True, a check symbol will be calculated and appended
        - split_length: If specified, the string will be divided into clusters
        of that size separated by hyphens (0 = no splitting)

    Returns:
        - encoded symbol string

    Raises:
        ValueError: If number is negative or split is negative
    """
    number = int(number)
    if number < 0:
        raise ValueError(f"number {number} is not a positive integer")

    split_length = int(split_length)
    if split_length < 0:
        raise ValueError(f"split {split_length} is not a positive integer")

    check_symbol = ""
    if checksum:
        check_symbol = ENCODE_SYMBOLS[number % CHECK_BASE]

    if number == 0:
        return "0" + check_symbol

    symbol_string = ""
    while number > 0:
        remainder = number % BASE
        number //= BASE
        symbol_string = ENCODE_SYMBOLS[remainder] + symbol_string
    symbol_string += check_symbol

    if split_length:
        chunks = [
            symbol_string[pos : pos + split_length]
            for pos in range(0, len(symbol_string), split_length)
        ]
        symbol_string = "-".join(chunks)

    return symbol_string


def decode(
    symbol_string: str, *, checksum: bool = False, strict: bool = False
) -> int:
    """Decode an encoded symbol string.

    Args:
        - symbol_string: The encoded symbol string to decode
        - checksum: If True, the string is assumed to have a trailing check
        symbol which will be validated
        - strict: If True, raises ValueError if normalization is required

    Returns:
        - decoded integer value

    Raises:
        ValueError: If checksum validation fails, if strict mode is enabled and
        normalization is needed, or if the string contains invalid characters
    """
    symbol_string = normalize(symbol_string, strict=strict)
    check_symbol = None
    if checksum:
        check_symbol = symbol_string[-1]
        symbol_string = symbol_string[:-1]

    number = 0
    for symbol in symbol_string:
        number = number * BASE + DECODE_SYMBOLS[symbol]

    if checksum:
        check_value = DECODE_SYMBOLS[check_symbol]
        modulo = number % CHECK_BASE
        if check_value != modulo:
            raise ValueError(
                f"invalid check symbol '{check_symbol}' for string "
                f"'{symbol_string}{check_symbol}'"
            )

    return number


def normalize(symbol_string: str, *, strict: bool = False) -> str:
    """Normalize an encoded symbol string.

    Normalization provides error correction and prepares the string for
    decoding. These transformations are applied:

       1. Hyphens are removed
       2. 'I', 'i', 'L' or 'l' are converted to '1'
       3. 'O' or 'o' are converted to '0'
       4. All characters are converted to uppercase

    Args:
        - symbol_string: The symbol string to normalize
        - strict: If True, raises ValueError if any transformations are applied

    Returns:
        - normalized symbol string

    Raises:
        TypeError: If an invalid string type is provided
        ValueError: If the normalized string contains invalid characters, or if
        strict mode is enabled and normalization was needed
    """
    if not isinstance(symbol_string, str):
        raise TypeError(
            f"string is of invalid type {symbol_string.__class__.__name__}"
        )

    norm_string = (
        symbol_string.replace("-", "").translate(NORMALIZE_MAP).upper()
    )

    if not VALID_SYMBOLS.match(norm_string):
        raise ValueError(f"string '{norm_string}' contains invalid characters")

    if strict and norm_string != symbol_string:
        raise ValueError(f"string '{symbol_string}' requires normalization")

    return norm_string
