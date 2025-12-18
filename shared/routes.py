# shared/endpoints.py
from enum import Enum
from typing import Iterable, Union, Optional

SERVICE_SLUG = "dsx-connect"
API_MAJOR = 1
API_PREFIX_V1 = f"{SERVICE_SLUG}/api/v{API_MAJOR}"


class DSXConnectAPI(str, Enum):
    """Server endpoints (called by connectors). Values are *relative* to API_PREFIX."""
    CONNECTION_TEST = "test/connection"
    DSXA_CONNECTION_TEST = "test/dsxa-connection"
    CONFIG = "config"
    VERSION = "version"
    READYZ = "readyz"
    HEALTHZ = "healthz"

    SCAN_PREFIX = "scan"
    CONNECTORS_PREFIX = "connectors"
    NOTIFICATIONS_PREFIX = "subscribe"
    DIANNA_PREFIX = "dianna"
    ADMIN_DEAD_LETTER_QUEUE_PREFIX = "admin/dead-letter"

class ScanPath(str, Enum):
    REQUEST = "request"
    RESULTS = "results"
    STATS = "stats"
    JOBS = "jobs"

class NotificationPath(str, Enum):
    CONNECTOR_REGISTERED = "connector-registered"
    SCAN_RESULT = "scan-result"
    JOB_SUMMARY = "job-summary"

class ConnectorPath(str, Enum):
    LIST_CONNECTORS = "list"
    REGISTER_CONNECTORS = "register"
    UNREGISTER_CONNECTORS = "unregister/{connector_uuid}"
    TRIGGER_FULLSCAN_CONNECTOR = "full_scan/{connector_uuid}"
    TRIGGER_CONFIG_CONNECTOR = "config/{connector_uuid}"
    TRIGGER_READYZ_CONNECTOR = "readyz/{connector_uuid}"
    TRIGGER_HEALTHZ_CONNECTOR = "healthz/{connector_uuid}"  # Add this line
    TRIGGER_REPOCHECK_CONNECTOR = "repo_check/{connector_uuid}"


class DeadLetterPath(str, Enum):
    STATS = "stats"
    STATS_ONE = "stats/{queue_type}"
    ITEMS = "items/{queue_type}"
    REQUEUE = "requeue"
    REQUEUE_ONE = "requeue/{queue_type}"
    CLEAR = "clear"
    CLEAR_ONE = "clear/{queue_type}"
    HEALTH = "health"


class ConnectorAPI(str, Enum):
    """Connector endpoints (called by dsx_connect). All are relative segments."""
    READ_FILE = "read_file"
    ITEM_ACTION = "item_action"
    FULL_SCAN = "full_scan"
    WEBHOOK_EVENT = "webhook/event"
    REPO_CHECK = "repo_check"
    ESTIMATE = "estimate"
    CONFIG = "config"
    READYZ = "readyz"
    HEALTHZ = "healthz"


class Action(str, Enum):
    # Generic CRUD-ish / common ops
    CREATE = "create"
    STATUS = "status"
    LIST   = "list"
    GET    = "get"
    UPDATE = "update"
    DELETE = "delete"

    # Health/metrics
    HEALTH = "health"
    STATS  = "stats"

    # Domain-specific actions you referenced
    REQUEUE   = "requeue"
    CLEAR     = "clear"
    FULLSCAN  = "full_scan"
    CONFIG    = "config"
    READY     = "ready"
    CONNECTION        = "connection"
    DSXA_CONNECTION   = "dsxa_connection"
    REGISTER          = "register"
    UNREGISTER        = "unregister"
    OVERVIEW          = "overview"
    CONNECTOR_REGISTERED = "connector_registered"


# ----------------- helpers -----------------

def _assert_rel(segment: str) -> str:
    """Ensure segment is relative (no leading/trailing slash). Allow internal '/' for subpaths/templates."""
    if not segment:
        raise ValueError("Empty path segment not allowed")
    if segment.startswith("/") or segment.endswith("/"):
        raise ValueError(f"Path must be relative (no leading/trailing slash): {segment!r}")
    return segment


def _normalized_parts(parts: Iterable[Union[str, Enum]]) -> str:
    segs = []
    for p in parts:
        s = p.value if isinstance(p, Enum) else str(p)
        # Allow full URLs as the *first* arg to join_url; otherwise enforce relative
        if s.startswith("http://") or s.startswith("https://"):
            segs.append(s.rstrip("/"))
        else:
            segs.append(_assert_rel(s))
    # If first element was a URL, keep it as-is; otherwise it's all relative
    if segs and (segs[0].startswith("http://") or segs[0].startswith("https://")):
        head, *tail = segs
        return head + ("/" + "/".join(tail) if tail else "")
    return "/".join(segs)


def api_path(ep: DSXConnectAPI, *subpaths: Union[str, Enum]) -> str:
    """Path-only (no scheme/host), always starting a '/'  Example: '/api/v1/dsx-connect/scan-request/123'"""
    rel = _normalized_parts((ep, *subpaths)) if subpaths else ep.value
    return f"/{API_PREFIX_V1}/{rel}"

def format_route(template: Union[str, Enum], **params) -> str:
    """
    Format a templated *relative* route segment into a concrete path component.

    Use this when your route enums contain placeholders (e.g., "unregister/{connector_uuid}")
    and you need the concrete segment to pass into `rel_path(...)` or `join_url(...)`.

    - Accepts either an Enum value or a raw string.
    - Normalizes the result to be *relative* (no leading/trailing slashes).
    - Raises KeyError if a placeholder is missing.
    - Raises ValueError if the formatted result isn’t relative.

    Example:
        format_route(ConnectorPath.UNREGISTER_CONNECTORS, connector_uuid="1234")
        -> "unregister/1234"
    """
    s = template.value if isinstance(template, Enum) else str(template)
    out = s.strip("/").format(**params)
    if out.startswith("/") or out.endswith("/"):
        raise ValueError(f"Route segment must be relative: {out!r}")
    return out

def _slug(p: Union[str, Enum]) -> str:
    s = p.value if isinstance(p, Enum) else str(p)
    return s.replace("/", ".").replace("{", "").replace("}", "").replace("-", "_")

def route_path(*parts: Union[str, Enum]) -> str:
    """For FastAPI route prefix and path definition. Always starts with '/'."""
    def seg(p):
        s = p.value if isinstance(p, Enum) else str(p)
        return s.strip("/")
    return "/" + "/".join(seg(p) for p in parts if str(p))

def route_name(
        endpoint: DSXConnectAPI,
        path: Optional[Union[str, Enum]] = None,
        action: Optional["Action"] = None,   # keep your small Action enum
        method: Optional[str] = None,         # only if you ever need it
) -> str:
    """For FastAPI route name"""
    parts = [_slug(endpoint)]
    if path is not None:
        parts.append(_slug(path))
    if action is not None:
        parts.append(action.value)
    if method:
        parts.append(method.lower())
    return ".".join(parts)

def service_url(base: str, *parts: Union[str, Enum]) -> str:
    """
    For outbound HTTP calls. base='http://host:port', parts must be relative.
      join_url('http://host:8599', API_PREFIX, DSXConnectAPI.SCAN_REQUEST) ->
         'http://host:8599/api/v1/dsx-connect/scan-request'
    """
    base_clean = base.rstrip("/")
    tail = _normalized_parts(parts) if parts else ""
    return f"{base_clean}/{tail}" if tail else base_clean
