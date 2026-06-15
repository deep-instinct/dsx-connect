# DSX-Transfer VS Code Extension

This extension helps developers create, validate, and run `dsx-transfer.yaml` from VS Code.

## Commands

- `DSX-Transfer: Create Config`
- `DSX-Transfer: Add Local Harness`
- `DSX-Transfer: Validate Config`
- `DSX-Transfer: Run Transfer`
- `DSX-Transfer: Show Config Schema`
- `DSX-Transfer: Check Environment`

## CLI Mapping

```bash
dsx-transfer config init --preset filesystem-to-gcs --output dsx-transfer.yaml
dsx-transfer config validate --config dsx-transfer.yaml
dsx-transfer migrate --config dsx-transfer.yaml
dsx-transfer config schema
```

`Create Config` opens the existing config, overwrites it, or cancels when the file already exists.
`Add Local Harness` creates `.dsx-transfer/harness` with a filesystem-to-filesystem local demo config, sample files, a run script, and a short README.
`Run Transfer` validates first, runs the transfer, and updates the `Last Report` view with summary, blocked objects, and failed objects.
`Check Environment` reports the workspace, invocation mode, visible GCS credential variable, CLI availability, and config-file presence.

## Source-Tree Settings

For development from this repo:

```json
{
  "dsxTransfer.useModuleInvocation": true,
  "dsxTransfer.pythonPath": "./.venv/bin/python",
  "dsxTransfer.modulePythonPath": ".:dsx_transfer:dsxa_sdk_py",
  "dsxTransfer.configPath": "dsx-transfer.yaml"
}
```

The extension validates the configured `dsx-transfer.yaml` on save and publishes CLI diagnostics inline. It also ships a generated `dsx-transfer.schema.json` for editor schema support.

## Local Development

```bash
cd dsx_transfer_vscode_ext
npm run check
```

Then open this folder in VS Code and launch an Extension Development Host.
