import fs from "node:fs/promises";
import { DSXAClient } from "../src/index.js";

const client = new DSXAClient({ baseUrl: process.env.DSXA_BASE_URL || "http://127.0.0.1:5000" });
const filePath = process.argv[2];

if (!filePath) {
  console.error("usage: node examples/node-scan-base64.mjs <file-path>");
  process.exit(1);
}

const buffer = await fs.readFile(filePath);
const result = await client.scanBase64(buffer.toString("base64"));
console.log(JSON.stringify(result, null, 2));
