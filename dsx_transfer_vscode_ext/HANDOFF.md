# DSX-Transfer VS Code Extension Handoff

Status: developer workflow extension scaffold is implemented and statically validated.

This extension is intentionally separate from `dsxa_assistant_vscode_ext`. It is focused on DSX-Transfer config and run workflows.

## Current Shape

- `package.json`: VS Code manifest, commands, settings
- `src/extension.js`: extension implementation
- `.vscode/launch.json`: Extension Development Host launch config
- `README.md`: local development notes
- `DEMO.md` and `demo-01.md`: manual demo flows
- `dsx-transfer.schema.json`: bundled YAML schema

## Implemented Commands

- `DSX-Transfer: Open Config`
- `DSX-Transfer: Focus Workbench`
- `DSX-Transfer: Create New Transfer`
- `DSX-Transfer: Use Active File as Config`
- `DSX-Transfer: Create Config`
- `DSX-Transfer: Open Local Harness`
- `DSX-Transfer: Add Local Harness`
- `DSX-Transfer: Add Python Integration Skeleton`
- `DSX-Transfer: Run Local Harness`
- `DSX-Transfer: Validate Config`
- `DSX-Transfer: Run Transfer`
- `DSX-Transfer: Show Config Schema`
- `DSX-Transfer: Check Environment`
- `DSX-Transfer: Open Report Item JSON`

## Behavior

The extension calls the local DSX-Transfer CLI and writes results to the `DSX-Transfer` output channel.

Command mapping:

```bash
dsx-transfer config init --preset filesystem-to-gcs --output dsx-transfer.yaml
dsx-transfer config validate --config dsx-transfer.yaml
dsx-transfer migrate --config dsx-transfer.yaml
dsx-transfer config schema
```

For source-tree runs, configure workspace settings:

```json
{
  "dsxTransfer.useModuleInvocation": true,
  "dsxTransfer.pythonPath": "./.venv/bin/python",
  "dsxTransfer.modulePythonPath": ".:dsx_transfer:dsxa_sdk_py",
  "dsxTransfer.configPath": "dsx-transfer.yaml"
}
```

`Validate Config` parses CLI JSON diagnostics and publishes VS Code diagnostics against the configured YAML file.
The extension also validates the configured `dsx-transfer.yaml` on save.
`Run Transfer` validates first, runs `migrate --config`, parses the JSON report, and shows summary counts.
`Create Config` handles an existing config with Open Existing, Overwrite, or Cancel.
`Check Environment` reports workspace/config/invocation/GCS credential visibility/CLI availability.
`Create New Transfer` creates an annotated filesystem-to-GCS workspace, sample source files, a Python integration skeleton, and a workflow checklist in the activity view.
`Add Local Harness` creates a local filesystem-to-filesystem harness with sample allowed and blocked files.
`Run Local Harness` runs the harness config and updates `Last Report`.

## Implemented Views

Activity Bar container: `DSX-Transfer`

- `Last Report`: shows transfer summary plus blocked and failed outcomes from the most recent run.
- When `Create New Transfer` is used, `Last Report` first shows a four-step workflow checklist:
  1. Edit generated config
  2. Use active file as config
  3. Validate config
  4. Run transfer

The checklist advances only after the corresponding command succeeds.

## Schema Support

The extension includes `dsx-transfer.schema.json`, generated from:

```bash
PYTHONPATH=.:dsx_transfer:dsxa_sdk_py ./.venv/bin/python -m dsx_transfer.cli config schema
```

The schema is contributed for `dsx-transfer.yaml` and `dsx-transfer.yml`.

## Validation Already Run

From `dsx_transfer_vscode_ext/`:

```bash
npm run check
```

From the repo root:

```bash
PYTHONPATH=.:dsx_transfer:dsxa_sdk_py ./.venv/bin/python -m dsx_transfer.cli config schema
```

## Not Yet Done

- Run in an actual VS Code Extension Development Host.
- Run create/validate/run commands against a real workspace config from inside VS Code.
- Run the generated local harness from inside VS Code.
- Run the generated Python integration skeleton.
- Decide whether to bundle/cache `dsx-transfer.schema.json` or keep fetching schema dynamically from the CLI.
- Package as `.vsix`.
- Add automated extension tests.
