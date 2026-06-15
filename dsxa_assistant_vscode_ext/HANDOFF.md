# DSXA VS Code Assistant Handoff

Status: initial scaffold created.

This directory contains the first VS Code extension pass for two related goals:

- built-in DSXA scanning from VS Code
- application helper that finds likely file-ingress points and generates an integration plan

## Current Shape

Extension directory:

- `package.json`: VS Code manifest, commands, settings, views, local SDK dependency
- `src/extension.js`: extension implementation
- `resources/dsxa.svg`: activity bar icon
- `.vscode/launch.json`: Extension Development Host launch config
- `README.md`: quick local development notes

The extension depends on the local JS SDK package:

```json
"@deep-instinct/dsxa-sdk-js": "file:../dsxa_sdk_js"
```

`npm install` has been run locally in this directory.
`node_modules/` exists locally but is ignored by the repo-level `.gitignore`.

## Implemented Commands

- `DSXA: Configure Connection`
- `DSXA: Health Check`
- `DSXA: Scan Current File`
- `DSXA: Scan Selected Files`
- `DSXA: Scan Workspace Folder`
- `DSXA: Find Application Integration Points`
- `DSXA: Generate Integration Plan`
## Implemented Views

Activity Bar container: `DSXA`

- `Scan Results`
- `Integration Points`

## Scanner Behavior

The scanner path uses `@deep-instinct/dsxa-sdk-js/node`.

Settings:

- `dsxa.baseUrl`
- `dsxa.authToken`
- `dsxa.scanConcurrency`
- `dsxa.maxFileSizeBytes`
- `dsxa.workspaceIncludeGlob`
- `dsxa.workspaceExcludeGlob`

Single-file scans, selected file/folder scans, and workspace scans all flow through the same scan function.
Batch scans use configured concurrency.
Results are shown in the `Scan Results` tree and the `DSXA Assistant` output channel.

## Application Helper Behavior

The helper scans workspace source files for likely file-ingress or storage-write points.

Current language/framework coverage:

- Node/Express
- Python
- Java/Spring
- .NET
- Go

Detected findings populate the `Integration Points` tree.
`DSXA: Generate Integration Plan` opens a Markdown document with:

- recommended flow
- detected files/lines
- starter snippets for direct DSXA integration
- DSX-Connect NG mode note when configured

## Validation Already Run

From `dsxa_assistant_vscode_ext/`:

```bash
npm install
npm run check
node -e "import('@deep-instinct/dsxa-sdk-js/node').then(m => console.log(Object.keys(m).sort().join(',')))"
```

Results:

- `npm install` succeeded
- `npm run check` passed
- SDK export resolution returned `DSXAClient,scanFilePath,scanFolder`

JSON validation was also run for:

- `package.json`
- `.vscode/launch.json`

## Not Yet Done

- Run in an actual VS Code Extension Development Host.
- Scan a real file against a live DSXA endpoint from inside VS Code.
- Package as `.vsix`.
- Add automated extension tests.
- Improve verdict normalization once real DSXA responses are observed in the extension.
- Add a real code-action/edit flow for generated app integration patches.
- Add DSX-Connect NG job-submission mode beyond the current generated-plan note.

## Next Best Steps

1. Open `dsxa_assistant_vscode_ext/` as the VS Code workspace.
2. Run the launch config: `Run DSXA Assistant Extension`.
3. In the Extension Development Host, run `DSXA: Configure Connection`.
4. Run `DSXA: Health Check`.
5. Run `DSXA: Scan Current File` against a known benign sample.
6. Run `DSXA: Find Application Integration Points` against this repo or a small test app.
7. Based on real behavior, decide whether the next implementation should be:
   - result presentation polish
   - direct code patch generation
   - DSX-Connect NG mode
   - `.vsix` packaging
