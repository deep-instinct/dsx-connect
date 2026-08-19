# DSX File Gateway Desktop

DSX File Gateway Desktop is an MVP Electron client for the normalized enterprise file gateway model.

The app lets a developer:

1. Connect to DSX-Connect.
2. Discover enterprise-approved destinations.
3. Pick one or more local files.
4. Submit those files to DSX-Connect for either governed delivery or scan-only verdicts.
5. Watch the governed DSX-Connect job status.

The app does not own scan policy, remediation, audit, or destination governance.
Those responsibilities stay in DSX-Connect.

## Run From Source

```bash
cd dsx_file_gateway_desktop
npm install
npm run dev
```

Default DSX-Connect URL:

```text
http://dsx-connect.10.2.4.103.nip.io/api/v1
```

## Required DSX-Connect API

The MVP uses:

```text
GET  /api/v1/files/destinations
POST /api/v1/files/transfers
GET  /api/v1/execution/jobs/{job_id}/progress
GET  /api/v1/execution/jobs/{job_id}/dsxa
GET  /api/v1/execution/jobs/{job_id}/items/dsxa
```

`POST /api/v1/files/transfers` accepts multipart file uploads, stores them in the DSX-Connect gateway upload cache, and submits a durable `file.transfer` job using cached content sources.

When `destination_id` is omitted, the same endpoint submits a durable `file.scan` job. The uploaded files are scanned from the gateway cache and no delivery target is created.
