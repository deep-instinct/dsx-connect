import os
from dsx_connect.config import get_config
from shared.dsx_logging import dsx_logging
from dsx_connect.taskworkers.names import Queues
from dsx_connect.taskworkers.celery_app import celery_app
"""
Primarily for use in debugging, this start script will start all Celery queues and the workers
"""

if __name__ == "__main__":
    # # Sample data for scan_request_task
    # sample_scan_request = {
    #     "location": "file.txt",
    #     "metainfo": "test scan",
    #     "connector_url": "http://example.com"
    # }
    #
    # Get the config to ensure we're using the right broker/backend
    config = get_config()

    # Print debug info
    print(f"Worker will connect to broker: {config.workers.broker}")
    print(f"Worker will connect to backend: {config.workers.backend}")
    try:
        print(f"Registry Redis URL (DSXCONNECT_REDIS_URL): {config.redis_url}")
    except Exception:
        pass
    try:
        print(f"Results DB URL (DSXCONNECT_RESULTS_DB): {config.results_database.loc}")
        print(f"Results retain (DSXCONNECT_RESULTS_DB__RETAIN): {config.results_database.retain}")
    except Exception:
        pass
    print(f"Queues to listen on:")
    print(f"  - {Queues.REQUEST}")
    print(f"  - {Queues.VERDICT}")
    print(f"  - {Queues.RESULT}")
    print(f"  - {Queues.NOTIFICATION}")
    print(f"  - {Queues.ANALYZE}")
    if getattr(config.workers, "scan_request_batch_enabled", False):
        print(f"  - {Queues.REQUEST_BATCH}")

    pool = os.getenv("DSXCONNECT_WORKER_POOL", "solo")
    concurrency = int(os.getenv("DSXCONNECT_WORKER_CONCURRENCY",
                                os.getenv("DSXCONNECT_SCAN_REQUEST_WORKER_CONCURRENCY", "1")))
    queues = [Queues.REQUEST, Queues.VERDICT, Queues.RESULT, Queues.NOTIFICATION, Queues.ANALYZE]
    if getattr(config.workers, "scan_request_batch_enabled", False):
        queues.append(Queues.REQUEST_BATCH)

    dsx_logging.info(f"Starting Celery worker (pool={pool}, concurrency={concurrency})...")
    celery_app.worker_main([
        "worker",
        "--loglevel=warning",
        f"--pool={pool}",
        f"--queues={','.join(queues)}",  # include batch queue when enabled
        f"--concurrency={concurrency}"
    ])
