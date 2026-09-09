"""Request-ID middleware.

Ensures every request has a correlation id: reuse an inbound ``X-Request-ID`` header if present,
otherwise generate one. The id is placed in a context var (so logs pick it up) and echoed back on
the response as ``x-request-id``.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import request_id_ctx

REQUEST_ID_HEADER = "x-request-id"


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach a request id to the logging context and the response headers."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        token = request_id_ctx.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_ctx.reset(token)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
