from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
import time
import uuid

from fastapi import HTTPException, status

from dsx_connect_ng.config import RecoverySettings
from dsx_connect_ng.control_plane.config_models import resolve_policy_runtime_config
from dsx_connect_ng.control_plane.service import ControlPlaneService
from dsx_connect_ng.jobs.bus import JobBus
from dsx_connect_ng.jobs.contracts import (
    DiannaAnalysisRequested,
    MessageEnvelope,
    PolicyEvaluationRequested,
    RemediationRequested,
    ResultSinkEmitRequested,
    ScanItemRequested,
)
from dsx_connect_ng.jobs.models import (
    BatchJobRecord,
    BatchJobSubmitRequest,
    ContentPreservationDecision,
    DeliveryRequest,
    DiannaAnalysisRequest,
    DomainJobEnvelope,
    JobCreate,
    JobItemCreate,
    JobItemRecord,
    JobItemSummary,
    JobBacklogSnapshot,
    JobLatencySnapshot,
    JobProgressSnapshot,
    JobRuntimeSnapshot,
    JobRecord,
    JobSubmitRequest,
    JobThroughputSnapshot,
    LatencySummary,
    OutboxFlushResult,
    OutboxRecord,
    PolicyDecision,
    PolicyHandoffDecision,
    RemediationRequest,
    StageRecord,
    StageUpdateRequest,
    BottleneckHint,
    ThroughputWindow,
)
from dsx_connect_ng.jobs.repository import JobRepository
from dsx_connect_ng.recovery import RecoveryMode, ResolvedRecoveryMode


class JobService:
    def __init__(
        self,
        repo: JobRepository,
        bus: JobBus,
        control_plane: ControlPlaneService | None = None,
        recovery_settings: RecoverySettings | None = None,
    ) -> None:
        self.repo = repo
        self.bus = bus
        self.control_plane = control_plane
        self.recovery_settings = recovery_settings or RecoverySettings()

    def _resolve_effective_recovery_mode(self, requested_mode: RecoveryMode | None) -> tuple[ResolvedRecoveryMode, dict]:
        configured_mode = self.recovery_settings.mode
        selected_mode = requested_mode or configured_mode
        if selected_mode == "adaptive":
            effective_mode: ResolvedRecoveryMode = "batch"
            source = "requested_adaptive" if requested_mode == "adaptive" else "settings_adaptive_default"
            reason = "adaptive_defaults_to_batch_until_workload_hints_are_modeled"
        else:
            effective_mode = selected_mode
            source = "request" if requested_mode is not None else "settings_default"
            reason = "explicit_mode_selected"
        return effective_mode, {
            "source": source,
            "requestedMode": requested_mode,
            "configuredMode": configured_mode,
            "effectiveMode": effective_mode,
            "reason": reason,
            "batchSize": self.recovery_settings.batch_size,
            "checkpointEveryItems": self.recovery_settings.checkpoint_every_items,
            "checkpointEverySeconds": self.recovery_settings.checkpoint_every_seconds,
            "largeObjectThresholdBytes": self.recovery_settings.large_object_threshold_bytes,
            "preferItemModeForArchives": self.recovery_settings.prefer_item_mode_for_archives,
        }

    def _validate_control_plane_references(
        self,
        *,
        integration_id: str | None,
        scope_id: str | None,
    ) -> None:
        if self.control_plane is None:
            return
        if integration_id is not None:
            self.control_plane.get_integration_or_404(integration_id)
        if scope_id is None:
            return
        scope = self.control_plane.get_scope_or_404(scope_id)
        if integration_id is not None and scope.integration_id != integration_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "scope_integration_mismatch",
                    "scope_id": scope_id,
                    "scope_integration_id": scope.integration_id,
                    "integration_id": integration_id,
                },
            )

    def _infer_batch_scope_id(self, payload: BatchJobSubmitRequest) -> str | None:
        if payload.scope_id or self.control_plane is None or not payload.integration_id:
            return payload.scope_id
        source = str((payload.payload or {}).get("source") or "")
        if source not in {"connector", "connector_monitor"}:
            return None

        matched_scope_ids: set[str] = set()
        for item in payload.items:
            selector = str(item.object_identity or "").strip()
            if not selector:
                return None
            matched = self.control_plane.match_scope(
                integration_id=payload.integration_id,
                scope_type="path",
                resource_selector=selector,
            )
            if matched is None:
                return None
            matched_scope_ids.add(matched.scope_id)
            if len(matched_scope_ids) > 1:
                return None
        return next(iter(matched_scope_ids), None)

    def list_jobs(
        self,
        *,
        integration_id: str | None = None,
        state: str | None = None,
        limit: int = 100,
    ) -> list[JobRecord]:
        return self.repo.list_jobs(integration_id=integration_id, state=state, limit=limit)

    def get_job_or_404(self, job_id: str) -> JobRecord:
        row = self.repo.get_job(job_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job_not_found")
        return row

    def get_batch_job_or_404(self, job_id: str) -> BatchJobRecord:
        job = self.get_job_or_404(job_id)
        return BatchJobRecord(job=job, item_summary=self.repo.summarize_job_items(job_id))

    def cancel_job(self, job_id: str) -> BatchJobRecord:
        job = self.get_job_or_404(job_id)
        cancellable_states = {
            "accepted",
            "publish_pending",
            "queued",
            "scanning",
            "scanned",
            "remediating",
            "deliver_pending",
            "delivering_result",
        }
        cancelled_at = datetime.now(timezone.utc)
        error = {
            "code": "job_cancelled",
            "message": "Job was cancelled by operator request.",
        }
        self.repo.update_job_state(job.job_id, state="cancelled", error=error, completed_at=cancelled_at)
        self.repo.cancel_job_items(
            job_id=job.job_id,
            states=cancellable_states,
            error=error,
            completed_at=cancelled_at,
        )
        return self.get_batch_job_or_404(job.job_id)

    def is_job_cancelled(self, job_id: str) -> bool:
        job = self.repo.get_job(job_id)
        return job is not None and (job.state == "cancelled" or (job.error or {}).get("code") == "job_cancelled")

    def get_job_item_or_404(self, job_item_id: str) -> JobItemRecord:
        row = self.repo.get_job_item(job_item_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job_item_not_found")
        return row

    def list_job_items(self, *, job_id: str, state: str | None = None, limit: int = 1000) -> list[JobItemRecord]:
        self.get_job_or_404(job_id)
        return self.repo.list_job_items(job_id=job_id, state=state, limit=limit)

    def get_job_progress(self, job_id: str, *, item_limit: int = 100) -> JobProgressSnapshot:
        job = self.get_job_or_404(job_id)
        summary = self.repo.summarize_job_items(job_id)
        bounded_limit = max(1, min(item_limit, 5000))
        items = self.repo.list_job_items(job_id=job_id, limit=bounded_limit)
        now = datetime.now(timezone.utc)
        terminal_items = summary.completed + summary.failed + summary.cancelled
        if summary.total and terminal_items == summary.total and job.state not in {"completed", "failed", "cancelled"}:
            self._refresh_parent_job_state(job_id)
            job = self.get_job_or_404(job_id)
        percent_complete = round((terminal_items / summary.total) * 100.0, 3) if summary.total else None
        last_activity_at = max((item.updated_at for item in items), default=job.updated_at)
        elapsed_seconds = max(0.0, ((job.completed_at or now) - job.created_at).total_seconds())
        recent_60s = self.repo.summarize_recent_terminal_job_items(job_id, since=now - timedelta(seconds=60))
        recent_300s = self.repo.summarize_recent_terminal_job_items(job_id, since=now - timedelta(seconds=300))

        throughput = self._build_throughput_snapshot(
            job=job,
            now=now,
            completed_items=summary.completed,
            failed_items=summary.failed,
            cancelled_items=summary.cancelled,
            recent_60s=recent_60s,
            recent_300s=recent_300s,
        )
        eta_seconds = None
        estimated_completion_at = None
        if summary.total and terminal_items < summary.total and throughput.recent_300s.items_per_second:
            eta_seconds = round((summary.total - terminal_items) / throughput.recent_300s.items_per_second, 3)
            estimated_completion_at = now + timedelta(seconds=eta_seconds)

        latency = self._build_latency_snapshot(items)
        runtime = JobRuntimeSnapshot(scan_leases_active=self._count_active_scan_runtime(job_id))
        backlog = JobBacklogSnapshot(
            accepted=summary.accepted,
            publish_pending=summary.publish_pending,
            queued=summary.queued,
            scanning=max(summary.scanning, runtime.scan_leases_active),
            scanned=summary.scanned,
            policy_pending=self.repo.count_policy_pending_items(job_id),
            remediation_pending=summary.remediating,
            delivery_pending=summary.deliver_pending + summary.delivering_result,
        )
        hints = self._build_bottleneck_hints(summary=summary, latency=latency, backlog=backlog)
        return JobProgressSnapshot(
            job_id=job.job_id,
            state=job.state,
            item_summary=summary,
            total_items=summary.total,
            terminal_items=terminal_items,
            percent_complete=percent_complete,
            elapsed_seconds=round(elapsed_seconds, 3),
            eta_seconds=eta_seconds,
            estimated_completion_at=estimated_completion_at,
            last_activity_at=last_activity_at,
            throughput=throughput,
            latency=latency,
            backlog=backlog,
            runtime=runtime,
            bottleneck_hints=hints,
            derived_from_item_count=len(items),
            derived_from_item_limit=bounded_limit,
        )

    def mark_scan_runtime_started(self, *, job_id: str, job_item_id: str) -> None:
        marker = getattr(self.repo, "mark_scan_runtime_started", None)
        if callable(marker):
            marker(job_id=job_id, job_item_id=job_item_id)

    def clear_scan_runtime(self, *, job_item_id: str) -> None:
        clearer = getattr(self.repo, "clear_scan_runtime", None)
        if callable(clearer):
            clearer(job_item_id=job_item_id)

    def _count_active_scan_runtime(self, job_id: str) -> int:
        counter = getattr(self.repo, "count_active_scan_runtime", None)
        if not callable(counter):
            return 0
        return int(counter(job_id))

    def _build_throughput_snapshot(
        self,
        *,
        job: JobRecord,
        now: datetime,
        completed_items: int,
        failed_items: int,
        cancelled_items: int,
        recent_60s: JobItemSummary,
        recent_300s: JobItemSummary,
    ) -> JobThroughputSnapshot:
        elapsed = max(0.001, ((job.completed_at or now) - job.created_at).total_seconds())
        terminal_items = completed_items + failed_items + cancelled_items

        def window(seconds: int, summary: JobItemSummary) -> ThroughputWindow:
            recent_terminal = summary.completed + summary.failed + summary.cancelled
            return ThroughputWindow(
                seconds=seconds,
                completed_items=summary.completed,
                terminal_items=recent_terminal,
                failed_items=summary.failed,
                cancelled_items=summary.cancelled,
                items_per_second=round(recent_terminal / seconds, 3),
            )

        return JobThroughputSnapshot(
            total=ThroughputWindow(
                seconds=None,
                completed_items=completed_items,
                terminal_items=terminal_items,
                failed_items=failed_items,
                cancelled_items=cancelled_items,
                items_per_second=round(terminal_items / elapsed, 3),
            ),
            recent_60s=window(60, recent_60s),
            recent_300s=window(300, recent_300s),
        )

    def _build_latency_snapshot(self, items: list[JobItemRecord]) -> JobLatencySnapshot:
        reader_values: list[float] = []
        stream_read_values: list[float] = []
        response_wait_values: list[float] = []
        scanner_engine_values: list[float] = []
        dsxa_values: list[float] = []
        request_values: list[float] = []
        scan_stage_values: list[float] = []
        queue_wait_values: list[float] = []
        for item in items:
            metadata = item.scan_stage.metadata or {}
            self._append_number(reader_values, metadata.get("readerElapsedMs"))
            self._append_number(stream_read_values, metadata.get("streamReadElapsedMs"))
            self._append_number(response_wait_values, metadata.get("scannerResponseWaitElapsedMs"))
            scan_duration_us = (item.scan_stage.result or {}).get("scan_duration_in_microseconds")
            if isinstance(scan_duration_us, (int, float)):
                scanner_engine_values.append(float(scan_duration_us) / 1000.0)
            else:
                self._append_number(scanner_engine_values, metadata.get("scannerEngineElapsedMs"))
            self._append_number(dsxa_values, metadata.get("dsxaElapsedMs"))
            self._append_number(request_values, metadata.get("requestElapsedMs"))
            if item.scan_stage.started_at and item.scan_stage.completed_at:
                scan_stage_values.append((item.scan_stage.completed_at - item.scan_stage.started_at).total_seconds() * 1000.0)
            if item.scan_stage.started_at:
                queue_wait_values.append((item.scan_stage.started_at - item.created_at).total_seconds() * 1000.0)
        return JobLatencySnapshot(
            reader_elapsed_ms=self._summarize_latency(reader_values),
            stream_read_elapsed_ms=self._summarize_latency(stream_read_values),
            scanner_response_wait_elapsed_ms=self._summarize_latency(response_wait_values),
            scanner_engine_elapsed_ms=self._summarize_latency(scanner_engine_values),
            dsxa_elapsed_ms=self._summarize_latency(dsxa_values),
            request_elapsed_ms=self._summarize_latency(request_values),
            scan_stage_ms=self._summarize_latency(scan_stage_values),
            queue_wait_ms=self._summarize_latency(queue_wait_values),
        )

    @staticmethod
    def _append_number(target: list[float], value: object) -> None:
        if isinstance(value, (int, float)):
            target.append(float(value))

    @staticmethod
    def _summarize_latency(values: list[float]) -> LatencySummary:
        if not values:
            return LatencySummary()
        ordered = sorted(values)
        p95_index = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * 0.95) - 1))
        return LatencySummary(
            count=len(ordered),
            avg_ms=round(sum(ordered) / len(ordered), 3),
            p95_ms=round(ordered[p95_index], 3),
        )

    def _build_bottleneck_hints(
        self,
        *,
        summary,
        latency: JobLatencySnapshot,
        backlog: JobBacklogSnapshot,
    ) -> list[BottleneckHint]:
        hints: list[BottleneckHint] = []
        if backlog.queued > max(100, summary.total * 0.1) and backlog.scanning == 0:
            hints.append(
                BottleneckHint(
                    code="scan_dispatch_backlog",
                    severity="warning",
                    message="Items are queued but no scan items are currently running.",
                    details={"queued": backlog.queued, "scanning": backlog.scanning},
                )
            )
        if latency.queue_wait_ms.avg_ms and latency.queue_wait_ms.avg_ms > 10_000:
            hints.append(
                BottleneckHint(
                    code="queue_wait_high",
                    severity="warning",
                    message="Average wait before scan start is high.",
                    details={"avg_ms": latency.queue_wait_ms.avg_ms, "p95_ms": latency.queue_wait_ms.p95_ms},
                )
            )
        if latency.dsxa_elapsed_ms.avg_ms and latency.reader_elapsed_ms.avg_ms:
            if latency.dsxa_elapsed_ms.avg_ms > latency.reader_elapsed_ms.avg_ms * 3 and latency.dsxa_elapsed_ms.avg_ms > 100:
                hints.append(
                    BottleneckHint(
                        code="scanner_api_latency_dominates",
                        severity="info",
                        message="Scanner API request wall time dominates reader elapsed time.",
                        details={
                            "scanner_api_avg_ms": latency.dsxa_elapsed_ms.avg_ms,
                            "reader_avg_ms": latency.reader_elapsed_ms.avg_ms,
                            "scanner_engine_avg_ms": latency.scanner_engine_elapsed_ms.avg_ms,
                        },
                    )
                )
            if latency.reader_elapsed_ms.avg_ms > latency.dsxa_elapsed_ms.avg_ms * 3 and latency.reader_elapsed_ms.avg_ms > 100:
                hints.append(
                    BottleneckHint(
                        code="reader_latency_dominates",
                        severity="info",
                        message="Reader elapsed time dominates DSXA elapsed time.",
                        details={"reader_avg_ms": latency.reader_elapsed_ms.avg_ms, "dsxa_avg_ms": latency.dsxa_elapsed_ms.avg_ms},
                    )
                )
        if summary.failed > 0 and summary.total and (summary.failed / summary.total) >= 0.05:
            hints.append(
                BottleneckHint(
                    code="failure_rate_high",
                    severity="warning",
                    message="At least 5% of job items have failed.",
                    details={"failed": summary.failed, "total": summary.total},
                )
            )
        return hints

    def list_outbox(
        self,
        *,
        publish_state: str | None = None,
        limit: int = 100,
    ) -> list[OutboxRecord]:
        return self.repo.list_outbox_records(publish_state=publish_state, limit=limit)

    def get_outbox_or_404(self, outbox_id: str) -> OutboxRecord:
        row = self.repo.get_outbox_record(outbox_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="outbox_not_found")
        return row

    def _refresh_parent_job_state(self, job_id: str) -> None:
        current_job = self.repo.get_job(job_id)
        if current_job is not None and (
            current_job.state == "cancelled" or (current_job.error or {}).get("code") == "job_cancelled"
        ):
            self.repo.update_job_state(
                job_id,
                state="cancelled",
                error=current_job.error,
                completed_at=current_job.completed_at or datetime.now(timezone.utc),
            )
            return
        summary = self.repo.summarize_job_items(job_id)
        if summary.total == 0:
            return
        if summary.publish_pending > 0:
            pending_items = [item for item in self.repo.list_job_items(job_id=job_id) if item.state == "publish_pending"]
            error_code = "batch_publish_partial_failure" if any(item.error for item in pending_items) else "batch_publish_pending"
            self.repo.update_job_state(job_id, state="publish_pending", error={"code": error_code})
            return
        if summary.scanning > 0 or summary.remediating > 0 or summary.delivering_result > 0:
            self.repo.update_job_state(job_id, state="running", error=None)
            return
        terminal_count = summary.completed + summary.failed + summary.cancelled
        if terminal_count == summary.total:
            if summary.cancelled == summary.total:
                self.repo.update_job_state(
                    job_id,
                    state="cancelled",
                    error={"code": "job_cancelled"},
                    completed_at=datetime.now(timezone.utc),
                )
                return
            if summary.failed > 0:
                self.repo.update_job_state(
                    job_id,
                    state="failed",
                    error={"code": "batch_item_failures", "failedItemCount": summary.failed},
                    completed_at=datetime.now(timezone.utc),
                )
                return
            self.repo.update_job_state(job_id, state="completed", error=None, completed_at=datetime.now(timezone.utc))
            return
        if summary.queued > 0 or summary.scanned > 0 or summary.deliver_pending > 0:
            self.repo.update_job_state(job_id, state="queued", error=None)
            return
        if summary.accepted == summary.total:
            self.repo.update_job_state(job_id, state="accepted", error=None)

    def _build_scan_item_requested(self, *, job: JobRecord, job_item: JobItemRecord) -> MessageEnvelope:
        message = ScanItemRequested(
            job_id=job.job_id,
            job_item_id=job_item.job_item_id,
            integration_id=job.integration_id,
            scope_id=job.scope_id,
            object_identity=job_item.object_identity,
            idempotency_key=job.idempotency_key,
            content_source=job_item.content_source.model_dump(mode="json"),
            read_hint={
                "objectIdentity": job_item.object_identity,
            },
            scan_options={
                **job.payload,
                **job_item.payload,
            },
        )
        return message.as_envelope()

    def _is_scan_only_batch_job(self, job: JobRecord, items: list[JobItemRecord]) -> bool:
        if job.payload.get("scanOnly") is True or job.payload.get("scan_only") is True:
            return True
        return bool(items) and all(item.payload.get("scanOnly") is True or item.payload.get("scan_only") is True for item in items)

    def replay_nonterminal_scan_only_batches(self, *, limit: int = 1000) -> int:
        terminal_states = {"completed", "failed", "cancelled"}
        replayed = 0
        for job in self.repo.list_jobs(limit=limit):
            if job.state in terminal_states:
                continue
            items = self.repo.list_job_items(job_id=job.job_id, limit=1_000_000)
            if not self._is_scan_only_batch_job(job, items):
                continue
            existing_scan_outbox_item_ids: set[str] = set()
            for outbox in self.repo.list_outbox_records(publish_state=None, limit=1_000_000):
                if outbox.job_id != job.job_id or outbox.topic != "scan.requested":
                    continue
                if outbox.publish_state not in {"pending", "publishing"}:
                    continue
                job_item_id = outbox.payload.get("job_item_id")
                if isinstance(job_item_id, str):
                    existing_scan_outbox_item_ids.add(job_item_id)
            for item in items:
                if item.state in terminal_states:
                    continue
                self.repo.update_job_item_state(
                    item.job_item_id,
                    state="publish_pending",
                    error={"code": "scan_only_batch_replay"},
                    completed_at=None,
                )
                if item.job_item_id in existing_scan_outbox_item_ids:
                    continue
                self.repo.create_outbox_record(
                    job=job,
                    topic="scan.requested",
                    payload=self._build_scan_item_requested(job=job, job_item=item).model_dump(mode="json"),
                )
                replayed += 1
            self.repo.update_job_state(job.job_id, state="publish_pending", error={"code": "scan_only_batch_replay"})
        return replayed

    def _build_dianna_analysis_requested(
        self,
        *,
        job: JobRecord,
        job_item: JobItemRecord,
        payload: DiannaAnalysisRequest,
    ) -> MessageEnvelope:
        message = DiannaAnalysisRequested(
            job_id=job.job_id,
            job_item_id=job_item.job_item_id,
            integration_id=job.integration_id,
            scope_id=job.scope_id,
            object_identity=job_item.object_identity,
            idempotency_key=job.idempotency_key,
            content_source=job_item.content_source.model_dump(mode="json"),
            request_reason=payload.reason,
            scan_result=job_item.scan_stage.result or {},
            request_options=payload.payload,
        )
        return message.as_envelope()

    def _build_policy_evaluation_requested(
        self,
        *,
        job: JobRecord,
        job_item: JobItemRecord,
    ) -> MessageEnvelope:
        policy_context, item_metadata = self._build_policy_handoff_context(job=job, job_item=job_item)
        message = PolicyEvaluationRequested(
            job_id=job.job_id,
            job_item_id=job_item.job_item_id,
            integration_id=job.integration_id,
            scope_id=job.scope_id,
            object_identity=job_item.object_identity,
            idempotency_key=job.idempotency_key,
            scan_result=job_item.scan_stage.result or {},
            item_payload=job_item.payload,
            policy_context=policy_context,
            item_metadata=item_metadata,
        )
        return message.as_envelope()

    def _build_result_sink_emit_requested(
        self,
        *,
        job: JobRecord,
        job_item: JobItemRecord,
        payload: DeliveryRequest,
        result_type: str = "workflow_summary",
        result_payload: dict | None = None,
    ) -> MessageEnvelope:
        message = ResultSinkEmitRequested(
            job_id=job.job_id,
            job_item_id=job_item.job_item_id,
            integration_id=job.integration_id,
            scope_id=job.scope_id,
            object_identity=job_item.object_identity,
            result_type=result_type,
            result_payload=result_payload or {},
            final_result=self._build_final_result(job_item),
            delivery_target=payload.delivery_target,
        )
        return message.as_envelope()

    def _build_remediation_requested(
        self,
        *,
        job: JobRecord,
        job_item: JobItemRecord,
        payload: RemediationRequest,
    ) -> MessageEnvelope:
        message = RemediationRequested(
            job_id=job.job_id,
            job_item_id=job_item.job_item_id,
            integration_id=job.integration_id,
            scope_id=job.scope_id,
            object_identity=job_item.object_identity,
            content_source=job_item.content_source,
            scan_result=job_item.scan_stage.result or {},
            remediation_plan=payload.remediation_plan,
        )
        return message.as_envelope()

    def _build_final_result(self, job_item: JobItemRecord) -> dict:
        return {
            "objectIdentity": job_item.object_identity,
            "scan": job_item.scan_stage.result or {},
            "scanMetadata": job_item.scan_stage.metadata or {},
            "remediation": job_item.remediation_stage.result or {},
            "dianna": job_item.dianna_stage.result or {},
            "contentSource": job_item.content_source.model_dump(mode="json"),
        }

    def _build_policy_handoff_context(self, *, job: JobRecord, job_item: JobItemRecord) -> tuple[dict, dict]:
        if self.control_plane is None:
            return {}, {}
        integration = self.control_plane.get_integration_or_404(job.integration_id) if job.integration_id else None
        scope = self.control_plane.get_scope_or_404(job.scope_id) if job.scope_id else None
        integration_config = integration.config if integration is not None else {}
        scope_policy = scope.post_scan_policy if scope is not None else {}
        resolved_policy = resolve_policy_runtime_config(integration_config, scope_policy)
        policy_context = {
            "integration_config": integration_config,
            "scope_policy": scope_policy,
            "resolved_policy": resolved_policy.model_dump(mode="json", exclude_none=True),
        }
        item_metadata = {
            "integration": (
                {
                    "integration_id": integration.integration_id,
                    "platform": integration.platform,
                    "platform_key": integration.platform_key,
                }
                if integration is not None
                else {}
            ),
            "scope": (
                {
                    "scope_id": scope.scope_id,
                    "scope_type": scope.scope_type,
                    "scope_mode": scope.mode,
                    "resource_selector": scope.resource_selector,
                    "normalized_selector": scope.normalized_selector,
                }
                if scope is not None
                else {}
            ),
        }
        return policy_context, item_metadata

    def _delivery_blocked_by_dianna(self, job_item: JobItemRecord) -> bool:
        if not job_item.delivery_requirements.wait_for_dianna:
            return False
        return job_item.dianna_stage.state not in {"completed", "failed", "skipped"}

    def _extract_remediation_plan(self, job_item: JobItemRecord) -> dict:
        handoff = self._extract_policy_handoff_decision(job_item)
        if handoff is not None:
            return handoff.remediation.details.get("remediation_plan", {})
        policy_result = job_item.policy_stage.result or {}
        return (
            policy_result.get("remediation_plan")
            or policy_result.get("remediationPlan")
            or job_item.payload.get("remediationPlan")
            or job_item.payload.get("remediation_plan")
            or {}
        )

    def _extract_delivery_target(self, job_item: JobItemRecord, *, result_type: str = "workflow_summary") -> dict:
        handoff = self._extract_policy_handoff_decision(job_item)
        if handoff is not None:
            targets = self._extract_delivery_targets_from_handoff(handoff, result_type=result_type)
            if targets:
                return targets[0]
        policy_result = job_item.policy_stage.result or {}
        return (
            policy_result.get("delivery_target")
            or policy_result.get("deliveryTarget")
            or job_item.payload.get("deliveryTarget")
            or job_item.payload.get("delivery_target")
            or {}
        )

    @staticmethod
    def _extract_delivery_targets_from_handoff(handoff: PolicyHandoffDecision, *, result_type: str) -> list[dict]:
        delivery = handoff.delivery
        target_config = {
            "scan_result": (delivery.scan_targets, delivery.scan_targets_configured),
            "remediation_result": (delivery.remediation_targets, delivery.remediation_targets_configured),
            "dianna_result": (delivery.dianna_targets, delivery.dianna_targets_configured),
            "workflow_summary": (
                delivery.workflow_summary_targets,
                delivery.workflow_summary_targets_configured,
            ),
        }.get(result_type)
        if target_config is None:
            return delivery.targets
        candidate_targets, configured = target_config
        return candidate_targets if configured else candidate_targets or delivery.targets

    def _extract_policy_handoff_decision(self, job_item: JobItemRecord) -> PolicyHandoffDecision | None:
        policy_result = job_item.policy_stage.result or {}
        if "policy_stage_result" in policy_result:
            return PolicyHandoffDecision.model_validate(policy_result)
        return None

    def _extract_legacy_policy_decision(self, job_item: JobItemRecord) -> PolicyDecision:
        return PolicyDecision.model_validate(job_item.policy_stage.result or {})

    def _extract_content_preservation(self, job_item: JobItemRecord) -> ContentPreservationDecision | None:
        handoff = self._extract_policy_handoff_decision(job_item)
        if handoff is None:
            return None
        return handoff.content_preservation

    def _scan_result_should_be_delivered(self, job_item: JobItemRecord) -> bool:
        handoff = self._extract_policy_handoff_decision(job_item)
        if handoff is None:
            return False
        mode = handoff.result_delivery_policy.scan
        if mode == "never":
            return False
        verdict = ((job_item.scan_stage.result or {}).get("verdict") or "").strip().lower()
        if mode == "all_results":
            return True
        if mode == "malicious_only":
            return verdict in {"malicious", "suspicious"}
        return False

    def _remediation_result_should_be_delivered(self, job_item: JobItemRecord) -> bool:
        handoff = self._extract_policy_handoff_decision(job_item)
        if handoff is None:
            return False
        mode = handoff.result_delivery_policy.remediation
        if mode == "never":
            return False
        if mode == "all_outcomes":
            return True
        if mode == "failures_only":
            return job_item.remediation_stage.state == "failed"
        return False

    def _dianna_result_should_be_delivered(self, job_item: JobItemRecord) -> bool:
        handoff = self._extract_policy_handoff_decision(job_item)
        if handoff is None:
            return False
        mode = handoff.result_delivery_policy.dianna
        if mode == "never":
            return False
        if mode == "completed_only":
            return job_item.dianna_stage.state == "completed"
        if mode == "all_outcomes":
            return job_item.dianna_stage.state in {"completed", "failed", "skipped"}
        return False

    def _scan_verdict_reason(self, job_item: JobItemRecord) -> str:
        verdict = ((job_item.scan_stage.result or {}).get("verdict") or "").strip().lower()
        if verdict == "benign":
            return "benign_verdict"
        return "below_policy_threshold"

    def _build_remediation_skipped_result(self, job_item: JobItemRecord) -> dict:
        handoff = self._extract_policy_handoff_decision(job_item)
        if handoff is not None and handoff.remediation.state == "requested":
            return {"reason": "remediation_not_executed"}
        policy_result = job_item.policy_stage.result or {}
        if policy_result.get("remediation_plan") or policy_result.get("remediationPlan"):
            return {"reason": "remediation_not_executed"}
        verdict = ((job_item.scan_stage.result or {}).get("verdict") or "").strip().lower()
        if verdict == "benign":
            reason = "benign_verdict"
        else:
            reason = "remediation_not_configured"
        return {"reason": reason}

    def _build_dianna_skipped_result(self, job_item: JobItemRecord) -> dict:
        handoff = self._extract_policy_handoff_decision(job_item)
        if handoff is not None and handoff.dianna.reason:
            result = {"reason": handoff.dianna.reason}
            if handoff.dianna.details:
                result["details"] = handoff.dianna.details
            return result
        verdict = ((job_item.scan_stage.result or {}).get("verdict") or "").strip()
        result = {"reason": "not_auto_requested"}
        if verdict:
            result["details"] = {"verdict": verdict}
        return result

    def _derive_item_state_from_stages(self, current: JobItemRecord, *, stage_name: str, stage_record: StageRecord) -> tuple[str, dict | None, datetime | None]:
        scan_stage = current.scan_stage
        policy_stage = current.policy_stage
        remediation_stage = current.remediation_stage
        delivery_stage = current.delivery_stage
        dianna_stage = current.dianna_stage
        if stage_name == "scan_stage":
            scan_stage = stage_record
        elif stage_name == "policy_stage":
            policy_stage = stage_record
        elif stage_name == "remediation_stage":
            remediation_stage = stage_record
        elif stage_name == "delivery_stage":
            delivery_stage = stage_record
        elif stage_name == "dianna_stage":
            dianna_stage = stage_record

        completed_at = None
        item_error = None
        item_state = current.state

        if stage_name == "dianna_stage":
            return item_state, current.error, current.completed_at

        if scan_stage.state == "running":
            return "scanning", None, None
        if scan_stage.state == "failed":
            return "failed", scan_stage.error, datetime.now(timezone.utc)
        if scan_stage.state != "completed":
            return item_state, current.error, current.completed_at

        if policy_stage.state == "running":
            return "scanned", None, None
        if policy_stage.state == "failed":
            return "failed", policy_stage.error, datetime.now(timezone.utc)

        if remediation_stage.state == "running":
            return "remediating", None, None
        if remediation_stage.state == "failed":
            return "failed", remediation_stage.error, datetime.now(timezone.utc)

        if delivery_stage.state == "running":
            return "delivering_result", None, None
        if delivery_stage.state == "failed":
            return "failed", delivery_stage.error, datetime.now(timezone.utc)
        if delivery_stage.state == "pending":
            if remediation_stage.state == "pending":
                return "scanned", None, None
            return "deliver_pending", None, None

        if delivery_stage.state in {"completed", "skipped"}:
            completed_at = datetime.now(timezone.utc)
            return "completed", None, completed_at

        if remediation_stage.state in {"completed", "skipped"} and delivery_stage.state == "skipped":
            completed_at = datetime.now(timezone.utc)
            return "completed", None, completed_at

        return item_state, item_error, completed_at

    async def _maybe_emit_follow_on_requests(self, job_item: JobItemRecord, *, stage_name: str, payload: StageUpdateRequest) -> None:
        if payload.state not in {"completed", "skipped"}:
            return
        if stage_name == "policy_stage":
            handoff = self._extract_policy_handoff_decision(job_item)
            decision = self._extract_legacy_policy_decision(job_item) if handoff is None else None
            if handoff is not None:
                if handoff.delivery.wait_for_dianna:
                    self.repo.update_job_item_delivery_requirements(
                        job_item.job_item_id,
                        wait_for_dianna=True,
                    )
                    job_item = self.get_job_item_or_404(job_item.job_item_id)
                preservation = handoff.content_preservation
                if preservation.mode in {"cached", "quarantine"}:
                    locator = preservation.details.get("locator") or job_item.content_source.locator
                    updated_source = job_item.content_source.model_copy(
                        update={"mode": preservation.mode, "locator": locator}
                    )
                    self.repo.update_job_item_content_source(job_item.job_item_id, updated_source)
                    job_item = self.get_job_item_or_404(job_item.job_item_id)
                if handoff.dianna.state == "requested":
                    await self.request_dianna_analysis(
                        job_item.job_item_id,
                        DiannaAnalysisRequest(
                            reason="auto_on_malicious",
                            wait_for_delivery=handoff.delivery.wait_for_dianna,
                            payload=handoff.dianna.details,
                        ),
                    )
                    job_item = self.get_job_item_or_404(job_item.job_item_id)
                elif job_item.dianna_stage.state == "pending":
                    self.update_dianna_stage(
                        job_item.job_item_id,
                        StageUpdateRequest(
                            state="skipped",
                            result=self._build_dianna_skipped_result(job_item),
                        ),
                    )
                    job_item = self.get_job_item_or_404(job_item.job_item_id)
                remediation_plan = handoff.remediation.details.get("remediation_plan", {})
                if handoff.remediation.state == "requested" and remediation_plan:
                    await self.request_remediation(
                        job_item.job_item_id,
                        RemediationRequest(remediation_plan=remediation_plan),
                    )
                    return
                if job_item.remediation_stage.state == "pending":
                    self.update_remediation_stage(
                        job_item.job_item_id,
                        StageUpdateRequest(
                            state="skipped",
                            result=self._build_remediation_skipped_result(job_item),
                        ),
                    )
                    job_item = self.get_job_item_or_404(job_item.job_item_id)
                if self._scan_result_should_be_delivered(job_item):
                    await self.request_stage_result_delivery(
                        job_item.job_item_id,
                        result_type="scan_result",
                        result_payload=job_item.scan_stage.result or {},
                    )
                    job_item = self.get_job_item_or_404(job_item.job_item_id)
                await self._maybe_request_workflow_summary_emit(job_item)
                return
            if decision.wait_for_dianna_before_delivery:
                self.repo.update_job_item_delivery_requirements(
                    job_item.job_item_id,
                    wait_for_dianna=True,
                )
                job_item = self.get_job_item_or_404(job_item.job_item_id)
            if decision.request_dianna:
                await self.request_dianna_analysis(
                    job_item.job_item_id,
                    DiannaAnalysisRequest(
                        reason=decision.dianna_reason,
                        wait_for_delivery=decision.wait_for_dianna_before_delivery,
                        payload=decision.dianna_options,
                    ),
                )
                job_item = self.get_job_item_or_404(job_item.job_item_id)
            elif job_item.dianna_stage.state == "pending":
                self.update_dianna_stage(
                    job_item.job_item_id,
                    StageUpdateRequest(
                        state="skipped",
                        result=self._build_dianna_skipped_result(job_item),
                    ),
                )
                job_item = self.get_job_item_or_404(job_item.job_item_id)
            if decision.remediation_plan:
                await self.request_remediation(
                    job_item.job_item_id,
                    RemediationRequest(remediation_plan=decision.remediation_plan),
                )
                return
            if job_item.remediation_stage.state == "pending":
                self.update_remediation_stage(
                    job_item.job_item_id,
                    StageUpdateRequest(
                        state="skipped",
                        result=self._build_remediation_skipped_result(job_item),
                    ),
                )
                job_item = self.get_job_item_or_404(job_item.job_item_id)
            if self._scan_result_should_be_delivered(job_item):
                await self.request_stage_result_delivery(
                    job_item.job_item_id,
                    result_type="scan_result",
                    result_payload=job_item.scan_stage.result or {},
                )
                job_item = self.get_job_item_or_404(job_item.job_item_id)
            await self._maybe_request_workflow_summary_emit(job_item)
            return
        if stage_name == "remediation_stage":
            if self._remediation_result_should_be_delivered(job_item):
                await self.request_stage_result_delivery(
                    job_item.job_item_id,
                    result_type="remediation_result",
                    result_payload=job_item.remediation_stage.result or {},
                )
                job_item = self.get_job_item_or_404(job_item.job_item_id)
            await self._maybe_request_workflow_summary_emit(job_item)
            return
        if stage_name == "dianna_stage" and job_item.delivery_requirements.wait_for_dianna:
            if self._dianna_result_should_be_delivered(job_item):
                await self.request_stage_result_delivery(
                    job_item.job_item_id,
                    result_type="dianna_result",
                    result_payload=job_item.dianna_stage.result or {},
                )
                job_item = self.get_job_item_or_404(job_item.job_item_id)
            await self._maybe_request_workflow_summary_emit(job_item)

    async def _maybe_request_workflow_summary_emit(self, job_item: JobItemRecord) -> None:
        delivery_target = self._extract_delivery_target(job_item, result_type="workflow_summary")
        if not delivery_target:
            if (
                job_item.delivery_stage.state == "pending"
                and job_item.remediation_stage.state in {"completed", "failed", "skipped"}
                and not self._delivery_blocked_by_dianna(job_item)
            ):
                self.update_delivery_stage(
                    job_item.job_item_id,
                    StageUpdateRequest(
                        state="skipped",
                        result={"reason": "workflow_summary_not_requested"},
                    ),
                )
            return
        try:
            await self.request_workflow_summary_emit(
                job_item.job_item_id,
                DeliveryRequest(delivery_target=delivery_target),
            )
        except HTTPException as exc:
            if exc.status_code == status.HTTP_409_CONFLICT and exc.detail in {
                "delivery_waiting_on_dianna",
                "delivery_requires_terminal_remediation_state",
            }:
                return
            raise

    async def request_stage_result_delivery(
        self,
        job_item_id: str,
        *,
        result_type: str,
        result_payload: dict,
    ) -> JobItemRecord:
        current = self.get_job_item_or_404(job_item_id)
        job = self.get_job_or_404(current.job_id)
        delivery_target = self._extract_delivery_target(current, result_type=result_type)
        if not delivery_target:
            return current
        requested = self._build_result_sink_emit_requested(
            job=job,
            job_item=current,
            payload=DeliveryRequest(delivery_target=delivery_target),
            result_type=result_type,
            result_payload=result_payload,
        )
        outbox = self.repo.create_outbox_record(
            job=job,
            topic="result_sink.emit.requested",
            payload=requested.model_dump(mode="json"),
        )
        await self._publish_outbox_record(outbox)
        refreshed = self.repo.get_job_item(current.job_item_id)
        if refreshed is None:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="job_item_state_update_failed")
        if refreshed.remediation_stage.state in {"completed", "skipped"} and refreshed.delivery_stage.state == "pending":
            refreshed = self.update_delivery_stage(
                job_item_id,
                StageUpdateRequest(
                    state="skipped",
                    result={"reason": "auxiliary_result_delivery_not_required", "result_type": result_type},
                ),
            )
        return refreshed

    def _update_job_item_stage(
        self,
        job_item_id: str,
        *,
        stage_name: str,
        payload: StageUpdateRequest,
        refresh_parent: bool = True,
    ) -> JobItemRecord:
        current = self.get_job_item_or_404(job_item_id)
        return self._update_job_item_stage_from_current(
            current,
            stage_name=stage_name,
            payload=payload,
            refresh_parent=refresh_parent,
        )

    def _update_job_item_stage_from_current(
        self,
        current: JobItemRecord,
        *,
        stage_name: str,
        payload: StageUpdateRequest,
        refresh_parent: bool = True,
    ) -> JobItemRecord:
        existing_stage = getattr(current, stage_name)
        started_at = existing_stage.started_at
        if payload.state == "running" and started_at is None:
            started_at = datetime.now(timezone.utc)
        completed_at = datetime.now(timezone.utc) if payload.state in {"completed", "failed", "skipped"} else None
        stage_record = StageRecord(
            state=payload.state,
            started_at=started_at,
            completed_at=completed_at,
            result=payload.result,
            metadata=payload.metadata,
            error=payload.error,
        )
        item_state, item_error, item_completed_at = self._derive_item_state_from_stages(
            current,
            stage_name=stage_name,
            stage_record=stage_record,
        )
        updated = self.repo.update_job_item_stage(
            current.job_item_id,
            stage_name=stage_name,
            stage_record=stage_record,
            state=item_state,
            error=item_error,
            completed_at=item_completed_at,
        )
        if updated is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job_item_not_found")
        if refresh_parent:
            self._refresh_parent_job_state(current.job_id)
        refreshed = self.repo.get_job_item(current.job_item_id)
        if refreshed is None:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="job_item_state_update_failed")
        return refreshed

    def update_scan_stage(self, job_item_id: str, payload: StageUpdateRequest, *, refresh_parent: bool = True) -> JobItemRecord:
        return self._update_job_item_stage(job_item_id, stage_name="scan_stage", payload=payload, refresh_parent=refresh_parent)

    def update_policy_stage(self, job_item_id: str, payload: StageUpdateRequest, *, refresh_parent: bool = True) -> JobItemRecord:
        return self._update_job_item_stage(job_item_id, stage_name="policy_stage", payload=payload, refresh_parent=refresh_parent)

    def update_remediation_stage(self, job_item_id: str, payload: StageUpdateRequest, *, refresh_parent: bool = True) -> JobItemRecord:
        return self._update_job_item_stage(job_item_id, stage_name="remediation_stage", payload=payload, refresh_parent=refresh_parent)

    def update_delivery_stage(self, job_item_id: str, payload: StageUpdateRequest, *, refresh_parent: bool = True) -> JobItemRecord:
        return self._update_job_item_stage(job_item_id, stage_name="delivery_stage", payload=payload, refresh_parent=refresh_parent)

    def update_dianna_stage(self, job_item_id: str, payload: StageUpdateRequest, *, refresh_parent: bool = True) -> JobItemRecord:
        return self._update_job_item_stage(job_item_id, stage_name="dianna_stage", payload=payload, refresh_parent=refresh_parent)

    async def advance_scan_stage(self, job_item_id: str, payload: StageUpdateRequest) -> JobItemRecord:
        updated = self.update_scan_stage(job_item_id, payload)
        await self._maybe_emit_follow_on_requests(updated, stage_name="scan_stage", payload=payload)
        return self.get_job_item_or_404(job_item_id)

    async def advance_policy_stage(self, job_item_id: str, payload: StageUpdateRequest) -> JobItemRecord:
        fast_completed = await self._try_fast_complete_policy_stage(job_item_id, payload)
        if fast_completed is not None:
            return fast_completed
        updated = self.update_policy_stage(job_item_id, payload)
        await self._maybe_emit_follow_on_requests(updated, stage_name="policy_stage", payload=payload)
        return self.get_job_item_or_404(job_item_id)

    async def _try_fast_complete_policy_stage(
        self,
        job_item_id: str,
        payload: StageUpdateRequest,
    ) -> JobItemRecord | None:
        if payload.state != "completed" or not payload.result:
            return None
        if "policy_stage_result" not in payload.result:
            return None
        handoff = PolicyHandoffDecision.model_validate(payload.result)
        if handoff.delivery.wait_for_dianna:
            return None
        if handoff.dianna.state == "requested":
            return None
        if handoff.remediation.state == "requested":
            return None
        if handoff.content_preservation.mode in {"cached", "quarantine"}:
            return None
        if self._extract_delivery_targets_from_handoff(handoff, result_type="workflow_summary"):
            return None

        current = self.get_job_item_or_404(job_item_id)
        if current.scan_stage.state != "completed":
            return None
        job = self.get_job_or_404(current.job_id)
        scan_result = current.scan_stage.result or {}
        scan_result_delivery_requested = False
        if self._scan_result_should_be_delivered_for_handoff(handoff, scan_result):
            scan_targets = self._extract_delivery_targets_from_handoff(handoff, result_type="scan_result")
            if scan_targets:
                scan_result_delivery_requested = True
                requested = self._build_result_sink_emit_requested(
                    job=job,
                    job_item=current,
                    payload=DeliveryRequest(delivery_target=scan_targets[0]),
                    result_type="scan_result",
                    result_payload=scan_result,
                )
                outbox = self.repo.create_outbox_record(
                    job=job,
                    topic="result_sink.emit.requested",
                    payload=requested.model_dump(mode="json"),
                )
                await self._publish_outbox_record(outbox, update_item_stage=False)

        now = datetime.now(timezone.utc)
        policy_stage = StageRecord(
            state="completed",
            started_at=current.policy_stage.started_at,
            completed_at=now,
            result=payload.result,
            metadata=payload.metadata,
            error=payload.error,
        )
        dianna_stage = StageRecord(
            state="skipped",
            completed_at=now,
            result=self._build_dianna_skipped_result_from_handoff(handoff, scan_result),
        )
        remediation_stage = StageRecord(
            state="skipped",
            completed_at=now,
            result=self._build_remediation_skipped_result_from_handoff(handoff, scan_result),
        )
        delivery_stage = StageRecord(
            state="skipped",
            completed_at=now,
            result=(
                {"reason": "auxiliary_result_delivery_not_required", "result_type": "scan_result"}
                if scan_result_delivery_requested
                else {"reason": "workflow_summary_not_requested"}
            ),
        )
        updated = self.repo.update_job_item_stages(
            current.job_item_id,
            stage_records={
                "policy_stage": policy_stage,
                "dianna_stage": dianna_stage,
                "remediation_stage": remediation_stage,
                "delivery_stage": delivery_stage,
            },
            state="completed",
            error=None,
            completed_at=now,
        )
        if updated is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job_item_not_found")
        return updated

    @staticmethod
    def _scan_result_should_be_delivered_for_handoff(handoff: PolicyHandoffDecision, scan_result: dict) -> bool:
        mode = handoff.result_delivery_policy.scan
        if mode == "never":
            return False
        verdict = (scan_result.get("verdict") or "").strip().lower()
        if mode == "all_results":
            return True
        if mode == "malicious_only":
            return verdict in {"malicious", "suspicious"}
        return False

    @staticmethod
    def _build_dianna_skipped_result_from_handoff(handoff: PolicyHandoffDecision, scan_result: dict) -> dict:
        if handoff.dianna.reason:
            result = {"reason": handoff.dianna.reason}
            if handoff.dianna.details:
                result["details"] = handoff.dianna.details
            return result
        verdict = (scan_result.get("verdict") or "").strip()
        return {"reason": "not_auto_requested", "details": {"verdict": verdict}} if verdict else {"reason": "not_auto_requested"}

    @staticmethod
    def _build_remediation_skipped_result_from_handoff(handoff: PolicyHandoffDecision, scan_result: dict) -> dict:
        if handoff.remediation.reason:
            return {"reason": handoff.remediation.reason}
        verdict = (scan_result.get("verdict") or "").strip().lower()
        if verdict == "benign":
            return {"reason": "benign_verdict"}
        return {"reason": "remediation_not_configured"}

    async def advance_remediation_stage(self, job_item_id: str, payload: StageUpdateRequest) -> JobItemRecord:
        updated = self.update_remediation_stage(job_item_id, payload)
        await self._maybe_emit_follow_on_requests(updated, stage_name="remediation_stage", payload=payload)
        return self.get_job_item_or_404(job_item_id)

    async def advance_delivery_stage(self, job_item_id: str, payload: StageUpdateRequest) -> JobItemRecord:
        self.update_delivery_stage(job_item_id, payload)
        return self.get_job_item_or_404(job_item_id)

    async def advance_dianna_stage(self, job_item_id: str, payload: StageUpdateRequest) -> JobItemRecord:
        updated = self.update_dianna_stage(job_item_id, payload)
        await self._maybe_emit_follow_on_requests(updated, stage_name="dianna_stage", payload=payload)
        return self.get_job_item_or_404(job_item_id)

    async def request_remediation(self, job_item_id: str, payload: RemediationRequest) -> JobItemRecord:
        current = self.get_job_item_or_404(job_item_id)
        job = self.get_job_or_404(current.job_id)
        if current.scan_stage.state != "completed":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="remediation_requires_completed_scan")
        if not payload.remediation_plan:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="remediation_plan_required")
        requested = self._build_remediation_requested(job=job, job_item=current, payload=payload)
        outbox = self.repo.create_outbox_record(
            job=job,
            topic="remediation.requested",
            payload=requested.model_dump(mode="json"),
        )
        await self._publish_outbox_record(outbox)
        refreshed = self.repo.get_job_item(job_item_id)
        if refreshed is None:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="job_item_state_update_failed")
        return refreshed

    async def request_policy_evaluation(self, job_item_id: str) -> JobItemRecord:
        current = self.get_job_item_or_404(job_item_id)
        job = self.get_job_or_404(current.job_id)
        if current.scan_stage.state != "completed":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="policy_requires_completed_scan")
        requested = self._build_policy_evaluation_requested(job=job, job_item=current)
        outbox = self.repo.create_outbox_record(
            job=job,
            topic="policy.requested",
            payload=requested.model_dump(mode="json"),
        )
        await self._publish_outbox_record(outbox)
        refreshed = self.repo.get_job_item(job_item_id)
        if refreshed is None:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="job_item_state_update_failed")
        return refreshed

    async def complete_scan_and_request_policy(self, job_item_id: str, payload: StageUpdateRequest) -> JobItemRecord:
        current = self.get_job_item_or_404(job_item_id)
        updated = self._update_job_item_stage_from_current(
            current,
            stage_name="scan_stage",
            payload=payload,
            refresh_parent=False,
        )
        job = self.get_job_or_404(updated.job_id)
        if updated.scan_stage.state != "completed":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="policy_requires_completed_scan")
        requested = self._build_policy_evaluation_requested(job=job, job_item=updated)
        outbox = self.repo.create_outbox_record(
            job=job,
            topic="policy.requested",
            payload=requested.model_dump(mode="json"),
        )
        await self._publish_outbox_record(outbox)
        refreshed = self.repo.get_job_item(job_item_id)
        if refreshed is None:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="job_item_state_update_failed")
        return refreshed

    def complete_scan_only(self, job_item_id: str, payload: StageUpdateRequest) -> JobItemRecord:
        if payload.state != "completed" or not payload.result:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="scan_only_requires_completed_scan")
        current = self.get_job_item_or_404(job_item_id)
        now, stage_records = self._build_scan_only_completion_stages(current=current, payload=payload)
        updated = self.repo.update_job_item_stages(
            current.job_item_id,
            stage_records=stage_records,
            state="completed",
            error=None,
            completed_at=now,
        )
        if updated is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job_item_not_found")
        return updated

    def complete_scan_only_bulk(
        self,
        updates: list[tuple[str, str, StageUpdateRequest]],
        *,
        refresh_parent: bool = True,
    ) -> int:
        if not updates:
            return 0
        job_ids = {job_id for job_id, _job_item_id, _payload in updates}
        bulk_update = getattr(self.repo, "update_job_items_stages_bulk", None)
        if not callable(bulk_update):
            count = 0
            for _job_id, job_item_id, payload in updates:
                self.complete_scan_only(job_item_id, payload)
                count += 1
            if refresh_parent:
                for job_id in job_ids:
                    self._refresh_parent_job_state(job_id)
            return count
        rows: list[dict[str, object]] = []
        for job_id, job_item_id, payload in updates:
            if payload.state != "completed" or not payload.result:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="scan_only_requires_completed_scan")
            now, stage_records = self._build_scan_only_completion_stages(current=None, payload=payload)
            rows.append(
                {
                    "job_id": job_id,
                    "job_item_id": job_item_id,
                    "stage_records": stage_records,
                    "state": "completed",
                    "error": None,
                    "completed_at": now,
                }
            )
        count = int(bulk_update(rows))
        if refresh_parent:
            for job_id in job_ids:
                self._refresh_parent_job_state(job_id)
        return count

    def _build_scan_only_completion_stages(
        self,
        *,
        current: JobItemRecord | None,
        payload: StageUpdateRequest,
    ) -> tuple[datetime, dict[str, StageRecord]]:
        existing_scan_stage = current.scan_stage if current is not None else StageRecord()
        now = datetime.now(timezone.utc)
        scan_stage = StageRecord(
            state="completed",
            started_at=existing_scan_stage.started_at,
            completed_at=now,
            result=payload.result,
            metadata=payload.metadata,
            error=payload.error,
        )
        verdict = (payload.result.get("verdict") or payload.result.get("verdictName") or "").strip()
        return (
            now,
            {
                "scan_stage": scan_stage,
                "policy_stage": StageRecord(
                    state="skipped",
                    completed_at=now,
                    result={"reason": "scan_only"},
                ),
                "dianna_stage": StageRecord(
                    state="skipped",
                    completed_at=now,
                    result={"reason": "scan_only", "details": {"verdict": verdict}} if verdict else {"reason": "scan_only"},
                ),
                "remediation_stage": StageRecord(
                    state="skipped",
                    completed_at=now,
                    result={"reason": "scan_only"},
                ),
                "delivery_stage": StageRecord(
                    state="skipped",
                    completed_at=now,
                    result={"reason": "scan_only"},
                ),
            },
        )

    async def request_dianna_analysis(self, job_item_id: str, payload: DiannaAnalysisRequest) -> JobItemRecord:
        current = self.get_job_item_or_404(job_item_id)
        job = self.get_job_or_404(current.job_id)
        scan_state = current.scan_stage.state
        verdict = ((current.scan_stage.result or {}).get("verdict") or "").lower()
        if scan_state != "completed":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="dianna_requires_completed_scan")
        if verdict and verdict not in {"malicious", "suspicious"}:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="dianna_not_applicable_for_non_malicious_scan")
        if current.content_source.mode == "none":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="dianna_requires_available_content_source")
        if payload.wait_for_delivery:
            current = self.repo.update_job_item_delivery_requirements(job_item_id, wait_for_dianna=True) or current
        requested = self._build_dianna_analysis_requested(job=job, job_item=current, payload=payload)
        outbox = self.repo.create_outbox_record(
            job=job,
            topic="dianna.requested",
            payload=requested.model_dump(mode="json"),
        )
        await self._publish_outbox_record(outbox)
        refreshed = self.repo.get_job_item(job_item_id)
        if refreshed is None:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="job_item_state_update_failed")
        return refreshed

    async def request_workflow_summary_emit(self, job_item_id: str, payload: DeliveryRequest) -> JobItemRecord:
        current = self.get_job_item_or_404(job_item_id)
        job = self.get_job_or_404(current.job_id)
        if current.scan_stage.state != "completed":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="delivery_requires_completed_scan")
        if current.remediation_stage.state not in {"pending", "completed", "failed", "skipped"}:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="delivery_requires_terminal_remediation_state")
        if self._delivery_blocked_by_dianna(current):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="delivery_waiting_on_dianna")
        if current.state != "deliver_pending":
            current = self.repo.update_job_item_state(
                job_item_id,
                state="deliver_pending",
                error=current.error,
                completed_at=None,
            ) or current
            self._refresh_parent_job_state(current.job_id)
        requested = self._build_result_sink_emit_requested(job=job, job_item=current, payload=payload)
        outbox = self.repo.create_outbox_record(
            job=job,
            topic="result_sink.emit.requested",
            payload=requested.model_dump(mode="json"),
        )
        await self._publish_outbox_record(outbox)
        refreshed = self.repo.get_job_item(job_item_id)
        if refreshed is None:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="job_item_state_update_failed")
        return refreshed

    async def request_result_delivery(self, job_item_id: str, payload: DeliveryRequest) -> JobItemRecord:
        return await self.request_workflow_summary_emit(job_item_id, payload)

    async def _publish_outbox_record(
        self,
        outbox: OutboxRecord,
        *,
        update_item_stage: bool = True,
    ) -> tuple[bool, OutboxRecord]:
        claimed_outbox = self.repo.claim_outbox_record(outbox.outbox_id)
        if claimed_outbox is None:
            existing = self.repo.get_outbox_record(outbox.outbox_id) or outbox
            return True, existing
        if "message_type" in claimed_outbox.payload:
            envelope = MessageEnvelope.model_validate(claimed_outbox.payload)
        else:
            envelope = DomainJobEnvelope.model_validate(claimed_outbox.payload)
        low_persistence_scan_only = self._is_low_persistence_scan_only_envelope(envelope)
        if envelope.job_item_id:
            current_item = None if low_persistence_scan_only else self.repo.get_job_item(envelope.job_item_id)
            if current_item is not None:
                if current_item.state == "cancelled":
                    skipped_outbox = self.repo.mark_outbox_published(claimed_outbox.outbox_id)
                    self._refresh_parent_job_state(claimed_outbox.job_id)
                    if skipped_outbox is None:
                        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="outbox_state_update_failed")
                    return True, skipped_outbox
                if isinstance(envelope, MessageEnvelope) and envelope.message_type == "scan_item_requested":
                    if current_item.state in {"completed", "failed", "cancelled"}:
                        skipped_outbox = self.repo.mark_outbox_published(claimed_outbox.outbox_id)
                        self._refresh_parent_job_state(claimed_outbox.job_id)
                        if skipped_outbox is None:
                            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="outbox_state_update_failed")
                        return True, skipped_outbox
                    self.repo.update_job_item_state(envelope.job_item_id, state="queued", error=None)
        try:
            await self.bus.publish(envelope)
        except Exception as exc:
            error = {
                "code": "job_publish_failed",
                "message": str(exc),
            }
            failed_outbox = self.repo.mark_outbox_failed(claimed_outbox.outbox_id, error=error)
            if envelope.job_item_id and update_item_stage:
                current_item = self.repo.get_job_item(envelope.job_item_id)
                if isinstance(envelope, MessageEnvelope) and envelope.message_type == "policy_evaluation_requested" and current_item is not None:
                    stage = current_item.policy_stage.model_copy(update={"error": error})
                    self.repo.update_job_item_stage(
                        envelope.job_item_id,
                        stage_name="policy_stage",
                        stage_record=stage,
                        state=current_item.state,
                        error=current_item.error,
                        completed_at=current_item.completed_at,
                    )
                elif isinstance(envelope, MessageEnvelope) and envelope.message_type == "dianna_analysis_requested" and current_item is not None:
                    stage = current_item.dianna_stage.model_copy(update={"error": error})
                    self.repo.update_job_item_stage(
                        envelope.job_item_id,
                        stage_name="dianna_stage",
                        stage_record=stage,
                        state=current_item.state,
                        error=current_item.error,
                        completed_at=current_item.completed_at,
                    )
                elif isinstance(envelope, MessageEnvelope) and envelope.message_type in {"result_sink_emit_requested", "result_delivery_requested"} and current_item is not None:
                    stage = current_item.delivery_stage.model_copy(update={"error": error})
                    self.repo.update_job_item_stage(
                        envelope.job_item_id,
                        stage_name="delivery_stage",
                        stage_record=stage,
                        state=current_item.state,
                        error=current_item.error,
                        completed_at=current_item.completed_at,
                    )
                else:
                    self.repo.update_job_item_state(envelope.job_item_id, state="publish_pending", error=error)
                self._refresh_parent_job_state(claimed_outbox.job_id)
            else:
                self.repo.update_job_state(claimed_outbox.job_id, state="publish_pending", error=error)
            if failed_outbox is None:
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="outbox_state_update_failed")
            return False, failed_outbox

        published_outbox = self.repo.mark_outbox_published(claimed_outbox.outbox_id)
        if envelope.job_item_id and update_item_stage:
            current_item = None if low_persistence_scan_only else self.repo.get_job_item(envelope.job_item_id)
            refresh_parent = True
            if isinstance(envelope, MessageEnvelope) and envelope.message_type == "policy_evaluation_requested" and current_item is not None:
                stage = current_item.policy_stage.model_copy(update={"error": None})
                self.repo.update_job_item_stage(
                    envelope.job_item_id,
                    stage_name="policy_stage",
                    stage_record=stage,
                    state=current_item.state,
                    error=current_item.error,
                    completed_at=current_item.completed_at,
                )
            elif isinstance(envelope, MessageEnvelope) and envelope.message_type == "dianna_analysis_requested" and current_item is not None:
                stage = current_item.dianna_stage.model_copy(update={"error": None})
                self.repo.update_job_item_stage(
                    envelope.job_item_id,
                    stage_name="dianna_stage",
                    stage_record=stage,
                    state=current_item.state,
                    error=current_item.error,
                    completed_at=current_item.completed_at,
                )
            elif isinstance(envelope, MessageEnvelope) and envelope.message_type in {"result_sink_emit_requested", "result_delivery_requested"} and current_item is not None:
                stage = current_item.delivery_stage.model_copy(update={"error": None})
                self.repo.update_job_item_stage(
                    envelope.job_item_id,
                    stage_name="delivery_stage",
                    stage_record=stage,
                    state=current_item.state,
                    error=current_item.error,
                    completed_at=current_item.completed_at,
                )
            elif isinstance(envelope, MessageEnvelope) and envelope.message_type == "scan_item_requested":
                refresh_parent = False
            else:
                self.repo.update_job_item_state(envelope.job_item_id, state="queued", error=None)
            if refresh_parent:
                self._refresh_parent_job_state(outbox.job_id)
        else:
            self.repo.update_job_state(outbox.job_id, state="queued", error=None)
        if published_outbox is None:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="outbox_state_update_failed")
        return True, published_outbox

    @staticmethod
    def _is_low_persistence_scan_only_envelope(envelope: MessageEnvelope | DomainJobEnvelope) -> bool:
        if not isinstance(envelope, MessageEnvelope) or envelope.message_type != "scan_item_requested":
            return False
        scan_options = envelope.payload.get("scan_options") or {}
        if not isinstance(scan_options, dict):
            return False
        scan_only = scan_options.get("scanOnly") is True or scan_options.get("scan_only") is True
        effective_recovery_mode = scan_options.get("effectiveRecoveryMode") or scan_options.get("effective_recovery_mode")
        return scan_only and effective_recovery_mode != "item"

    def _is_low_persistence_scan_only_outbox(self, outbox: OutboxRecord) -> bool:
        if outbox.topic != "scan.requested":
            return False
        try:
            envelope = MessageEnvelope.model_validate(outbox.payload)
        except Exception:
            return False
        return self._is_low_persistence_scan_only_envelope(envelope)

    async def _publish_low_persistence_scan_only_outbox_records(
        self,
        records: list[OutboxRecord],
    ) -> list[tuple[bool, OutboxRecord]]:
        claim_many = getattr(self.repo, "claim_outbox_records", None)
        mark_many = getattr(self.repo, "mark_outbox_published_many", None)
        if not callable(claim_many) or not callable(mark_many):
            return [await self._publish_outbox_record(record) for record in records]

        claimed = claim_many([record.outbox_id for record in records])
        results: list[tuple[bool, OutboxRecord]] = []
        successfully_published: list[OutboxRecord] = []
        for outbox in claimed:
            try:
                envelope = MessageEnvelope.model_validate(outbox.payload)
                await self.bus.publish(envelope)
            except Exception as exc:
                error = {
                    "code": "job_publish_failed",
                    "message": str(exc),
                }
                failed_outbox = self.repo.mark_outbox_failed(outbox.outbox_id, error=error)
                results.append((False, failed_outbox or outbox))
                continue
            successfully_published.append(outbox)

        published_rows = mark_many([outbox.outbox_id for outbox in successfully_published])
        published_by_id = {outbox.outbox_id: outbox for outbox in published_rows}
        for outbox in successfully_published:
            results.append((True, published_by_id.get(outbox.outbox_id, outbox)))

        claimed_ids = {outbox.outbox_id for outbox in claimed}
        for record in records:
            if record.outbox_id not in claimed_ids:
                existing = self.repo.get_outbox_record(record.outbox_id) or record
                results.append((True, existing))
        return results

    async def submit_job(self, payload: JobSubmitRequest) -> JobRecord:
        if payload.idempotency_key:
            existing = self.repo.get_job_by_idempotency_key(payload.idempotency_key)
            if existing is not None:
                return existing
        self._validate_control_plane_references(
            integration_id=payload.integration_id,
            scope_id=payload.scope_id,
        )

        created = self.repo.create_job(
            JobCreate(
                job_id=payload.job_id,
                job_type=payload.job_type,
                state="accepted",
                integration_id=payload.integration_id,
                scope_id=payload.scope_id,
                object_identity=payload.object_identity,
                idempotency_key=payload.idempotency_key,
                payload=payload.payload,
            )
        )
        queued_envelope = created.as_envelope(state_override="queued")
        outbox = self.repo.create_outbox_record(
            job=created,
            topic=created.job_type,
            payload=queued_envelope.model_dump(mode="json"),
        )
        await self._publish_outbox_record(outbox)
        job = self.repo.get_job(created.job_id)
        if job is None:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="job_state_update_failed")
        return job

    async def submit_batch_job(self, payload: BatchJobSubmitRequest) -> BatchJobRecord:
        if not payload.items:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="batch_items_required")
        if payload.idempotency_key:
            existing = self.repo.get_job_by_idempotency_key(payload.idempotency_key)
            if existing is not None:
                return self.get_batch_job_or_404(existing.job_id)
        inferred_scope_id = self._infer_batch_scope_id(payload)
        self._validate_control_plane_references(
            integration_id=payload.integration_id,
            scope_id=inferred_scope_id,
        )
        effective_recovery_mode, recovery_policy_snapshot = self._resolve_effective_recovery_mode(payload.recovery_mode)

        created = self.repo.create_job(
            JobCreate(
                job_id=payload.job_id,
                job_type=payload.job_type,
                state="accepted",
                integration_id=payload.integration_id,
                scope_id=inferred_scope_id,
                idempotency_key=payload.idempotency_key,
                payload={
                    **payload.payload,
                    "itemCount": len(payload.items),
                    "recoveryModeRequested": payload.recovery_mode,
                    "effectiveRecoveryMode": effective_recovery_mode,
                    "recoveryPolicySnapshot": recovery_policy_snapshot,
                },
            )
        )
        batch_had_publish_failure = False
        publish_mode = payload.payload.get("publishMode") or payload.payload.get("publish_mode")
        bulk_create = getattr(self.repo, "create_job_items_and_outbox_records", None)
        defer_publish = (
            publish_mode == "deferred"
            or payload.payload.get("deferPublish") is True
            or (
                publish_mode not in {"immediate", "inline"}
                and payload.payload.get("deferPublish") is not False
                and callable(bulk_create)
            )
        )
        if defer_publish and callable(bulk_create):
            job_items: list[JobItemRecord] = []
            outbox_payloads: list[dict] = []
            for index, item in enumerate(payload.items):
                job_item = JobItemRecord(
                    job_item_id=f"job_item_{uuid.uuid4().hex}",
                    job_id=created.job_id,
                    item_index=index,
                    object_identity=item.object_identity,
                    state="publish_pending",
                    payload=item.payload,
                )
                job_items.append(job_item)
                outbox_payloads.append(
                    self._build_scan_item_requested(job=created, job_item=job_item).model_dump(mode="json")
                )
            bulk_create(
                job=created,
                job_items=job_items,
                topic="scan.requested",
                payloads=outbox_payloads,
            )
            self.repo.update_job_state(created.job_id, state="publish_pending", error={"code": "batch_publish_pending"})
            return self.get_batch_job_or_404(created.job_id)

        for index, item in enumerate(payload.items):
            job_item = self.repo.create_job_item(
                JobItemCreate(
                    job_id=created.job_id,
                    item_index=index,
                    object_identity=item.object_identity,
                    state="publish_pending" if defer_publish else "accepted",
                    payload=item.payload,
                )
            )
            queued_envelope = self._build_scan_item_requested(job=created, job_item=job_item)
            outbox = self.repo.create_outbox_record(
                job=created,
                topic="scan.requested",
                payload=queued_envelope.model_dump(mode="json"),
            )
            if defer_publish:
                continue
            published, _ = await self._publish_outbox_record(outbox)
            if not published:
                batch_had_publish_failure = True

        if defer_publish:
            self.repo.update_job_state(created.job_id, state="publish_pending", error={"code": "batch_publish_pending"})
        elif batch_had_publish_failure:
            self.repo.update_job_state(created.job_id, state="publish_pending", error={"code": "batch_publish_partial_failure"})
        else:
            self.repo.update_job_state(created.job_id, state="queued", error=None)
        return self.get_batch_job_or_404(created.job_id)

    def active_scan_item_count(self) -> int:
        active_count = 0
        terminal_states = {"completed", "failed", "cancelled"}
        for job in self.repo.list_jobs(limit=1000):
            if job.state in terminal_states:
                continue
            items = self.repo.list_job_items(job_id=job.job_id, limit=1_000_000)
            if job.effective_recovery_mode != "item" and self._is_scan_only_batch_job(job, items):
                continue
            summary = self.repo.summarize_job_items(job.job_id)
            active_count += summary.queued + summary.scanning + summary.scanned
        return active_count

    async def flush_outbox(self, *, limit: int = 100, max_active_scan_items: int | None = None) -> OutboxFlushResult:
        started = time.perf_counter()
        publish_limit = limit
        active_scan_items: int | None = None
        publish_capacity: int | None = None
        if max_active_scan_items is not None:
            active_scan_items = self.active_scan_item_count()
            publish_capacity = max(max_active_scan_items - active_scan_items, 0)
            publish_limit = min(limit, publish_capacity)

        list_started = time.perf_counter()
        records = self.repo.list_outbox_records_fair(publish_state="pending", limit=publish_limit)
        list_elapsed_ms = (time.perf_counter() - list_started) * 1000.0
        selected_topics: dict[str, int] = {}
        for record in records:
            selected_topics[record.topic] = selected_topics.get(record.topic, 0) + 1
        selected_job_ids = sorted({record.job_id for record in records})
        now = datetime.now(timezone.utc)
        first_outbox_created_at = min((record.created_at for record in records), default=None)
        last_outbox_created_at = max((record.created_at for record in records), default=None)
        result = OutboxFlushResult(
            attempted=len(records),
            active_scan_items=active_scan_items,
            max_active_scan_items=max_active_scan_items,
            publish_capacity=publish_capacity,
            list_elapsed_ms=round(list_elapsed_ms, 3),
            selected_job_ids=selected_job_ids[:20],
            selected_topics=selected_topics,
            oldest_pending_age_ms=(
                round((now - first_outbox_created_at).total_seconds() * 1000.0, 3)
                if first_outbox_created_at is not None
                else None
            ),
            newest_pending_age_ms=(
                round((now - last_outbox_created_at).total_seconds() * 1000.0, 3)
                if last_outbox_created_at is not None
                else None
            ),
            first_outbox_created_at=first_outbox_created_at,
            last_outbox_created_at=last_outbox_created_at,
        )
        scan_publish_job_ids: set[str] = set()
        publish_started = time.perf_counter()
        if records and all(self._is_low_persistence_scan_only_outbox(record) for record in records):
            publish_results = await self._publish_low_persistence_scan_only_outbox_records(records)
        else:
            publish_results = [await self._publish_outbox_record(record) for record in records]
        for record, (published, updated) in zip(records, publish_results):
            result.records.append(updated)
            if published:
                result.published += 1
                if record.topic == "scan.requested":
                    scan_publish_job_ids.add(record.job_id)
            else:
                result.failed += 1
        for job_id in scan_publish_job_ids:
            self._refresh_parent_job_state(job_id)
        result.publish_elapsed_ms = round((time.perf_counter() - publish_started) * 1000.0, 3)
        result.total_elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
        published_at_values = [record.published_at for record in result.records if record.published_at is not None]
        result.first_published_at = min(published_at_values, default=None)
        result.last_published_at = max(published_at_values, default=None)
        return result
