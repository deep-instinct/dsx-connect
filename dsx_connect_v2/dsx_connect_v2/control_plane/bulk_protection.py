"""Reviewed bulk protection changes, audited using durable jobs without scan dispatch."""
from copy import deepcopy
from datetime import timedelta

from fastapi import HTTPException

from dsx_connect_v2.control_plane.models import ProtectedScopeCreate, ProtectedScopeUpdate, utcnow
from dsx_connect_v2.control_plane.service import normalize_selector, selectors_overlap
from dsx_connect_v2.jobs.models import JobCreate, JobItemCreate, StageRecord

JOB_TYPE = "protection.bulk"
MAX_TARGETS = 10000


def prepare(service, jobs, targets, *, action, policy, replace_existing):
    if action == "apply":
        service._validate_scope_policy(policy)
    unique = {}
    for target in targets:
        service.get_integration_or_404(target["integration_id"])
        selector = target["selector"].strip()
        if not selector:
            raise HTTPException(422, "Empty asset selector")
        unique[(target["integration_id"], normalize_selector("path", selector))] = {**target, "selector": selector}
    if not unique or len(unique) > MAX_TARGETS:
        raise HTTPException(422, f"Select between 1 and {MAX_TARGETS} assets")
    snapshots = []
    scopes_by_integration = {}
    counts = {"new": 0, "replace": 0, "resume": 0, "disable": 0, "scan": 0, "skip": 0}
    for target in unique.values():
        integration_id = target["integration_id"]
        if integration_id not in scopes_by_integration:
            scopes_by_integration[integration_id] = service.list_scopes(integration_id=integration_id)
        scopes = scopes_by_integration[integration_id]
        normalized = normalize_selector("path", target["selector"])
        exact = next((s for s in scopes if s.scope_type == "path" and s.normalized_selector == normalized), None)
        overlapping = [s for s in scopes if s.scope_type == "path" and selectors_overlap("path", s.normalized_selector, normalized)]
        kind, reason = "skip", None
        if overlapping and not exact:
            reason = "Overlapping scope: manage that scope separately"
        elif action == "scan":
            if not exact or not exact.enabled:
                reason = "Unprotected asset: assign a profile before scanning"
            elif jobs.repo.has_active_scope_scan(exact.scope_id):
                reason = "A scan is already active for this scope"
            else:
                kind = "scan"
        elif action == "disable":
            kind = "disable" if exact and exact.enabled else "skip"
            reason = None if kind == "disable" else "Already unprotected"
        elif exact and exact.enabled and not replace_existing:
            reason = "Existing protection preserved"
        else:
            kind = "replace" if exact and exact.enabled else "resume" if exact else "new"
        counts[kind] += 1
        snapshots.append({**target, "kind": kind, "reason": reason,
                          "scope_id": exact.scope_id if exact else None,
                          "scope_updated_at": exact.updated_at.isoformat() if exact else None})
    job = jobs.repo.create_job(JobCreate(job_type=JOB_TYPE, state="preparing", payload={
        "action": action, "policy": policy if action == "apply" else {},
        "replace_existing": replace_existing, "counts": counts, "total": len(snapshots),
    }))
    try:
        for index, target in enumerate(snapshots):
            jobs.repo.create_job_item(JobItemCreate(
                job_id=job.job_id, item_index=index,
                object_identity=f"{target['integration_id']}:{target['selector']}",
                state="accepted", payload=target,
                **{name: StageRecord(state="skipped") for name in
                   ("scan_stage", "policy_stage", "remediation_stage", "delivery_stage", "dianna_stage")},
            ))
        jobs.repo.update_job_state(job.job_id, state="planned")
    except Exception:
        jobs.repo.update_job_state(job.job_id, state="failed", error={"message": "Could not persist complete selection"}, completed_at=utcnow())
        raise
    return describe(jobs, job.job_id)


def describe(jobs, operation_id, *, include_outcomes=False):
    job = jobs.get_job_or_404(operation_id)
    if job.job_type != JOB_TYPE:
        raise HTTPException(404, "Bulk protection operation not found")
    summary = jobs.repo.summarize_job_items(operation_id)
    items = jobs.repo.list_job_items(job_id=operation_id, limit=MAX_TARGETS if include_outcomes else 100)
    counts = {"completed": summary.completed, "failed": summary.failed, "skipped": summary.cancelled,
              "pending": summary.total - summary.completed - summary.failed - summary.cancelled}
    outcomes = []
    for item in items:
        outcome = "skipped" if item.state == "cancelled" else item.state if item.state in {"completed", "failed"} else "pending"
        outcomes.append({**item.payload, "outcome": outcome, "error": item.error,
                         "scan_job_id": (item.policy_stage.result or {}).get("scan_job_id")})
    return {"operation_id": operation_id, "state": job.state, "created_at": job.created_at,
            "updated_at": job.updated_at, "action": job.payload["action"],
            "review": job.payload["counts"], "total": job.payload["total"], "progress": counts,
            "policy_name": job.payload.get("policy", {}).get("display_name"),
            "stalled": job.state in {"running", "queued"} and utcnow() - job.updated_at > timedelta(minutes=5),
            "outcomes": outcomes}


def execute(service, jobs, operation_id, scan_scope=None):
    if not jobs.repo.claim_protection_job(operation_id, "queued", "running"):
        return
    job = jobs.get_job_or_404(operation_id)
    failed = False
    try:
        for item in jobs.repo.list_job_items(job_id=operation_id, limit=MAX_TARGETS):
            target = item.payload
            try:
                if target["kind"] == "skip":
                    jobs.repo.update_job_item_state(item.job_item_id, state="cancelled", error={"message": target["reason"]}, completed_at=utcnow())
                    continue
                current = service.get_scope_or_404(target["scope_id"]) if target["scope_id"] else None
                if current and current.updated_at.isoformat() != target["scope_updated_at"]:
                    raise HTTPException(409, "Scope changed after review; refresh and review again")
                if job.payload["action"] == "scan":
                    if scan_scope is None:
                        raise RuntimeError("Scan submission callback unavailable")
                    batch = scan_scope(current.scope_id)
                    jobs.repo.update_job_item_stage(item.job_item_id, stage_name="policy_stage",
                        stage_record=StageRecord(state="skipped", result={"scan_job_id": batch.job.job_id}), state="accepted")
                elif job.payload["action"] == "disable":
                    service.update_scope(current.scope_id, ProtectedScopeUpdate(enabled=False), expected_updated_at=target["scope_updated_at"])
                else:
                    policy = deepcopy(job.payload["policy"])
                    # Preserve the asset's explicit scanner/protected-entity binding.
                    if current and current.post_scan_policy.get("scanner"):
                        policy["scanner"] = deepcopy(current.post_scan_policy["scanner"])
                    if current:
                        service.update_scope(current.scope_id, ProtectedScopeUpdate(enabled=True, post_scan_policy=policy), expected_updated_at=target["scope_updated_at"])
                    else:
                        service.create_scope(ProtectedScopeCreate(
                            integration_id=target["integration_id"], scope_type="path",
                            resource_selector=target["selector"], display_name=target.get("display_name") or target["selector"],
                            mode="full_scan", enabled=True, post_scan_policy=policy,
                        ))
                jobs.repo.update_job_item_state(item.job_item_id, state="completed", completed_at=utcnow())
            except Exception as exc:
                if job.payload["action"] == "scan" and isinstance(exc, HTTPException) and isinstance(exc.detail, dict) and exc.detail.get("code") == "scope_scan_active":
                    jobs.repo.update_job_item_state(item.job_item_id, state="cancelled", error={"message": exc.detail["message"]}, completed_at=utcnow())
                    continue
                failed = True
                message = str(exc.detail) if isinstance(exc, HTTPException) else "Protection update failed; inspect server logs"
                jobs.repo.update_job_item_state(item.job_item_id, state="failed", error={"message": message}, completed_at=utcnow())
            finally:
                jobs.repo.update_job_state(operation_id, state="running")
        jobs.repo.update_job_state(operation_id, state="failed" if failed else "completed", completed_at=utcnow())
    except Exception:
        jobs.repo.update_job_state(operation_id, state="failed", error={"message": "Operation interrupted; review per-asset outcomes before another operation"}, completed_at=utcnow())
        raise
