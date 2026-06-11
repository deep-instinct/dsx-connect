from __future__ import annotations

from collections.abc import Mapping

from dsx_transfer.dsxa_file_types import expand_file_type_actions
from dsx_transfer.models import ScanDecision, ScanObservation, TransferAction, TransferItem, TransferVerdict


DEFAULT_VERDICT_ACTIONS: dict[TransferVerdict, TransferAction] = {
    "benign": "allow",
    "malicious": "block",
    "suspicious": "block",
    "unknown": "block",
    "error": "error",
}


class GuardedTransferPolicy:
    def __init__(
        self,
        *,
        policy_id: str | None = None,
        verdict_actions: Mapping[TransferVerdict, TransferAction] | None = None,
        file_type_actions: Mapping[str, TransferAction] | None = None,
    ) -> None:
        self.policy_id = policy_id
        self.verdict_actions = {**DEFAULT_VERDICT_ACTIONS, **dict(verdict_actions or {})}
        self.file_type_actions = expand_file_type_actions(file_type_actions or {})

    def evaluate(self, *, item: TransferItem, observation: ScanObservation) -> ScanDecision:
        if observation.file_type and observation.file_type in self.file_type_actions:
            action = self.file_type_actions[observation.file_type]
            reason = f"file_type_rule:{observation.file_type}"
        else:
            action = self.verdict_actions.get(observation.verdict, "block")
            reason = f"verdict_rule:{observation.verdict}"
        return ScanDecision(
            verdict=observation.verdict,
            action=action,
            file_type=observation.file_type,
            policy_id=self.policy_id,
            scan_guid=observation.scan_guid,
            reason=reason,
            details={
                **observation.details,
                "object_identity": item.object_identity,
            },
        )
