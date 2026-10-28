# Governed File Movement

Governed file movement is the application-facing file gateway flow. An application requests an upload or a source-to-destination transfer through DSX-Connect. Connectors provide repository access, while the control plane coordinates scanning, policy, delivery, and result tracking.

## Separation of Duties and Operational Boundaries

The File Gateway separates application development, file security, and repository operations. Each team manages the part of the workflow it owns.

| Role | Responsibility | Access boundary |
| --- | --- | --- |
| Application developers and third-party callers | Submit files, select an allowed destination, and inspect outcomes | Gateway credentials bound to a DSX-Connect Application, with destination, action, and path grants |
| Enterprise Security | Define how files are scanned and handled: permit delivery, block, quarantine, delete, or request further analysis | DSX-Connect protection profiles, policies, and disposition controls |
| Internal IT / DevOps | Deploy connectors and maintain repository connectivity and permissions | Repository credentials and cloud or filesystem access managed within connector deployments |

### Developers Use the Gateway

An operator defines a DSX-Connect **Application** representing the real caller and grants it access to selected destinations. The caller authenticates to DSX-Connect, discovers the destinations it is permitted to use, and submits files through the gateway.

For example, a developer uploading to a GCS bucket uses the DSX-Connect file API. The connector holds the Google credentials and performs the repository operation. The developer needs gateway access rather than a bucket credential or a repository-specific integration. The same boundary applies to external suppliers and third-party applications.

### Security Owns File Disposition

The enterprise Security team defines how accepted files enter the scan and policy workflow and which outcomes permit further movement. DSX-Connect coordinates that workflow and records the scan, policy, remediation, and delivery outcomes. Available actions depend on the configured policy and connector capabilities.

A scanning service alone returns a verdict and leaves each application team to implement what happens next. With a governed gateway, those handling decisions belong to the enterprise's security policy. Application teams integrate submission and status handling, while the enterprise controls delivery, quarantine, deletion, and follow-up analysis.

This boundary matters when files arrive from a third party. Once the gateway accepts the file into enterprise-managed processing, the enterprise owns its handling. A caller can receive a rejected or failed upload outcome and an appropriate explanation; its gateway grants determine what further actions it can request. Acceptance into processing and successful delivery to a repository are separate outcomes.

### IT / DevOps Owns Repository Access

Internal IT / DevOps deploys and operates the connectors, configures repository credentials, and grants the permissions required for discovery, reads, delivery, and remediation. Repository credentials stay within that operational boundary instead of being distributed to application developers or external partners.

Gateway grants and repository permissions work together: the Application determines what the caller may request, and the connector's repository permissions determine what DSX-Connect can execute. This lets teams manage application access, security policy, and repository access independently.

The sections below distinguish the current upload path from the planned repository-transfer and authorization features. The separation of duties is the operating model for both.

## Direct upload

The application supplies file content to the gateway. The upload cache holds that content for workers to scan and evaluate before any policy-permitted delivery through the destination connector.

![File gateway direct upload flow](../assets/diagrams/dsx-connect-2-flow-gateway-upload.svg#only-light)
![File gateway direct upload flow](../assets/diagrams/dsx-connect-2-flow-gateway-upload-dark.svg#only-dark)

## Repository transfer

This source-to-destination path is planned; the diagram describes the intended workflow rather than an available repository-transfer API.

The application or operator selects a source and destination. Workers read content through the source connector, scan and evaluate it, and deliver it through the destination connector when policy permits.

![File gateway repository transfer flow](../assets/diagrams/dsx-connect-2-flow-gateway-transfer.svg#only-light)
![File gateway repository transfer flow](../assets/diagrams/dsx-connect-2-flow-gateway-transfer-dark.svg#only-dark)

Both variants record job and stage state in PostgreSQL and dispatch asynchronous work through the outbox relay and RabbitMQ. Operators can inspect scan findings, policy dispositions, and delivery outcomes. Repository monitoring and full scans evaluate repository content independently of these application-initiated operations.

## Gateway authorization design

The following access-control model and phased plan describe the proposed authorization design. They should not be read as confirmation that every grant, identity-provider, or quota feature is implemented.

## Two Layers of Access

### Repository Access

Repository access is owned by the connector/runtime integration.

Examples:

- GCS connector uses WIF, external WIF, or a service account JSON key.
- Filesystem connector uses mounted filesystem permissions.
- SharePoint connector uses Graph API credentials.
- S3 connector uses IAM role assumption or access keys.

This layer controls what the connector can do against the backing platform:

- enumerate buckets, folders, drives, sites, or shares
- read file content
- write delivered files
- quarantine, delete, move, or tag content
- consume monitoring events

This is the granted-permission model: DSX-Connect does not take access to a repository; the repository owner grants DSX-Connect a bounded set of permissions.

### Gateway Access

Gateway access is owned by DSX-Connect.

This layer controls what callers can do through DSX-Connect:

- which protected destinations they can discover
- which destinations they can submit files to
- whether they can read results
- whether they can request remediation
- which path or prefix they can target
- which policy profile applies

Repository access answers:

> Can the connector perform this operation in the repository?

Gateway access answers:

> Is this caller allowed to ask DSX-Connect to perform this operation?

Both must pass.

## Why Both Layers Matter

Repository credentials are usually broader than any single application should have.

For example, a GCS connector may be granted access to `lg-test-01` so it can read, scan, and deliver files across a protected bucket.
That does not mean every application using DSX-Connect should be allowed to write to every prefix in `lg-test-01`.

DSX-Connect should act as the enforcement point between applications and repositories:

```text
Application Identity
    |
    v
DSX-Connect Gateway Authorization
    |
    v
Protected Destination / Policy / Prefix Grant
    |
    v
Connector Repository Authorization
    |
    v
Backing Repository
```

This gives Security centralized control without forcing every application team to manage cloud IAM, repository SDKs, malware policy, remediation behavior, or audit logging.

## Proposed Authorization Model

### Principal

A principal represents the caller.

Examples:

- application client
- API key identity
- OAuth client
- service account
- desktop user identity
- mTLS certificate identity

For the MVP, an API token or static client credential is sufficient.
The target design should support enterprise identity providers and short-lived credentials.

### Protected Destination

A protected destination is an enabled protected scope exposed through the gateway.

Examples:

- `GCS Lab Destination` -> `gs://lg-test-01`
- `Claims Intake` -> `gs://ford-claims/inbound`
- `Finance Fileshare` -> `/mnt/netapp/finance`
- `Legal SharePoint` -> SharePoint site/drive scope

The destination is not just a UI label.
It binds together:

- integration
- repository scope
- connector capabilities
- policy profile
- audit context
- optional classification

### Grant

A grant authorizes a principal to use a protected destination.

Conceptual shape:

```json
{
  "principal_id": "app_claims_portal",
  "destination_id": "scope_claims_intake",
  "actions": ["discover", "submit", "status"],
  "path_prefixes": ["inbound/claims/"],
  "policy_profile": "claims-upload-policy",
  "enabled": true
}
```

The gateway should deny requests when no matching grant exists.

### Actions

Gateway actions should be explicit.

Initial actions:

- `discover`: caller can see the destination in `GET /files/destinations`
- `submit`: caller can submit files to the destination
- `status`: caller can read status for jobs it submitted
- `scan`: caller can submit files for scan-only verdict workflows that do not deliver to a destination
- `read_result`: caller can read detailed scan/result payloads
- `cancel`: caller can cancel jobs it submitted

Future actions:

- `read_object`
- `remediate`
- `quarantine`
- `release`
- `delete`
- `admin`
- `export`

### Path and Prefix Bounds

Grants may limit the caller to a subset of a protected destination.

Example:

```text
Destination: gs://ford-enterprise-intake
Grant path prefix: claims/inbound/
Allowed target: gs://ford-enterprise-intake/claims/inbound/report.pdf
Denied target:  gs://ford-enterprise-intake/legal/inbound/report.pdf
```

Path authorization must be enforced server-side during submission.
The UI may help with previews, but the API must be authoritative.

## API Behavior

### Destination Discovery

`GET /files/destinations` should return only destinations the caller can discover.

Without identity-aware filtering, the endpoint leaks enterprise topology.

MVP behavior:

- authenticated caller required
- filter protected destinations by grant
- include caller-allowed actions and path constraints in the response

Example:

```json
{
  "destinations": [
    {
      "id": "scope_claims_intake",
      "display_name": "Claims Intake",
      "platform": "gcs",
      "protected_target": "gs://ford-claims",
      "allowed_actions": ["discover", "submit", "status"],
      "allowed_path_prefixes": ["inbound/claims/"]
    }
  ]
}
```

### Transfer Submission

`POST /files/transfers` should enforce:

- caller identity exists
- caller has `submit` on the destination
- requested relative path is within an allowed prefix
- destination is enabled
- destination policy allows the request
- connector has required repository capability

Only after gateway authorization passes should DSX-Connect create the job.

### Destination-Less Scan Submission

Some applications only need a verdict.
They are not asking DSX-Connect to deliver the file to a repository.

That workflow should be modeled explicitly instead of overloading destination-backed transfer.
For example, a future `POST /files/scans` endpoint could require:

- caller identity exists
- caller has the `scan` action
- application or request resolves to a scan policy
- application or request resolves to a DSXA protected entity
- quota checks pass

This preserves the same identity, attribution, metering, and audit model while avoiding a fake destination.

### Quota Enforcement

Gateway authorization should eventually include application quota checks before job creation.
Quotas may apply to file count, bytes processed, request rate, concurrent jobs, or monthly usage.

Quota denial should be explicit and auditable.
The denial should identify the application and quota category without exposing unrelated tenant or destination details.

### Job Status

Job status should be scoped to the submitting principal unless the caller has a broader operator/admin grant.

This avoids one application reading another application's transfer history.

## Audit Requirements

Every gateway request should record:

- principal id
- authentication mechanism
- client/application label
- destination id
- integration id
- scope id
- requested relative path
- resolved repository target
- file names and hashes
- policy profile
- authorization decision
- denial reason when denied
- job id when accepted
- final delivery target and outcome

Audit should make the distinction clear:

- gateway authorization allowed or denied the caller
- repository authorization allowed or denied the connector operation

This helps diagnose cases where the application is authorized in DSX-Connect but the connector lacks backing repository permission, or vice versa.

## MVP Plan

### Phase 1: Static Gateway Clients

Add:

- `gateway_clients`
- `gateway_grants`
- static bearer token or API key authentication

Implement:

- identify caller from token
- filter `GET /files/destinations`
- enforce `submit` on `POST /files/transfers`
- enforce optional relative path prefixes
- record principal and grant metadata in job payload/audit data

This is enough to prove the enterprise gateway pattern.

### Phase 2: Identity Provider Integration

Add:

- OIDC/JWT validation
- client/application claims mapping
- group or role based grants
- token expiry and issuer/audience validation

This aligns the gateway with enterprise identity.

### Phase 3: Policy-Integrated Grants

Add:

- grant-level policy profile binding
- classification requirements
- environment constraints
- approval workflows for sensitive destinations

This lets Security express not only who can submit where, but also which policy is applied.

### Phase 4: Brokered Runtime Access

Longer term, repository access should move toward brokered short-lived credentials where possible.

For GCS, that means WIF or service account impersonation.
For AWS, STS role assumption.
For Azure, managed identity or OAuth tokens.

Gateway grants remain separate from repository credentials.
The broker answers how DSX-Connect obtains execution access.
Gateway authorization answers whether the caller is allowed to invoke that access.

## Design Principles

- Do not expose all protected scopes to all callers.
- Do not rely on cloud IAM alone to authorize application use of the gateway.
- Do not rely on UI filtering for authorization.
- Enforce grants in the API before job creation.
- Keep repository credentials scoped to connector/runtime needs.
- Keep application grants scoped to business intent.
- Audit both authorization layers.

## Relationship to Existing Documents

- [Application Identity and Attribution](../dsx-connect-2/concepts/application-identity-and-attribution.md)
- [ADR-006: Granted Permission Model for Connector Integrations](../architecture-vnext/adr/adr-006-permission-model.md)
- [Credential Strategy Mapping](../architecture-vnext/design/credentialing/credential-mapping.md)

For a practical application scenario, see [Developer File API and Managed File Transfer](../case-studies/developer-file-api-vs-mft.md).
