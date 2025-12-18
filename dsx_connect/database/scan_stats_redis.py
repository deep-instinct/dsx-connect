import json
import redis

from dsx_connect.database.scan_stats_base_db import ScanStatsBaseDB
from dsx_connect.models.scan_result import ScanStatsModel
from dsx_connect.config import get_config


class ScanStatsRedisDB(ScanStatsBaseDB):
    """Redis-backed scan stats store using a single JSON blob.

    Key: 'dsxconnect:scan_stats'
    """

    def __init__(self, collection_name: str = 'scan_stats'):
        self._key = f"dsxconnect:{collection_name}"
        cfg = get_config()
        self._r = redis.from_url(str(cfg.results_database.loc))

    def upsert(self, stats: ScanStatsModel):
        try:
            payload = stats.model_dump_json()
        except Exception:
            payload = stats.json()
        self._r.set(self._key, payload)

    def get(self) -> ScanStatsModel:
        raw = self._r.get(self._key)
        if not raw:
            return ScanStatsModel()
        try:
            data = raw.decode('utf-8') if isinstance(raw, (bytes, bytearray)) else raw
            return ScanStatsModel.model_validate(json.loads(data))
        except Exception:
            return ScanStatsModel()

    def __len__(self):
        return 1 if self._r.exists(self._key) else 0
