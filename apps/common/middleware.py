"""Request-scoped context used by logging and error responses."""

import contextvars
import time
import uuid

_request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

HEADER = "HTTP_X_REQUEST_ID"
RESPONSE_HEADER = "X-Request-ID"


def get_request_id() -> str:
    return _request_id.get()


def set_request_id(value: str) -> None:
    _request_id.set(value)


class RequestIDMiddleware:
    """
    Attaches a correlation id to every request.

    An upstream proxy's `X-Request-ID` is honoured so a single id can be traced
    across the edge, the API and the websocket workers; otherwise one is minted.
    The id is echoed back on the response and injected into every log record.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        incoming = request.META.get(HEADER, "")
        # An attacker-controlled header lands in logs, so keep it short and dumb.
        request_id = incoming[:64] if incoming else uuid.uuid4().hex
        set_request_id(request_id)
        request.request_id = request_id

        started = time.perf_counter()
        response = self.get_response(request)
        response[RESPONSE_HEADER] = request_id
        response["X-Response-Time-ms"] = f"{(time.perf_counter() - started) * 1000:.1f}"
        return response
