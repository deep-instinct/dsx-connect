# DSXA TUI

A lightweight terminal UI for DSXA scanner operations, built on top of `dsxa-sdk-py`.

## Quick start

```bash
cd dsxa_tui
pip install -e .
dsxa-tui
```

If `dsxa-sdk-py` is not available from your package index yet, install local SDK first:

```bash
pip install -e ../dsxa_sdk_py
pip install -e .
```

## Current features

- Configure scanner connection (`base_url`, auth token, protected entity, TLS verify)
- Scan a local file
- Scan a SHA256 hash
- Show raw DSXA JSON response in the output pane
- `Tab` completion in the `File Path` field
- In-app `Pick File` / `Pick Folder` modal selector

## Next

- Folder scan with progress/counters
- Context/profile management
- EICAR test action
