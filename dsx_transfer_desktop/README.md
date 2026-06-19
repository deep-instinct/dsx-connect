# DSX-Transfer Desktop

DSX-Transfer Desktop is an Electron app for running guarded file-share transfers with a Node-native desktop runner.

The first demo flow copies files from a source folder or mounted file share to a destination folder only after the scanner and transfer policy return an allow decision.

## Run From Source

From the repository root:

```bash
cd dsx_transfer_desktop
npm install
npm run dev
```

## Build Installers

```bash
cd dsx_transfer_desktop
npm run build:mac
npm run build:win
```

The packaged app uses Electron's bundled Node.js runtime. It does not require a system Python runtime.

## Run a Downloaded macOS Build

Current local/demo builds are unsigned. If macOS blocks the app with a message like "Apple could not verify..." after downloading a `.dmg` or `.zip`, remove the quarantine attribute before launching it:

```bash
xattr -dr com.apple.quarantine "/Applications/DSX-Transfer Desktop.app"
```

If you are testing from an unpacked build instead of `/Applications`, point the command at that `.app` path:

```bash
xattr -dr com.apple.quarantine "/path/to/DSX-Transfer Desktop.app"
```

## Demo Flow

- DSXA scanner: sends file streams through DSXA before commit.
- Verdict actions: benign, malicious, unknown, and error decisions can be mapped to allow or block.
- File-share transfer: source and destination are local folders or mounted shares.

Each run writes a generated `dsx-transfer.yaml`, audit JSONL, checkpoint file, performance JSONL, and run log under the app user-data directory.
