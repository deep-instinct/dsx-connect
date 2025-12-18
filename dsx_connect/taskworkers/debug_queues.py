# debug_queues.py - Run this to see what queue names are being generated

from dsx_connect.taskworkers.names import Queues, Tasks
from dsx_connect.config import get_config, APP_ENV

print("=== QUEUE NAMES ===")
print(f"APP_ENV: {APP_ENV}")
print(f"REQUEST: {Queues.REQUEST}")
print(f"VERDICT: {Queues.VERDICT}")
print(f"RESULT: {Queues.RESULT}")
print(f"NOTIFICATION: {Queues.NOTIFICATION}")

print("\n=== TASK NAMES ===")
print(f"REQUEST: {Tasks.REQUEST}")
print(f"VERDICT: {Tasks.VERDICT}")
print(f"RESULT: {Tasks.RESULT}")
print(f"NOTIFICATION: {Tasks.NOTIFICATION}")

print("\n=== CONFIG ===")
cfg = get_config()
print(f"Broker: {cfg.workers.broker}")
print(f"Backend: {cfg.workers.backend}")
print(f"Redis URL: {cfg.redis_url}")

# Test task registration
from dsx_connect.taskworkers.celery_app import celery_app
print("\n=== REGISTERED TASKS ===")
for task_name in sorted(celery_app.tasks.keys()):
    if not task_name.startswith('celery.'):
        print(f"  {task_name}")