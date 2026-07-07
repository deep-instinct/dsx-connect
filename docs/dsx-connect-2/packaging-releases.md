# Packaging Releases

DSX-Connect 2 releases should publish two kinds of artifacts:

* container images
* Helm charts

Images and charts should be distributed separately, but versioned together.
The Helm chart should point at the matching default image tag through its `appVersion`.

## Recommended Distribution Model

Use a container registry for runtime images and OCI Helm charts.

For a DSX-Connect 2 release such as `2.0.0`:

| Artifact | Example |
| --- | --- |
| Image | `dsxconnect/dsx-connect:2.0.0` |
| Chart | `oci://registry-1.docker.io/dsxconnect/dsx-connect-chart --version 2.0.0` |
| Chart `appVersion` | `2.0.0` |

For a connector release such as GCS connector `0.5.56`:

| Artifact | Example |
| --- | --- |
| Image | `dsxconnect/google-cloud-storage-connector:0.5.56` |
| Chart | `oci://registry-1.docker.io/dsxconnect/google-cloud-storage-connector-chart --version 0.5.56` |

GitHub Releases should remain the human-facing release surface:

* release notes
* install examples
* migration notes
* links to image and chart artifacts
* checksums or provenance details when needed

## Build and Push DSX-Connect 2 Images

Build and push a multi-architecture DSX-Connect 2 image:

```bash
scripts/dsx-connect-ng/build-image.sh \
  --tag 2.0.0 \
  --registry dsxconnect \
  --push \
  --platform linux/amd64,linux/arm64
```

This publishes:

```text
dsxconnect/dsx-connect:2.0.0
```

## Package and Push the DSX-Connect 2 Chart

Package and push the Helm chart as an OCI artifact:

```bash
scripts/dsx-connect-ng/package-chart.sh \
  --push oci://registry-1.docker.io/dsxconnect
```

Consumers can install from the OCI chart reference:

```bash
helm install dsx-connect oci://registry-1.docker.io/dsxconnect/dsx-connect-chart \
  --version 2.0.0 \
  -n dsx-connect \
  --create-namespace
```

## Build and Push Connector Images

Build and push connector images with the connector build script:

```bash
scripts/connectors/build-image.sh google_cloud_storage \
  --tag 0.5.56 \
  --registry dsxconnect \
  --push \
  --platform linux/amd64,linux/arm64
```

This publishes:

```text
dsxconnect/google-cloud-storage-connector:0.5.56
```

Use the same pattern for other connectors.

## Registry Strategy

Recommended split:

| Registry | Purpose |
| --- | --- |
| GHCR | CI images, developer previews, short-lived test tags |
| Product registry, OCR, or Docker Hub | customer-facing release images |
| OCI chart registry | released Helm charts, ideally in the same namespace as images |

Keeping images and charts in the same OCI registry namespace simplifies:

* authentication
* install documentation
* release discovery
* artifact provenance

## CI/CD Release Flow

A practical release flow:

1. Pull requests build and test images without publishing customer tags.
2. Main branch builds can publish short-lived CI tags if needed.
3. A release tag triggers multi-architecture image builds.
4. The same release workflow packages and pushes Helm charts.
5. GitHub Releases publish release notes and install examples.

## GitHub Actions Release

DSX-Connect 2 release builds should run in GitHub Actions so release artifacts match a Git commit, not a local working tree.

Use:

```text
.github/workflows/release-dsx-connect-v2.yml
```

The workflow can be started manually from GitHub Actions, or by pushing a tag that matches:

```text
dsx-connect-v2.0.0
```

For tag-triggered releases, the tag version must match `dsx_connect_ng/pyproject.toml`.
For example, if `pyproject.toml` says `2.0.0`, the expected tag is:

```text
dsx-connect-v2.0.0
```

The workflow publishes:

```text
dsxconnect/dsx-connect:2.0.0
oci://registry-1.docker.io/dsxconnect/dsx-connect-chart --version 2.0.0
```

If `push_latest` is enabled, it also publishes:

```text
dsxconnect/dsx-connect:latest
```

Required repository or environment secrets:

| Secret | Purpose |
| --- | --- |
| `OCR_USERNAME` | Registry username |
| `OCR_TOKEN` | Registry token or password |

Recommended environment:

```text
dsx-connect-release
```

Use the environment to require approval before pushing customer-facing images and charts.

## Versioning Rules

Use immutable release tags.

Recommended rules:

* never move a released version tag
* chart version and chart `appVersion` should match for DSX-Connect 2 releases
* connector chart version and connector image tag should match for connector releases
* use explicit tags in deployment values, not `latest`
* use CI-specific tags for test builds, such as commit SHA or branch-safe tags

## Local Testing Before Release

Before publishing release artifacts, validate the local path:

```bash
scripts/dsx-connect-ng/build-image.sh \
  --tag dev \
  --registry local/dsx-connect \
  --load

scripts/dsx-connect-ng/deploy-k3s.sh \
  --tag dev \
  --registry local/dsx-connect \
  --release dsx-connect \
  --namespace dsx-connect \
  -f dsx_connect_ng/deploy/helm/values-local-stack.yaml
```

Then build and deploy connector images locally:

```bash
scripts/connectors/build-image.sh google_cloud_storage \
  --tag dev \
  --registry local/dsx-connect \
  --load

scripts/connectors/deploy-k3s.sh google_cloud_storage \
  --tag dev \
  --registry local/dsx-connect \
  --release gcs \
  --namespace dsx-connect \
  -f connectors/google_cloud_storage/deploy/helm/values-local-ng.yaml \
  --pull-policy IfNotPresent
```

Use the Operator Console to confirm connector registration, asset inventory, and scan dispatch before cutting a release.
