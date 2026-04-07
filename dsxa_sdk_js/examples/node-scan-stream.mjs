import fs from "node:fs";
import { DSXAClient } from "../src/index.js";

const client = new DSXAClient({ baseUrl: process.env.DSXA_BASE_URL || "http://127.0.0.1:5000" });
const filePath = process.argv[2];

if (!filePath) {
  console.error("usage: node examples/node-scan-stream.mjs <file-path>");
  process.exit(1);
}

const stream = fs.createReadStream(filePath);
const result = await client.scanBinaryStream(stream);
console.log(JSON.stringify(result, null, 2));
