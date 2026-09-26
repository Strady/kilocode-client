"""Error types for the Kilo client, mapped from the server's error responses.

The server returns structured error bodies of the shape ``{ "name": ..., "data": ... }``
for most errors, and plain ``{ "message": ... }`` (or the ``effect_HttpApiError_*``
shapes) for transport-level failures. This module normalizes them into a small
hierarchy of exceptions and preserves the raw detail from the response body.
"""

from __future__ import annotations

from typing import Any

import httpx


class KiloError(Exception):
    """Base class for all errors raised by the Kilo client."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        name: str | None = None,
        data: Any = None,
        method: str | None = None,
        url: str | None = None,
        request_id: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.name = name
        self.data = data
        self.method = method
        self.url = url
        self.request_id = request_id
        super().__init__(message)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"{type(self).__name__}({self.args[0]!r}, status_code={self.status_code}, "
            f"name={self.name!r})"
        )


class KiloHTTPError(KiloError):
    """Raised for any non-2xx HTTP response.

    Subclasses exist for the most common statuses, but ``KiloHTTPError`` itself is
    raised when no specific subclass matches.
    """


class BadRequestError(KiloHTTPError):
    """HTTP 400. The server could not validate parameters, query, headers or body."""


class NotFoundError(KiloHTTPError):
    """HTTP 404. A session, message or part with the given ID does not exist."""


class UnauthorizedError(KiloHTTPError):
    """HTTP 401. Missing or invalid credentials."""


class ForbiddenError(KiloHTTPError):
    """HTTP 403. Authenticated but not permitted to perform the action."""


class ServerError(KiloHTTPError):
    """HTTP 5xx. The server failed unexpectedly."""


class ConsentRequiredError(KiloHTTPError):
    """HTTP 409. The session requires explicit user consent/permission to proceed."""


class DecodeError(KiloError):
    """The server returned JSON that could not be parsed into the expected model."""


# Mapping from HTTP status code to the exception class we raise for it.
_STATUS_EXCEPTIONS = {
    400: BadRequestError,
    401: UnauthorizedError,
    403: ForbiddenError,
    404: NotFoundError,
    409: ConsentRequiredError,
}


def _extract_message(body: Any) -> str:
    """Best-effort extraction of a human readable message from an error body."""
    if isinstance(body, dict):
        # effect_HttpApiError_* shapes: {"name": "...", "message": "..."}
        top_msg = body.get("message")
        if isinstance(top_msg, str):
            return top_msg
        # { "name": "...", "data": { "message": "..." } }
        data = body.get("data")
        if isinstance(data, dict):
            data_msg = data.get("message")
            if isinstance(data_msg, str):
                return data_msg
            provider = data.get("providerID")
            if isinstance(provider, str):
                return f"provider {provider}: {data_msg or ''}"
        if isinstance(data, str):
            return data
    if isinstance(body, str):
        return body
    return ""


def raise_for_response(response: httpx.Response) -> None:
    """Raise the appropriate exception for a non-2xx ``httpx.Response``.

    Parses the JSON error body if present and attaches its fields to the exception.
    """
    status = response.status_code
    try:
        body: Any = response.json()
    except Exception:  # noqa: BLE001 - body is not JSON
        body = response.text

    message = _extract_message(body) or (response.text if response.text else f"HTTP {status}")

    name: str | None = None
    data: Any = None
    if isinstance(body, dict):
        if isinstance(body.get("name"), str):
            name = body["name"]
        data = body.get("data")

    cls = _STATUS_EXCEPTIONS.get(status, KiloHTTPError)
    raise cls(
        message,
        status_code=status,
        name=name,
        data=data,
        method=response.request.method,
        url=str(response.request.url),
    )


def is_error_status(status_code: int) -> bool:
    return status_code >= 400
