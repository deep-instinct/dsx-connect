# DSXA SDK JS

JavaScript SDK for DSXA APIs, usable in both Node.js and browser apps.

## Install (local workspace)

```bash
npm install ./dsxa_sdk_js
```

This is the simplest local equivalent of installing from source without publishing to npm.

If you want the CLI locally without publishing, prefer:

```bash
npm install ./dsxa_sdk_js
npx dsxa-node --help
```

For editable-style local development, use:

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

## Node.js (ESM)

```js
import { DSXAClient } from "@deep-instinct/dsxa-sdk-js";
import { scanFilePath, scanFolder } from "@deep-instinct/dsxa-sdk-js/node";

const client = new DSXAClient({
  baseUrl: "http://127.0.0.1:5000",
  authToken: "",
});

const one = await scanFilePath(client, "/tmp/file.pdf", { customMetadata: "source=node" });
const many = await scanFolder(client, "/tmp/samples", { concurrency: 4 });
```

See [`examples/`](./examples/) for runnable Node.js examples including:

- single file scan
- async folder scan summary
- async folder scan with per-file results
- hash scan
- stream upload
- base64 upload

Browser examples are also included:

- `examples/browser-scan-file.html`
- `examples/browser-scan-folder.html`

Response objects are modeled, not returned as raw JSON only. The JS SDK now returns wrapper classes such as:

- `ScanResponse`
- `ScanByPathResponse`
- `HashScanResponse`
- `VerdictDetails`
- `FileInfo`

These expose normalized properties like `scanGuid`, `verdict`, `verdictDetails`, and `fileInfo`, while still supporting `toJSON()`.

## CLI

The JS package also provides a small Node CLI:

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

The command name is `dsxa-node` so it does not collide with the Python CLI (`dsxa`) if both are installed on the same machine.

For folder scans, the CLI prints `Concurrency: <N>` in the final summary so the effective concurrency is explicit in benchmark output. The default concurrency is `4`.

## Browser (ESM)

```html
<script type="module">
  import { DSXAClient } from "/node_modules/@deep-instinct/dsxa-sdk-js/src/index.js";

  const client = new DSXAClient({ baseUrl: "http://127.0.0.1:5000" });

  const fileInput = document.querySelector("#file");
  fileInput.addEventListener("change", async () => {
    const file = fileInput.files[0];
    const res = await client.scanFile(file, { customMetadata: "source=browser" });
    console.log(res);
  });
</script>
```

Notes:
- Browser folder scanning depends on browser APIs and user file selection (`webkitdirectory` / File System Access API).
- Native desktop wrappers (Swift/Electron/Tauri/pywebview) can provide richer folder picking and then call this SDK.
