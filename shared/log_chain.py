import logging
import logging.handlers
import json
import socket
import ssl
from datetime import datetime

from typing import Optional

from fastapi.encoders import jsonable_encoder
from dsx_connect.models.scan_result import ScanResultModel


# -------------------------------------------------------------------
# 1) APPLICATION LOGGER (console, file, etc.)
# -------------------------------------------------------------------
dsx_logging = logging.getLogger(__name__)
# (Elsewhere you’d configure dsx_logging’s handlers/formatters as you like,
# e.g. StreamHandler to stdout or a FileHandler.)

# -------------------------------------------------------------------
# 2) SYSLOG LOGGER (sends ONLY to SysLog server)
# -------------------------------------------------------------------
syslog_logger = logging.getLogger("syslog_logger")
syslog_logger.setLevel(logging.INFO)  # Only INFO or above go to syslog
# We delay attaching the SysLogHandler until init_syslog_handler() is called.

_syslog_handler: Optional[logging.Handler] = None


class TLSSysLogHandler(logging.Handler):
    """Minimal TLS syslog handler using newline-delimited framing.

    Note: Many servers accept LF-delimited frames; for strict RFC6587 octet-counting,
    this can be extended to prefix the length. This implementation aims for practicality.
    """

    def __init__(self, host: str, port: int, *,
                 ca_file: str | None = None,
                 cert_file: str | None = None,
                 key_file: str | None = None,
                 insecure: bool = False):
        super().__init__()
        self.host = host
        self.port = port
        ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=ca_file if ca_file else None)
        if insecure:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        if cert_file and key_file:
            ctx.load_cert_chain(certfile=cert_file, keyfile=key_file)
        self._ctx = ctx
        self._sock: ssl.SSLSocket | None = None
        self._connect()

    def _connect(self):
        try:
            raw = socket.create_connection((self.host, self.port), timeout=5.0)
            self._sock = self._ctx.wrap_socket(raw, server_hostname=self.host)
        except Exception:
            self._sock = None

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        data = (msg + "\n").encode("utf-8", errors="ignore")
        if not self._sock:
            self._connect()
        if not self._sock:
            return
        try:
            self._sock.sendall(data)
        except Exception:
            # reconnect once
            try:
                if self._sock:
                    self._sock.close()
            except Exception:
                pass
            self._sock = None
            self._connect()
            if self._sock:
                try:
                    self._sock.sendall(data)
                except Exception:
                    pass


def init_syslog_handler(syslog_host: str = "localhost", syslog_port: int = 514,
                        transport: str = "tcp",
                        tls_ca: str | None = None,
                        tls_cert: str | None = None,
                        tls_key: str | None = None,
                        tls_insecure: bool = False):
    """Initialize the syslog handler for the worker process.

    transport: 'tcp' (default), 'udp', or 'tls'
    """
    global _syslog_handler
    if _syslog_handler:
        return   # already initialized

    try:
        if transport.lower() == "udp":
            _syslog_handler = logging.handlers.SysLogHandler(
                address=(syslog_host, syslog_port),
                facility=logging.handlers.SysLogHandler.LOG_LOCAL0,
                socktype=socket.SOCK_DGRAM
            )
        elif transport.lower() == "tcp":
            _syslog_handler = logging.handlers.SysLogHandler(
                address=(syslog_host, syslog_port),
                facility=logging.handlers.SysLogHandler.LOG_LOCAL0,
                socktype=socket.SOCK_STREAM
            )
        elif transport.lower() == "tls":
            _syslog_handler = TLSSysLogHandler(
                host=syslog_host,
                port=syslog_port,
                ca_file=tls_ca,
                cert_file=tls_cert,
                key_file=tls_key,
                insecure=bool(tls_insecure),
            )
        else:
            raise ValueError(f"Unsupported syslog transport: {transport}")
        # Prefix with a static tag and newline for UDP/TCP so downstream collectors/SIEMs
        # can easily spot dsx-connect scan events. TLS handler already appends a newline on write.
        fmt = "dsx-connect %(message)s\n" if transport.lower() in ("udp", "tcp") else "dsx-connect %(message)s"
        _syslog_handler.setFormatter(logging.Formatter(fmt))
        syslog_logger.addHandler(_syslog_handler)

        # Emit the initial “workers initialized” message to remote syslog
        syslog_logger.info("dsx-connect-workers initialized to use syslog")

        dsx_logging.info(f"Initialized syslog handler for {syslog_host}:{syslog_port} transport={transport}")
    except Exception as e:
        # Use warning to avoid alarming non-results workers or dev environments without a collector
        dsx_logging.warning(f"Syslog handler not initialized: {e}")


def log_verdict_chain(
    scan_result: ScanResultModel,
    scan_request_task_id: str,
    current_task_id: Optional[str] = None,
) -> bool:
    """
    Log the complete chain (scan request, verdict, and item action) to syslog.

    Args:
        scan_request: The original scan request details.
        verdict: The scan verdict result.
        item_action_status: Whether the item_action (if triggered) was successful and the action performed.
        scan_request_task_id: The task ID of the initiating scan_request_task.
        current_task_id: The task ID of the verdict_task (optional).

    """
    global _syslog_handler
    if not _syslog_handler:
        dsx_logging.warning("Syslog handler not initialized, skipping log")
        return False

    try:
        # Derive optional fields for easier downstream parsing
        try:
            job_id = getattr(scan_result, "scan_job_id", None) or (
                getattr(getattr(scan_result, "scan_request", None), "scan_job_id", None)
            )
        except Exception:
            job_id = None
        try:
            status = getattr(scan_result, "status", None)
        except Exception:
            status = None
        try:
            rid = getattr(scan_result, "id", None)
        except Exception:
            rid = None

        # Only emit the parts operators care about: the request, verdict, and action.
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "source": "dsx-connect",
            "scan_request": scan_result.scan_request.model_dump(),
            "verdict": scan_result.verdict.model_dump(),
            "item_action": scan_result.item_action.model_dump(),
        }
        syslog_message = json.dumps(jsonable_encoder(log_data))
        syslog_logger.info(syslog_message)

        dsx_logging.debug(f"Sent verdict chain to syslog: {syslog_message}")
        return True
    except Exception as e:
        dsx_logging.error(f"Failed to log verdict chain to syslog: {e}", exc_info=True)
        return False
