from __future__ import annotations

from datetime import datetime, timezone

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
    JobRecord,
    JobSubmitRequest,
    OutboxFlushResult,
    OutboxRecord,
    PolicyDecision,
    PolicyHandoffDecision,
    RemediationRequest,
    StageRecord,
    StageUpdateRequest,
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

    def get_job_item_or_404(self, job_item_id: str) -> JobItemRecord:
        row = self.repo.get_job_item(job_item_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job_item_not_found")
        return row

    def list_job_items(self, *, job_id: str, state: str | None = None, limit: int = 1000) -> list[JobItemRecord]:
        self.get_job_or_404(job_id)
        return self.repo.list_job_items(job_id=job_id, state=state, limit=limit)

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
        summary = self.repo.summarize_job_items(job_id)
        if summary.total == 0:
            return
        if summary.publish_pending > 0:
            self.repo.update_job_state(job_id, state="publish_pending", error={"code": "batch_publish_partial_failure"})
            return
        if summary.scanning > 0 or summary.remediating > 0 or summary.delivering_result > 0:
            self.repo.update_job_state(job_id, state="running", error=None)
            return
        terminal_count = summary.completed + summary.failed + summary.cancelled
        if terminal_count == summary.total:
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
            delivery = handoff.delivery
            targets = {
                "scan_result": delivery.scan_targets or delivery.targets,
                "remediation_result": delivery.remediation_targets or delivery.targets,
                "dianna_result": delivery.dianna_targets or delivery.targets,
                "workflow_summary": delivery.workflow_summary_targets or delivery.targets,
            }.get(result_type, delivery.targets)
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
        refreshed = self.repo.get_job_item(job_item_id)
        if refreshed is None:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="job_item_state_update_failed")
        return refreshed

    def _update_job_item_stage(self, job_item_id: str, *, stage_name: str, payload: StageUpdateRequest) -> JobItemRecord:
        current = self.get_job_item_or_404(job_item_id)
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
            job_item_id,
            stage_name=stage_name,
            stage_record=stage_record,
            state=item_state,
            error=item_error,
            completed_at=item_completed_at,
        )
        if updated is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job_item_not_found")
        self._refresh_parent_job_state(current.job_id)
        refreshed = self.repo.get_job_item(job_item_id)
        if refreshed is None:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="job_item_state_update_failed")
        return refreshed

    def update_scan_stage(self, job_item_id: str, payload: StageUpdateRequest) -> JobItemRecord:
        return self._update_job_item_stage(job_item_id, stage_name="scan_stage", payload=payload)

    def update_policy_stage(self, job_item_id: str, payload: StageUpdateRequest) -> JobItemRecord:
        return self._update_job_item_stage(job_item_id, stage_name="policy_stage", payload=payload)

    def update_remediation_stage(self, job_item_id: str, payload: StageUpdateRequest) -> JobItemRecord:
        return self._update_job_item_stage(job_item_id, stage_name="remediation_stage", payload=payload)

    def update_delivery_stage(self, job_item_id: str, payload: StageUpdateRequest) -> JobItemRecord:
        return self._update_job_item_stage(job_item_id, stage_name="delivery_stage", payload=payload)

    def update_dianna_stage(self, job_item_id: str, payload: StageUpdateRequest) -> JobItemRecord:
        return self._update_job_item_stage(job_item_id, stage_name="dianna_stage", payload=payload)

    async def advance_scan_stage(self, job_item_id: str, payload: StageUpdateRequest) -> JobItemRecord:
        updated = self.update_scan_stage(job_item_id, payload)
        await self._maybe_emit_follow_on_requests(updated, stage_name="scan_stage", payload=payload)
        return self.get_job_item_or_404(job_item_id)

    async def advance_policy_stage(self, job_item_id: str, payload: StageUpdateRequest) -> JobItemRecord:
        updated = self.update_policy_stage(job_item_id, payload)
        await self._maybe_emit_follow_on_requests(updated, stage_name="policy_stage", payload=payload)
        return self.get_job_item_or_404(job_item_id)

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

    async def _publish_outbox_record(self, outbox: OutboxRecord) -> tuple[bool, OutboxRecord]:
        claimed_outbox = self.repo.claim_outbox_record(outbox.outbox_id)
        if claimed_outbox is None:
            existing = self.repo.get_outbox_record(outbox.outbox_id) or outbox
            return True, existing
        if "message_type" in claimed_outbox.payload:
            envelope = MessageEnvelope.model_validate(claimed_outbox.payload)
        else:
            envelope = DomainJobEnvelope.model_validate(claimed_outbox.payload)
        try:
            await self.bus.publish(envelope)
        except Exception as exc:
            error = {
                "code": "job_publish_failed",
                "message": str(exc),
            }
            failed_outbox = self.repo.mark_outbox_failed(claimed_outbox.outbox_id, error=error)
            if envelope.job_item_id:
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
        if envelope.job_item_id:
            current_item = self.repo.get_job_item(envelope.job_item_id)
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
            else:
                self.repo.update_job_item_state(envelope.job_item_id, state="queued", error=None)
            self._refresh_parent_job_state(outbox.job_id)
        else:
            self.repo.update_job_state(outbox.job_id, state="queued", error=None)
        if published_outbox is None:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="outbox_state_update_failed")
        return True, published_outbox

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
        self._validate_control_plane_references(
            integration_id=payload.integration_id,
            scope_id=payload.scope_id,
        )
        effective_recovery_mode, recovery_policy_snapshot = self._resolve_effective_recovery_mode(payload.recovery_mode)

        created = self.repo.create_job(
            JobCreate(
                job_id=payload.job_id,
                job_type=payload.job_type,
                state="accepted",
                integration_id=payload.integration_id,
                scope_id=payload.scope_id,
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
        for index, item in enumerate(payload.items):
            job_item = self.repo.create_job_item(
                JobItemCreate(
                    job_id=created.job_id,
                    item_index=index,
                    object_identity=item.object_identity,
                    state="accepted",
                    payload=item.payload,
                )
            )
            queued_envelope = self._build_scan_item_requested(job=created, job_item=job_item)
            outbox = self.repo.create_outbox_record(
                job=created,
                topic="scan.requested",
                payload=queued_envelope.model_dump(mode="json"),
            )
            published, _ = await self._publish_outbox_record(outbox)
            if not published:
                batch_had_publish_failure = True

        if batch_had_publish_failure:
            self.repo.update_job_state(created.job_id, state="publish_pending", error={"code": "batch_publish_partial_failure"})
        else:
            self.repo.update_job_state(created.job_id, state="queued", error=None)
        return self.get_batch_job_or_404(created.job_id)

    async def flush_outbox(self, *, limit: int = 100) -> OutboxFlushResult:
        records = self.repo.list_outbox_records(publish_state="pending", limit=limit)
        result = OutboxFlushResult(attempted=len(records))
        for record in records:
            published, updated = await self._publish_outbox_record(record)
            result.records.append(updated)
            if published:
                result.published += 1
            else:
                result.failed += 1
        return result
