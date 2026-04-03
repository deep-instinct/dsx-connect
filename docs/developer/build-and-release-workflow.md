# Build and Release Workflow

This page defines the intended build, versioning, and release workflow for DSX-Connect artifacts as the project matures.

## Goals

- Keep local development fast and convenient.
- Keep official release artifacts reproducible and traceable.
- Avoid silently changing versions during build or release.
- Separate local testing from shared dev publishing and official release publication.

## Core Principle

Version bumps are explicit.

Build and publish workflows should use the version already checked into source. They should not silently bump versions as a side effect.

This is a shift from the earlier convenience model where release tasks auto-bumped versions. That was useful early on, but it becomes risky as release maturity increases.

## Why Explicit Bumps

Explicit version bumps make release intent clear:

- a developer decides that a component changed in a release-worthy way
- the version is updated in source
- CI builds and publishes exactly that version

This avoids a class of problems where:

- a release task changes versions unexpectedly
- the published artifact version is not obvious from the source tree
- different machines produce different release outcomes

## The Remaining Caveat

The old auto-bump model had one advantage:

- if a developer changed code that affects an image but forgot to bump the version, a new image still got produced

That convenience is real, but it should be handled with validation, not silent mutation.

The long-term answer is:

- explicit bumping by developers
- CI always builds for validation
- release workflows fail or warn when version intent is inconsistent

Examples of useful guardrails:

- fail release if the release tag already exists
- fail release if publish is requested but the checked-in version was already published
- optionally warn when release-relevant source changed but version did not

## Three Workflow Lanes

### 1. Local Development

This is the normal developer loop for local Docker, Docker Compose, or local Colima/k3s testing.

Use local builds and local deployment assets from the working tree.

Example tasks:

```bash
inv build-all-local
inv deploy-all-local
```

Docker Compose workflow:

```bash
inv build-all-local
inv compose-up-local
inv compose-down-local
```

Docker Compose with the bundled DSXA stack:

```bash
inv build-all-local
inv compose-up-local --include-dsxa
```

Characteristics:

- builds images into the local Docker daemon
- does not push images to Docker Hub
- does not publish Helm charts to OCI
- uses local chart directories for Helm deploys
- uses repo-local `docker-compose-*.yaml` files for Compose deploys
- uses local `:latest` image tags for Compose deploys
- optimized for "does this work on my machine?"

For local development, rebuilding should not require a version bump. Local build tasks should behave like development tasks, not official release tasks.

### 2. Shared Dev / Test Registry

This is for shared testing outside a single developer machine.

Example task:

```bash
inv push-all-dev
```

Characteristics:

- builds current-version images
- pushes them to a dev namespace or dev registry
- packages and pushes Helm charts to a dev OCI repo
- does not bump versions
- intended for shared clusters, teammate testing, or CI-managed pre-release validation

This is still not the official release path.

### 3. Official Release

Official release publication should be CI-driven, not laptop-driven.

Characteristics:

- builds from a specific commit/tag
- uses the version already checked into source
- publishes official images and charts
- creates GitHub releases and release artifacts where applicable
- should be the only authoritative source of customer-facing artifacts

Rule of thumb:

> If customers may consume it, it should be built and published by CI from a known commit, not from a developer laptop.

## Current Task Model

### Root Invoke Tasks

At the repository root:

- `inv build-all-local`
  - rebuild local images for core and selected connectors
- `inv deploy-all-local`
  - deploy from local Helm chart directories into the local cluster
- `inv compose-up-local`
  - start the local Docker Compose stack from repo compose files
- `inv compose-down-local`
  - stop the local Docker Compose stack
- `inv push-all-dev`
  - build and publish current-version dev images/charts
- `inv release-all`
  - official-style release path
  - this is now considered release-oriented, not the normal local developer path

### Desktop App Versioning Tasks

Desktop apps now have their own local `invoke` tasks in their own directories.

DSXA Desktop:

```bash
cd dsxa_desktop
inv bump
inv bump --version 1.2.4
```

DSX-Connect Desktop:

```bash
cd dsx_connect_desktop
inv bump
inv bump --version 0.8.2
```

Those tasks update the version files for each desktop app without involving the root task namespace.

## Local vs OCI Helm Charts

For local testing, charts should generally be installed from the working tree:

```bash
helm upgrade --install dsx-connect ./dsx_connect/deploy/helm
```

or via `inv deploy-all-local`.

For shared dev and official release publication, Helm charts may be packaged and pushed to an OCI repo:

```text
oci://...
```

So:

- local testing uses local chart paths
- shared dev and official release use OCI-published charts

## Local Docker Compose

For local Docker Compose testing, the project should use compose files directly from the repository rather than publishing compose bundles or pushing images first.

The local compose tasks:

- create the shared `dsx-connect-network` if needed
- use local `:latest` tags produced by `inv build-all-local`
- layer the core compose file together with selected connector compose files
- optionally add the bundled DSXA compose file

This keeps the local Compose workflow parallel to the local Helm workflow:

- Helm local: local images + local chart directories
- Compose local: local images + local compose files

## Recommended Release Discipline

The intended mature workflow is:

1. Make code changes.
2. Bump only the component versions that actually changed.
3. Validate locally with local build/deploy workflows.
4. Optionally publish to a shared dev registry for broader testing.
5. Publish official artifacts from CI using the already checked-in versions.

This keeps versioning explicit, artifacts reproducible, and local development fast.
