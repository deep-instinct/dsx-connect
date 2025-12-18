import json
from dsx_connect.models.scan_result import ScanStatsModel
from dsx_connect.database.scan_stats_base_db import ScanStatsBaseDB


class ScanStatsCollection(ScanStatsBaseDB):
    def __init__(self):
        super().__init__()
        self._record = None  # Only one stats record now

    def upsert(self, stats: ScanStatsModel):
        stats_dict = json.loads(stats.json())
        if self._record:
            self._record.update(stats_dict)
        else:
            self._record = stats_dict

    def get(self) -> ScanStatsModel:
        return ScanStatsModel(**self._record) if self._record else ScanStatsModel()

    def __len__(self):
        return 1 if self._record else 0
