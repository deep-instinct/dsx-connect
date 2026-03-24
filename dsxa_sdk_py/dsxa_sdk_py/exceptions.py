from __future__ import annotations

from http import HTTPStatus


class DSXAError(Exception):
    """Base exception for DSXA SDK errors."""


class AuthenticationError(DSXAError):
    """Raised when DSXA rejects the provided auth token."""


class BadRequestError(DSXAError):
    """Raised for 4xx responses caused by invalid input (protected entity, headers, etc.)."""


class NotFoundError(DSXAError):
    """Raised when a resource such as scan GUID cannot be found."""


class ServerError(DSXAError):
    """Raised for unexpected DSXA server errors (HTTP 5xx)."""


def map_http_status(status_code: int, message: str) -> DSXAError:
    """Translate HTTP status code to an SDK exception."""
    if status_code in {
        HTTPStatus.UNAUTHORIZED,
        HTTPStatus.FORBIDDEN,
    }:
        return AuthenticationError(message)
    if status_code == HTTPStatus.NOT_FOUND:
        return NotFoundError(message)
    if HTTPStatus.BAD_REQUEST <= status_code < HTTPStatus.INTERNAL_SERVER_ERROR:
        return BadRequestError(message)
    return ServerError(message)
