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
- `@deep-instinct/dsxa-sdk-js/node`
  - `scanFilePath(client, filePath, opts?)`
  - `scanFolder(client, folder, { concurrency, perFile }?)`

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

## Notes

- Folder scanning in a plain browser is constrained by browser file APIs.
- Native wrappers (Swift/Electron/Tauri/pywebview) can expose folder pickers and still call this SDK.
