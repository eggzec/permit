import uuid

from fastapi import Request, Response


async def add_request_id(request: Request, call_next: object) -> Response:
    """Add a unique request_id to each request context.

    Returns:
        Response: The response with X-Request-ID header.
    """
    raw_header = request.headers.get("X-Request-ID")
    stripped_header = raw_header.strip() if raw_header else ""
    request_id = stripped_header if stripped_header else str(uuid.uuid4())
    request.state.request_id = request_id

    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response
