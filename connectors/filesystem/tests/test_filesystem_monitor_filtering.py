import os
import sys
import time
import pathlib
from pathlib import Path

import pytest


def _build_monitor(fsconn, tmp_path: Path):
    # Avoid import issues with module-local import style
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from connectors.filesystem.filesystem_monitor import (
        FilesystemMonitor,
        FilesystemMonitorCallback,
    )
    from shared.async_ops import run_async
    from shared.models.connector_models import ScanRequestModel

    class TestCallback(FilesystemMonitorCallback):
        def file_modified_callback(self, file_path: pathlib.Path):
            run_async(fsconn.webhook_handler(
                ScanRequestModel(location=str(file_path), metainfo=file_path.name)
            ))

    return FilesystemMonitor(
        folder=tmp_path,
        filter=fsconn.config.filter,
        callback=TestCallback(),
    )


def _wait_for(predicate, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def _setup_fsconn(tmp_path, monkeypatch):
    # Ensure local import path and load module
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from connectors.filesystem import filesystem_connector as fsconn

    # Configure connector base
    fsconn.config.asset = str(tmp_path)
    fsconn.config.monitor = True

    # Capture scan requests
    scan_calls: list[str] = []

    async def fake_scan_file_request(scan_request):
        scan_calls.append(scan_request.location)
        from shared.models.status_responses import StatusResponse, StatusResponseEnum
        return StatusResponse(status=StatusResponseEnum.SUCCESS, message="ok")

    monkeypatch.setattr(fsconn.connector, "scan_file_request", fake_scan_file_request)
    return fsconn, scan_calls


def test_monitor_filter_include_extension_only(tmp_path, monkeypatch):
    fsconn, scan_calls = _setup_fsconn(tmp_path, monkeypatch)
    # Only .txt files
    fsconn.config.filter = "**/*.txt"

    monitor = _build_monitor(fsconn, tmp_path)

    txt = tmp_path / "keep.txt"
    binf = tmp_path / "drop.bin"
    txt.write_text("a")
    binf.write_text("b")

    FakeEvent = type("FakeEvent", (), {})
    for p in (txt, binf):
        ev = FakeEvent(); ev.is_directory = False; ev.src_path = str(p)
        monitor.on_modified(ev)

    assert _wait_for(lambda: str(txt) in scan_calls)
    # Negative assertion: ensure .bin did not get scanned
    time.sleep(0.2)
    assert str(binf) not in scan_calls


def test_monitor_filter_include_subtree_recursive(tmp_path, monkeypatch):
    fsconn, scan_calls = _setup_fsconn(tmp_path, monkeypatch)
    fsconn.config.filter = "sub1"

    sub1 = tmp_path / "sub1"; sub1.mkdir()
    other = tmp_path / "other"; other.mkdir()
    in_sub = sub1 / "a.txt"; in_sub.write_text("x")
    out_sub = other / "b.txt"; out_sub.write_text("y")

    monitor = _build_monitor(fsconn, tmp_path)

    FakeEvent = type("FakeEvent", (), {})
    for p in (in_sub, out_sub):
        ev = FakeEvent(); ev.is_directory = False; ev.src_path = str(p)
        monitor.on_modified(ev)

    assert _wait_for(lambda: str(in_sub) in scan_calls)
    time.sleep(0.2)
    assert str(out_sub) not in scan_calls


def test_monitor_filter_direct_children_only(tmp_path, monkeypatch):
    fsconn, scan_calls = _setup_fsconn(tmp_path, monkeypatch)
    fsconn.config.filter = "sub1/*"

    sub1 = tmp_path / "sub1"; (sub1 / "nested").mkdir(parents=True)
    a = sub1 / "a.txt"; a.write_text("1")
    deep = sub1 / "nested" / "c.txt"; deep.write_text("3")

    monitor = _build_monitor(fsconn, tmp_path)

    FakeEvent = type("FakeEvent", (), {})
    for p in (a, deep):
        ev = FakeEvent(); ev.is_directory = False; ev.src_path = str(p)
        monitor.on_modified(ev)

    assert _wait_for(lambda: str(a) in scan_calls)
    time.sleep(0.2)
    assert str(deep) not in scan_calls


def test_monitor_filter_excludes_and_mixed(tmp_path, monkeypatch):
    fsconn, scan_calls = _setup_fsconn(tmp_path, monkeypatch)
    # Include sub1 but exclude any tmp or sub2 subtrees
    fsconn.config.filter = "sub1 -tmp --exclude sub2"

    # Layout
    sub1 = tmp_path / "sub1"; sub1.mkdir()
    sub2 = sub1 / "sub2"; sub2.mkdir()
    tmpd = sub1 / "tmp"; tmpd.mkdir()
    ok = sub1 / "ok.txt"; ok.write_text("ok")
    in_sub2 = sub2 / "no.txt"; in_sub2.write_text("no")
    in_tmp = tmpd / "skip.txt"; in_tmp.write_text("skip")
    outside = tmp_path / "outside.txt"; outside.write_text("out")

    monitor = _build_monitor(fsconn, tmp_path)

    FakeEvent = type("FakeEvent", (), {})
    for p in (ok, in_sub2, in_tmp, outside):
        ev = FakeEvent(); ev.is_directory = False; ev.src_path = str(p)
        monitor.on_modified(ev)

    assert _wait_for(lambda: str(ok) in scan_calls)
    time.sleep(0.2)
    assert str(in_sub2) not in scan_calls
    assert str(in_tmp) not in scan_calls
    assert str(outside) not in scan_calls


def test_monitor_filter_top_level_only_star(tmp_path, monkeypatch):
    fsconn, scan_calls = _setup_fsconn(tmp_path, monkeypatch)
    # Only top-level files
    fsconn.config.filter = "*"

    sub = tmp_path / "sub"; sub.mkdir()
    top = tmp_path / "top.txt"; top.write_text("t")
    deep = sub / "deep.txt"; deep.write_text("d")

    monitor = _build_monitor(fsconn, tmp_path)

    FakeEvent = type("FakeEvent", (), {})
    for p in (top, deep):
        ev = FakeEvent(); ev.is_directory = False; ev.src_path = str(p)
        monitor.on_modified(ev)

    assert _wait_for(lambda: str(top) in scan_calls)
    time.sleep(0.2)
    assert str(deep) not in scan_calls


def test_monitor_filter_with_quoted_tokens(tmp_path, monkeypatch):
    fsconn, scan_calls = _setup_fsconn(tmp_path, monkeypatch)
    # Include 'scan here' subtree, exclude 'not here'
    fsconn.config.filter = "'scan here' -'not here'"

    sh = tmp_path / "scan here"; sh.mkdir()
    nh = tmp_path / "not here"; nh.mkdir()
    keep = sh / "keep.txt"; keep.write_text("k")
    drop = nh / "drop.txt"; drop.write_text("d")

    monitor = _build_monitor(fsconn, tmp_path)

    FakeEvent = type("FakeEvent", (), {})
    for p in (keep, drop):
        ev = FakeEvent(); ev.is_directory = False; ev.src_path = str(p)
        monitor.on_modified(ev)

    assert _wait_for(lambda: str(keep) in scan_calls)
    time.sleep(0.2)
    assert str(drop) not in scan_calls


def test_monitor_filter_glob_starstar_and_exclude_bare(tmp_path, monkeypatch):
    fsconn, scan_calls = _setup_fsconn(tmp_path, monkeypatch)
    fsconn.config.filter = "test/2025*/** -sub2"

    base = tmp_path / "test"; base.mkdir()
    y2025 = base / "2025-01-15"; y2025.mkdir(parents=True)
    y2024 = base / "2024-12-31"; y2024.mkdir(parents=True)
    ok = y2025 / "ok.txt"; ok.write_text("ok")
    sub2 = y2025 / "sub2"; sub2.mkdir()
    blocked = sub2 / "blocked.txt"; blocked.write_text("no")
    wrong_year = y2024 / "nope.txt"; wrong_year.write_text("nope")

    monitor = _build_monitor(fsconn, tmp_path)

    FakeEvent = type("FakeEvent", (), {})
    for p in (ok, blocked, wrong_year):
        ev = FakeEvent(); ev.is_directory = False; ev.src_path = str(p)
        monitor.on_modified(ev)

    assert _wait_for(lambda: str(ok) in scan_calls)
    time.sleep(0.2)
    assert str(blocked) not in scan_calls
    assert str(wrong_year) not in scan_calls
