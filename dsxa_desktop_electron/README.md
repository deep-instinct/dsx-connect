# DSXA Desktop (Electron)

Independent Electron desktop client for DSXA, built on top of `@deep-instinct/dsxa-sdk-js`.

This app is intentionally separate from `dsx_connect_desktop/`. It does not host DSX-Connect and does not share its runtime model.

## Current scaffold

- Electron shell with isolated renderer + preload bridge
- Local profile persistence under the app user data directory
- File picker integration
- `Scan File` flow using the JavaScript SDK from the Electron main process
- Raw JSON result output

## Install

```bash
cd dsxa_desktop_electron
npm install
```

## Run

```bash
npm start
```

## Build

```bash
npm run build:mac
```

Architecture-specific macOS builds:

```bash
npm run build:mac:x64
npm run build:mac:arm64
```
