from __future__ import annotations

import json
from pathlib import Path

from dsx_transfer.contracts import CheckpointStore
from dsx_transfer.models import CheckpointRecord, TransferItem, TransferItemOutcome, utcnow


def _fingerprint(item: TransferItem) -> str:
    return "|".join(
        [
            str(item.size_bytes or ""),
            str(item.metadata.get("mtime_ns") or ""),
            str(item.metadata.get("relative_path") or item.object_identity),
        ]
    )


def _checkpoint_key(transfer_id: str, item: TransferItem) -> str:
    return f"{transfer_id}:{item.object_identity}"


class JsonCheckpointStore(CheckpointStore):
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    async def get(self, *, transfer_id: str, item: TransferItem) -> CheckpointRecord | None:
        raw = self._load().get(_checkpoint_key(transfer_id, item))
        if raw is None:
            return None
        record = CheckpointRecord.model_validate(raw)
        if record.metadata_fingerprint != _fingerprint(item):
            return None
        return record

    async def put(self, *, transfer_id: str, outcome: TransferItemOutcome) -> None:
        data = self._load()
        item = outcome.item
        data[_checkpoint_key(transfer_id, item)] = CheckpointRecord(
            transfer_id=transfer_id,
            object_identity=item.object_identity,
            source_uri=item.source_uri,
            destination_uri=item.destination_uri,
            state=outcome.state,
            size_bytes=item.size_bytes,
            metadata_fingerprint=_fingerprint(item),
            outcome=outcome,
            updated_at=utcnow(),
        ).model_dump(mode="json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8") or "{}")
