class TaskError(Exception):
    """Base class with classification hooks."""
    retriable: bool = False
    reason: str = "task_error"


class ConnectorConnectionError(TaskError):
    retriable = True
    reason = "connector_connection"


class ConnectorServerError(TaskError):
    retriable = True
    reason = "connector_server_5xx"


class ConnectorClientError(TaskError):
    retriable = False
    reason = "connector_client_4xx"


class MalformedScanRequest(TaskError):
    retriable = False
    reason = "invalid_scan_request"


class DsxaTimeoutError(TaskError):
    retriable = True
    reason = "dsxa_timeout"


class DsxaServerError(TaskError):
    retriable = True
    reason = "dsxa_server_5xx"


class DsxaClientError(TaskError):
    retriable = False
    reason = "dsxa_client_4xx"


class MalformedResponse(TaskError):
    retriable = False
    reason = "bad_payload"


class FatalPolicyViolation(TaskError):
    retriable = False
    reason = "policy_violation"
