"""
A single, predictable error envelope.

The client normalises failures in `src/api/errors.ts`: it reads `detail` for the
human message, and treats any top-level key whose value is a list of strings as
field errors for the form. This handler guarantees both are always present and
never lets an unexpected exception leak a stack trace to a phone.
"""

import logging
import uuid

from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger(__name__)


class ConflictError(exceptions.APIException):
    """409 -- the request is valid but the world moved on (e.g. table full)."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = "That action conflicts with the current state."
    default_code = "conflict"


class DomainError(exceptions.APIException):
    """422 -- a rule of the game was broken (e.g. not your turn)."""

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_detail = "That move isn't allowed right now."
    default_code = "domain_error"


def _summarise(data) -> str:
    """Best-effort one-line message from a DRF error body."""
    if isinstance(data, str):
        return data
    if isinstance(data, list) and data:
        return _summarise(data[0])
    if isinstance(data, dict):
        if isinstance(data.get("detail"), str):
            return data["detail"]
        for value in data.values():
            summary = _summarise(value)
            if summary:
                return summary
    return ""


def api_exception_handler(exc, context):
    # Translate the framework-agnostic exceptions DRF doesn't know about.
    if isinstance(exc, DjangoValidationError):
        exc = exceptions.ValidationError(
            exc.message_dict if hasattr(exc, "message_dict") else list(exc.messages)
        )
    elif isinstance(exc, Http404):
        exc = exceptions.NotFound()
    elif isinstance(exc, PermissionDenied):
        exc = exceptions.PermissionDenied()
    elif isinstance(exc, IntegrityError):
        # A race lost at the database (duplicate join, duplicate email) reads as
        # a conflict to the caller, not a server fault.
        logger.warning("integrity_error", extra={"error": str(exc)})
        exc = ConflictError()

    response = drf_exception_handler(exc, context)

    if response is None:
        # Genuinely unhandled: log with an id the user can quote, return 500.
        incident = uuid.uuid4().hex[:12]
        logger.exception(
            "unhandled_exception",
            extra={"incident": incident, "view": str(context.get("view"))},
        )
        return Response(
            {
                "detail": "Something went wrong on our end. Please try again.",
                "code": "server_error",
                "incident": incident,
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    data = response.data
    if not isinstance(data, dict):
        # DRF returns a bare list for top-level ValidationErrors.
        data = {"detail": _summarise(data), "nonFieldErrors": data}

    # `detail` is the client's headline message, so it must always be a plain
    # string -- DRF hands back a list whenever the error was raised as one.
    if not isinstance(data.get("detail"), str):
        data["detail"] = _summarise(data) or "Request failed."
    data.setdefault("code", getattr(exc, "default_code", "error"))
    response.data = data

    if response.status_code >= 500:
        logger.error("api_error", extra={"status": response.status_code, "body": data})

    return response
