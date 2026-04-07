const {
  VerdictDetails,
  FileInfo,
  ScanResponse,
  ScanByPathResponse,
  HashScanResponse,
} = require("./models.cjs");

function toBody(data) {
  if (data == null) throw new Error("data is required");
  if (typeof Buffer !== "undefined" && Buffer.isBuffer(data)) return data;
  if (data instanceof Uint8Array) return data;
  if (data instanceof ArrayBuffer) return new Uint8Array(data);
  if (typeof Blob !== "undefined" && data instanceof Blob) return data;
  if (typeof data === "string") return new TextEncoder().encode(data);
  throw new Error("Unsupported payload type");
}

function isStreamingBody(data) {
  if (data == null) return false;
  if (typeof ReadableStream !== "undefined" && data instanceof ReadableStream) return true;
  return (
    typeof data === "object" &&
    (typeof data.pipe === "function" ||
      typeof data.getReader === "function" ||
      typeof data[Symbol.asyncIterator] === "function")
  );
}

function encodePassword(value) {
  if (!value) return "";
  if (typeof Buffer !== "undefined") return Buffer.from(value, "utf8").toString("base64");
  if (typeof btoa === "function") return btoa(value);
  throw new Error("No base64 encoder available");
}

function parseTextBody(text) {
  try {
    return JSON.parse(text);
  } catch {
    return { raw: text };
  }
}

class DSXAHttpError extends Error {
  constructor(message, status, body) {
    super(message);
    this.name = "DSXAHttpError";
    this.status = status;
    this.body = body;
  }
}

function asScanResponse(payload) {
  return ScanResponse.fromJson(payload);
}

function asHashScanResponse(payload) {
  return HashScanResponse.fromJson(payload);
}

function asScanByPathResponse(payload) {
  return ScanByPathResponse.fromJson(payload);
}

class DSXAClient {
  constructor({ baseUrl, authToken = "", defaultProtectedEntity = 1, fetchImpl, timeoutMs = 30000 } = {}) {
    if (!baseUrl) throw new Error("baseUrl is required");
    this.baseUrl = String(baseUrl).replace(/\/+$/, "");
    this.authToken = authToken || "";
    this.defaultProtectedEntity = defaultProtectedEntity;
    this.fetchImpl = fetchImpl || global.fetch;
    this.timeoutMs = timeoutMs;
    if (!this.fetchImpl) throw new Error("fetch implementation is required");
  }

  _headers({ protectedEntity, customMetadata, password, base64Header } = {}) {
    const headers = { "Content-Type": "application/octet-stream" };
    const pe = protectedEntity ?? this.defaultProtectedEntity;
    if (pe != null) headers.protected_entity = String(pe);
    if (customMetadata) headers["X-Custom-Metadata"] = String(customMetadata);
    if (password) headers.scan_password = encodePassword(String(password));
    if (base64Header) headers["X-Content-Type"] = "base64";
    if (this.authToken) {
      headers.AUTH = this.authToken;
      headers.AUTH_TOKEN = this.authToken;
    }
    return headers;
  }

  async _request(method, path, { headers = {}, body, signal } = {}) {
    const url = `${this.baseUrl}${path}`;
    const requestInit = { method, headers, body, signal };
    if (body != null && isStreamingBody(body)) {
      requestInit.duplex = "half";
    }
    const res = await this.fetchImpl(url, requestInit);
    const text = await res.text();
    const payload = parseTextBody(text);
    if (!res.ok) throw new DSXAHttpError(`HTTP ${res.status} ${res.statusText || "Error"}`, res.status, payload);
    return payload;
  }

  async scanBinary(data, opts = {}) {
    return asScanResponse(await this._request("POST", "/scan/binary/v2", {
      headers: this._headers(opts),
      body: toBody(data),
      signal: opts.signal,
    }));
  }

  async scanBinaryStream(data, opts = {}) {
    return asScanResponse(await this._request("POST", "/scan/binary/v2", {
      headers: this._headers(opts),
      body: data,
      signal: opts.signal,
    }));
  }

  async scanBase64(encodedData, opts = {}) {
    return asScanResponse(await this._request("POST", "/scan/base64/v2", {
      headers: this._headers(opts),
      body: toBody(typeof encodedData === "string" ? encodedData : encodedData),
      signal: opts.signal,
    }));
  }

  async scanHash(fileHash, opts = {}) {
    const headers = this._headers(opts);
    headers["Content-Type"] = "application/json";
    return asHashScanResponse(await this._request("POST", "/scan/by_hash", {
      headers,
      body: JSON.stringify({ hash: String(fileHash || "") }),
      signal: opts.signal,
    }));
  }

  async scanByPath(streamPath, opts = {}) {
    const headers = this._headers(opts);
    headers["Stream-Path"] = String(streamPath || "");
    return asScanByPathResponse(await this._request("GET", "/scan/by_path", { headers, signal: opts.signal }));
  }

  async getScanByPathResult(scanGuid, opts = {}) {
    const headers = this._headers(opts);
    headers["Content-Type"] = "application/json";
    return asScanResponse(await this._request("POST", "/result/by_path", {
      headers,
      body: JSON.stringify({ scan_guid: String(scanGuid || "") }),
      signal: opts.signal,
    }));
  }

  async pollScanByPath(scanGuid, { intervalMs = 5000, timeoutMs = 900000, ...opts } = {}) {
    const started = Date.now();
    for (;;) {
      const result = await this.getScanByPathResult(scanGuid, opts);
      const verdict = String(result?.verdict || "").toLowerCase();
      if (verdict && verdict !== "pending") return result;
      if (Date.now() - started > timeoutMs) throw new Error(`poll_scan_by_path timeout after ${timeoutMs}ms`);
      await new Promise((r) => setTimeout(r, intervalMs));
    }
  }
}

module.exports = {
  DSXAClient,
  DSXAHttpError,
  VerdictDetails,
  FileInfo,
  ScanResponse,
  ScanByPathResponse,
  HashScanResponse,
};
