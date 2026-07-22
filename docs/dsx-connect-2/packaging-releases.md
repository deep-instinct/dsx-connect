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

!!! warning "Keep image and chart OCI refs separate"
    Do not publish the Helm chart and container image to the same OCI repository and tag.
    For example, `dsxconnect/dsx-connect:2.0.0` must remain the runnable container image, while `dsxconnect/dsx-connect-chart:2.0.0` is the Helm chart artifact.
    If both artifacts use `dsxconnect/dsx-connect:2.0.0`, Kubernetes can pull the chart artifact as the pod image and fail before `python` starts.

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

## Release and Lab Upgrade Checklist

Use this flow when cutting a DSX-Connect 2 release and immediately updating the shared lab stack.

1. Bump the DSX-Connect version in source.
   Update `dsx_connect_ng/pyproject.toml`, `dsx_connect_ng/deploy/helm/Chart.yaml`, and version-pinned DSX-Connect 2 docs.

2. Validate before tagging.

   ```bash
   pytest dsx_connect_ng/tests/test_ui_routes.py
   scripts/dsx-connect-ng/package-chart.sh --destination /tmp/dsx-connect-charts
   ```

3. Commit, tag, push, and watch the DSX-Connect release.

   ```bash
   git commit -m "Bump DSX-Connect v2 to 2.0.14"
   git tag dsx-connect-v2.0.14
   git push origin main dsx-connect-v2.0.14
   gh run list --workflow release-dsx-connect-v2.yml --limit 5
   gh run watch <run_id> --exit-status
   ```

4. If connector artifacts changed, bump each connector version in source.
   Update the connector `version.py`, connector Helm `Chart.yaml`, and version-pinned connector docs.

5. Validate connector releases before tagging.

   ```bash
   scripts/connectors/test.sh filesystem
   scripts/connectors/lint-chart.sh filesystem
   scripts/connectors/package-chart.sh filesystem --version 2.0.7 --app-version 2.0.7 --destination /tmp/dsx-connect-connector-charts

   scripts/connectors/test.sh google_cloud_storage
   scripts/connectors/lint-chart.sh google_cloud_storage
   scripts/connectors/package-chart.sh google_cloud_storage --version 2.0.9 --app-version 2.0.9 --destination /tmp/dsx-connect-connector-charts
   ```

6. Commit, tag, push, and watch connector releases.
   Connector release tags must use `connector-<connector_slug>-v<version>`.

   ```bash
   git commit -m "Bump connector releases"
   git tag connector-filesystem-v2.0.7
   git tag connector-google_cloud_storage-v2.0.9
   git push origin main connector-filesystem-v2.0.7 connector-google_cloud_storage-v2.0.9

   gh run list --workflow release-connector.yml --limit 10
   gh run watch <filesystem_run_id> --exit-status
   gh run watch <gcs_run_id> --exit-status
   ```

7. Upgrade the lab only after the release workflows succeed.
   For a persistent lab, prefer the helper documented in [Development deployment](deployment/development.md#update-a-lab-stack-with-helper-scripts).

   ```bash
   scripts/dsx-connect-ng/update-lab-stack.sh \
     --connect-version 2.0.14 \
     --gcs-version 2.0.9 \
     --filesystem-version 2.0.7 \
     --core-values ~/.dsx-connect-lab/dsx-connect-values.yaml \
     --gcs-values ~/.dsx-connect-lab/gcs-values.yaml \
     --filesystem-values ~/.dsx-connect-lab/filesystem-values.yaml
   ```

   Direct Helm upgrades are also acceptable when values are already attached to the lab releases:

   ```bash
   helm --kube-context k3s-uslab upgrade --install dsx-connect \
     oci://registry-1.docker.io/dsxconnect/dsx-connect-chart \
     --version 2.0.14 -n dsx-connect --reuse-values --wait --timeout 5m

   helm --kube-context k3s-uslab upgrade --install filesystem \
     oci://registry-1.docker.io/dsxconnect/filesystem-connector-chart \
     --version 2.0.7 -n dsx-connect --reuse-values --wait --timeout 5m

   helm --kube-context k3s-uslab upgrade --install gcs \
     oci://registry-1.docker.io/dsxconnect/google-cloud-storage-connector-chart \
     --version 2.0.9 -n dsx-connect --reuse-values --wait --timeout 5m
   ```

8. Verify the lab.

   ```bash
   helm --kube-context k3s-uslab list -n dsx-connect
   kubectl --context k3s-uslab rollout status deploy/dsx-connect-api -n dsx-connect --timeout=180s
   kubectl --context k3s-uslab rollout status deploy/filesystem-filesystem-connector -n dsx-connect --timeout=180s
   kubectl --context k3s-uslab rollout status deploy/gcs-google-cloud-storage-connector -n dsx-connect --timeout=180s

   kubectl --context k3s-uslab get deploy dsx-connect-api filesystem-filesystem-connector gcs-google-cloud-storage-connector \
     -n dsx-connect \
     -o jsonpath='{range .items[*]}{.metadata.name}{"="}{.spec.template.spec.containers[0].image}{"\n"}{end}'
   ```

   Check the UI metadata endpoint when an ingress host is configured:

   ```bash
   curl -k -sSL http://dsx-connect.<lab-host-ip>.nip.io/api/v1/ui/meta
   ```

## Versioning Rules

Use immutable release tags.

Recommended rules:

* never move a released version tag
* chart version and chart `appVersion` should match for DSX-Connect 2 releases
* connector chart version and connector image tag should match for connector releases
* use explicit tags in deployment values, not `latest`
* use CI-specific tags for test builds, such as commit SHA or branch-safe tags

## Local Testing Before Release

Before publishing release artifacts, validate the local path with the workflows in [Development deployment](deployment/development.md).
Use the Operator Console to confirm connector registration, asset inventory, and scan dispatch before cutting a release.
