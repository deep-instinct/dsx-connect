"""
ConnectorKeys module defines Redis key namespaces for connector presence and configuration.

This replaces the old Keys dataclass from the deprecated `topics.py`.  It uses the
global namespace (NS) from ``dsx_connect.messaging.namespace`` to build fully-qualified
Redis keys.  See ``registration.py`` and ``registry.py`` for usage.

Example:
    key = ConnectorKeys.presence("1234")
    # -> "<env>:dsx-connect:connectors:presence:1234"

The CONNECTOR_PRESENCE_BASE and CONNECTOR_CONFIG_BASE constants allow you to
construct scan patterns for Redis ``scan_iter`` to find all registered
connector entries.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from .namespace import NS


@dataclass(frozen=True)
class ConnectorKeys:
    """Namespace and helper functions for connector presence/config keys in Redis."""

    # Base prefixes for connector presence and configuration keys
    CONNECTOR_PRESENCE_BASE: Final[str] = f"{NS}:connectors:presence"
    CONNECTOR_CONFIG_BASE: Final[str] = f"{NS}:connectors:config"

    @staticmethod
    def presence(uuid: str) -> str:
        """
        Build a fully-qualified Redis key for storing the presence info of a connector.

        Args:
            uuid: Connector UUID as a string.

        Returns:
            The Redis key for this connector's presence information.
        """
        return f"{ConnectorKeys.CONNECTOR_PRESENCE_BASE}:{uuid}"

    @staticmethod
    def config(uuid: str) -> str:
        """
        Build a fully-qualified Redis key for storing configuration details of a connector.

        Args:
            uuid: Connector UUID as a string.

        Returns:
            The Redis key for this connector's configuration information.
        """
        return f"{ConnectorKeys.CONNECTOR_CONFIG_BASE}:{uuid}"