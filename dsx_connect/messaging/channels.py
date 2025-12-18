from __future__ import annotations
from enum import StrEnum
from .namespace import NS



class Channel(StrEnum):
    """
    Enumeration of pub/sub channels used by dsx-connect.

    These channels are fully-qualified Redis pub/sub topics scoped to the global
    namespace defined in ``dsx_connect.messaging.namespace.NS``.  They replace the
    old ``Topics`` enum from ``topics.py``.  Channels fall into two broad
    categories:

    * UI-facing notifications (used by SSE endpoints)
    * Internal registry bus (used for connector registration/unregistration)

    See ``registration.py`` and ``registry.py`` for usage of the
    ``REGISTRY_CONNECTORS`` channel.
    """

    # Internal registry bus (cache warm/evict).  Used by ConnectorsRegistry to
    # receive upsert/unregister events from ``registration.py``.  Payloads are
    # full ConnectorInstanceModel JSON for upserts and a minimal envelope for
    # unregister events.
    REGISTRY_CONNECTORS = f"{NS}:registry:connectors"

    # UI-facing notification buses (Server-Sent Events).  These publish
    # lightweight envelopes to the frontend.  See ``dsx_connect_api.py`` for
    # subscription endpoints.
    NOTIFY_CONNECTORS = f"{NS}:notify:connectors"
    NOTIFY_SCAN_RESULT = f"{NS}:notify:scan_result"
    # Dead-letter queue notifications: broadcast requeue/clear events to the UI
    NOTIFY_DLQ = f"{NS}:notify:dlq"

