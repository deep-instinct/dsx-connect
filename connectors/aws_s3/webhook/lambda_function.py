import os
import httpx

#
# The following is example lambda code that can be used to call the Connector's webhook/event API on an S3 bucket event

# Customize your DSX webhook URL
WEBHOOK_URL = os.environ.get("DSX_CONNECTOR_WEBHOOK_URL")

def lambda_handler(event, context):
    try:
        # Send to DSX Connector's webhook
        with httpx.Client(timeout=10.0, verify=False) as client:
            resp = client.post(WEBHOOK_URL, json=event)
            resp.raise_for_status()

        return {"statusCode": 200, "body": "Webhook sent successfully"}
    except Exception as e:
        return {"statusCode": 500, "body": f"Error: {str(e)}"}
