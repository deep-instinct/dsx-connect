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
cd dsxa_tauri
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

## Notes

- Frontend uses `window.__TAURI__` global API (Tauri v2 with global API enabled in `tauri.conf.json`).
- App state is persisted to app config directory in `contexts.json`.
