# DSX-Transfer VS Code Extension Demo

This demo shows the extension as a developer workbench for creating, validating, running, and inspecting DSX-Transfer configs.

## Setup

Open the repo workspace in VS Code:

```bash
code /Users/logangilbert/PycharmProjects/dsx-connect
```

Use these workspace settings for source-tree execution:

```json
{
  "dsxTransfer.useModuleInvocation": true,
  "dsxTransfer.pythonPath": "/Users/logangilbert/PycharmProjects/dsx-connect/.venv/bin/python",
  "dsxTransfer.modulePythonPath": ".:dsx_transfer:dsxa_sdk_py",
  "dsxTransfer.configPath": "dsx-transfer.yaml"
}
```

For GCS runs, also set:

```json
{
  "dsxTransfer.extraEnv": {
    "GOOGLE_APPLICATION_CREDENTIALS": "/path/to/service-account.json"
  }
}
```

## Extension Host

From the extension project:

```bash
cd /Users/logangilbert/PycharmProjects/dsx-connect/dsx_transfer_vscode_ext
npm run check
```

Open the extension folder in VS Code and press `F5`.

In the Extension Development Host, open:

```bash
/Users/logangilbert/PycharmProjects/dsx-connect
```

## Demo Flow

### Local Harness

1. Open the DSX-Transfer activity bar icon.
2. Confirm the welcome actions are visible in `Last Report`.
3. Run `DSX-Transfer: Check Environment`.
4. Run `DSX-Transfer: Add Local Harness`.
5. Show the generated config:

```text
.dsx-transfer/harness/dsx-transfer.local.yaml
```

6. Run `DSX-Transfer: Run Local Harness`.
7. In `Last Report`, show:

- transfer summary
- `Blocked` count is `1`
- `Failed` count is `0`
- `blocked-demo.txt` is blocked as `suspicious`
- `hello.txt` is allowed

8. Select `blocked-demo.txt` and run `DSX-Transfer: Open Report Item JSON`.
9. Open `.dsx-transfer/harness/destination` and confirm only `hello.txt` was written.
10. Open `.dsx-transfer/harness/audit/local-harness.jsonl` if present.

## Config Switching

1. Open `.dsx-transfer/harness/dsx-transfer.local.yaml`.
2. Run `DSX-Transfer: Use Active File as Config`.
3. Run `DSX-Transfer: Validate Config`.
4. Run `DSX-Transfer: Run Transfer`.

This demonstrates that CLI, extension, and generated harness all use the same `dsx-transfer.yaml` config contract.

## GCS Config Flow

1. Run `DSX-Transfer: Create Config`.
2. Open `dsx-transfer.yaml`.
3. Update:

```yaml
source:
  path: /real/source/path

destination:
  uri: gs://real-bucket/archive
```

4. Set `GOOGLE_APPLICATION_CREDENTIALS` in `dsxTransfer.extraEnv`.
5. Run `DSX-Transfer: Validate Config`.
6. Run `DSX-Transfer: Run Transfer`.

## Expected Local Harness Output

The local harness should report:

```text
planned 2, allowed 1, blocked 1, failed 0
```

## Filesystem-to-GCS Skeleton Flow

This is the main developer integration demo.

1. Run `DSX-Transfer: Create New Transfer`.
2. Choose a directory for the transfer workspace.
3. Enter:

- transfer id
- filesystem source path
- GCS destination URI
- DSXA scanner URL

4. Show the generated files:

```text
dsx-transfer.yaml
source/hello.txt
source/blocked-demo.txt
integration/python/run_transfer.py
integration/python/smoke_test.py
integration/python/.env.example
integration/python/README.md
```

5. Edit `dsx-transfer.yaml` if needed:

```yaml
destination:
  kind: gcs
  uri: gs://real-bucket/archive
```

6. Confirm the generated scanner:

```yaml
scanner:
  mode: dsxa
  dsxa:
    base_url: https://scanner.example.com
```

7. Set credentials in VS Code workspace settings:

```json
{
  "dsxTransfer.extraEnv": {
    "GOOGLE_APPLICATION_CREDENTIALS": "/path/to/service-account.json"
  }
}
```

8. Run `DSX-Transfer: Validate Config`.
9. Run `DSX-Transfer: Run Transfer`.
10. In `Last Report`, show:

- planned count
- allowed count
- blocked count
- failed count
- DSXA scan decisions

11. Confirm GCS contains the allowed files and does not contain blocked files.

Run the generated Python skeleton:

```bash
cd integration/python
DSX_TRANSFER_WORKSPACE=/path/to/workspace DSX_TRANSFER_CONFIG=/path/to/transfer/dsx-transfer.yaml python run_transfer.py
```

Expected result shape:

```text
summary: planned=<n> allowed=<n> blocked=<n> failed=<n>
```
