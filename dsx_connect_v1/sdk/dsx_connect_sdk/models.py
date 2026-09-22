from __future__ import annotations

from typing import Any, TypedDict


class AnalyzeFromSiemResponse(TypedDict, total=False):
    connector_uuid: str
    dianna_analysis_task_id: str
    location_requested: str
    location_resolved: str
    status: str
    task_id: str
    used_quarantine_fallback: bool


class DiannaResultResponse(TypedDict, total=False):
    status: str
    result: Any
