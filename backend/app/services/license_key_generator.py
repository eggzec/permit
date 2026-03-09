"""License key generator — cryptographically random key generation.

Generates license keys in the format ``XXXX-XXXX-XXXX-XXXX`` where each
character is drawn from the uppercase alphanumeric alphabet ``A-Z0-9``
using :mod:`secrets` for cryptographic randomness (~82 bits of entropy
per key).

Supports optional batch metadata and collision detection with bounded
retries.
"""

from __future__ import annotations

import logging
import re
import secrets
import string
from dataclasses import dataclass, field

from app.core.exceptions import LicenseKeyGenerationError


logger = logging.getLogger(__name__)

ALPHABET: str = string.ascii_uppercase + string.digits
"""Uppercase alphanumeric character set used for key generation."""

SEGMENT_LENGTH: int = 4
"""Number of characters per key segment."""

NUM_SEGMENTS: int = 4
"""Number of segments in a license key."""

MAX_RETRIES: int = 10
"""Maximum collision-retry attempts before raising an error."""

LICENSE_KEY_PATTERN: re.Pattern[str] = re.compile(
    r"^[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$"
)
"""Compiled regex that every generated key must match."""


@dataclass(frozen=True, slots=True)
class BatchMetadata:
    """Optional metadata attached to a batch of generated license keys.

    Attributes:
        batch_id: Identifier grouping keys that belong to the same
            issuance batch.
        campaign: Marketing or distribution campaign associated with
            the batch.
        issued_by: Identifier (user-id, email, or service name) of the
            entity that triggered key generation.
    """

    batch_id: str | None = None
    campaign: str | None = None
    issued_by: str | None = None


@dataclass(slots=True)
class GeneratedLicenseKey:
    """Container for a generated license key and its batch metadata.

    Attributes:
        key: The formatted license key string
            (e.g. ``"A1B2-C3D4-E5F6-G7H8"``).
        metadata: Optional :class:`BatchMetadata` associated with the
            key.
    """

    key: str
    metadata: BatchMetadata = field(default_factory=BatchMetadata)


def _generate_segment() -> str:
    """Generate a single random segment of :data:`SEGMENT_LENGTH` characters.

    Returns:
        str: A string of ``SEGMENT_LENGTH`` uppercase-alphanumeric
            characters chosen via :func:`secrets.choice`.
    """
    return "".join(secrets.choice(ALPHABET) for _ in range(SEGMENT_LENGTH))


def _generate_raw_key() -> str:
    """Generate a raw license key with hyphen-separated segments.

    Returns:
        str: A key in ``XXXX-XXXX-XXXX-XXXX`` format.
    """
    return "-".join(_generate_segment() for _ in range(NUM_SEGMENTS))


def generate_license_key(
    existing_keys: set[str] | None = None, metadata: BatchMetadata | None = None
) -> GeneratedLicenseKey:
    """Generate a single unique license key with collision detection.

    Attempts up to :data:`MAX_RETRIES` times to produce a key that does
    not collide with *existing_keys*.  Each generated key is validated
    against :data:`LICENSE_KEY_PATTERN` before the collision check.

    Args:
        existing_keys: A set of previously issued keys used for
            collision detection.  Pass ``None`` or an empty set when
            uniqueness checking is not required.
        metadata: Optional :class:`BatchMetadata` to attach to the
            returned result.

    Returns:
        GeneratedLicenseKey: The generated key together with its
            metadata.

    Raises:
        LicenseKeyGenerationError: If a unique key cannot be produced
            within :data:`MAX_RETRIES` attempts.
    """
    if existing_keys is None:
        existing_keys = set()

    effective_metadata = metadata or BatchMetadata()

    for attempt in range(1, MAX_RETRIES + 1):
        key = _generate_raw_key()

        if not LICENSE_KEY_PATTERN.match(key):
            logger.warning(
                "Generated key failed format validation on attempt %d", attempt
            )
            continue

        if key not in existing_keys:
            logger.debug(
                "License key generated on attempt %d (batch_id=%s)",
                attempt,
                effective_metadata.batch_id,
            )
            return GeneratedLicenseKey(key=key, metadata=effective_metadata)

        logger.warning(
            "Collision detected on attempt %d/%d", attempt, MAX_RETRIES
        )

    raise LicenseKeyGenerationError(
        f"Could not generate a unique license key after {MAX_RETRIES} retries"
    )


def generate_license_keys_batch(
    count: int,
    existing_keys: set[str] | None = None,
    metadata: BatchMetadata | None = None,
) -> list[GeneratedLicenseKey]:
    """Generate a batch of unique license keys.

    Each key in the batch is guaranteed to be unique against both the
    provided *existing_keys* and all previously generated keys within
    the same batch invocation.

    Args:
        count: Number of keys to generate.  Must be >= 1.
        existing_keys: A set of previously issued keys used for
            collision detection.  Pass ``None`` or an empty set when
            external uniqueness checking is not required.
        metadata: Optional :class:`BatchMetadata` to attach to every
            key in the batch.

    Returns:
        list[GeneratedLicenseKey]: A list of *count* unique keys, each
            carrying the supplied metadata.

    Raises:
        ValueError: If *count* is less than 1.
    """
    if count < 1:
        raise ValueError("count must be >= 1")

    if existing_keys is None:
        existing_keys = set()

    combined_keys: set[str] = set(existing_keys)
    results: list[GeneratedLicenseKey] = []

    for i in range(count):
        generated = generate_license_key(
            existing_keys=combined_keys, metadata=metadata
        )
        combined_keys.add(generated.key)
        results.append(generated)
        logger.debug(
            "Batch key %d/%d generated: %s", i + 1, count, generated.key
        )

    return results
