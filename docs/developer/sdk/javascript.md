# JavaScript SDK Calls

This page documents the DSXA JavaScript SDK in this repo.

Source: `dsxa_sdk_js/`

## Runtime targets

- Node.js: ESM and CommonJS
- Browser: ESM (`fetch`-based)

## Package exports

- `@deep-instinct/dsxa-sdk-js`
  - `DSXAClient`
  - `DSXAHttpError`
  - `ScanResponse`
  - `ScanByPathResponse`
  - `HashScanResponse`
  - `VerdictDetails`
  - `FileInfo`
- `@deep-instinct/dsxa-sdk-js/node`
  - `scanFilePath(client, filePath, opts?)`
  - `scanFolder(client, folder, { concurrency, perFile }?)`

## Local install without publishing

The simplest local install is:

```bash
npm install ./dsxa_sdk_js
```

That is the easiest equivalent to "install this package from source locally" without publishing it to npm.

For local CLI usage, prefer:

```bash
npm install ./dsxa_sdk_js
npx dsxa-node --help
```

For editable-style development:

```bash
cd dsxa_sdk_js
npm link
dsxa-node --help
```

If you specifically want a global install:

```bash
npm install -g ./dsxa_sdk_js
```

Depending on your npm configuration, global install may require a user-owned npm prefix instead of the default `/usr/local` path.

## CLI

The JavaScript package also provides a Node CLI:

Primary uses:

- baseline DSXA throughput and compare concurrency settings
- scan individual files or folders from the command line
- serve as runnable example code for SDK users

```bash
npx dsxa-node scan-file /tmp/file.pdf
npx dsxa-node scan-folder /tmp/samples --concurrency 4
```

If installed globally:

```bash
npm install -g @deep-instinct/dsxa-sdk-js
dsxa-node scan-file /tmp/file.pdf
```

The command name is `dsxa-node`, intentionally distinct from the Python CLI name `dsxa`.

For folder scans, the CLI prints `Concurrency: <N>` in the final summary so the effective concurrency is explicit in benchmark output. The default concurrency is `4`.

## Core calls

- `scanBinary(data, opts?)`
- `scanBase64(encodedData, opts?)`
- `scanHash(fileHash, opts?)`
- `scanByPath(streamPath, opts?)`
- `getScanByPathResult(scanGuid, opts?)`
- `pollScanByPath(scanGuid, { intervalMs, timeoutMs, ...opts }?)`
- `scanFile(fileOrBlob, opts?)` (browser-oriented convenience)

## Node usage

```js
import { DSXAClient } from "@deep-instinct/dsxa-sdk-js";
import { scanFilePath, scanFolder } from "@deep-instinct/dsxa-sdk-js/node";

const client = new DSXAClient({ baseUrl: "http://127.0.0.1:5000" });
await scanFilePath(client, "/tmp/a.pdf", { customMetadata: "source=node" });
await scanFolder(client, "/tmp/samples", { concurrency: 4 });
```

Runnable Node examples in this repo:

- `dsxa_sdk_js/examples/node-scan-file.mjs`
- `dsxa_sdk_js/examples/node-scan-folder.mjs`
- `dsxa_sdk_js/examples/node-scan-folder-verbose.mjs`
- `dsxa_sdk_js/examples/node-scan-hash.mjs`
- `dsxa_sdk_js/examples/node-scan-stream.mjs`
- `dsxa_sdk_js/examples/node-scan-base64.mjs`

## Browser usage

```html
<script type="module">
  import { DSXAClient } from "/node_modules/@deep-instinct/dsxa-sdk-js/src/index.js";

  const client = new DSXAClient({ baseUrl: "http://127.0.0.1:5000" });
  const file = document.querySelector("#file").files[0];
  const result = await client.scanFile(file, { customMetadata: "source=browser" });
  console.log(result);
</script>
```

Runnable browser examples in this repo:

- `dsxa_sdk_js/examples/browser-scan-file.html`
- `dsxa_sdk_js/examples/browser-scan-folder.html`

Browser folder scanning example pattern:

```html
<input id="folder" type="file" webkitdirectory multiple />
```

Then scan each selected `File` with `client.scanFile(file, ...)`.

## Notes

- Folder scanning in a plain browser is constrained by browser file APIs.
- Native wrappers (Swift/Electron/Tauri/pywebview) can expose folder pickers and still call this SDK.
- The browser examples use `type="module"` and import from `../src/index.js` for local repo usage.
- Client methods return modeled result objects by default, not just raw parsed JSON.
