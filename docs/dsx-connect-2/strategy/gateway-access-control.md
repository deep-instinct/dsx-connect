# Gateway Access Control Model

## Purpose

As DSX-Connect evolves into a normalized enterprise file gateway, it becomes the focal point for connectivity to enterprise repositories.
That creates two separate access-control questions:

1. What is DSX-Connect allowed to do in the repository?
2. What is an application allowed to do through DSX-Connect?

These are intentionally different layers.

For example, a Google Cloud Storage connector may use Workload Identity Federation to access a bucket.
That only answers whether the connector can reach GCS.
It does not answer whether a specific application, desktop client, service, or user should be allowed to send a file to that bucket through DSX-Connect.

DSX-Connect needs both layers.

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

- [Normalized Enterprise File Gateway](normalized-enterprise-file-gateway.md)
- [ADR-006: Granted Permission Model for Connector Integrations](../../architecture-vnext/adr/adr-006-permission-model.md)
- [Credential Strategy Mapping](../../architecture-vnext/design/credentialing/credential-mapping.md)
