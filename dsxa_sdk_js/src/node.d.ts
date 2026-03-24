import { DSXAClient } from "./index.js";

export { DSXAClient };

export declare function scanFilePath(client: DSXAClient, filePath: string, opts?: Record<string, unknown>): Promise<any>;
export declare function scanFolder(
  client: DSXAClient,
  folder: string,
  opts?: { concurrency?: number; perFile?: Record<string, unknown> }
): Promise<{
  operation: "scan-folder-summary";
  folder: string;
  scanned: number;
  ok: number;
  failed: number;
  results: Array<{ file: string; status: "ok" | "failed"; result?: any; error?: string }>;
}>;
