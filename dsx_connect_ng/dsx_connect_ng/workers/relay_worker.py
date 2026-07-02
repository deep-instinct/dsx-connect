from __future__ import annotations

import argparse
import asyncio
import json
import threading
import logging
from time import perf_counter
from typing import Any

from shared.dsx_logging import dsx_logging

from dsx_connect_ng.config import settings
from dsx_connect_ng.jobs.postgres_repo import OUTBOX_NOTIFY_CHANNEL
from dsx_connect_ng.jobs.models import OutboxFlushResult
from dsx_connect_ng.jobs.service import JobService
from dsx_connect_ng.workers.runtime import build_job_service


class PostgresOutboxWakeListener:
    def __init__(self, db_url: str, *, channel: str = OUTBOX_NOTIFY_CHANNEL) -> None:
        self.db_url = db_url
        self.channel = channel
        self._conn: Any | None = None
        self._conn_lock = threading.Lock()
        self._ready = threading.Event()
        self._notified = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._startup_error: BaseException | None = None

    def _listen_loop(self) -> None:
        import psycopg

        conn = None
        try:
            conn = psycopg.connect(self.db_url, autocommit=True)
            conn.execute(f"LISTEN {self.channel}")
            with self._conn_lock:
                self._conn = conn
            self._ready.set()
            while not self._stop.is_set():
                for _notify in conn.notifies(timeout=0.25, stop_after=1):
                    self._notified.set()
                    break
        except BaseException as exc:
            self._startup_error = exc
            self._ready.set()
            if not self._stop.is_set():
                raise
        finally:
            with self._conn_lock:
                self._conn = None
            if conn is not None and not conn.closed:
                conn.close()

    async def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._ready.clear()
        self._stop.clear()
        self._startup_error = None
        self._thread = threading.Thread(target=self._listen_loop, name="postgres-outbox-wake-listener", daemon=True)
        self._thread.start()
        ready = await asyncio.to_thread(self._ready.wait, 5.0)
        if not ready:
            raise TimeoutError("postgres_outbox_wake_listener_not_ready")
        if self._startup_error is not None:
            raise self._startup_error

    async def wait(self, timeout_seconds: float) -> bool:
        if timeout_seconds <= 0:
            await asyncio.sleep(0)
            return False
        notified = await asyncio.to_thread(self._notified.wait, timeout_seconds)
        if notified:
            self._notified.clear()
        return notified

    def close(self) -> None:
        self._stop.set()
        with self._conn_lock:
            conn = self._conn
        if conn is not None and not conn.closed:
            conn.close()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)


def build_outbox_wake_listener(summary: dict[str, Any]) -> PostgresOutboxWakeListener | None:
    if summary.get("job_repository_backend") != "postgres":
        return None
    if not settings.postgres.url:
        return None
    return PostgresOutboxWakeListener(settings.postgres.url)


async def relay_once(service: JobService, *, limit: int, max_active_scan_items: int | None = None) -> OutboxFlushResult:
    return await service.flush_outbox(limit=limit, max_active_scan_items=max_active_scan_items)


def _flush_event_payload(result: OutboxFlushResult) -> dict[str, Any]:
    return {
        "event": "relay_flush",
        "attempted": result.attempted,
        "published": result.published,
        "failed": result.failed,
        "active_scan_items": result.active_scan_items,
        "max_active_scan_items": result.max_active_scan_items,
        "publish_capacity": result.publish_capacity,
        "list_elapsed_ms": result.list_elapsed_ms,
        "publish_elapsed_ms": result.publish_elapsed_ms,
        "total_elapsed_ms": result.total_elapsed_ms,
        "selected_job_ids": result.selected_job_ids,
        "selected_topics": result.selected_topics,
        "oldest_pending_age_ms": result.oldest_pending_age_ms,
        "newest_pending_age_ms": result.newest_pending_age_ms,
        "first_outbox_created_at": result.first_outbox_created_at.isoformat()
        if result.first_outbox_created_at is not None
        else None,
        "last_outbox_created_at": result.last_outbox_created_at.isoformat()
        if result.last_outbox_created_at is not None
        else None,
        "first_published_at": result.first_published_at.isoformat()
        if result.first_published_at is not None
        else None,
        "last_published_at": result.last_published_at.isoformat()
        if result.last_published_at is not None
        else None,
    }


def _log_event(level: int, payload: dict[str, Any]) -> None:
    if dsx_logging.isEnabledFor(level):
        dsx_logging.log(level, json.dumps(payload, sort_keys=True))


def _log_flush_result(result: OutboxFlushResult) -> None:
    if result.attempted == 0 and result.failed == 0:
        _log_event(logging.DEBUG, _flush_event_payload(result))
        return
    _log_event(logging.INFO, _flush_event_payload(result))


async def relay_forever(
    service: JobService,
    *,
    limit: int,
    poll_interval_seconds: float,
    max_active_scan_items: int | None,
    wake_listener: PostgresOutboxWakeListener | None = None,
) -> None:
    try:
        if wake_listener is not None:
            await wake_listener.start()
        while True:
            result = await relay_once(service, limit=limit, max_active_scan_items=max_active_scan_items)
            _log_flush_result(result)
            if result.attempted > 0:
                continue
            if wake_listener is None:
                await asyncio.sleep(poll_interval_seconds)
            else:
                wait_started = perf_counter()
                notified = await wake_listener.wait(poll_interval_seconds)
                wait_elapsed_ms = round((perf_counter() - wait_started) * 1000, 3)
                if notified or dsx_logging.isEnabledFor(logging.DEBUG):
                    _log_event(
                        logging.DEBUG,
                        {
                            "event": "relay_wakeup",
                            "notified": notified,
                            "timeout_seconds": poll_interval_seconds,
                            "elapsed_ms": wait_elapsed_ms,
                        },
                    )
    finally:
        if wake_listener is not None:
            wake_listener.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Retry pending execution outbox records.")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Flush pending outbox records once and exit.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=settings.relay.batch_size,
        help="Maximum pending outbox records to process per flush.",
    )
    parser.add_argument(
        "--poll-interval-seconds",
        type=float,
        default=settings.relay.poll_interval_seconds,
        help="Sleep interval between flush cycles in continuous mode.",
    )
    parser.add_argument(
        "--max-active-scan-items",
        type=int,
        default=settings.relay.max_active_scan_items,
        help="Only publish pending scan requests while queued/scanning/scanned items are below this cap.",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    service, summary = build_job_service()
    wake_listener = build_outbox_wake_listener(summary)
    if wake_listener is not None:
        await wake_listener.start()
    _log_event(
        logging.INFO,
        {
            "event": "relay_start",
            **summary,
            "outbox_wakeup": "postgres_notify" if wake_listener is not None else "poll_interval",
            "outbox_notify_channel": OUTBOX_NOTIFY_CHANNEL if wake_listener is not None else None,
            "outbox_wakeup_ready": wake_listener is not None,
        },
    )
    replayed = service.replay_nonterminal_scan_only_batches()
    _log_event(
        logging.INFO,
        {
            "event": "relay_scan_only_replay",
            "replayed": replayed,
        },
    )
    if args.once:
        result = await relay_once(service, limit=args.batch_size, max_active_scan_items=args.max_active_scan_items)
        _log_flush_result(result)
        return
    await relay_forever(
        service,
        limit=args.batch_size,
        poll_interval_seconds=args.poll_interval_seconds,
        max_active_scan_items=args.max_active_scan_items,
        wake_listener=wake_listener,
    )


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
