# DSXA SDK JS

JavaScript SDK for DSXA APIs, usable in both Node.js and browser apps.

## Install (local workspace)

```bash
npm install ./dsxa_sdk_js
```

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
