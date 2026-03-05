import re
import uuid

from fastapi import Request, Response
from starlette.middleware.base import RequestResponseEndpoint


_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
    r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _is_valid_request_id(value: str) -> bool:
    """Check that value is a well-formed UUID string.

    Returns:
        bool: True when the value matches the UUID4 hex pattern.
    """
    return bool(_UUID_RE.match(value))


async def add_request_id(
    request: Request, call_next: RequestResponseEndpoint
) -> Response:
    """Add a unique request_id to each request context.

    Returns:
        Response: The response with X-Request-ID header.
    """
    raw_header = request.headers.get("X-Request-ID")
    stripped = raw_header.strip() if raw_header else ""
    if stripped and _is_valid_request_id(stripped):
        request_id = stripped
    else:
        request_id = str(uuid.uuid4())
    request.state.request_id = request_id

    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response
