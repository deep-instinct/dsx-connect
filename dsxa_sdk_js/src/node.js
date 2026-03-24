import { promises as fs } from "node:fs";
import path from "node:path";
import { DSXAClient } from "./index.js";

export { DSXAClient };

export async function scanFilePath(client, filePath, opts = {}) {
  const data = await fs.readFile(filePath);
  return client.scanBinary(data, opts);
}

async function walk(dir, out) {
  const entries = await fs.readdir(dir, { withFileTypes: true });
  for (const ent of entries) {
    const full = path.join(dir, ent.name);
    if (ent.isDirectory()) await walk(full, out);
    else if (ent.isFile()) out.push(full);
  }
}

export async function scanFolder(client, folder, { concurrency = 4, perFile = {} } = {}) {
  const files = [];
  await walk(folder, files);
  const results = [];
  let i = 0;

  async function worker() {
    while (i < files.length) {
      const idx = i++;
      const file = files[idx];
      try {
        const data = await fs.readFile(file);
        const res = await client.scanBinary(data, perFile);
        results[idx] = { file, status: "ok", result: res };
      } catch (error) {
        results[idx] = { file, status: "failed", error: error?.message || String(error) };
      }
    }
  }

  await Promise.all(Array.from({ length: Math.max(1, Number(concurrency) || 1) }, () => worker()));
  return {
    operation: "scan-folder-summary",
    folder,
    scanned: files.length,
    ok: results.filter((r) => r?.status === "ok").length,
    failed: results.filter((r) => r?.status === "failed").length,
    results,
  };
}
