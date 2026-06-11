from __future__ import annotations

from typing import AsyncIterator, Mapping

from dsx_transfer.contracts import ScanGate
from dsx_transfer.models import ScanDecision, ScanObservation, TransferAction, TransferItem, TransferVerdict
from dsx_transfer.policy import GuardedTransferPolicy


EICAR_TEST_SIGNATURE = b"".join(
    [
        b"X5O!P%@AP[4",
        b"\\PZX54(P^)7CC)7}$",
        b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE",
        b"!$H+H*",
    ]
)


class StaticVerdictScanGate(ScanGate):
    def __init__(
        self,
        *,
        default_verdict: TransferVerdict = "benign",
        verdicts_by_identity: Mapping[str, TransferVerdict] | None = None,
        file_types_by_identity: Mapping[str, str] | None = None,
        verdict_actions: Mapping[TransferVerdict, TransferAction] | None = None,
        file_type_actions: Mapping[str, TransferAction] | None = None,
        policy: GuardedTransferPolicy | None = None,
        policy_id: str | None = None,
        detect_eicar_test_file: bool = False,
    ) -> None:
        self.default_verdict = default_verdict
        self.verdicts_by_identity = dict(verdicts_by_identity or {})
        self.file_types_by_identity = dict(file_types_by_identity or {})
        self.detect_eicar_test_file = detect_eicar_test_file
        self.policy = policy or GuardedTransferPolicy(
            policy_id=policy_id,
            verdict_actions=verdict_actions,
            file_type_actions=file_type_actions,
        )

    async def decide(self, item: TransferItem, chunks: AsyncIterator[bytes]) -> ScanDecision:
        bytes_scanned = 0
        eicar_detected = False
        tail = b""
        async for chunk in chunks:
            bytes_scanned += len(chunk)
            if self.detect_eicar_test_file and not eicar_detected:
                window = tail + chunk
                eicar_detected = EICAR_TEST_SIGNATURE in window
                tail = window[-(len(EICAR_TEST_SIGNATURE) - 1) :]
        verdict = self.verdicts_by_identity.get(item.object_identity)
        if verdict is None:
            verdict = "malicious" if eicar_detected else self.default_verdict
        observation = ScanObservation(
            verdict=verdict,
            file_type=self.file_types_by_identity.get(item.object_identity),
            details={
                "bytes_scanned": bytes_scanned,
                "demo_eicar_test_file_detected": eicar_detected,
            },
        )
        return self.policy.evaluate(item=item, observation=observation)
