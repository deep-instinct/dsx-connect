const fs = require("node:fs/promises");
const fsSync = require("node:fs");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

function nowIso() {
  return new Date().toISOString();
}

async function listFiles(root, destinationRoot) {
  const resolvedRoot = path.resolve(root);
  const resolvedDestinationRoot = path.resolve(destinationRoot);
  const files = [];

  async function walk(dir) {
    const entries = await fs.readdir(dir, { withFileTypes: true });
    entries.sort((a, b) => a.name.localeCompare(b.name));
    for (const entry of entries) {
      const absolute = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        await walk(absolute);
      } else if (entry.isFile()) {
        const stat = await fs.stat(absolute);
        const relative = path.relative(resolvedRoot, absolute).split(path.sep).join("/");
        files.push({
          source_uri: pathToFileURL(absolute).toString(),
          destination_uri: pathToFileURL(path.join(resolvedDestinationRoot, relative)).toString(),
          object_identity: relative,
          size_bytes: stat.size,
          content_type: null,
          metadata: {
            source_path: absolute,
            relative_path: relative,
            mtime_ms: stat.mtimeMs
          }
        });
      }
    }
  }

  await walk(resolvedRoot);
  return files;
}

function normalizeDsxaVerdict(value) {
  const normalized = String(value || "").trim().toLowerCase().replace(/[_-]/g, " ");
  if (normalized === "benign") return "benign";
  if (normalized === "malicious") return "malicious";
  if (normalized === "non compliant" || normalized === "suspicious") return "suspicious";
  if (["unknown", "unsupported file type", "not scanned", "scanning"].includes(normalized)) return "unknown";
  return "error";
}

function getField(value, name) {
  if (!value || typeof value !== "object") return undefined;
  return value[name];
}

function scanObservationFromDsxa(response) {
  const fileInfo = getField(response, "file_info");
  const fileType = getField(fileInfo, "file_type");
  return {
    verdict: normalizeDsxaVerdict(getField(response, "verdict")),
    file_type: fileType == null ? null : String(fileType),
    scan_guid: getField(response, "scan_guid") == null ? null : String(getField(response, "scan_guid")),
    details: response && typeof response === "object" ? response : {}
  };
}

function evaluatePolicy({ item, observation, policyId, verdictActions }) {
  const verdict = observation.verdict || "error";
  const action = verdictActions[verdict] || "block";
  return {
    verdict,
    action,
    file_type: observation.file_type,
    policy_id: policyId || null,
    scan_guid: observation.scan_guid,
    reason: `verdict:${verdict}`,
    details: observation.details || {}
  };
}

function isWindowsExecutableFileType(fileType) {
  const normalized = String(fileType || "").trim().toLowerCase();
  if (!normalized) return false;
  return (
    normalized === "pe" ||
    normalized === "exe" ||
    normalized.includes("portable executable") ||
    normalized.includes("windows executable") ||
    normalized.includes("win32") ||
    normalized.includes("win64")
  );
}

function applyFileTypeBlocks(decision, fileTypeBlocks) {
  if (fileTypeBlocks?.windowsExecutables && isWindowsExecutableFileType(decision.file_type)) {
    return {
      ...decision,
      action: "block",
      reason: `${decision.reason};file_type:windows_executable`
    };
  }
  return decision;
}

function stateForAction(action) {
  if (action === "exclude") return "excluded";
  return "blocked";
}

function isAbortError(error) {
  return error?.name === "AbortError";
}

function createAbortError(message = "Transfer cancelled") {
  const error = new Error(message);
  error.name = "AbortError";
  return error;
}

function throwIfAborted(signal) {
  if (signal?.aborted) {
    throw createAbortError();
  }
}

async function scanFile({ filePath, settings, signal }) {
  throwIfAborted(signal);
  const baseUrl = String(settings.dsxaBaseUrl || "").replace(/\/+$/, "");
  const url = `${baseUrl}/scan/binary/v2`;
  const headers = {
    "Content-Type": "application/octet-stream"
  };
  if (settings.dsxaProtectedEntity !== "" && settings.dsxaProtectedEntity != null) {
    headers.protected_entity = String(Number.parseInt(String(settings.dsxaProtectedEntity), 10) || 1);
  }
  if (settings.dsxaAuthToken) {
    headers.AUTH_TOKEN = settings.dsxaAuthToken;
    headers.AUTH = settings.dsxaAuthToken;
  }
  const response = await fetch(url, {
    method: "POST",
    headers,
    body: fsSync.createReadStream(filePath),
    duplex: "half",
    signal
  });
  const text = await response.text();
  if (!response.ok) {
    throw new Error(`DSXA HTTP ${response.status} ${response.statusText}: ${text.slice(0, 2000)}`);
  }
  try {
    return JSON.parse(text);
  } catch (error) {
    throw new Error(`DSXA returned non-JSON response: ${text.slice(0, 2000)}`);
  }
}

async function copyAllowedFile(item, destinationRoot, signal) {
  throwIfAborted(signal);
  const relative = item.metadata.relative_path || item.object_identity;
  const destination = path.resolve(destinationRoot, relative);
  const root = path.resolve(destinationRoot);
  if (!destination.startsWith(root + path.sep) && destination !== root) {
    throw new Error(`Destination escaped root: ${destination}`);
  }
  await fs.mkdir(path.dirname(destination), { recursive: true });
  throwIfAborted(signal);
  await fs.copyFile(item.metadata.source_path, destination);
  throwIfAborted(signal);
  const stat = await fs.stat(destination);
  return stat.size;
}

async function writeJsonFile(target, payload) {
  await fs.mkdir(path.dirname(target), { recursive: true });
  await fs.writeFile(target, JSON.stringify(payload, null, 2), "utf8");
}

function auditEventFromOutcome(transferId, outcome) {
  const decision = outcome.decision || {};
  return {
    event_type: "transfer_item_outcome",
    transfer_id: transferId,
    source_uri: outcome.item.source_uri,
    destination_uri: outcome.item.destination_uri,
    object_identity: outcome.item.object_identity,
    state: outcome.state,
    verdict: decision.verdict || null,
    action: decision.action || null,
    file_type: decision.file_type || null,
    policy_id: decision.policy_id || null,
    bytes_written: outcome.bytes_written || 0,
    error: outcome.error || null,
    details: {},
    event_time: nowIso()
  };
}

function reportSummary(outcomes) {
  return {
    planned_count: outcomes.length,
    allowed_count: outcomes.filter((outcome) => outcome.state === "allowed").length,
    blocked_count: outcomes.filter((outcome) => outcome.state === "blocked").length,
    failed_count: outcomes.filter((outcome) => outcome.state === "failed").length,
    skipped_count: outcomes.filter((outcome) => outcome.state === "skipped").length,
    excluded_count: outcomes.filter((outcome) => outcome.state === "excluded").length
  };
}

async function runGuardedTransfer({ settings, paths, onProgress, signal }) {
  const sourceRoot = path.resolve(settings.sourcePath);
  const destinationRoot = path.resolve(settings.destinationPath);
  const transferId = paths.transferId;
  const policyId = "desktop-default";
  const verdictActions = {
    benign: "allow",
    malicious: "block",
    suspicious: "block",
    unknown: "block",
    error: "block",
    ...(settings.verdictActions || {})
  };
  const fileTypeBlocks = {
    windowsExecutables: true,
    ...(settings.fileTypeBlocks || {})
  };

  const startedAt = nowIso();
  const items = await listFiles(sourceRoot, destinationRoot);
  const outcomes = [];
  const checkpointRecords = {};
  const counts = {
    completed: 0,
    allowed: 0,
    blocked: 0,
    failed: 0,
    skipped: 0,
    excluded: 0
  };
  let auditLines = [];
  let auditWrite = Promise.resolve();
  const concurrency = Math.max(1, Number.parseInt(String(settings.transferConcurrency || 4), 10) || 4);
  let cursor = 0;
  let lastProgressAt = 0;
  let lastProgressCompleted = -1;

  async function flushAudit() {
    if (!auditLines.length) {
      return auditWrite;
    }
    const batch = auditLines.join("");
    auditLines = [];
    auditWrite = auditWrite.then(async () => {
      await fs.mkdir(path.dirname(paths.auditPath), { recursive: true });
      await fs.appendFile(paths.auditPath, batch, "utf8");
    });
    return auditWrite;
  }

  function emitProgress(item, state, force = false) {
    if (!onProgress) return;
    const currentTime = Date.now();
    const shouldEmit =
      force ||
      counts.completed === 0 ||
      counts.completed === items.length ||
      counts.completed - lastProgressCompleted >= 10 ||
      currentTime - lastProgressAt >= 250;
    if (!shouldEmit) return;
    lastProgressAt = currentTime;
    lastProgressCompleted = counts.completed;
    onProgress({
      event: "transfer_progress",
      completed_items: counts.completed,
      total_items: items.length,
      allowed_items: counts.allowed,
      blocked_items: counts.blocked,
      failed_items: counts.failed,
      skipped_items: counts.skipped,
      excluded_items: counts.excluded,
      object_identity: item?.object_identity || null,
      state
    });
  }

  async function executeItem(item) {
    throwIfAborted(signal);
    const itemStartedAt = nowIso();
    try {
      const response = await scanFile({ filePath: item.metadata.source_path, settings, signal });
      const observation = scanObservationFromDsxa(response);
      const decision = applyFileTypeBlocks(
        evaluatePolicy({ item, observation, policyId, verdictActions }),
        fileTypeBlocks
      );
      let bytesWritten = 0;
      let state = stateForAction(decision.action);
      if (decision.action === "allow") {
        bytesWritten = await copyAllowedFile(item, destinationRoot, signal);
        state = "allowed";
      }
      return {
        item,
        state,
        decision,
        bytes_written: bytesWritten,
        started_at: itemStartedAt,
        completed_at: nowIso(),
        error: null
      };
    } catch (error) {
      if (signal?.aborted || isAbortError(error)) {
        throw createAbortError();
      }
      return {
        item,
        state: "failed",
        decision: null,
        bytes_written: 0,
        started_at: itemStartedAt,
        completed_at: nowIso(),
        error: {
          type: error?.name || "Error",
          message: error?.message || String(error)
        }
      };
    }
  }

  async function worker() {
    while (cursor < items.length && !signal?.aborted) {
      const item = items[cursor];
      cursor += 1;
      const outcome = await executeItem(item);
      outcomes.push(outcome);
      auditLines.push(`${JSON.stringify(auditEventFromOutcome(transferId, outcome))}\n`);
      if (auditLines.length >= 100) {
        await flushAudit();
      }
      const checkpointRecord = {
        transfer_id: transferId,
        object_identity: item.object_identity,
        source_uri: item.source_uri,
        destination_uri: item.destination_uri,
        state: outcome.state,
        size_bytes: item.size_bytes,
        metadata_fingerprint: item.metadata.mtime_ms == null ? null : String(item.metadata.mtime_ms),
        outcome,
        updated_at: nowIso()
      };
      checkpointRecords[item.object_identity] = checkpointRecord;
      counts.completed += 1;
      if (outcome.state === "allowed") counts.allowed += 1;
      else if (outcome.state === "blocked") counts.blocked += 1;
      else if (outcome.state === "failed") counts.failed += 1;
      else if (outcome.state === "skipped") counts.skipped += 1;
      else if (outcome.state === "excluded") counts.excluded += 1;
      emitProgress(item, outcome.state);
    }
  }

  emitProgress(null, "planned", true);
  const workers = Array.from({ length: Math.min(concurrency, Math.max(1, items.length)) }, () => worker());
  const workerResults = await Promise.allSettled(workers);
  await flushAudit();
  await writeJsonFile(paths.checkpointPath, checkpointRecords);
  emitProgress(null, signal?.aborted ? "cancelled" : "completed", true);
  outcomes.sort((a, b) => a.item.object_identity.localeCompare(b.item.object_identity));
  const report = {
    transfer_id: transferId,
    source_uri: pathToFileURL(sourceRoot).toString(),
    destination_uri: pathToFileURL(destinationRoot).toString(),
    policy_id: policyId,
    outcomes,
    started_at: startedAt,
    completed_at: nowIso(),
    ...reportSummary(outcomes)
  };
  const failedWorker = workerResults.find((result) => result.status === "rejected" && !isAbortError(result.reason));
  if (failedWorker) {
    throw failedWorker.reason;
  }
  if (signal?.aborted || workerResults.some((result) => result.status === "rejected" && isAbortError(result.reason))) {
    const error = createAbortError();
    error.report = report;
    throw error;
  }
  return report;
}

module.exports = {
  runGuardedTransfer
};
