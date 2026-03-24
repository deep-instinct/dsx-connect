import { DSXAClient } from "../src/index.js";
import { scanFilePath } from "../src/node.js";

const client = new DSXAClient({ baseUrl: process.env.DSXA_BASE_URL || "http://127.0.0.1:5000" });
const filePath = process.argv[2];

if (!filePath) {
  console.error("usage: node examples/node-scan-file.mjs <file-path>");
  process.exit(1);
}

const result = await scanFilePath(client, filePath);
console.log(JSON.stringify(result, null, 2));
