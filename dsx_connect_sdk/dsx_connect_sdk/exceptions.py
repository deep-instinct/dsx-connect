from __future__ import annotations

from typing import Any


class DiannaApiError(RuntimeError):
    """Raised for DSX-Connect DIANNA API failures."""

    def __init__(self, message: str, *, status_code: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload
