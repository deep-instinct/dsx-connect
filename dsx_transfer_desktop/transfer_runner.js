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

function stateForAction(action) {
  if (action === "exclude") return "excluded";
  return "blocked";
}

async function scanFile({ filePath, settings }) {
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
    duplex: "half"
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

async function copyAllowedFile(item, destinationRoot) {
  const relative = item.metadata.relative_path || item.object_identity;
  const destination = path.resolve(destinationRoot, relative);
  const root = path.resolve(destinationRoot);
  if (!destination.startsWith(root + path.sep) && destination !== root) {
    throw new Error(`Destination escaped root: ${destination}`);
  }
  await fs.mkdir(path.dirname(destination), { recursive: true });
  await fs.copyFile(item.metadata.source_path, destination);
  const stat = await fs.stat(destination);
  return stat.size;
}

async function appendJsonLine(target, payload) {
  await fs.mkdir(path.dirname(target), { recursive: true });
  await fs.appendFile(target, `${JSON.stringify(payload)}\n`, "utf8");
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

async function runGuardedTransfer({ settings, paths, onProgress }) {
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

  const startedAt = nowIso();
  const items = await listFiles(sourceRoot, destinationRoot);
  const outcomes = [];
  const checkpointRecords = {};
  let checkpointWrite = Promise.resolve();
  let completed = 0;
  const concurrency = Math.max(1, Number.parseInt(String(settings.transferConcurrency || 4), 10) || 4);
  let cursor = 0;

  async function executeItem(item) {
    const itemStartedAt = nowIso();
    try {
      const response = await scanFile({ filePath: item.metadata.source_path, settings });
      const observation = scanObservationFromDsxa(response);
      const decision = evaluatePolicy({ item, observation, policyId, verdictActions });
      let bytesWritten = 0;
      let state = stateForAction(decision.action);
      if (decision.action === "allow") {
        bytesWritten = await copyAllowedFile(item, destinationRoot);
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
    while (cursor < items.length) {
      const item = items[cursor];
      cursor += 1;
      const outcome = await executeItem(item);
      outcomes.push(outcome);
      await appendJsonLine(paths.auditPath, auditEventFromOutcome(transferId, outcome));
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
      checkpointWrite = checkpointWrite.then(async () => {
        await fs.mkdir(path.dirname(paths.checkpointPath), { recursive: true });
        await fs.writeFile(paths.checkpointPath, JSON.stringify(checkpointRecords, null, 2), "utf8");
      });
      await checkpointWrite;
      completed += 1;
      if (onProgress) {
        onProgress({
          event: "transfer_progress",
          completed_items: completed,
          total_items: items.length,
          object_identity: item.object_identity,
          state: outcome.state
        });
      }
    }
  }

  await Promise.all(Array.from({ length: Math.min(concurrency, Math.max(1, items.length)) }, () => worker()));
  outcomes.sort((a, b) => a.item.object_identity.localeCompare(b.item.object_identity));
  return {
    transfer_id: transferId,
    source_uri: pathToFileURL(sourceRoot).toString(),
    destination_uri: pathToFileURL(destinationRoot).toString(),
    policy_id: policyId,
    outcomes,
    started_at: startedAt,
    completed_at: nowIso(),
    ...reportSummary(outcomes)
  };
}

module.exports = {
  runGuardedTransfer
};
