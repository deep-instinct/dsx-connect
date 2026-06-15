# DSXA VS Code Assistant

This extension has two jobs:

- scan files and folders directly from VS Code with DSXA
- help developers add DSXA or DSX-Connect NG scanning to applications

## Commands

- `DSXA: Configure Connection`
- `DSXA: Health Check`
- `DSXA: Scan Current File`
- `DSXA: Scan Selected Files`
- `DSXA: Scan Workspace Folder`
- `DSXA: Find Application Integration Points`
- `DSXA: Generate Integration Plan`

## Local Development

```bash
cd dsxa_assistant_vscode_ext
npm install
npm run check
```

Then open this folder in VS Code and launch an Extension Development Host.

The extension depends on the local JS SDK package at `../dsxa_sdk_js`.
