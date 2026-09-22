"""Public SDK interface for DSX-Connect APIs."""

from .client import DiannaApiClient, DSXConnectClient, DSXConnectCoreApiClient
from .exceptions import DiannaApiError, DSXConnectCoreApiError
from .domains import (
    ConnectorsDomain,
    CoreDomain,
    DiannaDomain,
    ResultsDomain,
    ScanDomain,
    SseDomain,
)

__all__ = [
    "DSXConnectClient",
    "DiannaApiClient",
    "DSXConnectCoreApiClient",
    "DiannaApiError",
    "DSXConnectCoreApiError",
    "CoreDomain",
    "ScanDomain",
    "ResultsDomain",
    "SseDomain",
    "ConnectorsDomain",
    "DiannaDomain",
]

__version__ = "0.1.0"
