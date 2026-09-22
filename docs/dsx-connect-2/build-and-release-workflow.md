# DSX-Connect 2 Build and Release Workflow

This page describes the supported build and release path for DSX-Connect 2. It complements [Packaging Releases](packaging-releases.md), which defines the image and Helm artifact layout.

## Release inputs

The DSX-Connect 2 release workflow uses the version in `dsx_connect_v2/pyproject.toml` unless a version is supplied through manual workflow dispatch. For a tag-triggered release, the tag must match that version:

```text
dsx-connect-v<version>
```

For example, version `2.0.0` must be released with:

```bash
git tag dsx-connect-v2.0.0
git push origin main dsx-connect-v2.0.0
```

The workflow fails when a pushed tag does not match the checked-in version.

## Local validation

Before creating a release tag, validate the v2 package, chart, and tests from the working tree:

```bash
pytest dsx_connect_v2/tests/test_ui_routes.py
scripts/dsx-connect-v2/package-chart.sh --destination /tmp/dsx-connect-charts
```

For local image and deployment testing, use the v2 development workflow described in [Development Deployment](deployment/development.md). Local builds and chart packaging do not publish customer-facing artifacts.

## CI release workflow

The GitHub Actions workflow is:

```text
.github/workflows/release-dsx-connect-v2.yml
```

It can run in either of these modes:

- **Tag-triggered:** push a `dsx-connect-v*` tag that matches the checked-in version.
- **Manual:** dispatch the workflow and optionally provide the version, registry, Helm repository, target platforms, and whether to publish `latest`.

The workflow builds and publishes:

- a multi-architecture DSX-Connect 2 container image;
- the matching Helm chart as an OCI artifact;
- `latest` when the manual `push_latest` option is enabled.

The image and chart use separate artifact names. For version `2.0.0`, the expected outputs are:

```text
dsxconnect/dsx-connect:2.0.0
oci://registry-1.docker.io/dsxconnect/dsx-connect-chart --version 2.0.0
```

## Required CI configuration

The release job requires these secrets:

| Secret | Purpose |
| --- | --- |
| `OCR_USERNAME` | Registry username |
| `OCR_TOKEN` | Registry token or password |

The default workflow target is Docker Hub and its OCI registry endpoint. Change the workflow dispatch inputs when publishing to another compatible registry.

## Release sequence

1. Update the v2 version in `dsx_connect_v2/pyproject.toml` and the Helm chart metadata.
2. Run the local tests and chart packaging checks.
3. Commit and push the version change.
4. Create and push the matching `dsx-connect-v<version>` tag, or manually dispatch the workflow with an explicit version.
5. Watch the GitHub Actions run and verify the image and chart artifacts.
6. Update the lab only after the release workflow succeeds.

Connector releases are separate from the core DSX-Connect 2 release and use the connector-specific workflows and tags documented in [Packaging Releases](packaging-releases.md).

