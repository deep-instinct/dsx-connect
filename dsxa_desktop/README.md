# DSXA Tauri

Cross-platform Tauri desktop client for DSXA with:
- Contexts (base URL, auth token, protected entity, metadata)
- Tabbed scan modes: `Scan File`, `Scan Folder`, `Scan Hash`
- Folder scan progress + stop/cancel

## Prerequisites

- Node.js 20+
- Rust toolchain (`cargo`, `rustc`)
- Tauri platform prerequisites:
  - macOS: Xcode command-line tools
  - Windows: MSVC build tools + WebView2
  - Linux: WebKit2GTK + build-essential deps

## Install

```bash
cd dsxa_desktop
npm install
```

## Run (dev)

```bash
npm run tauri:dev
```

## Build desktop app

```bash
npm run tauri:build
```

## Build Intel macOS app locally

If GitHub Actions cannot produce an Intel mac build in your org, you can build it locally on an Intel Mac:

```bash
cd dsxa_desktop
npm ci
npm run tauri:build -- --bundles app
```

App output:

```text
src-tauri/target/release/bundle/macos/DSXA Desktop.app
```

Optional zip artifact:

```bash
mkdir -p dist
ditto -c -k --sequesterRsrc --keepParent "src-tauri/target/release/bundle/macos/DSXA Desktop.app" "dist/dsxa-desktop-macos-intel-app.zip"
```

## Upload local Intel artifact to existing GitHub release

Yes, you can upload the locally built Intel zip to the same release used by CI.

Using GitHub CLI:

```bash
gh release upload dsxa-desktop-1.2.0 dist/dsxa-desktop-macos-intel-app.zip --clobber
```

Or in GitHub UI:
- Open the release tag (for example `dsxa-desktop-1.2.0`)
- Click `Edit`
- Drag/drop `dsxa-desktop-macos-intel-app.zip` into assets
- Save

## Notes

- Frontend uses `window.__TAURI__` global API (Tauri v2 with global API enabled in `tauri.conf.json`).
- App state is persisted to app config directory in `contexts.json`.
