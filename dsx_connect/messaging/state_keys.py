from __future__ import annotations

PREFIX = "dsxconnect"


def job_key(job_id: str) -> str:
    return f"{PREFIX}:job:{job_id}"


def job_key_pattern() -> str:
    return f"{PREFIX}:job:*"


def job_keys(job_id: str) -> str:
    return f"{job_key(job_id)}:tasks"


def scanner_inflight_key() -> str:
    return f"{PREFIX}:scanner:inflight"
