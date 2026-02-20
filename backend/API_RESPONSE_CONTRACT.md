# API Response Contract Documentation

## Overview

This document describes the standardized API response contract for the permit backend, ensuring consistency across all success and error scenarios.

---

## Success Response

### Structure

```json
{
  "data": {
    "field1": "value1",
    "field2": "value2"
  }
}
```

### Description

- **`data`** (required): Contains the actual response payload. This can be any JSON-serializable object.

### Example

```json
{
  "data": {
    "status": "ok",
    "timestamp": "2026-02-20T10:30:45.123Z"
  }
}
```

---

## Error Response

### Structure

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable error message",
    "http_status": 400,
    "details": [
      {
        "field": "field_name",
        "message": "Field-specific error"
      }
    ],
    "request_id": "unique-request-identifier"
  }
}
```

### Field Descriptions

- **`code`** (required, string): Standardized error code (see catalog below)
- **`message`** (required, string): Human-readable error message
- **`http_status`** (required, int): HTTP status code matching the response
- **`details`** (optional, array): Additional error details, useful for validation errors
  - **`field`** (optional, string): Field name for validation errors
  - **`message`** (string): Detailed error message
- **`request_id`** (required, string): Unique request identifier for tracing and debugging

### Example

```json
{
  "error": {
    "code": "VALIDATION_FAILED",
    "message": "Invalid request parameters",
    "http_status": 422,
    "details": [
      {
        "field": "email",
        "message": "Invalid email format"
      },
      {
        "field": "age",
        "message": "Must be a positive integer"
      }
    ],
    "request_id": "req-a1b2c3d4e5f6g7h8"
  }
}
```

---

## Error Code Catalog

### Validation Errors (HTTP 400 / 422)

| Code | HTTP Status | Description |
|------|-------------|-------------|
| `VALIDATION_FAILED` | 422 | Pydantic validation error or invalid request format |
| `INVALID_REQUEST` | 400 | General invalid request error |

### Authentication & Authorization (HTTP 401 / 403)

| Code | HTTP Status | Description |
|------|-------------|-------------|
| `AUTH_INVALID` | 401 | Invalid credentials or authentication token |
| `AUTH_REQUIRED` | 401 | Authentication credentials are missing |
| `FORBIDDEN` | 403 | User lacks permission to access the resource |

### Resource Errors (HTTP 404 / 409)

| Code | HTTP Status | Description |
|------|-------------|-------------|
| `RESOURCE_NOT_FOUND` | 404 | Requested resource does not exist |
| `RESOURCE_ALREADY_EXISTS` | 409 | Resource already exists (conflict) |
| `RESOURCE_CONFLICT` | 409 | Operation conflicts with existing data |

### Business Logic Errors (HTTP 422)

| Code | HTTP Status | Description |
|------|-------------|-------------|
| `BUSINESS_LOGIC_ERROR` | 422 | Business rule violation |
| `INVALID_STATE` | 422 | Resource is in an invalid state for the operation |

### Server Errors (HTTP 500 / 503)

| Code | HTTP Status | Description |
|------|-------------|-------------|
| `INTERNAL_SERVER_ERROR` | 500 | Unexpected server error (with full traceback logged server-side) |
| `SERVICE_UNAVAILABLE` | 503 | Service temporarily unavailable |

---

## Request ID Tracing

Every request generates or accepts a unique `request_id`:

- **Auto-generated**: If no `X-Request-ID` header is provided, a UUID is generated
- **Custom**: Pass `X-Request-ID` header in the request to track requests
- **Returned**: The response includes `X-Request-ID` header for easy correlation
- **Logged**: All errors include the `request_id` in both the response and server-side logs

### Example Request/Response with Request ID

**Request:**
```
GET /api/v1/health
X-Request-ID: my-custom-request-123
```

**Response:**
```
HTTP/1.1 200 OK
X-Request-ID: my-custom-request-123

{
  "data": {
    "status": "ok",
    "timestamp": "2026-02-20T10:30:45.123Z"
  }
}
```

---

## Exception Handling Strategy

### Server-Side Logging

All errors are logged on the server with:
- Full exception tracebacks
- Request ID for correlation
- Additional context (field names, error details)

### Client-Side Response

Clients receive:
- Standardized error structure (never raw stack traces)
- Actionable error messages
- Request ID for support/debugging reference
- HTTP status code matching the error context

### Error Mapping

The FastAPI exception handlers map the following to the contract:

1. **Custom `APIException`** → Uses configured error code and HTTP status
2. **Pydantic `ValidationError`** → `VALIDATION_FAILED` (422)
3. **Unhandled `Exception`** → `INTERNAL_SERVER_ERROR` (500)

---

## Usage Examples

### Success Response

**Endpoint:** `GET /api/v1/health`

**Response (200 OK):**
```json
{
  "data": {
    "status": "ok",
    "timestamp": "2026-02-20T10:30:45.123Z"
  }
}
```

### Validation Error

**Endpoint:** `POST /api/v1/login`

**Request (invalid):**
```json
{
  "username": "",
  "password": ""
}
```

**Response (422 Unprocessable Entity):**
```json
{
  "error": {
    "code": "VALIDATION_FAILED",
    "message": "Validation error",
    "http_status": 422,
    "details": [
      {
        "field": "username",
        "message": "String should have at least 1 character"
      }
    ],
    "request_id": "550e8400-e29b-41d4-a716-446655440000"
  }
}
```

### Authentication Error

**Endpoint:** `GET /api/v1/protected`

**Response (401 Unauthorized):**
```json
{
  "error": {
    "code": "AUTH_INVALID",
    "message": "Invalid credentials",
    "http_status": 401,
    "details": [],
    "request_id": "550e8400-e29b-41d4-a716-446655440001"
  }
}
```

### Not Found Error

**Endpoint:** `GET /api/v1/resource/999`

**Response (404 Not Found):**
```json
{
  "error": {
    "code": "RESOURCE_NOT_FOUND",
    "message": "Resource not found",
    "http_status": 404,
    "details": [],
    "request_id": "550e8400-e29b-41d4-a716-446655440002"
  }
}
```

### Server Error

**Response (500 Internal Server Error):**
```json
{
  "error": {
    "code": "INTERNAL_SERVER_ERROR",
    "message": "An unexpected error occurred",
    "http_status": 500,
    "details": [],
    "request_id": "550e8400-e29b-41d4-a716-446655440003"
  }
}
```

---

## Importing and Using Exceptions

### In Your Route Handlers

```python
from app.core.exceptions import (
    ValidationException,
    AuthenticationException,
    NotFoundException,
    BusinessLogicException,
)

@router.post("/user")
async def create_user(user_data: UserSchema):
    # Validation error example
    if not user_data.email:
        raise ValidationException(
            message="Email is required",
            details=[{"field": "email", "message": "Email cannot be empty"}]
        )
    
    # Business logic error
    if user_exists(user_data.email):
        raise BusinessLogicException(
            message="User with this email already exists"
        )
    
    # Create user...
    return {"data": {"id": user.id, "email": user.email}}
```

---

## Best Practices

1. **Always use exceptions**: Raise appropriate exceptions rather than returning error responses manually
2. **Include request_id**: All server-side logs include request_id for tracing
3. **Never expose stack traces**: They are logged server-side but never sent to clients
4. **Use error details for validation**: Include field-level details for validation errors
5. **Consistent error codes**: Use the standardized error codes from the catalog
6. **Meaningful messages**: Provide clear, actionable error messages to clients
