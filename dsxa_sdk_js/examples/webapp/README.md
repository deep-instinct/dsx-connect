# DSXA JS WebApp File Upload Demo

Minimal browser webapp for a loan-processing style intake flow:

- user selects one or more files in the browser
- browser scans each file with `dsxa_sdk_js`
- benign files are shown as accepted
- malicious, non-compliant, executable, or failed files are shown as rejected or held

## Key Components

- Static browser page: `examples/webapp/index.html`
- Browser scan flow: `examples/webapp/app.js`
- Intake policy decisions: `examples/webapp/policy.js`
- SDK browser scan call: `DSXAClient.scanFile()` in `src/index.js`

The main per-file handoff from the webapp into the SDK happens here:

```js
const response = await client.scanFile(file, {
  protectedEntity,
  customMetadata: `loan-intake:${file.name}`,
});
```

That code lives in `scanOneFile()` in `examples/webapp/app.js`.

Inside the SDK, that resolves to the underlying DSXA REST call here:

```js
return asScanResponse(await this._request("POST", "/scan/binary/v2", {
  headers: this._headers(opts),
  body: toBody(data),
  signal: opts.signal,
}));
```

That code lives in `DSXAClient.scanBinary()` in `src/index.js`.

## Prerequisites

- A modern browser with ES module support
- DSXA reachable from the browser
- DSXA CORS support enabled, for example with `-e CORS=true`
- A simple local static file server

## Run

From the repo root:

```bash
cd dsxa_sdk_js
python3 -m http.server 8000
```

Then open `http://127.0.0.1:8000/examples/webapp/`.

## Notes

- This browser demo scans files directly from the client browser to DSXA.
- Accepted files are shown in the UI only; they are not saved anywhere server-side.
- If you see `Failed to fetch`, check browser DevTools for CORS, endpoint reachability, or mixed-content errors.
