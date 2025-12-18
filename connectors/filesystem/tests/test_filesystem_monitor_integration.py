import os
import sys
import time
from pathlib import Path
import pathlib

import pytest

try:
    import watchfiles  # noqa: F401
    HAVE_WATCHFILES = True
except Exception:
    HAVE_WATCHFILES = False


pytestmark = pytest.mark.skipif(
    not (os.environ.get("FS_MONITOR_E2E") in {"1", "true", "TRUE"} and HAVE_WATCHFILES),
    reason="Set FS_MONITOR_E2E=true and install watchfiles to run this test",
)


def test_monitor_e2e_with_watchfiles(tmp_path, monkeypatch):
    # Ensure local module imports resolve (filesystem_connector uses a local import of filesystem_monitor)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # add connectors/filesystem to sys.path

    from connectors.filesystem import filesystem_connector as fsconn
    from shared.models.connector_models import ScanRequestModel
    from shared.models.status_responses import StatusResponse, StatusResponseEnum

    # Configure connector to monitor our temp directory
    fsconn.config.asset = str(tmp_path)
    fsconn.config.monitor = True

    # Capture scan requests to avoid outbound HTTP
    scan_calls: list[str] = []

    async def fake_scan_file_request(scan_request: ScanRequestModel) -> StatusResponse:
        scan_calls.append(scan_request.location)
        return StatusResponse(status=StatusResponseEnum.SUCCESS, message="ok")

    monkeypatch.setattr(fsconn.connector, "scan_file_request", fake_scan_file_request)

    # Start the real watch loop
    from shared.async_ops import run_async
    run_async(fsconn.start_monitor())

    try:
        # Give watcher a moment to initialize
        time.sleep(0.3)

        # Create a file to trigger event
        p: pathlib.Path = tmp_path / "e2e.txt"
        p.write_text("content")

        # Wait until scan is recorded
        deadline = time.time() + 6.0
        while time.time() < deadline and str(p) not in scan_calls:
            time.sleep(0.1)

        assert str(p) in scan_calls
    finally:
        if getattr(fsconn.connector, "filesystem_monitor", None):
            fsconn.connector.filesystem_monitor.stop()

