from abc import ABC, abstractmethod
from dsx_connect.models.scan_result import ScanStatsModel


class ScanStatsBaseDB(ABC):
    def __init__(self):
        pass

    @abstractmethod
    def upsert(self, stats: ScanStatsModel):
        """Update an existing record in the database based on the scan_id."""
        pass

    @abstractmethod
    def get(self) -> ScanStatsModel:
        pass
