"use strict";

const PROBE_BYTES = Buffer.from("dsx desktop scanner status probe\n", "utf8");

function normalizeScannerBaseUrl(value) {
  const raw = String(value || "").trim();
  if (!raw) {
    return { error: "missing" };
  }
  let parsed;
  try {
    parsed = new URL(raw);
  } catch {
    return { error: "invalid" };
  }

  if (parsed.pathname.endsWith("/scan/binary/v2")) {
    parsed.pathname = parsed.pathname.slice(0, -"/scan/binary/v2".length) || "/";
    parsed.search = "";
    parsed.hash = "";
  }

  return { baseUrl: parsed };
}

function buildScannerHeaders({ authToken, protectedEntity, contentType = "application/octet-stream" } = {}) {
  const headers = {};
  if (contentType) {
    headers["Content-Type"] = contentType;
  }
  if (protectedEntity !== "" && protectedEntity != null) {
    headers.protected_entity = String(Number.parseInt(String(protectedEntity), 10) || 1);
  }
  if (authToken) {
    headers.AUTH_TOKEN = String(authToken);
    headers.AUTH = String(authToken);
  }
  return headers;
}

async function probeDsxaScanner(options = {}) {
  const normalized = normalizeScannerBaseUrl(options.baseUrl || options.scanBinaryUrl);
  if (normalized.error === "missing") {
    return {
      state: "unreachable",
      message: "Scanner URL missing"
    };
  }
  if (normalized.error === "invalid") {
    return {
      state: "unreachable",
      message: "Scanner URL invalid"
    };
  }

  const scanUrl = new URL("/scan/binary/v2", normalized.baseUrl);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), Number(options.timeoutMs || 2500));
  try {
    const response = await fetch(scanUrl.toString(), {
      method: "POST",
      headers: buildScannerHeaders(options),
      body: options.body || PROBE_BYTES,
      signal: controller.signal
    });
    if (response.status === 401 || response.status === 403) {
      return {
        state: "unreachable",
        message: "Scanner auth failed",
        status: response.status
      };
    }
    if (!response.ok) {
      return {
        state: "unreachable",
        message: "Scanner scan failed",
        status: response.status
      };
    }
    return {
      state: "active",
      message: "Scanner active",
      status: response.status
    };
  } catch (error) {
    return {
      state: "unreachable",
      message: "Scanner unreachable",
      error: error?.name === "AbortError" ? "timeout" : error?.message || String(error)
    };
  } finally {
    clearTimeout(timeout);
  }
}

module.exports = {
  buildScannerHeaders,
  normalizeScannerBaseUrl,
  probeDsxaScanner
};
