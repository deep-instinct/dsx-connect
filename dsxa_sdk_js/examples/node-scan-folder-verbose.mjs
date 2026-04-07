import { DSXAClient } from "../src/index.js";
import { scanFolder } from "../src/node.js";

const client = new DSXAClient({ baseUrl: process.env.DSXA_BASE_URL || "http://127.0.0.1:5000" });
const folderPath = process.argv[2];
const concurrencyArg = process.argv[3];
const concurrency = concurrencyArg ? Number(concurrencyArg) : 4;

if (!folderPath) {
  console.error("usage: node examples/node-scan-folder-verbose.mjs <folder-path> [concurrency]");
  process.exit(1);
}

const startedAt = Date.now();
const result = await scanFolder(client, folderPath, { concurrency });
const elapsedMs = Date.now() - startedAt;

console.log(
  JSON.stringify(
    {
      operation: result.operation,
      folder: result.folder,
      concurrency,
      scanned: result.scanned,
      ok: result.ok,
      failed: result.failed,
      elapsedMs,
      results: result.results,
    },
    null,
    2,
  ),
);
