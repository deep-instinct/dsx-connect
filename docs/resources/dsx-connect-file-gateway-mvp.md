# DSX-Connect File Gateway Quickstart

This is a short handout for showing how an application developer can use DSX-Connect as a file gateway:

1. discover approved destinations through the API
2. submit a file
3. poll for the result

The point of the demo is that the application does not implement repository-specific logic, scan policy, or remediation. DSX-Connect owns that behavior.

## What You Need

- DSX-Connect API base URL
- a bearer token for the gateway
- one or more local files to submit

For the following examples, use your DSX-Connect API base URL:

```text
http://YOUR_DSX_CONNECT_HOST/api/v1
```

Change this to wherever your DSX-Connect API resides.

## 1. Discover Destinations

Ask DSX-Connect which destinations are available to the caller:

```bash
curl -sS \
  http://YOUR_DSX_CONNECT_HOST/api/v1/files/destinations \
  -H 'Authorization: Bearer YOUR_GATEWAY_TOKEN'
```

The response is a list of destination records. Pick the destination you want to use and note its `destination_id`.

## 2. Submit a File

Use `POST /api/v1/files/transfers` with multipart form data.

### Governed transfer to a destination

```bash
curl -sS -X POST \
  http://YOUR_DSX_CONNECT_HOST/api/v1/files/transfers \
  -H 'Authorization: Bearer YOUR_GATEWAY_TOKEN' \
  -F 'destination_id=YOUR_DESTINATION_ID' \
  -F 'destination_path=' \
  -F 'metadata={"application":"YOUR_APPLICATION_ID"}' \
  -F 'files=@/path/to/sample-file.pdf'
```

### Scan-only submission

If you omit `destination_id`, the gateway can submit a scan-only job instead of a delivery job:

```bash
curl -sS -X POST \
  http://YOUR_DSX_CONNECT_HOST/api/v1/files/transfers \
  -H 'Authorization: Bearer YOUR_GATEWAY_TOKEN' \
  -F 'metadata={"application":"YOUR_APPLICATION_ID"}' \
  -F 'files=@/path/to/sample-file.pdf'
```

## 3. Poll for Job Progress

The transfer response includes a `job_id`. Use that to check progress:

```bash
curl -sS \
  http://YOUR_DSX_CONNECT_HOST/api/v1/execution/jobs/JOB_ID/progress?item_limit=25 \
  -H 'Authorization: Bearer YOUR_GATEWAY_TOKEN'
```

To see the DSXA result for each item:

```bash
curl -sS \
  http://YOUR_DSX_CONNECT_HOST/api/v1/execution/jobs/JOB_ID/items/dsxa?limit=100 \
  -H 'Authorization: Bearer YOUR_GATEWAY_TOKEN'
```

## What The Developer Sees

The developer experience should be simple:

- discover the approved destination list
- choose one destination
- upload a file
- read the job result

DSX-Connect handles:

- connector access
- destination governance
- scan orchestration
- policy decisions
- audit records
- result delivery

## Why S3-Compatible Storage Fits the Demo

An S3-compatible destination is useful for a demo because it behaves like object storage from the application point of view.

That makes it a good target for the file gateway story:

- the app only cares that a destination exists
- DSX-Connect knows which destination is approved
- the underlying storage can be AWS S3 or another S3-compatible system

This keeps the developer workflow stable while the storage backend changes.
