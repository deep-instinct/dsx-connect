# dsx_connect/taskworkers/celery_app.py
from celery import Celery
from kombu import Exchange, Queue
from dsx_connect.config import get_config
from dsx_connect.taskworkers.names import Queues, Tasks

cfg = get_config().workers

celery_app = Celery(
    "dsx_connect",
    broker=str(cfg.broker),
    backend=str(cfg.backend),
    include=[
        "dsx_connect.taskworkers.workers.scan_request",
        "dsx_connect.taskworkers.workers.verdict_action",
        "dsx_connect.taskworkers.workers.scan_result",
        "dsx_connect.taskworkers.workers.scan_result_notify",
        "dsx_connect.taskworkers.workers.dianna_analysis",
    ]
)

celery_app.conf.update(
    timezone="UTC",
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_default_queue=Queues.REQUEST,
    task_queues=[
        Queue(Queues.REQUEST, Exchange(Queues.REQUEST), routing_key=Queues.REQUEST),
        Queue(Queues.RESULT,  Exchange(Queues.RESULT),  routing_key=Queues.RESULT),
        Queue(Queues.VERDICT, Exchange(Queues.VERDICT), routing_key=Queues.VERDICT),
        Queue(Queues.NOTIFICATION, Exchange(Queues.NOTIFICATION), routing_key=Queues.NOTIFICATION),
        Queue(Queues.ANALYZE, Exchange(Queues.ANALYZE), routing_key=Queues.ANALYZE),
    ],
    task_routes={
        Tasks.REQUEST: {"queue": Queues.REQUEST, "routing_key": Queues.REQUEST},
        Tasks.RESULT:  {"queue": Queues.RESULT,  "routing_key": Queues.RESULT},
        Tasks.VERDICT: {"queue": Queues.VERDICT, "routing_key": Queues.VERDICT},
        Tasks.NOTIFICATION: {"queue": Queues.NOTIFICATION, "routing_key": Queues.NOTIFICATION},
        Tasks.DIANNA_ANALYZE: {"queue": Queues.ANALYZE, "routing_key": Queues.ANALYZE},
    },
    # backoff/retry knobs (defaults—each task can override)
    task_soft_time_limit=120,   # seconds
    task_acks_late=True,
)

# try:
#     from dsx_connect.taskworkers import taskworkers
#     dsx_logging.debug(f"Successfully imported taskworkers module")
#     from dsx_connect.taskworkers.workers import scan_result_notify
#     dsx_logging.debug(f"Successfully imported workers.scan_result_notify module")
#
#     # Debug: Check if tasks are now registered
#     dsx_logging.debug("Registered tasks after import:")
#     for task_name in celery_app.tasks:
#         if not task_name.startswith('celery.'):
#             dsx_logging.debug(f"  {task_name}")
#
# except ImportError as e:
#     dsx_logging.error(f"Failed to import taskworkers: {e}")
#
# # Debug: Verify the configuration was applied
# dsx_logging.debug(f"Final Celery broker_url: {celery_app.conf.broker_url}")
# dsx_logging.debug(f"Final Celery result_backend: {celery_app.conf.result_backend}")
