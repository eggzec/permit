"""Unit tests for the license key generator module.

Tests cover:
- Single key format validation against the required pattern.
- Cryptographic randomness (keys are non-deterministic).
- Batch generation with intra-batch uniqueness guarantees.
- Collision detection and bounded retry behaviour.
- LicenseKeyGenerationError raised after retry exhaustion.
- BatchMetadata attachment and propagation.
- Edge cases: count validation, empty/None existing-key sets.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.core.exceptions import LicenseKeyGenerationError
from app.schemas.response import ErrorCode
from app.services.license_key_generator import (
    ALPHABET,
    LICENSE_KEY_PATTERN,
    MAX_RETRIES,
    BatchMetadata,
    GeneratedLicenseKey,
    generate_license_key,
    generate_license_keys_batch,
)


@pytest.mark.unit
class TestLicenseKeyFormat:
    """Verify generated keys match the ``XXXX-XXXX-XXXX-XXXX`` pattern."""

    def test_single_key_matches_pattern(self):
        result = generate_license_key()
        assert LICENSE_KEY_PATTERN.match(result.key), (
            f"Key {result.key!r} does not match the required pattern"
        )

    def test_key_length_is_19_characters(self):
        result = generate_license_key()
        assert len(result.key) == 19

    def test_key_has_four_segments(self):
        result = generate_license_key()
        segments = result.key.split("-")
        assert len(segments) == 4

    def test_each_segment_has_four_characters(self):
        result = generate_license_key()
        for segment in result.key.split("-"):
            assert len(segment) == 4

    def test_key_uses_only_uppercase_alphanumeric(self):
        result = generate_license_key()
        raw = result.key.replace("-", "")
        assert all(c in ALPHABET for c in raw)

    def test_multiple_keys_all_match_pattern(self):
        for _ in range(50):
            result = generate_license_key()
            assert LICENSE_KEY_PATTERN.match(result.key)


@pytest.mark.unit
class TestKeyUniqueness:
    """Verify keys are unique across invocations."""

    def test_generated_keys_are_unique(self):
        keys = {generate_license_key().key for _ in range(100)}
        assert len(keys) == 100

    def test_collision_with_existing_keys_triggers_retry(self):
        first = generate_license_key()
        existing = {first.key}
        second = generate_license_key(existing_keys=existing)
        assert second.key != first.key
        assert second.key not in existing


@pytest.mark.unit
class TestCollisionRetryExhaustion:
    """Verify LicenseKeyGenerationError is raised when retries are exhausted."""

    def test_raises_after_max_retries(self):
        colliding_key = "AAAA-BBBB-CCCC-DDDD"
        existing = {colliding_key}

        with patch(
            "app.services.license_key_generator._generate_raw_key",
            return_value=colliding_key,
        ):
            with pytest.raises(LicenseKeyGenerationError) as exc_info:
                generate_license_key(existing_keys=existing)

            assert str(MAX_RETRIES) in str(exc_info.value)

    def test_error_has_correct_error_code(self):
        colliding_key = "XXXX-YYYY-ZZZZ-1234"
        existing = {colliding_key}

        with patch(
            "app.services.license_key_generator._generate_raw_key",
            return_value=colliding_key,
        ):
            with pytest.raises(LicenseKeyGenerationError) as exc_info:
                generate_license_key(existing_keys=existing)

            assert (
                exc_info.value.error_code
                == ErrorCode.LICENSE_KEY_GENERATION_ERROR
            )

    def test_error_has_500_status(self):
        colliding_key = "AAAA-BBBB-CCCC-DDDD"
        existing = {colliding_key}

        with patch(
            "app.services.license_key_generator._generate_raw_key",
            return_value=colliding_key,
        ):
            with pytest.raises(LicenseKeyGenerationError) as exc_info:
                generate_license_key(existing_keys=existing)

            assert exc_info.value.http_status == 500

    def test_succeeds_on_last_retry(self):
        colliding_key = "AAAA-BBBB-CCCC-DDDD"
        unique_key = "ZZZZ-9999-YYYY-8888"
        existing = {colliding_key}

        side_effects = [colliding_key] * (MAX_RETRIES - 1) + [unique_key]

        with patch(
            "app.services.license_key_generator._generate_raw_key",
            side_effect=side_effects,
        ):
            result = generate_license_key(existing_keys=existing)
            assert result.key == unique_key


@pytest.mark.unit
class TestBatchMetadata:
    """Verify batch metadata is correctly attached to generated keys."""

    def test_default_metadata_is_empty(self):
        result = generate_license_key()
        assert result.metadata.batch_id is None
        assert result.metadata.campaign is None
        assert result.metadata.issued_by is None

    def test_metadata_attached_to_single_key(self):
        meta = BatchMetadata(
            batch_id="batch-001",
            campaign="summer-sale",
            issued_by="admin@example.com",
        )
        result = generate_license_key(metadata=meta)

        assert result.metadata.batch_id == "batch-001"
        assert result.metadata.campaign == "summer-sale"
        assert result.metadata.issued_by == "admin@example.com"

    def test_metadata_propagated_in_batch(self):
        meta = BatchMetadata(
            batch_id="batch-002", campaign="launch", issued_by="system"
        )
        results = generate_license_keys_batch(count=5, metadata=meta)

        for result in results:
            assert result.metadata.batch_id == "batch-002"
            assert result.metadata.campaign == "launch"
            assert result.metadata.issued_by == "system"

    def test_partial_metadata(self):
        meta = BatchMetadata(batch_id="batch-003")
        result = generate_license_key(metadata=meta)

        assert result.metadata.batch_id == "batch-003"
        assert result.metadata.campaign is None
        assert result.metadata.issued_by is None

    def test_metadata_is_frozen(self):
        meta = BatchMetadata(batch_id="batch-004")
        with pytest.raises(AttributeError):
            meta.batch_id = "modified"  # type: ignore[misc]


@pytest.mark.unit
class TestBatchGeneration:
    """Verify batch generation produces correct counts and unique keys."""

    def test_batch_returns_correct_count(self):
        results = generate_license_keys_batch(count=10)
        assert len(results) == 10

    def test_batch_keys_are_unique(self):
        results = generate_license_keys_batch(count=50)
        keys = [r.key for r in results]
        assert len(set(keys)) == 50

    def test_batch_keys_all_match_pattern(self):
        results = generate_license_keys_batch(count=20)
        for result in results:
            assert LICENSE_KEY_PATTERN.match(result.key)

    def test_batch_excludes_existing_keys(self):
        existing = {"AAAA-BBBB-CCCC-DDDD", "EEEE-FFFF-0000-1111"}
        results = generate_license_keys_batch(count=5, existing_keys=existing)

        for result in results:
            assert result.key not in existing

    def test_batch_count_zero_raises_value_error(self):
        with pytest.raises(ValueError, match="count must be >= 1"):
            generate_license_keys_batch(count=0)

    def test_batch_count_negative_raises_value_error(self):
        with pytest.raises(ValueError, match="count must be >= 1"):
            generate_license_keys_batch(count=-1)

    def test_batch_single_item(self):
        results = generate_license_keys_batch(count=1)
        assert len(results) == 1
        assert LICENSE_KEY_PATTERN.match(results[0].key)


@pytest.mark.unit
class TestExistingKeysHandling:
    """Verify edge cases around the existing_keys parameter."""

    def test_none_existing_keys_accepted(self):
        result = generate_license_key(existing_keys=None)
        assert LICENSE_KEY_PATTERN.match(result.key)

    def test_empty_set_existing_keys_accepted(self):
        result = generate_license_key(existing_keys=set())
        assert LICENSE_KEY_PATTERN.match(result.key)

    def test_batch_with_none_existing_keys(self):
        results = generate_license_keys_batch(count=3, existing_keys=None)
        assert len(results) == 3


@pytest.mark.unit
class TestGeneratedLicenseKeyDataclass:
    """Verify the GeneratedLicenseKey container behaves correctly."""

    def test_key_is_accessible(self):
        result = generate_license_key()
        assert isinstance(result.key, str)

    def test_metadata_is_accessible(self):
        result = generate_license_key()
        assert isinstance(result.metadata, BatchMetadata)

    def test_return_type(self):
        result = generate_license_key()
        assert isinstance(result, GeneratedLicenseKey)


@pytest.mark.unit
class TestLicenseKeyPattern:
    """Verify the LICENSE_KEY_PATTERN regex itself."""

    @pytest.mark.parametrize(
        "key",
        [
            pytest.param("ABCD-EFGH-1234-5678", id="valid_mixed"),
            pytest.param("AAAA-BBBB-CCCC-DDDD", id="valid_all_alpha"),
            pytest.param("1111-2222-3333-4444", id="valid_all_numeric"),
            pytest.param("A1B2-C3D4-E5F6-G7H8", id="valid_alternating"),
        ],
    )
    def test_valid_keys_match(self, key):
        assert LICENSE_KEY_PATTERN.match(key)

    @pytest.mark.parametrize(
        "key",
        [
            pytest.param("abcd-efgh-1234-5678", id="lowercase_rejected"),
            pytest.param("ABCD-EFGH-1234", id="three_segments_rejected"),
            pytest.param(
                "ABCDE-FGHI-1234-5678", id="five_char_segment_rejected"
            ),
            pytest.param("ABCD EFGH 1234 5678", id="spaces_rejected"),
            pytest.param("ABCD-EFGH-1234-567!", id="special_char_rejected"),
            pytest.param("", id="empty_string_rejected"),
            pytest.param(
                "ABCD-EFGH-1234-5678-9ABC", id="five_segments_rejected"
            ),
        ],
    )
    def test_invalid_keys_rejected(self, key):
        assert LICENSE_KEY_PATTERN.match(key) is None
