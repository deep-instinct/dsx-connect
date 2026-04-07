import { DSXAClient } from "../src/index.js";
import { scanFolder } from "../src/node.js";

const client = new DSXAClient({ baseUrl: process.env.DSXA_BASE_URL || "http://127.0.0.1:5000" });
const folderPath = process.argv[2];
const concurrencyArg = process.argv[3];
const concurrency = concurrencyArg ? Number(concurrencyArg) : 4;

if (!folderPath) {
  console.error("usage: node examples/node-scan-folder.mjs <folder-path> [concurrency]");
  process.exit(1);
}

const result = await scanFolder(client, folderPath, { concurrency });
console.log(JSON.stringify(result, null, 2));
