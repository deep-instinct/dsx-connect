# DSX-Connect Vision: Normalized Enterprise File Gateway

## Executive Summary

Enterprise file-security programs often start by validating malware scanning across a few repositories.
The broader need is a common way to govern files as they enter, leave, or move through the business.

Application teams should not be responsible for implementing enterprise file security.

Today, individual teams often decide:

- which repository SDK to use
- which scanning API to call
- when a file must be scanned
- how a malicious file is remediated
- where quarantine lives
- what events are logged
- who receives notifications
- how policy is enforced

That creates duplicated engineering effort, inconsistent security controls, and decentralized governance.

The vision for DSX-Connect is to become a normalized enterprise file gateway:

```text
One API.
One policy model.
Any approved repository.
Central security governance.
```

DSX-Connect should give developers a simple file API while giving Security centralized control over policy, scanning, remediation, audit, notifications, and delivery.

## Strategic Positioning

DSX-Connect should be positioned as more than connector orchestration.

The long-term product position is:

> DSX-Connect is an enterprise-controlled file gateway that gives developers one normalized API for moving files into, out of, and across approved repositories, while Security centrally owns scanning, policy, remediation, audit, and delivery.

This shifts the conversation from:

> We provide malware scanning.

to:

> We provide centralized enterprise governance for every file entering, leaving, or moving throughout the organization.

Malware prevention remains essential, but it becomes one policy-controlled capability behind a broader enterprise file gateway.

## Current State

Today, every application is often responsible for its own file workflow:

```text
Application
    |
    v
Application logic
    |
    +-- choose repository SDK
    +-- authenticate to repository
    +-- upload or download file
    +-- call scanner
    +-- interpret verdict
    +-- quarantine or delete
    +-- notify
    +-- log
    +-- audit
```

Every application becomes partially responsible for security.

Consequences include:

- inconsistent remediation
- many repository-specific implementations
- different audit trails
- different notification workflows
- different policy enforcement behavior
- duplicated operational support
- accumulated security and application technical debt

Security loses centralized governance because each application owns too much of the file-security workflow.

## Desired State

Applications should not own enterprise file security policy.

Applications should express intent:

```text
submit this file
send this file to this approved destination
get the enterprise decision for this file
```

DSX-Connect owns policy and execution:

```text
Application
    |
    v
DSX-Connect
    |
    +-- resolve source or destination
    +-- apply enterprise policy
    +-- scan
    +-- remediate
    +-- audit
    +-- notify
    +-- deliver
    |
    v
Approved repository or application outcome
```

Applications integrate once.
Security policy evolves centrally.
Application code does not change every time enterprise policy changes.

## Product Pillars

### File Security Decision Service

Applications should not ask:

> Is this file malware?

Applications should ask:

> What is the enterprise decision for this file?

The response should be a policy outcome, not only a scanner verdict.

Example outcomes:

- allow
- block
- quarantine
- delete
- hold
- manual review
- release
- retry

The scanner verdict is an input to the decision.
DSX-Connect owns the final policy outcome.

### Normalized Repository Abstraction

Application developers should not need to understand every approved storage platform:

- Google Cloud Storage
- Amazon S3
- Azure Blob Storage
- NetApp
- NAS shares
- SharePoint
- managed file transfer
- partner file-exchange platforms

Applications should discover and use enterprise-approved destinations through a common API.

Connectors become more than technical integrations.
They represent approved enterprise file locations with capabilities and policy attached.

See [Gateway Access Control Model](gateway-access-control.md) for the proposed dual-layer access model: repository permissions such as GCS WIF or service account access, plus DSX-Connect gateway authorization for applications and users.

See [Developer File API Versus Managed File Transfer](developer-file-api-vs-mft.md) for the product boundary between DSX-Connect as a governed developer file API and MFT as a bulk managed movement platform.

See [Tenant Attribution, Metering, And Chargeback Architecture](../architecture/tenant-attribution-chargeback.md) for the requirement that every request carries tenant, application, policy, repository, scanner, and billing context across the complete scan workflow.

### Central Governance Plane

Security should centrally own:

- scan policy
- file type policy
- repository policy
- remediation policy
- notification policy
- audit policy
- compliance policy
- operational monitoring

Applications should focus on business logic, user experience, and application-specific workflow.

## Developer Experience

Application developers should not become security engineers.

Instead of implementing:

- repository-specific SDK calls
- repository credentials
- malware scanning
- quarantine
- remediation
- logging
- notifications
- audit

developers consume one approved enterprise service.

The developer-facing promise is:

```text
One integration.
One SDK.
Enterprise policy handled centrally.
Any approved repository.
```

## Integration Modes

DSX-Connect should support three developer-facing integration modes.

### Synchronous Decision API

The application uploads or streams a file and waits for a security decision.

Example:

```http
POST /api/v1/files/decisions
```

Conceptual response:

```json
{
  "decision": "allow",
  "verdict": "benign",
  "policy": "standard-upload-policy",
  "job_id": "job_...",
  "audit_id": "audit_..."
}
```

This mode fits:

- portals
- upload flows
- API gateways
- managed file-transfer handoffs
- CI/CD gates
- partner submissions

### Asynchronous Submit API

The application submits a file, object reference, or transfer request and receives a durable ID.

Example:

```http
POST /api/v1/files/submissions
```

Conceptual response:

```json
{
  "submission_id": "sub_...",
  "state": "accepted",
  "status_url": "/api/v1/files/submissions/sub_..."
}
```

This mode fits:

- large files
- bulk submissions
- archive processing
- batch workflows
- long-running policy workflows

### Connector And Event Mode

DSX-Connect watches, enumerates, or receives events from repositories and applies policy without application code.

Examples:

- GCS bucket enumeration
- filesystem and NAS folder scanning
- object-created events
- partner drop zones
- MFT landing folders
- repository migration workflows

This mode lets Security protect existing repositories without requiring every application to call an inline API.

## Normalized File API

The normalized API should let applications discover approved destinations and submit transfer intent.

Example destination discovery:

```http
GET /api/v1/destinations
```

Conceptual response:

```json
[
  {
    "id": "gcs-production",
    "type": "google_cloud_storage",
    "display_name": "GCS Production",
    "capabilities": ["read", "write", "scan", "quarantine"],
    "classification": "internal",
    "max_file_size_bytes": 2147483648,
    "policy": "standard-enterprise-upload"
  },
  {
    "id": "netapp-finance",
    "type": "filesystem",
    "display_name": "Finance NAS",
    "capabilities": ["read", "scan", "quarantine"],
    "classification": "confidential",
    "max_file_size_bytes": 2147483648,
    "policy": "finance-file-policy"
  }
]
```

Example transfer intent:

```http
POST /api/v1/transfers
```

Conceptual request:

```json
{
  "source": {
    "type": "upload"
  },
  "destination": {
    "id": "gcs-production",
    "path": "/claims/2026/report.pdf"
  },
  "metadata": {
    "application": "claims-portal",
    "business_unit": "insurance"
  }
}
```

The application does not care how the destination authenticates, where credentials live, how scanning is performed, or how remediation is applied.

DSX-Connect performs the enterprise workflow and returns a standard result.

## Enterprise Workflow

A normalized transfer or submission follows the same enterprise-controlled pattern:

```text
Application submits file or intent
    |
    v
DSX-Connect authenticates the application
    |
    v
DSX-Connect resolves allowed destinations
    |
    v
DSX-Connect evaluates policy
    |
    v
DSX-Connect scans through DSXA
    |
    v
DSX-Connect applies remediation
    |
    v
DSX-Connect audits and notifies
    |
    v
DSX-Connect delivers or blocks
    |
    v
Application receives status or decision
```

The important distinction is that applications receive an enterprise outcome.
They do not directly implement enterprise security decisions.

## Governance Model

### Today

```text
100 applications
    |
    v
100 file-security implementations
    |
    v
100 remediation policies
    |
    v
100 logging models
    |
    v
100 audit trails
```

### Future

```text
100 applications
    |
    v
one enterprise file gateway
    |
    v
one security policy model
    |
    v
one governance model
    |
    v
one audit trail
    |
    v
one operational model
```

## Separation Of Responsibilities

### Application Teams

Application teams own:

- business logic
- user experience
- application-specific workflow
- application metadata passed to DSX-Connect

Application teams do not own:

- scanner selection
- repository credentials
- malware policy
- remediation
- quarantine
- enterprise notifications
- audit policy
- compliance workflow

### Security Team

Security owns:

- approved repositories
- destination capabilities
- file security policy
- malware prevention
- remediation behavior
- governance
- audit
- compliance
- operational monitoring

## Enterprise Use Cases

The same gateway model applies across file workflows:

- inline enterprise application uploads
- customer portals
- partner portals
- managed file transfer
- NetApp and NAS scanning
- GCS and cloud object storage
- cloud migration
- CI/CD artifact validation
- inherited data from mergers and acquisitions
- outbound secure delivery
- internal repository-to-repository transfer

## Relationship To Current DSX-Connect 2

The current DSX-Connect 2 architecture already contains several pieces of this model:

- connectors represent repository-specific access
- assets and protected scopes represent governed repository locations
- scan jobs provide durable workflow
- RabbitMQ and workers provide asynchronous orchestration
- policy and remediation stages exist as first-class job-item states
- scan statistics and comparisons support operational tuning
- result sinks support future event fan-out
- connector proxy readers preserve repository isolation

The next product step is to expose a more explicit developer-facing file API on top of these primitives.

## Architectural Implications

This vision affects several design areas.

### Application Identity

DSX-Connect needs to know which application is submitting a file or transfer request.
Application identity controls which destinations and policies are available.

### Destination Catalog

Connectors and protected scopes should be presented as a destination catalog for application teams.
The catalog should expose capabilities, limits, classifications, and allowed operations.

### Policy Attachment

Policy should attach to applications, destinations, file metadata, business units, and enterprise defaults.
Applications may supply metadata, but Security owns policy interpretation.

### Standard Outcomes

Every integration mode should return standardized outcomes.
Applications should not interpret raw scanner-specific responses.

### Audit Correlation

Every request should produce durable audit identifiers that can be correlated across:

- DSX-Connect
- DSXA
- SIEM
- ticketing systems
- application logs
- repository actions

## Product Value

### For Developers

- one API
- one SDK
- no repository-specific code
- no repository credentials
- no security implementation
- faster application delivery
- consistent response model

### For Security

- one policy engine
- one governance model
- one audit trail
- consistent remediation
- centralized visibility
- centralized operational control
- easier compliance reporting

### For The Enterprise

- less duplicated engineering
- fewer inconsistent controls
- cleaner separation between business logic and security logic
- faster onboarding of new applications
- consistent handling for files across environments

## Product Vision Statement

Applications should not ask:

> How do I securely upload this file to Google Cloud Storage?

Applications should ask:

> Which approved enterprise destination should receive this file?

DSX-Connect answers that question.

Developers discover approved destinations through a common API.
Security owns the policies behind those destinations.
DSX-Connect executes the file workflow and records the audit trail.

The result is:

```text
One API.
One SDK.
Any repository.
One security policy.
One governance model.
```

This extends the original DSX-Connect 2 vision:

```text
One platform.
Every file.
Every environment.
```

to:

```text
One API.
One policy.
Any repository.
```
