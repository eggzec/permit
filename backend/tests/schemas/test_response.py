import pytest
from fastapi import status
from pydantic import ValidationError

from app.schemas.response import (
    ErrorBodyResponse,
    ErrorCode,
    ErrorDetail,
    ErrorResponse,
)


# ---------------------------------------------------------------------------
# ErrorBodyResponse
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_error_body_response_stores_all_fields(faker):
    """
    Purpose:
        Verifies that `app.schemas.response.ErrorBodyResponse` stores and round-trips all explicitly provided fields.
        This matters because the API error contract depends on the response schema preserving code, message, status, details, and request id exactly.

    Covers:
        - `app.schemas.response.ErrorBodyResponse`

    Rationale:
        The model is exercised directly because the contract under test is pure schema storage and validation behavior.

    Fixtures:
        faker: Session-scoped `Faker` instance used to generate message and request-id values.
    """
    msg = faker.sentence()
    request_id = faker.uuid4()
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
    "scenario",
    [
        pytest.param("missing_http_status", id="missing_http_status"),
        pytest.param("missing_request_id", id="missing_request_id"),
    ],
)
def test_error_body_response_required_field_raises_validation_error(
    faker, scenario: str
):
    """
    Purpose:
        Verifies that `app.schemas.response.ErrorBodyResponse` rejects payloads missing required fields.
        This matters because callers must not be able to construct partial error bodies that break the API response contract.

    Covers:
        - `app.schemas.response.ErrorBodyResponse`

    Rationale:
        The test starts from a complete payload and removes one required field per case so the validation failure stays isolated.

    Fixtures:
        faker: Session-scoped `Faker` instance used to generate message and request-id values.

    Parametrize:
        scenario: Identifies which required field is omitted from the error body payload.
        Cases:
            - <id="missing_http_status"> — omits the HTTP status field.
            - <id="missing_request_id"> — omits the request id field.
    """
    kwargs = {
        "code": ErrorCode.VALIDATION_FAILED,
        "message": faker.sentence(),
        "request_id": faker.uuid4(),
        "http_status": status.HTTP_400_BAD_REQUEST,
    }
    kwargs.pop(
        "http_status" if scenario == "missing_http_status" else "request_id"
    )

    with pytest.raises(ValidationError, match="Field required") as exc_info:
        ErrorBodyResponse(**kwargs)
    error_fields = {e["loc"][0] for e in exc_info.value.errors()}
    expected_missing = {"http_status", "request_id"} - kwargs.keys()
    assert expected_missing & error_fields, (
        f"Expected error for {expected_missing}"
    )


@pytest.mark.unit
def test_error_body_response_details_default_to_empty_list(faker):
    """
    Purpose:
        Verifies that `app.schemas.response.ErrorBodyResponse` defaults `details` to an empty list when the field is omitted.
        This matters because API error responses should not require callers to pass an explicit empty list for no-detail cases.

    Covers:
        - `app.schemas.response.ErrorBodyResponse`

    Rationale:
        The test omits only the details field so the defaulting behavior is the sole contract being exercised.

    Fixtures:
        faker: Session-scoped `Faker` instance used to generate message and request-id values.
    """
    body = ErrorBodyResponse(
        code=ErrorCode.VALIDATION_FAILED,
        message=faker.sentence(),
        http_status=status.HTTP_400_BAD_REQUEST,
        request_id=faker.uuid4(),
    )
    assert body.details == [], (
        f"Expected empty details list by default, got {body.details}"
    )


# ---------------------------------------------------------------------------
# ErrorResponse envelope
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_error_response_envelope_structure(faker):
    """
    Purpose:
        Verifies that `app.schemas.response.ErrorResponse` wraps an `ErrorBodyResponse` under the `error` field.
        This matters because the API emits errors through the envelope shape defined by this response model.

    Covers:
        - `app.schemas.response.ErrorBodyResponse`
        - `app.schemas.response.ErrorResponse`

    Rationale:
        The schema composition is exercised directly because the contract under test is model nesting rather than route behavior.

    Fixtures:
        faker: Session-scoped `Faker` instance used to generate message and request-id values.
    """
    error_response = ErrorResponse(
        error=ErrorBodyResponse(
            code=ErrorCode.VALIDATION_FAILED,
            message=faker.sentence(),
            http_status=status.HTTP_400_BAD_REQUEST,
            request_id=faker.uuid4(),
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
def test_error_detail_requires_message_field(faker):
    """
    Purpose:
        Verifies that `app.schemas.response.ErrorDetail` rejects construction when the required message field is missing.
        This matters because every API error detail must provide a human-readable message.

    Covers:
        - `app.schemas.response.ErrorDetail`

    Rationale:
        The failure is a direct schema validation rule, so a single missing-message case is sufficient.

    Fixtures:
        faker: Session-scoped `Faker` instance used to generate the field name.
    """
    with pytest.raises(ValidationError, match="Field required"):
        ErrorDetail(field=faker.word())


@pytest.mark.unit
def test_error_detail_accepts_field_as_none(faker):
    """
    Purpose:
        Verifies that `app.schemas.response.ErrorDetail` accepts `field=None` and preserves it.
        This matters because some API errors apply to the request body as a whole rather than a specific field.

    Covers:
        - `app.schemas.response.ErrorDetail`

    Rationale:
        The test provides only the optional-field scenario so the schema behavior stays focused on that contract.

    Fixtures:
        faker: Session-scoped `Faker` instance used to generate the detail message.
    """
    msg = faker.sentence()
    detail = ErrorDetail(field=None, message=msg)
    assert detail.field is None, (
        f"Expected field to be None, got {detail.field}"
    )
    assert detail.message == msg, (
        f"Expected message '{msg}', got '{detail.message}'"
    )


@pytest.mark.unit
def test_error_detail_with_both_fields_populated(faker):
    """
    Purpose:
        Verifies that `app.schemas.response.ErrorDetail` stores both `field` and `message` when both are provided.
        This matters because field-specific API validation errors need to preserve both pieces of information.

    Covers:
        - `app.schemas.response.ErrorDetail`

    Rationale:
        This is a direct schema round-trip assertion with no external dependencies or patches.

    Fixtures:
        faker: Session-scoped `Faker` instance used to generate the field name and message.
    """
    field = faker.word()
    msg = faker.sentence()
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
def test_error_body_response_rejects_invalid_error_code(faker):
    """
    Purpose:
        Verifies that `app.schemas.response.ErrorBodyResponse` rejects arbitrary strings for the typed `ErrorCode` field.
        This matters because API error responses must use one of the defined enum codes rather than an uncontrolled string.

    Covers:
        - `app.schemas.response.ErrorBodyResponse`
        - `app.schemas.response.ErrorCode`

    Rationale:
        A single invalid enum string is sufficient because the contract is that non-members fail schema validation.

    Fixtures:
        faker: Session-scoped `Faker` instance used to generate message and request-id values.
    """
    with pytest.raises(ValidationError, match="Input should be"):
        ErrorBodyResponse(
            code="NOT_A_REAL_CODE",
            message=faker.sentence(),
            http_status=status.HTTP_400_BAD_REQUEST,
            request_id=faker.uuid4(),
        )


# ---------------------------------------------------------------------------
# ErrorResponse required fields
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_error_response_requires_error_field():
    """
    Purpose:
        Verifies that `app.schemas.response.ErrorResponse` rejects construction when the required `error` field is omitted.
        This matters because the API error envelope must always contain an error payload rather than an empty shell.

    Covers:
        - `app.schemas.response.ErrorResponse`

    Rationale:
        The missing-field case directly expresses the required-envelope contract with no additional setup.

    Fixtures:
        None.
    """
    with pytest.raises(ValidationError, match="Field required"):
        ErrorResponse()
