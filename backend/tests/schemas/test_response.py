import pytest
from faker import Faker
from fastapi import status
from pydantic import ValidationError
from uuid6 import uuid7

from app.schemas.response import (
    ErrorBodyResponse,
    ErrorCode,
    ErrorDetail,
    ErrorResponse,
)


fake = Faker()


# ---------------------------------------------------------------------------
# ErrorBodyResponse
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_error_body_response_stores_all_fields():
    """ErrorBodyResponse must accept and round-trip all fields."""
    msg = fake.sentence()
    request_id = str(uuid7())
    error_body = ErrorBodyResponse(
        code=ErrorCode.VALIDATION_FAILED,
        message=msg,
        http_status=status.HTTP_400_BAD_REQUEST,
        details=[],
        request_id=request_id,
    )
    assert error_body.code == ErrorCode.VALIDATION_FAILED, (
        f"Expected code VALIDATION_FAILED, got {error_body.code}"
    )
    assert error_body.message == msg, (
        f"Expected message '{msg}', got '{error_body.message}'"
    )
    assert error_body.http_status == status.HTTP_400_BAD_REQUEST, (
        f"Expected http_status 400, got {error_body.http_status}"
    )
    assert error_body.details == [], (
        f"Expected empty details, got {error_body.details}"
    )
    assert error_body.request_id == request_id, (
        f"Expected request_id '{request_id}', got '{error_body.request_id}'"
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "kwargs",
    [
        pytest.param(
            dict(
                code=ErrorCode.VALIDATION_FAILED,
                message="Test message",
                request_id="req-123",
            ),
            id="missing_http_status",
        ),
        pytest.param(
            dict(
                code=ErrorCode.VALIDATION_FAILED,
                message="Test message",
                http_status=status.HTTP_400_BAD_REQUEST,
            ),
            id="missing_request_id",
        ),
    ],
)
def test_error_body_response_required_field_raises_validation_error(kwargs):
    """Omitting a required field must raise ValidationError."""
    # We keep static messages in parametrize for simplicity
    with pytest.raises(ValidationError) as exc_info:
        ErrorBodyResponse(**kwargs)
    # Optionally verify the missing field is in the error
    error_fields = {e["loc"][0] for e in exc_info.value.errors()}
    expected_missing = {"http_status", "request_id"} - kwargs.keys()
    assert expected_missing & error_fields, (
        f"Expected error for {expected_missing}"
    )


@pytest.mark.unit
def test_error_body_response_details_default_to_empty_list():
    """Omitting details when constructing ErrorBodyResponse must yield []."""
    body = ErrorBodyResponse(
        code=ErrorCode.VALIDATION_FAILED,
        message=fake.sentence(),
        http_status=status.HTTP_400_BAD_REQUEST,
        request_id=str(uuid7()),
    )
    assert body.details == [], (
        f"Expected empty details list by default, got {body.details}"
    )


# ---------------------------------------------------------------------------
# ErrorResponse envelope
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_error_response_envelope_structure():
    """ErrorResponse must wrap an ErrorBodyResponse in the error field."""
    error_response = ErrorResponse(
        error=ErrorBodyResponse(
            code=ErrorCode.VALIDATION_FAILED,
            message=fake.sentence(),
            http_status=status.HTTP_400_BAD_REQUEST,
            request_id=str(uuid7()),
        )
    )
    assert isinstance(error_response.error, ErrorBodyResponse), (
        "Expected error field to be ErrorBodyResponse,"
        f" got {type(error_response.error)}"
    )
    assert error_response.error.http_status == status.HTTP_400_BAD_REQUEST, (
        "Expected wrapped error http_status 400,"
        f" got {error_response.error.http_status}"
    )


# ---------------------------------------------------------------------------
# ErrorDetail
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_error_detail_requires_message_field():
    """ErrorDetail without message must raise ValidationError."""
    with pytest.raises(ValidationError):
        ErrorDetail(field=fake.word())  # missing required 'message'


@pytest.mark.unit
def test_error_detail_accepts_field_as_none():
    """ErrorDetail.field is optional — None must be stored as-is."""
    msg = fake.sentence()
    detail = ErrorDetail(field=None, message=msg)
    assert detail.field is None, (
        f"Expected field to be None, got {detail.field}"
    )
    assert detail.message == msg, (
        f"Expected message '{msg}', got '{detail.message}'"
    )


@pytest.mark.unit
def test_error_detail_with_both_fields_populated():
    """ErrorDetail must store both field and message when both are provided."""
    field = fake.word()
    msg = fake.sentence()
    detail = ErrorDetail(field=field, message=msg)
    assert detail.field == field, (
        f"Expected field '{field}', got '{detail.field}'"
    )
    assert detail.message == msg, (
        f"Expected message '{msg}', got '{detail.message}'"
    )


# ---------------------------------------------------------------------------
# ErrorCode enum enforcement
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_error_body_response_rejects_invalid_error_code():
    """ErrorBodyResponse.code is typed as ErrorCode; an arbitrary string that is
    not a valid enum member must be rejected with a ValidationError."""
    with pytest.raises(ValidationError):
        ErrorBodyResponse(
            code="NOT_A_REAL_CODE",
            message=fake.sentence(),
            http_status=status.HTTP_400_BAD_REQUEST,
            request_id=str(uuid7()),
        )


# ---------------------------------------------------------------------------
# ErrorResponse required fields
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_error_response_requires_error_field():
    """ErrorResponse.error is required. Omitting it must
    raise a ValidationError rather than silently
    constructing an empty envelope.
    """
    with pytest.raises(ValidationError):
        ErrorResponse()
