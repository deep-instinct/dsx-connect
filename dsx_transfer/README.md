# DSX-Transfer

Contract-first package for DSX-Transfer. The initial capability is Guarded Transfer: malware-aware, policy-enforced file movement with a scan gate before destination commit.

This is a sibling package to dsx-connect, intended to reuse shared DSX scanner, policy, audit, and job-state concepts without becoming a dsx-connect connector.

See [docs/index.md](docs/index.md) for architecture notes, scanner and policy design, audit/checkpoint semantics, integration targets, and roadmap.
See [docs/product-modes-and-diagrams.md](docs/product-modes-and-diagrams.md) for high-level diagrams covering enterprise transfer platform adapter mode and build-your-own guarded transfer mode.

Initial transfer targets include local or mounted filesystem destinations and GCS destinations:

```bash
dsx-transfer migrate \
  --source /mnt/source-share \
  --destination gs://customer-clean-bucket/archive \
  --scanner-mode dsxa \
  --dsxa-base-url https://scanner.example.com \
  --transfer-id fs-to-gcs-demo
```

The CLI can also run the shared `dsx-transfer.yaml` config used by UI and editor integrations:

```bash
dsx-transfer migrate --config dsx-transfer.yaml
```

Create, validate, and export schema for editor tooling:

```bash
dsx-transfer config init --preset filesystem-to-gcs --output dsx-transfer.yaml
dsx-transfer config validate --config dsx-transfer.yaml
dsx-transfer config schema
```

Example config:

```yaml
version: 1

transfer:
  id: fs-to-gcs-demo
  policy_id: block-malicious

source:
  kind: filesystem
  path: /mnt/source-share

destination:
  kind: gcs
  uri: gs://customer-clean-bucket/archive

scanner:
  mode: dsxa
  dsxa:
    base_url: https://scanner.example.com

policy:
  verdict_actions:
    malicious: block
    suspicious: block
    unknown: block

runtime:
  audit_jsonl: .dsx-transfer/audit/fs-to-gcs-demo.jsonl
  checkpoint: .dsx-transfer/checkpoints/fs-to-gcs-demo.json
```

Local source-tree setup for DSXA mode:

```bash
./.venv/bin/python -m pip install -e ./dsxa_sdk_py -e ./dsx_transfer
```

## Docs Site

The DSX-Transfer docs have a package-local MkDocs site in this directory.

Install the docs dependencies from the repo root:

```bash
./.venv/bin/python -m pip install -e './dsx_transfer[docs]'
```

Then serve the docs:

```bash
cd dsx_transfer
../.venv/bin/python -m mkdocs serve
```

The Markdown extension import is named `pymdownx`, but the package to install is `pymdown-extensions`.
