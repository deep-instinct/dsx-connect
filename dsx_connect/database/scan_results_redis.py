import json
from typing import Optional, List

import redis

from dsx_connect.database.scan_results_base_db import ScanResultsBaseDB
from dsx_connect.models.scan_result import ScanResultModel
from dsx_connect.config import get_config
from shared.dsx_logging import dsx_logging


class ScanResultsRedisDB(ScanResultsBaseDB):
    """Redis-backed scan results store.

    Data model:
    - List newest-first at key 'dsxconnect:scan_results' (LPUSH + LTRIM retain)
    - Per-job lists at 'dsxconnect:scan_results_by_job:<job_id>' (optional, for fast queries)
    - Per-task lookup at 'dsxconnect:scan_result_by_task:<task_id>' (string JSON)
    """

    def __init__(self, retain: int = -1, collection_name: str = "scan_results"):
        super().__init__(retain=retain)
        cfg = get_config()
        self._r = redis.from_url(str(cfg.results_database.loc))
        # keys
        self._main_key = f"dsxconnect:{collection_name}"
        self._task_key_prefix = f"dsxconnect:scan_result_by_task:"
        self._job_key_prefix = f"dsxconnect:{collection_name}_by_job:"

    # ---------- helpers ----------
    @staticmethod
    def _to_json(sr: ScanResultModel) -> str:
        try:
            return sr.model_dump_json()
        except Exception:
            return sr.json()

    @staticmethod
    def _from_json(s: str) -> ScanResultModel:
        data = json.loads(s)
        return ScanResultModel.model_validate(data)

    # ---------- base impl ----------
    def read_all(self) -> List[ScanResultModel]:
        vals = self._r.lrange(self._main_key, 0, -1) or []
        out = []
        for b in vals:
            try:
                out.append(self._from_json(b.decode("utf-8") if isinstance(b, (bytes, bytearray)) else b))
            except Exception:
                continue
        return out

    def insert(self, scan_result: ScanResultModel):
        # Assign a monotonically increasing id if not present
        try:
            if getattr(scan_result, "id", -1) is None or int(getattr(scan_result, "id", -1)) < 0:
                seq_key = f"{self._main_key}:seq"
                new_id = int(self._r.incr(seq_key))
                scan_result.id = new_id
        except Exception:
            pass
        payload = self._to_json(scan_result)
        pipe = self._r.pipeline()
        pipe.lpush(self._main_key, payload)
        if self._retain > 0:
            pipe.ltrim(self._main_key, 0, max(0, self._retain - 1))
        # Index by task id
        task_id = getattr(scan_result, "scan_request_task_id", None)
        if task_id:
            pipe.set(f"{self._task_key_prefix}{task_id}", payload, ex=7 * 24 * 3600)
        # Index by job id
        job_id = getattr(scan_result, "scan_job_id", None) or getattr(getattr(scan_result, "scan_request", None), "scan_job_id", None)
        if job_id:
            jkey = f"{self._job_key_prefix}{job_id}"
            pipe.lpush(jkey, payload)
            if self._retain > 0:
                pipe.ltrim(jkey, 0, max(0, self._retain - 1))
            # Optional expiry to avoid unbounded growth
            pipe.expire(jkey, 14 * 24 * 3600)
        pipe.execute()
        self._check_retain_limit()  # no-op for Redis (we already trim)

    def delete(self, key, value) -> ScanResultModel:
        # Not used by current code; implement best-effort remove from lists
        # Return the first matching record if found, else raise KeyError
        if key == "scan_request_task_id":
            raw = self._r.get(f"{self._task_key_prefix}{value}")
            if raw:
                rec = self._from_json(raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw)
                try:
                    self._r.delete(f"{self._task_key_prefix}{value}")
                finally:
                    return rec
        # Generic: scan main list and remove first match
        all_vals = self._r.lrange(self._main_key, 0, -1) or []
        for b in all_vals:
            try:
                rec = self._from_json(b.decode("utf-8") if isinstance(b, (bytes, bytearray)) else b)
            except Exception:
                continue
            if getattr(rec, key, None) == value or (
                getattr(rec, "scan_request", None) and getattr(getattr(rec, "scan_request"), key, None) == value
            ):
                # remove one occurrence
                self._r.lrem(self._main_key, 1, b)
                return rec
        raise KeyError("record_not_found")

    def delete_oldest(self):
        # Drop from tail
        self._r.rpop(self._main_key)

    def find(self, key: str, value: str) -> Optional[List[ScanResultModel]]:
        if key == "scan_request_task_id":
            raw = self._r.get(f"{self._task_key_prefix}{value}")
            if not raw:
                return []
            try:
                return [self._from_json(raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw)]
            except Exception:
                return []
        if key == "scan_job_id":
            vals = self._r.lrange(f"{self._job_key_prefix}{value}", 0, -1) or []
            out = []
            for b in vals:
                try:
                    out.append(self._from_json(b.decode("utf-8") if isinstance(b, (bytes, bytearray)) else b))
                except Exception:
                    continue
            return out
        # Fallback: linear scan of recent items
        vals = self._r.lrange(self._main_key, 0, max(0, (self._retain - 1) if self._retain > 0 else 9999)) or []
        out: list[ScanResultModel] = []
        for b in vals:
            try:
                rec = self._from_json(b.decode("utf-8") if isinstance(b, (bytes, bytearray)) else b)
            except Exception:
                continue
            if getattr(rec, key, None) == value or (
                getattr(rec, "scan_request", None) and getattr(getattr(rec, "scan_request"), key, None) == value
            ):
                out.append(rec)
        return out

    def __len__(self) -> int:
        try:
            return int(self._r.llen(self._main_key) or 0)
        except Exception as e:
            dsx_logging.debug(f"redis llen failed: {e}")
            return 0
