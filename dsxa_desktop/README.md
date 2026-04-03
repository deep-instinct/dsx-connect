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

## Versioning

Desktop releases use the checked-in app version, not a manually typed release tag.

- `src-tauri/tauri.conf.json` is the release-defining app version for Tauri bundles and installer filenames.
- `package.json` and `src-tauri/Cargo.toml` must match that same version.
- Before cutting a release, update all three files together and check them in.
- The GitHub Actions release workflow derives the GitHub release tag from `tauri.conf.json` and fails if any of the three version files drift.

Example:

- app version in source: `1.2.2`
- generated release tag: `dsxa-desktop-1.2.2`
- installer names: `DSXA Desktop_1.2.2_...`

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
gh release upload dsxa-desktop-1.2.2 dist/dsxa-desktop-macos-intel-app.zip --clobber
```

Or in GitHub UI:
- Open the release tag (for example `dsxa-desktop-1.2.2`)
- Click `Edit`
- Drag/drop `dsxa-desktop-macos-intel-app.zip` into assets
- Save

## Notes

- Frontend uses `window.__TAURI__` global API (Tauri v2 with global API enabled in `tauri.conf.json`).
- App state is persisted to app config directory in `contexts.json`.

## macOS distribution note

Unsigned or unnotarized macOS builds may be blocked by Gatekeeper with a message like:

```text
"DSXA Desktop" is damaged and can't be opened. You should move it to the Trash.
```

For local/internal use, first try opening the app from Finder:

1. Right-click `DSXA Desktop.app`
2. Choose `Open`
3. In the macOS warning dialog, click `Open` again

If macOS still refuses to open the app, the usual workaround is to remove the browser quarantine attribute after unzipping:

```bash
xattr -dr com.apple.quarantine "/path/to/DSXA Desktop.app"
```

For normal end-user distribution, the proper fix is to sign and notarize the app with an Apple Developer account. Without notarization, macOS may continue to block the app even if the build itself is valid.

## Windows distribution note

Unsigned Windows installers may show `Unknown Publisher` during installation. For internal or local testing, users can typically continue anyway if they trust the source of the MSI or EXE.

For normal end-user distribution, the proper fix is to sign the Windows installer with a code-signing certificate so Windows can show a verified publisher instead of `Unknown Publisher`.
