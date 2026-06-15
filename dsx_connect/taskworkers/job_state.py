from __future__ import annotations

import time

import redis

from dsx_connect.config import get_config
from dsx_connect.messaging.state_keys import job_key, job_keys
from shared.dsx_logging import dsx_logging


_REDIS = None


def _job_redis():
    global _REDIS
    if _REDIS is None:
        cfg = get_config()
        _REDIS = redis.from_url(str(cfg.redis_url), decode_responses=True)
    return _REDIS


def record_scan_request_terminal(job_id: str | None, outcome: str) -> dict | None:
    if not job_id:
        return None

    outcome_key = {
        "SUCCESS": "succeeded_count",
        "FAILED": "failed_count",
        "CANCELLED": "cancelled_count",
        "SKIPPED": "skipped_count",
    }.get(str(outcome).upper())
    if outcome_key is None:
        return None

    r = _job_redis()
    key = job_key(job_id)
    now = str(int(time.time()))

    r.hsetnx(key, "job_id", job_id)
    r.hsetnx(key, "status", "running")
    r.hincrby(key, "processed_count", 1)
    r.hincrby(key, "terminal_count", 1)
    r.hincrby(key, outcome_key, 1)
    r.hsetnx(key, "first_terminal_at", now)
    r.hset(key, mapping={"last_terminal_at": now, "last_update": now})
    r.expire(key, 7 * 24 * 3600)

    data = r.hgetall(key) or {}
    if data.get("enqueue_done") != "1" or data.get("finished_at"):
        return data

    def _to_int(value: str | None, default: int = -1) -> int:
        try:
            return int(value) if value is not None else default
        except Exception:
            return default

    enq_total = _to_int(data.get("enqueued_total"))
    expected = _to_int(data.get("expected_total"))
    enq_count = _to_int(data.get("enqueued_count"))
    total = enq_total if enq_total >= 0 else (expected if expected >= 0 else enq_count)
    terminal_count = _to_int(data.get("terminal_count"), 0)

    if total >= 0 and terminal_count >= total:
        status = data.get("status", "running")
        final_status = "cancelled" if status == "cancelled" else "completed"
        r.hset(key, mapping={"status": final_status, "finished_at": now, "last_update": now})
        dsx_logging.info(
            f"job.terminal_complete job={job_id} terminal={terminal_count} total={total} "
            f"succeeded={_to_int(data.get('succeeded_count'), 0)} failed={_to_int(data.get('failed_count'), 0)} "
            f"skipped={_to_int(data.get('skipped_count'), 0)} cancelled={_to_int(data.get('cancelled_count'), 0)} "
            f"finished_at={now}"
        )
        data["status"] = final_status
        data["finished_at"] = now
        data["last_update"] = now

    return data


def record_scan_request_enqueued(job_id: str | None, *, task_id: str | None = None, count: int = 1) -> dict | None:
    if not job_id or count <= 0:
        return None

    r = _job_redis()
    key = job_key(job_id)
    now = str(int(time.time()))

    r.hsetnx(key, "job_id", job_id)
    r.hsetnx(key, "status", "running")
    r.hsetnx(key, "started_at", now)
    total = r.hincrby(key, "enqueued_count", count)
    r.hsetnx(key, "first_enqueued_at", now)
    r.hset(
        key,
        mapping={
            "enqueued_total": str(total),
            "expected_total": str(total),
            "last_enqueued_at": now,
            "last_update": now,
        },
    )
    if task_id:
        try:
            r.rpush(job_keys(job_id), task_id)
        except Exception:
            pass
    r.expire(key, 7 * 24 * 3600)
    return r.hgetall(key) or {}
