from __future__ import annotations


class DiannaDomain:
    """DIANNA endpoints."""

    def __init__(self, dianna_api):
        self._api = dianna_api

    def analyze_from_siem(self, **kwargs):
        return self._api.analyze_from_siem(**kwargs)

    def get_result(self, analysis_id: str):
        return self._api.get_result(analysis_id)

    def get_result_by_task_id(self, dianna_analysis_task_id: str):
        return self._api.get_result_by_task_id(dianna_analysis_task_id)

    def poll_result(self, analysis_id: str, *, attempts: int = 30, sleep_seconds: float = 2.0):
        return self._api.poll_result(analysis_id, attempts=attempts, sleep_seconds=sleep_seconds)

    def poll_result_by_task_id(
        self,
        dianna_analysis_task_id: str,
        *,
        attempts: int = 30,
        sleep_seconds: float = 2.0,
    ):
        return self._api.poll_result_by_task_id(
            dianna_analysis_task_id,
            attempts=attempts,
            sleep_seconds=sleep_seconds,
        )
