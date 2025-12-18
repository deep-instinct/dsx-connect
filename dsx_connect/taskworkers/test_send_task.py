# test_send_task.py - Test sending a task to verify everything works

from dsx_connect.taskworkers.celery_app import celery_app
from dsx_connect.taskworkers.names import Tasks, Queues

# Test data
test_scan_request = {
    "location": "test_file.txt",
    "metainfo": "test scan request",
    "connector_url": "http://localhost:8080"  # Use a test URL
}

print("=== TESTING TASK SEND ===")
print(f"Sending task to queue: {Queues.REQUEST}")
print(f"Task name: {Tasks.REQUEST}")
print(f"Test data: {test_scan_request}")

try:
    # Send the task
    result = celery_app.send_task(
        Tasks.REQUEST,
        queue=Queues.REQUEST,
        args=[test_scan_request]
    )

    print(f"✅ Task sent successfully!")
    print(f"Task ID: {result.id}")
    print(f"Task state: {result.state}")

    # Try to get the result (with timeout)
    try:
        task_result = result.get(timeout=10)
        print(f"✅ Task completed with result: {task_result}")
    except Exception as e:
        print(f"⚠️  Task may still be running or failed: {e}")
        print("Check your worker logs for details")

except Exception as e:
    print(f"❌ Failed to send task: {e}")
    import traceback
    traceback.print_exc()