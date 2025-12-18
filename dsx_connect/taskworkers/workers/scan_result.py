# dsx_connect/taskworkers/workers/scan_result.py
from __future__ import annotations
from typing import Any, Dict
import time
import redis as _redis
from celery import signals
from celery.signals import worker_process_init
from functools import cached_property

from pydantic import ValidationError

from dsx_connect.taskworkers.celery_app import celery_app
from dsx_connect.taskworkers.names import Tasks, Queues
from dsx_connect.taskworkers.workers.base_worker import BaseWorker, RetryGroup, RetryGroups
from dsx_connect.taskworkers.dlq_store import enqueue_scan_result_dlq_sync, \
    make_scan_result_dlq_item
from dsx_connect.taskworkers.errors import TaskError, MalformedScanRequest, MalformedResponse

from dsx_connect.dsxa_client.verdict_models import DPAVerdictModel2
from shared.models.connector_models import ScanRequestModel, ItemActionModel
from dsx_connect.models.scan_result import ScanResultModel, ScanResultStatusEnum
from shared.dsx_logging import dsx_logging
from shared.models.status_responses import ItemActionStatusResponse


# Optional extras (DB, stats, notifications) are best-effort and should NOT trigger retries.
# If you have helpers, import them here; otherwise keep the try/except blocks inline.

def _send_syslog(scan_result: ScanResultModel, original_task_id: str, current_task_id: str) -> None:
    """Attempt to send syslog; if uninitialized, warn with task context.

    Only raise a retryable error if an unexpected exception bubbles up.
    """
    try:
        from shared.log_chain import log_verdict_chain
        sent = log_verdict_chain(
            scan_result=scan_result,
            scan_request_task_id=original_task_id,
            current_task_id=current_task_id,
        )
        if sent:
            dsx_logging.debug(
                f"[scan_result:{current_task_id}] syslog sent for {scan_result.scan_request.location}"
            )
        else:
            # Provide worker-context warning to make logs clearer than MainProcess warning
            dsx_logging.warning(
                f"[scan_result:{current_task_id}] syslog not initialized; skipping for {scan_result.scan_request.location}"
            )
    except Exception as e:
        # Mark as retriable so BaseWorker will backoff/retry
        raise TaskError(retriable=True, reason="syslog_failure") from e


class ScanResultWorker(BaseWorker):
    name = Tasks.RESULT
    RETRY_GROUPS = RetryGroups.none()  # no connector/dsxa mapping; retries driven by TaskError.retriable
    _scan_results_db = None
    _stats_db = None

    def __init__(self):
        super().__init__()
        if self.__class__._scan_results_db is None:
            from dsx_connect.config import get_config
            from dsx_connect.database.database_factory import (
                database_scan_results_factory, database_scan_stats_factory
            )
            cfg = get_config()
            # one-time, per-process
            self.__class__._scan_results_db = database_scan_results_factory(
                database_loc=cfg.results_database.loc,
                retain=cfg.results_database.retain,
                collection_name="scan_results",
            )
            self.__class__._stats_db = database_scan_stats_factory(
                database_loc=cfg.results_database.loc,
                collection_name="scan_stats",
            )

    def execute(
            self,
            scan_request_dict: Dict[str, Any],
            verdict_dict: Dict[str, Any],
            item_action_dict: Dict[str, Any],
            *,
            scan_request_task_id: str) -> str:
        # 1) validate inputs
        try:
            scan_request = ScanRequestModel.model_validate(scan_request_dict)
            verdict = DPAVerdictModel2.model_validate(verdict_dict)
            item_action_status = ItemActionStatusResponse.model_validate(item_action_dict)
        except ValidationError as e:
            raise MalformedResponse(f"Invalid scan_result inputs: {e}") from e

        # 2) build ScanResultModel
        scan_result = ScanResultModel(
            scan_request=scan_request,
            verdict=verdict,
            item_action=item_action_status,
            scan_request_task_id=scan_request_task_id,   # ← add this
            scan_job_id=getattr(scan_request, "scan_job_id", None),
        )
        # Derive overall status for logging/syslog
        try:
            from shared.models.status_responses import StatusResponseEnum as _SRE
            ia = item_action_status
            if ia and getattr(ia, "status", None) is not None:
                st = getattr(ia, "status")
                if st == _SRE.SUCCESS:
                    scan_result.status = ScanResultStatusEnum.ACTION_SUCCEEDED
                elif st == _SRE.ERROR:
                    scan_result.status = ScanResultStatusEnum.ACTION_FAILED
                else:
                    scan_result.status = ScanResultStatusEnum.SCANNED
            else:
                scan_result.status = ScanResultStatusEnum.SCANNED
        except Exception:
            scan_result.status = ScanResultStatusEnum.SCANNED

        # 3) critical: send syslog (retryable on failure)
        _send_syslog(scan_result, original_task_id=scan_request_task_id, current_task_id=self.context.task_id)

        # 4) optional extras (best-effort; never raise to retry)
        # 4a) Update job counters in Redis (best-effort)
        try:
            from dsx_connect.config import get_config
            cfg = get_config()
            job_id = getattr(scan_result, "scan_job_id", None) or getattr(getattr(scan_result, "scan_request", None), "scan_job_id", None)
            if job_id:
                key = f"dsxconnect:job:{job_id}"
                r = getattr(self.__class__, "_redis", None)
                if r is None:
                    self.__class__._redis = _redis.from_url(str(cfg.redis_url), decode_responses=True)
                    r = self.__class__._redis
                now = str(int(time.time()))
                r.hsetnx(key, "job_id", job_id)
                r.hsetnx(key, "status", "running")
                r.hincrby(key, "processed_count", 1)
                # verdict breakdown
                try:
                    v = getattr(getattr(scan_result, "verdict", None), "verdict", None)
                    v_key = None
                    if v is not None:
                        # v may be Enum-like with .value
                        vv = getattr(v, "value", v)
                        if isinstance(vv, str):
                            t = vv.lower().replace(" ", "_")
                            if t in {"benign","malicious","unknown","unsupported","not_scanned","encrypted"}:
                                v_key = t
                    if v_key:
                        r.hincrby(key, f"verdict_{v_key}", 1)
                except Exception:
                    pass
                r.hset(key, "last_update", now)
                r.expire(key, 7 * 24 * 3600)
        except Exception:
            pass

        # 4b) If we can determine total and counts match, mark finished
        try:
            job_id = getattr(scan_result, "scan_job_id", None) or getattr(getattr(scan_result, "scan_request", None), "scan_job_id", None)
            if job_id:
                r = getattr(self.__class__, "_redis", None)
                if r is not None:
                    data = r.hgetall(f"dsxconnect:job:{job_id}") or {}
                    try:
                        enq_total = int(data.get("enqueued_total", -1)) if data.get("enqueued_total") is not None else -1
                        expected = int(data.get("expected_total", -1)) if data.get("expected_total") is not None else -1
                        total = enq_total if enq_total > 0 else (expected if expected > 0 else -1)
                        processed = int(data.get("processed_count", 0))
                        if total > 0 and processed >= total and not data.get("finished_at"):
                            now = str(int(time.time()))
                            r.hset(f"dsxconnect:job:{job_id}", mapping={"status": "completed", "finished_at": now, "last_update": now})
                            try:
                                dsx_logging.info(f"job.complete job={job_id} processed={processed} total={total} finished_at={now}")
                            except Exception:
                                pass
                        elif data.get("enqueue_done") == "1":
                            # Older behavior: if enqueue_done is set and processed matches enqueued_total, mark done
                            if enq_total > 0 and processed >= enq_total and not data.get("finished_at"):
                                now = str(int(time.time()))
                                r.hset(f"dsxconnect:job:{job_id}", mapping={"status": "completed", "finished_at": now, "last_update": now})
                                try:
                                    dsx_logging.info(f"job.complete job={job_id} processed={processed} enqueued_total={enq_total} finished_at={now}")
                                except Exception:
                                    pass
                        else:
                            # Fallback: if we don't know total but enqueued_count is available and matches processed, complete
                            try:
                                enq_count = int(data.get("enqueued_count", -1)) if data.get("enqueued_count") is not None else -1
                            except Exception:
                                enq_count = -1
                            if enq_count >= 0 and processed >= enq_count and not data.get("finished_at"):
                                now = str(int(time.time()))
                                r.hset(f"dsxconnect:job:{job_id}", mapping={"status": "completed", "finished_at": now, "last_update": now})
                                try:
                                    dsx_logging.info(f"job.complete job={job_id} processed={processed} enqueued_count={enq_count} finished_at={now}")
                                except Exception:
                                    pass
                    except Exception:
                        pass
        except Exception:
            pass

        # 4c) Store to DB / stats / notifications
        self._best_effort_extras(scan_result)

        dsx_logging.info(f"[scan_result:{self.context.task_id}] completed for {scan_request.location}")
        return "SUCCESS"

    def _best_effort_extras(self, scan_result: ScanResultModel) -> None:
        """Store to DB / update stats / notify UI if enabled; never cause retries."""
        try:
            from dsx_connect.config import get_config
            cfg = get_config()

            if getattr(cfg.workers, "enable_scan_results_db", True):
                try:
                    self.__class__._scan_results_db.insert(scan_result)
                    dsx_logging.debug("[scan_result] stored in scan_results DB")
                except Exception as e:
                    try:
                        loc = getattr(get_config().results_database, "loc", "?")
                    except Exception:
                        loc = "?"
                    dsx_logging.warning(f"[scan_result] store DB failed (loc={loc}): {e}")

            if getattr(cfg.workers, "enable_scan_stats", True):
                try:
                    from dsx_connect.database.scan_stats_worker import ScanStatsWorker
                    ScanStatsWorker(self.__class__._stats_db).insert(scan_result)
                    dsx_logging.debug("[scan_result] stats updated")
                except Exception as e:
                    try:
                        loc = getattr(get_config().results_database, "loc", "?")
                    except Exception:
                        loc = "?"
                    dsx_logging.warning(f"[scan_result] stats update failed (loc={loc}): {e}")

            # Example: UI notifications
            if getattr(cfg.workers, "enable_notifications", True):
                try:
                    task = celery_app.send_task(
                        name=Tasks.NOTIFICATION,
                        queue=Queues.NOTIFICATION,
                        args=[scan_result.model_dump()]
                    )
                    dsx_logging.debug("[scan_result] notification published")
                except Exception as e:
                    dsx_logging.warning(f"[scan_result] notify failed: {e}")

            # Optionally trigger DIANNA analysis on malicious verdicts
            try:
                if getattr(cfg.dianna, 'auto_on_malicious', False):
                    v = getattr(getattr(scan_result, "verdict", None), "verdict", None)
                    v_norm = str(v or '').lower()
                    if 'malicious' in v_norm or v_norm in ('bad', 'infected'):
                        sr = getattr(scan_result, 'scan_request', None)
                        if sr and getattr(sr, 'connector_url', None) and getattr(sr, 'location', None):
                            payload = {
                                "connector": getattr(sr, 'connector', None).model_dump() if getattr(sr, 'connector', None) else None,
                                "connector_url": sr.connector_url,
                                "location": sr.location,
                                "metainfo": getattr(sr, 'metainfo', sr.location),
                            }
                            celery_app.send_task(
                                Tasks.DIANNA_ANALYZE,
                                args=[payload],
                                kwargs={},
                                queue=Queues.ANALYZE,
                            )
                            dsx_logging.info("[scan_result] auto DIANNA analysis enqueued")
            except Exception as e:
                dsx_logging.warning(f"[scan_result] auto-dianna failed: {e}")

        except Exception as e:
            # Don't bubble from extras
            dsx_logging.warning(f"[scan_result] extras wrapper failed: {e}")


    def _enqueue_dlq(
            self,
            *,
            error: Exception,
            reason: str,
            scan_request_task_id: str,
            current_task_id: str,
            retry_count: int,
            upstream_task_id: str | None = None,
            args: tuple,
            kwargs: dict,
    ) -> None:
        # args: [scan_request_dict, verdict_dict, item_action_dict, original_task_id?]
        scan_request_dict = args[0] if len(args) > 0 else {}
        verdict_dict      = args[1] if len(args) > 1 else {}
        item_action_dict  = args[2] if len(args) > 2 else {}

        item = make_scan_result_dlq_item(
            scan_request=scan_request_dict,
            verdict=verdict_dict,
            item_action=item_action_dict,
            error=error,
            reason=reason,
            scan_request_task_id=scan_request_task_id,  # forwarded root id
            current_task_id=current_task_id,            # this failing task
            retry_count=retry_count,
            upstream_task_id=upstream_task_id,
        )
        enqueue_scan_result_dlq_sync(item)

# Register with Celery
celery_app.register_task(ScanResultWorker())


# Initialize syslog once per worker process so _send_syslog can log immediately
@worker_process_init.connect
def _init_syslog_for_worker(**kwargs):
    try:
        # Initialize syslog only in the results worker process
        import os
        role = (os.getenv("DSX_WORKER_ROLE", "") or "").strip().lower()
        if role not in ("results", "scan_result", "scan-result"):
            return
        from dsx_connect.config import get_config
        from shared.log_chain import init_syslog_handler
        cfg = get_config()
        init_syslog_handler(
            syslog_host=cfg.syslog.syslog_server_url,
            syslog_port=cfg.syslog.syslog_server_port,
            transport=str(getattr(cfg.syslog, "transport", "udp")),
            tls_ca=getattr(cfg.syslog, "tls_ca_file", None),
            tls_cert=getattr(cfg.syslog, "tls_cert_file", None),
            tls_key=getattr(cfg.syslog, "tls_key_file", None),
            tls_insecure=bool(getattr(cfg.syslog, "tls_insecure", False)),
        )
        try:
            dsx_logging.info(
                f"[scan_result] syslog initialized {cfg.syslog.syslog_server_url}:{cfg.syslog.syslog_server_port}"
            )
        except Exception:
            pass
    except Exception as e:
        # Do not crash worker startup; _send_syslog will warn if missing
        try:
            dsx_logging.warning(f"[scan_result] syslog init failed: {e}")
        except Exception:
            pass
