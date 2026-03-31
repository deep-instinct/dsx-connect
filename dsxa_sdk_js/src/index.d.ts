export type ScanOptions = {
  protectedEntity?: number;
  customMetadata?: string;
  password?: string;
  base64Header?: boolean;
  signal?: AbortSignal;
};

export declare class DSXAHttpError extends Error {
  status: number;
  body: unknown;
  constructor(message: string, status: number, body: unknown);
}

export declare class DSXAClient {
  constructor(opts: {
    baseUrl: string;
    authToken?: string;
    defaultProtectedEntity?: number;
    fetchImpl?: typeof fetch;
    timeoutMs?: number;
  });
  scanBinary(data: Uint8Array | ArrayBuffer | Blob | string, opts?: ScanOptions): Promise<any>;
  scanBinaryStream(data: any, opts?: ScanOptions): Promise<any>;
  scanBase64(encodedData: string | Uint8Array, opts?: ScanOptions): Promise<any>;
  scanHash(fileHash: string, opts?: ScanOptions): Promise<any>;
  scanByPath(streamPath: string, opts?: ScanOptions): Promise<any>;
  getScanByPathResult(scanGuid: string, opts?: ScanOptions): Promise<any>;
  pollScanByPath(scanGuid: string, opts?: ScanOptions & { intervalMs?: number; timeoutMs?: number }): Promise<any>;
  scanFile(fileOrBlob: any, opts?: ScanOptions): Promise<any>;
}
