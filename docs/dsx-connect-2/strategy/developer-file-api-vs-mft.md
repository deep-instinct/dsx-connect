# Use Case: Developer File API Versus Managed File Transfer

## Summary

DSX-Connect File Gateway should be positioned as a developer-facing governed file API, not as a replacement for managed file transfer.

The application developer question is:

```text
How do I safely accept or place a file without becoming a storage,
malware, remediation, audit, and policy expert?
```

DSX-Connect answers that with one normalized API for approved file destinations, centralized security policy, malware scanning, remediation, audit, and delivery outcome.

The managed file transfer question is different:

```text
How do I reliably move large scheduled file sets between enterprise
systems, partners, and protocols?
```

That remains the core MFT domain.

## What MFT Owns

Managed file transfer platforms usually own enterprise-scale file movement:

- partner onboarding
- scheduled transfers
- SFTP, FTPS, AS2, and other transfer protocols
- routing between business endpoints
- delivery guarantees
- restart and retry behavior
- transfer audit
- non-repudiation
- operational transfer monitoring
- high-volume point-to-point movement

MFT is optimized for reliable transport and operational transfer management.

## What DSX-Connect File Gateway Owns

DSX-Connect File Gateway should own security governance around file ingress, egress, and repository placement:

- one upload or submit API for applications
- approved destination discovery
- repository abstraction
- centralized scan policy
- scan-before-delivery enforcement
- standardized security outcomes
- remediation policy
- quarantine, delete, hold, release, or allow behavior
- security metadata
- audit correlation
- delivery to approved repositories

DSX-Connect is optimized for consistent enterprise security decisions and policy enforcement.

## Positioning

DSX-Connect does not need to answer:

```text
How do we move a billion files from point A to point B?
```

That is an MFT, migration, synchronization, or bulk data movement problem.

DSX-Connect should answer:

```text
How does an application safely submit a file to an approved enterprise
destination while Security centrally controls policy, scanning,
remediation, and audit?
```

That is the developer file gateway problem.

## Clean Boundary

The clean boundary is:

```text
MFT moves files between business endpoints.

DSX-Connect governs whether files are allowed to move, where they are
allowed to land, and what security workflow must happen first.
```

There is some overlap when DSX-Connect uploads or delivers files, but the purpose is different.

DSX-Connect delivery exists to complete a governed security workflow.
MFT delivery exists to operate enterprise transfer workflows at scale.

## Developer Experience

Application developers should not need to implement:

- Google Cloud Storage SDK calls
- Amazon S3 SDK calls
- Azure Blob SDK calls
- filesystem or NAS access
- repository credentials
- malware scanning
- scanner verdict interpretation
- quarantine
- delete or release workflows
- enterprise notifications
- audit logging

Instead, applications should call one approved enterprise service.

Conceptually:

```http
GET /api/v1/files/destinations
```

The application discovers only destinations it is authorized to use.

Then:

```http
POST /api/v1/files/transfers
```

The application submits a file and destination intent.

DSX-Connect performs policy evaluation, scanning, remediation, audit, and delivery.

## Example Application Flow

```text
Application
    |
    v
Choose approved destination from DSX-Connect
    |
    v
Upload file to DSX-Connect
    |
    v
DSX-Connect applies enterprise policy
    |
    v
DSX-Connect scans through DSXA
    |
    v
DSX-Connect allows, blocks, quarantines, or delivers
    |
    v
Application receives standardized status
```

The application remains focused on business logic.
Security owns the security workflow.

## Relationship To Existing MFT Flows

DSX-Connect and MFT can coexist.

Common patterns include:

- MFT drops files into a landing zone and DSX-Connect scans or governs that zone.
- DSX-Connect scans files before they are handed to an MFT route.
- Applications use DSX-Connect directly for governed upload workflows.
- MFT remains the system of record for partner transfer operations.
- DSX-Connect remains the system of record for file security policy and outcomes.

This lets enterprises keep existing MFT investments while centralizing file security governance.

## MVP Guidance

For the Developer MVP, use product language that reinforces the developer API use case:

- Upload
- Destination
- Approved destination
- Security status
- Delivery outcome
- Policy outcome
- Audit ID

Avoid making the MVP feel like a general-purpose bulk transfer console.

Terms to use carefully:

- transfer
- route
- batch
- source-to-destination movement
- scheduled delivery

Those terms are useful internally, but they can make the product sound like an MFT replacement if they become the primary user-facing language.

## Product Statement

DSX-Connect File Gateway gives application developers one governed file API.

It is not intended to replace enterprise MFT.

MFT handles large-scale managed movement.
DSX-Connect handles security policy enforcement, repository abstraction, remediation, audit, and governed delivery for files entering or leaving applications.
