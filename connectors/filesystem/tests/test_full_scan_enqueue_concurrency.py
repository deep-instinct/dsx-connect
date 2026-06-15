import asyncio
import sys
from pathlib import Path

import pytest

from shared.models.status_responses import StatusResponse, StatusResponseEnum


@pytest.mark.asyncio
async def test_full_scan_handler_uses_bounded_enqueue_concurrency(tmp_path, monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from connectors.filesystem import filesystem_connector as fsconn

    files = []
    for idx in range(6):
        path = tmp_path / f"file-{idx}.txt"
        path.write_text(f"file {idx}")
        files.append(path)

    async def fake_get_filepaths_async(_root, _filter):
        for path in files:
            yield path

    in_flight = 0
    max_in_flight = 0
    seen_locations: list[str] = []

    async def fake_scan_file_request(scan_request):
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.01)
        seen_locations.append(scan_request.location)
        in_flight -= 1
        return StatusResponse(status=StatusResponseEnum.SUCCESS, message="ok")

    monkeypatch.setattr(fsconn, "get_filepaths_async", fake_get_filepaths_async)
    monkeypatch.setattr(fsconn.connector, "scan_file_request", fake_scan_file_request)
    monkeypatch.setattr(fsconn.config, "asset", str(tmp_path))
    monkeypatch.setattr(fsconn.config, "filter", "")
    monkeypatch.setattr(fsconn.config, "full_scan_enqueue_concurrency", 3)

    response = await fsconn.full_scan_handler()

    assert response.status == StatusResponseEnum.SUCCESS
    assert len(seen_locations) == len(files)
    assert max_in_flight >= 2
    assert max_in_flight <= 3
