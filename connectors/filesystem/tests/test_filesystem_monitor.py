import time
import pathlib
import sys
import os
from pathlib import Path

import pytest

from shared.models.connector_models import ScanRequestModel
from shared.models.status_responses import StatusResponse, StatusResponseEnum


def test_monitor_picks_up_new_file_and_triggers_scan(tmp_path, monkeypatch):
    # Force watchdog to use polling (fsevents can be blocked in CI/sandbox)
    os.environ["WATCHDOG_USE_POLLING"] = "true"

    # Ensure the filesystem connector's module-local imports resolve (it uses top-level import of filesystem_monitor)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # add connectors/filesystem to sys.path
    # Import the filesystem connector module components
    from connectors.filesystem import filesystem_connector as fsconn

    # Point the connector config to our temp directory and enable monitoring
    fsconn.config.asset = str(tmp_path)
    fsconn.config.monitor = True

    # Capture calls to scan (webhook is the only path that invokes this in the monitor flow)
    scan_calls: list[str] = []

    async def fake_scan_file_request(scan_request: ScanRequestModel) -> StatusResponse:
        # Record the scan request location (implies webhook was invoked)
        scan_calls.append(scan_request.location)
        return StatusResponse(status=StatusResponseEnum.SUCCESS, message="ok")

    # Stub networked scan method to avoid outbound HTTP and to observe calls
    monkeypatch.setattr(fsconn.connector, "scan_file_request", fake_scan_file_request)

    # No need to start a real watcher in tests; we trigger events directly

    # Build a monitor instance but do not start the OS observer; we'll invoke on_modified directly
    from connectors.filesystem.filesystem_monitor import FilesystemMonitor, FilesystemMonitorCallback
    from shared.async_ops import run_async

    class TestCallback(FilesystemMonitorCallback):
        def file_modified_callback(self, file_path: pathlib.Path):
            # Route through the real filesystem webhook handler
            run_async(fsconn.webhook_handler(ScanRequestModel(location=str(file_path), metainfo=file_path.name)))

    monitor = FilesystemMonitor(
        folder=pathlib.Path(fsconn.config.asset),
        filter="",
        callback=TestCallback(),
    )

    # Create a new file and simulate the watchdog-modified event
    test_file: pathlib.Path = tmp_path / "sample.txt"
    test_file.write_text("hello")

    FakeEvent = type("FakeEvent", (), {})
    event = FakeEvent()
    event.is_directory = False
    event.src_path = str(test_file)

    monitor.on_modified(event)

    # Wait briefly for async tasks to complete
    deadline = time.time() + 3.0
    while time.time() < deadline and str(test_file) not in scan_calls:
        time.sleep(0.05)

    assert str(test_file) in scan_calls
