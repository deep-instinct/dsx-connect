# Examples

These examples use the local source tree directly:

- `../src/index.js`
- `../src/node.js`

Set the DSXA endpoint with `DSXA_BASE_URL` if needed:

```bash
export DSXA_BASE_URL=http://127.0.0.1:5000
```

Examples:

```bash
node examples/node-scan-file.mjs /tmp/file.pdf
node examples/node-scan-folder.mjs /tmp/samples
node examples/node-scan-folder-verbose.mjs /tmp/samples
node examples/node-scan-hash.mjs <sha256>
node examples/node-scan-stream.mjs /tmp/file.pdf
node examples/node-scan-base64.mjs /tmp/file.pdf
```

Browser examples:

- `examples/browser-scan-file.html`
- `examples/browser-scan-folder.html`

Notes:

- `node-scan-folder.mjs` prints a folder summary.
- `node-scan-folder-verbose.mjs` prints per-file results and is the most complete async folder scan example.
- `node-scan-stream.mjs` uses the SDK streaming path.
- `browser-scan-folder.html` shows the browser-friendly folder pattern using `webkitdirectory`.
