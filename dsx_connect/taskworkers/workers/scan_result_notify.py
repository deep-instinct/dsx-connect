import os, asyncio
import time
import redis as _redis
from celery.signals import worker_process_init, worker_shutdown
from dsx_connect.messaging.bus import SyncBus
from dsx_connect.messaging.notifiers import Notifiers
from dsx_connect.models.scan_result import ScanResultModel
from dsx_connect.taskworkers.celery_app import celery_app
from dsx_connect.taskworkers.names import Tasks
from dsx_connect.taskworkers.workers.base_worker import BaseWorker, RetryGroups
from shared.dsx_logging import dsx_logging
from dsx_connect.config import get_config

class ScanResultNotificationWorker(BaseWorker):
    name = Tasks.NOTIFICATION
    RETRY_GROUPS = RetryGroups.none()

    def __init__(self):
        super().__init__()
        self.notifier = Notifiers(SyncBus(str(get_config().redis_url)))

    def execute(self, scan_result_dict: dict):
        dsx_logging.debug(f"[scan_result_notify:{self.context.task_id}] Publishing scan result")
        try:
            # Build event with job progress summary
            event = {"type": "scan_result", "scan_result": scan_result_dict}
            try:
                job_id = (scan_result_dict.get("scan_job_id")
                          or (scan_result_dict.get("scan_request") or {}).get("scan_job_id"))
                if job_id:
                    key = f"dsxconnect:job:{job_id}"
                    r = getattr(self.__class__, "_redis", None)
                    if r is None:
                        r = _redis.from_url(str(get_config().redis_url), decode_responses=True)
                        self.__class__._redis = r
                    data = r.hgetall(key) or {}
                    # Normalize ints
                    def _to_int(v):
                        try:
                            return int(v)
                        except Exception:
                            return None
                    processed = _to_int(data.get("processed_count")) or 0
                    enq_total = _to_int(data.get("enqueued_total"))
                    enq_count = _to_int(data.get("enqueued_count")) or 0
                    expected = _to_int(data.get("expected_total"))
                    total = enq_total if (enq_total is not None and enq_total >= 0) else expected
                    status = data.get("status", "running")
                    # Duration
                    try:
                        started = int(data.get("started_at", 0) or 0)
                        finished = int(data.get("finished_at", 0) or 0)
                        now_ts = int(time.time())
                        duration = (finished or now_ts) - started if started else None
                    except Exception:
                        duration = None

                    # ETA
                    eta = None
                    try:
                        if total and total > 0 and started and processed and (not finished) and processed < total:
                            elapsed = max(1, (now_ts - started))
                            throughput = processed / elapsed
                            if throughput > 0:
                                remaining = max(0, total - processed)
                                eta = int(remaining / throughput)
                    except Exception:
                        eta = None

                    # Derive completion based on available totals
                    comp_total = None
                    if total is not None and total >= 0:
                        comp_total = total
                    elif enq_total is not None and enq_total >= 0:
                        comp_total = enq_total
                    elif data.get("enqueue_done") == "1" and enq_count is not None and enq_count > 0:
                        comp_total = enq_count

                    summary = {
                        "job_id": job_id,
                        "status": ("completed" if (comp_total is not None and processed >= comp_total) else status),
                        "processed_count": processed,
                        "total": total,
                        "enqueued_total": enq_total,
                        "enqueued_count": enq_count,
                        "enqueue_done": data.get("enqueue_done"),
                        "last_update": data.get("last_update"),
                        "duration_secs": duration,
                        "eta_secs": eta,
                        "time_remaining": (lambda s: (f"{s//86400}d {(s%86400)//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}" if s is not None and s >= 0 and s >= 86400 else (f"{(s or 0)//3600:02d}:{((s or 0)%3600)//60:02d}:{(s or 0)%60:02d}" if s is not None and s >= 0 else None)))(eta),
                    }
                    event["job"] = summary
                    try:
                        dsx_logging.info(f"notify.scan_result job={job_id} status={status} processed={processed} total={total} duration={duration}")
                    except Exception:
                        pass
            except Exception:
                pass

            count = self.notifier.publish_scan_results_sync(event)
            dsx_logging.debug(f"[scan_result_notify:{self.context.task_id}] Published to {count} subscriber(s)")
        except Exception as e:
            dsx_logging.warning(f"[scan_result_notify:{self.context.task_id}] publish failed: {e}")
        return "OK"


# Register with Celery
celery_app.register_task(ScanResultNotificationWorker())
