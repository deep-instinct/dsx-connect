#!/usr/bin/env node

import fs from "node:fs/promises";
import { DSXAClient, DSXAHttpError } from "./index.js";
import { scanFilePath, scanFolder } from "./node.js";

function usage() {
  console.log(`dsxa-node - DSXA JavaScript SDK CLI

Primary uses:
  1. Baseline DSXA throughput and compare concurrency settings
  2. Scan individual files or whole folders from the command line
  3. Serve as runnable example code for SDK users

Usage:
  dsxa-node scan-file <file-path> [--base-url URL] [--auth-token TOKEN]
  dsxa-node scan-folder <folder-path> [--concurrency N] [--base-url URL] [--auth-token TOKEN]
  dsxa-node scan-hash <sha256> [--base-url URL] [--auth-token TOKEN]
  dsxa-node scan-stream <file-path> [--base-url URL] [--auth-token TOKEN]
  dsxa-node scan-base64 <file-path> [--base-url URL] [--auth-token TOKEN]

Options:
  --base-url URL          DSXA base URL (default: DSXA_BASE_URL or http://127.0.0.1:5000)
  --auth-token TOKEN      Optional DSXA auth token (default: DSXA_AUTH_TOKEN)
  --protected-entity N    Protected entity header (default: 1)
  --concurrency N         Folder scan concurrency. Effective value is echoed in the final summary. (default: 4)
  --help                  Show this help
`);
}

function parseArgs(argv) {
  const args = [...argv];
  const positionals = [];
  const options = {};

  while (args.length) {
    const arg = args.shift();
    if (!arg) continue;
    if (!arg.startsWith("--")) {
      positionals.push(arg);
      continue;
    }
    const key = arg.slice(2);
    if (key === "help") {
      options.help = true;
      continue;
    }
    const value = args.shift();
    if (value == null) {
      throw new Error(`Missing value for --${key}`);
    }
    options[key] = value;
  }

  return { positionals, options };
}

function createClient(options) {
  return new DSXAClient({
    baseUrl: options["base-url"] || process.env.DSXA_BASE_URL || "http://127.0.0.1:5000",
    authToken: options["auth-token"] || process.env.DSXA_AUTH_TOKEN || "",
    defaultProtectedEntity: Number(options["protected-entity"] || 1),
  });
}

function printResult(result) {
  console.log(JSON.stringify(result, null, 2));
}

function printFolderResult(item) {
  if (!item) return;
  if (item.status === "ok") {
    console.log(`${item.file}: ${item.result?.verdict || "Unknown"} (scan_guid=${item.result?.scanGuid || ""})`);
    return;
  }
  console.error(`${item.file}: ERROR ${item.error || item.message || "unknown error"}`);
}

function printFolderSummary(summary, elapsedMs, concurrency) {
  let totalScanDurationMicros = 0;
  for (const item of summary.results || []) {
    if (!item) continue;
    if (item.status === "ok") {
      totalScanDurationMicros += Number(item.result?.scanDurationInMicroseconds || 0);
    }
  }
  const totalScanDurationSeconds = totalScanDurationMicros / 1_000_000;
  console.log(`Concurrency: ${concurrency}`);
  console.log(
    `Processed ${summary.scanned} file(s) in ${(elapsedMs / 1000).toFixed(2)}s ` +
    `(scanned=${summary.ok}, errors=${summary.failed})`,
  );
  console.log(`DSXA Scan Time (sum): ${totalScanDurationSeconds.toFixed(2)}s`);
}

function printError(error) {
  if (error instanceof DSXAHttpError) {
    console.error(
      JSON.stringify(
        {
          status: "failed",
          message: error.message,
          httpStatus: error.status,
          body: error.body,
        },
        null,
        2,
      ),
    );
    return;
  }
  if (error instanceof TypeError && String(error.message || "").toLowerCase().includes("fetch failed")) {
    console.error(
      JSON.stringify(
        {
          status: "failed",
          message: "Connection to DSXA failed",
          hint: "Check --base-url / DSXA_BASE_URL and confirm the DSXA service is listening on that host:port.",
          detail: error.message,
        },
        null,
        2,
      ),
    );
    return;
  }
  console.error(error?.message || String(error));
}

async function main() {
  const { positionals, options } = parseArgs(process.argv.slice(2));
  const command = positionals[0];

  if (!command || options.help) {
    usage();
    process.exit(options.help ? 0 : 1);
  }

  const client = createClient(options);

  try {
    switch (command) {
      case "scan-file": {
        const filePath = positionals[1];
        if (!filePath) throw new Error("scan-file requires <file-path>");
        printResult(await scanFilePath(client, filePath));
        break;
      }
      case "scan-folder": {
        const folderPath = positionals[1];
        if (!folderPath) throw new Error("scan-folder requires <folder-path>");
        const concurrency = Number(options.concurrency || 4);
        const startedAt = Date.now();
        const summary = await scanFolder(client, folderPath, { concurrency, onResult: printFolderResult });
        printFolderSummary(summary, Date.now() - startedAt, concurrency);
        break;
      }
      case "scan-hash": {
        const hashValue = positionals[1];
        if (!hashValue) throw new Error("scan-hash requires <sha256>");
        printResult(await client.scanHash(hashValue));
        break;
      }
      case "scan-stream": {
        const filePath = positionals[1];
        if (!filePath) throw new Error("scan-stream requires <file-path>");
        const stream = (await import("node:fs")).createReadStream(filePath);
        printResult(await client.scanBinaryStream(stream));
        break;
      }
      case "scan-base64": {
        const filePath = positionals[1];
        if (!filePath) throw new Error("scan-base64 requires <file-path>");
        const buffer = await fs.readFile(filePath);
        printResult(await client.scanBase64(buffer.toString("base64")));
        break;
      }
      default:
        throw new Error(`Unknown command: ${command}`);
    }
  } catch (error) {
    printError(error);
    process.exit(1);
  }
}

await main();
