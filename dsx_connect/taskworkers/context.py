from __future__ import annotations
from dataclasses import dataclass
from shared.dsx_logging import dsx_logging

# Example: simple context with ids for logging/tracing
@dataclass
class ScanContext:
    scan_id: str
    connector_uuid: str
    location: str

# Lazy singletons (don’t create heavy clients at import)
_connector_client = None
_dsxa_client = None

def connector_client():
    global _connector_client
    if _connector_client is None:
        # construct using config (urls, keys)
        _connector_client = _build_connector_client()
    return _connector_client

def dsxa_client():
    global _dsxa_client
    if _dsxa_client is None:
        _dsxa_client = _build_dsxa_client()
    return _dsxa_client

def _build_connector_client():
    # TODO: use get_config() and return a thin client wrapper
    dsx_logging.info("Initializing Connector client")
    from dsx_connect.connectors.client import ConnectorClient
    return ConnectorClient()

def _build_dsxa_client():
    dsx_logging.info("Initializing DSXA client")
    from dsx_connect.services.dsxa_client import DsxaClient
    return DsxaClient()
