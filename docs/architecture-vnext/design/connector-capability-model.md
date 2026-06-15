# Connector Capability Model

A connector is a packaging and deployment unit for platform capabilities.

Products should not consume a connector as a monolith. They should consume specific capabilities exposed by that connector.

## Design Rule

```text
Products orchestrate workflows.
Connectors expose platform capabilities.
Shared contracts define capability boundaries.
```

This keeps product-specific behavior out of connector implementations and avoids creating separate connector stacks for DSX-Connect, DSX-Transfer, desktop tools, SDK workflows, or future file exchange integrations.

## Capability Shape

```text
Connector
  |
  +-- CapabilityManifest
  +-- CredentialProvider
  +-- IdentityResolver
  +-- Discoverer
  +-- Reader
  +-- Writer
  +-- Remediator
  +-- EventSource
```

The connector is the unit that knows how to authenticate, identify, and talk to a platform. The capabilities are the surfaces products compose into workflows.

## Capability Roles

### CapabilityManifest

Declares what the connector supports.

Examples:

- `discover`
- `read`
- `write`
- `remediate`
- `events`
- supported asset types
- supported auth modes
- platform-specific limits

### CredentialProvider

Owns platform authentication and credential refresh.

Products should not copy credential handling into workflow code.

### IdentityResolver

Maps product-level identities to platform-level object identities.

Examples:

- bucket and object identity
- file share and relative path
- drive ID and item ID
- tenant/project/subscription metadata

### Discoverer

Enumerates assets and inventory.

Used by:

- DSX-Connect protected scope discovery
- DSX-Transfer transfer planning
- operator UI asset views

### Reader

Provides file or object bytes and metadata.

Used by:

- DSX-Connect scan workers
- DSX-Transfer scan gates
- SDK and application upload workflows

### Writer

Commits bytes to a destination.

Used by:

- DSX-Transfer native transfer engine
- future guarded copy/move workflows
- destination-side quarantine or clean-room writes

### Remediator

Mutates existing platform content after scan/policy decisions.

Examples:

- delete
- move
- tag
- quarantine
- permission update

Used primarily by DSX-Connect.

### EventSource

Publishes or receives platform change events.

Used by:

- incremental discovery
- event-driven scans
- file exchange integrations
- post-write fallback integrations

## Product Composition

### DSX-Connect

```text
Discoverer
  -> protected scope matching
  -> Reader
  -> Scan
  -> Policy
  -> Remediator
  -> Result/Audit publishing
```

DSX-Connect uses connectors to discover and protect content in existing repositories.

### DSX-Transfer

```text
Discoverer / Planner
  -> Reader
  -> ScanGate
  -> Writer
  -> Audit / Checkpoint
```

DSX-Transfer uses connector capabilities to move content from a source to a sink while gating destination commit.

### Managed File Transfer Integrations

```text
PlatformEvent / TransferAdapter
  -> Reader or stream
  -> ScanGate
  -> CommitDecision
```

For MOVEit, GoAnywhere, Sterling, or similar platforms, the adapter may be the transfer platform itself rather than a storage source or sink.

## Implications

- A GCS connector can expose `Discoverer`, `Reader`, `Writer`, and `Remediator`.
- DSX-Connect can use GCS `Discoverer`, `Reader`, and `Remediator`.
- DSX-Transfer can use GCS `Discoverer`, `Reader`, and `Writer`.
- Shared capability contracts reduce duplicate source/sink adapter work.
- Product workflows stay independent even when they reuse the same connector package.

## Least Privilege

Breaking connectors into capabilities makes least privilege explicit.

Products should request credentials and platform permissions for the capabilities they actually use, not for every operation the connector package can theoretically perform.

Example:

```text
DSX-Connect discovery-only inventory:
  Discoverer
  IdentityResolver
  CredentialProvider

DSX-Connect remediation workflow:
  Discoverer
  Reader
  Remediator
  IdentityResolver
  CredentialProvider

DSX-Transfer source side:
  Discoverer / Planner
  Reader
  IdentityResolver
  CredentialProvider

DSX-Transfer destination side:
  Writer
  IdentityResolver
  CredentialProvider
```

This allows a connector package to support broad capability while a deployment grants narrow permission.

### Permission Shape

Capability manifests should describe required permission classes.

Examples:

- `discover`: list buckets, list drives, enumerate folders, list metadata
- `read`: get object/file bytes, get object metadata
- `write`: create object/file, multipart upload, set destination metadata
- `remediate_delete`: delete object/file
- `remediate_move`: move/copy/delete or rename object/file
- `remediate_tag`: update labels, tags, metadata, or custom properties
- `events`: subscribe to platform events or read change feeds

The manifest should distinguish capability support from granted permission.

```text
supported: connector implementation can do it
granted: this deployment credential is allowed to do it
requested: this product workflow needs it
```

### Product Benefit

Least privilege becomes a workflow decision:

- DSX-Transfer source credentials do not need delete permission.
- DSX-Transfer destination credentials do not need source read permission.
- DSX-Connect read-only monitoring does not need remediation permission.
- DSX-Connect remediation can be enabled only for specific scopes or integrations.
- MFT pre-commit integrations may only need stream read plus commit allow/block permissions.

This also improves customer review because required permissions can be explained in product terms instead of as a broad SDK or platform role.

## Non-Goals

- Do not force every connector to implement every capability.
- Do not require product workflows to route through unused capabilities.
- Do not make UI routes a connector capability boundary.
- Do not bake DSX-Connect remediation assumptions into DSX-Transfer writer contracts.
