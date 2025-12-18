from dsx_connect.database.scan_results_base_db import ScanResultsBaseDB
from dsx_connect.models.scan_result import ScanResultModel


class ScanResultsCollection(ScanResultsBaseDB):

    def __init__(self, retain: int = -1):
        super().__init__(retain)
        self.collection = []
        self.next_id = 1

    def insert(self, model: ScanResultModel) -> int:
        if self._retain == 0:
            return -1 # Do nothing if retain is 0 (store nothing)

        model.id = self.next_id
        self.collection.append(model)
        self.next_id += 1
        self._check_retain_limit()  # Check and enforce the retention limit
        return model.id

    def delete(self, id: int) -> bool:
        for i, model in enumerate(self.collection):
            if model.id == id:
                del self.collection[i]
                return True
        return False

    def delete_oldest(self) -> bool:
        if self.collection:
            record = self.collection.pop(0)  # Remove the oldest record
            return True
        return False

    def read_all(self) -> [ScanResultModel]:
        return self.collection

    def find(self, key: str, value: str) -> list[ScanResultModel] | None:
        models = []
        for model in self.collection:
            if getattr(model, key, None) == value:
                models.append(model)
        return models

    def __len__(self):
        return len(self.collection)
