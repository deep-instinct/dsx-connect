"""
Python SDK for interacting with Deep Instinct DSX Application Scanner (DSXA) REST APIs.
"""

from .client import DSXAClient, AsyncDSXAClient, ScanMode
from .exceptions import (
    DSXAError,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    ServerError,
)
from .models import (
    ScanResponse,
    ScanByPathResponse,
    ScanByPathVerdictResponse,
    VerdictEnum,
    ThreatType,
)

__all__ = [
    "DSXAClient",
    "AsyncDSXAClient",
    "ScanMode",
    "DSXAError",
    "AuthenticationError",
    "BadRequestError",
    "NotFoundError",
    "ServerError",
    "ScanResponse",
    "ScanByPathResponse",
    "ScanByPathVerdictResponse",
    "VerdictEnum",
    "ThreatType",
]

__version__ = "0.1.0"
