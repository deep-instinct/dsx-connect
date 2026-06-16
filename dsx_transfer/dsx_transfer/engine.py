from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime

from dsx_transfer.contracts import AuditSink, CheckpointStore, ScanGate, SinkAdapter, SourceAdapter
from dsx_transfer.models import AuditEvent, TransferAction, TransferItem, TransferItemOutcome, TransferItemState, TransferPlan, TransferReport, utcnow

ProgressCallback = Callable[[int, int, TransferItemOutcome], Awaitable[None]]


class TransferEngine:
    def __init__(
        self,
        *,
        source: SourceAdapter,
        sink: SinkAdapter,
        scan_gate: ScanGate,
        audit_sink: AuditSink | None = None,
        checkpoint_store: CheckpointStore | None = None,
        concurrency: int = 1,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        self.source = source
        self.sink = sink
        self.scan_gate = scan_gate
        self.audit_sink = audit_sink
        self.checkpoint_store = checkpoint_store
        self.concurrency = max(1, int(concurrency))
        self.progress_callback = progress_callback

    async def build_plan(self, *, destination_uri: str, transfer_id: str, policy_id: str | None = None) -> TransferPlan:
        return await self.source.plan(
            destination_uri=destination_uri,
            transfer_id=transfer_id,
            policy_id=policy_id,
        )

    async def execute_plan(self, plan: TransferPlan) -> TransferReport:
        started_at = utcnow()
        total_items = len(plan.items)
        completed_items = 0
        progress_lock = asyncio.Lock()

        async def record_progress(outcome: TransferItemOutcome) -> None:
            nonlocal completed_items
            if self.progress_callback is None:
                return
            async with progress_lock:
                completed_items += 1
                await self.progress_callback(completed_items, total_items, outcome)

        if self.concurrency == 1 or len(plan.items) <= 1:
            outcomes: list[TransferItemOutcome] = []
            for item in plan.items:
                outcome = await self._execute_item(plan.transfer_id, item)
                outcomes.append(outcome)
                await record_progress(outcome)
        else:
            semaphore = asyncio.Semaphore(self.concurrency)

            async def execute_with_limit(item: TransferItem) -> TransferItemOutcome:
                async with semaphore:
                    outcome = await self._execute_item(plan.transfer_id, item)
                    await record_progress(outcome)
                    return outcome

            outcomes = await asyncio.gather(*(execute_with_limit(item) for item in plan.items))
        return TransferReport(
            transfer_id=plan.transfer_id,
            source_uri=plan.source_uri,
            destination_uri=plan.destination_uri,
            policy_id=plan.policy_id,
            outcomes=outcomes,
            started_at=started_at,
            completed_at=utcnow(),
        )

    async def run(self, *, destination_uri: str, transfer_id: str, policy_id: str | None = None) -> TransferReport:
        plan = await self.build_plan(
            destination_uri=destination_uri,
            transfer_id=transfer_id,
            policy_id=policy_id,
        )
        return await self.execute_plan(plan)

    async def _execute_item(self, transfer_id: str, item: TransferItem) -> TransferItemOutcome:
        started_at: datetime = utcnow()
        try:
            checkpoint = await self._get_checkpoint(transfer_id, item)
            if checkpoint is not None and checkpoint.state == "allowed":
                outcome = TransferItemOutcome(
                    item=item,
                    state="skipped",
                    decision=checkpoint.outcome.decision,
                    bytes_written=checkpoint.outcome.bytes_written,
                    started_at=started_at,
                    completed_at=utcnow(),
                )
                await self._emit_audit(transfer_id, outcome)
                return outcome

            decision = await self.scan_gate.decide(item, self.source.open_item(item))
            if not decision.allowed:
                outcome = TransferItemOutcome(
                    item=item,
                    state=_state_for_non_allow_action(decision.action),
                    decision=decision,
                    started_at=started_at,
                    completed_at=utcnow(),
                )
                await self._record_outcome(transfer_id, outcome)
                return outcome
            bytes_written = await self.sink.write_item(item, self.source.open_item(item))
            outcome = TransferItemOutcome(
                item=item,
                state="allowed",
                decision=decision,
                bytes_written=bytes_written,
                started_at=started_at,
                completed_at=utcnow(),
            )
            await self._record_outcome(transfer_id, outcome)
            return outcome
        except Exception as exc:
            outcome = TransferItemOutcome(
                item=item,
                state="failed",
                started_at=started_at,
                completed_at=utcnow(),
                error={
                    "type": type(exc).__name__,
                    "message": str(exc),
                },
            )
            await self._record_outcome(transfer_id, outcome)
            return outcome

    async def _get_checkpoint(self, transfer_id: str, item: TransferItem):
        if self.checkpoint_store is None:
            return None
        return await self.checkpoint_store.get(transfer_id=transfer_id, item=item)

    async def _record_outcome(self, transfer_id: str, outcome: TransferItemOutcome) -> None:
        if self.checkpoint_store is not None:
            await self.checkpoint_store.put(transfer_id=transfer_id, outcome=outcome)
        await self._emit_audit(transfer_id, outcome)

    async def _emit_audit(self, transfer_id: str, outcome: TransferItemOutcome) -> None:
        if self.audit_sink is not None:
            await self.audit_sink.emit(AuditEvent.from_outcome(transfer_id=transfer_id, outcome=outcome))


def _state_for_non_allow_action(action: TransferAction) -> TransferItemState:
    if action == "exclude":
        return "excluded"
    return "blocked"
