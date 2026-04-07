import { DSXAClient } from "../src/index.js";

const client = new DSXAClient({ baseUrl: process.env.DSXA_BASE_URL || "http://127.0.0.1:5000" });
const fileHash = process.argv[2];

if (!fileHash) {
  console.error("usage: node examples/node-scan-hash.mjs <sha256>");
  process.exit(1);
}

const result = await client.scanHash(fileHash);
console.log(JSON.stringify(result, null, 2));
