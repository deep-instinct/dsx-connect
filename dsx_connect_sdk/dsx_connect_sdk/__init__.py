"""Public SDK interface for DSX-Connect DIANNA APIs."""

from .client import DiannaApiClient
from .exceptions import DiannaApiError

__all__ = [
    "DiannaApiClient",
    "DiannaApiError",
]

__version__ = "0.1.0"
