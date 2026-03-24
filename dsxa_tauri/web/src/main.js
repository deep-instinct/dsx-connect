const state = {
  selectedContext: "default",
  contexts: {},
  settings: {
    max_file_size_mb: 2048,
    connection_panel_collapsed: true
  }
};

let activeFolderJobId = null;
let unlistenFolderProgress = null;
let connectivityCheckTimer = null;
let isDsxaReachable = false;
let forceConnectionPanelExpanded = false;
let folderScanStartedAt = 0;
let folderVerdictStats = {
  benign: 0,
  malicious: 0,
  failed: 0,
  encrypted: 0,
  other: 0
};

const el = (id) => document.getElementById(id);
const tauri = window.__TAURI__;
const invoke = (cmd, args = {}) => tauri.core.invoke(cmd, args);

function isUnselectedPathText(value) {
  const text = String(value || "").trim().toLowerCase();
  return (
    /^<no (file|folder) selected>$/.test(text) ||
    text === "no file selected" ||
    text === "no file selected yet" ||
    text === "no folder selected" ||
    text === "no folder selected yet"
  );
}

function selectedPathValue(elementId) {
  const raw = (el(elementId)?.textContent || "").trim();
  if (!raw || isUnselectedPathText(raw)) return "";
  return raw;
}

function setPathDisplay(elementId, value, emptyText) {
  const node = el(elementId);
  if (!node) return;
  const text = String(value || "").trim();
  if (text) {
    node.textContent = text;
    node.title = text;
  } else {
    node.textContent = emptyText;
    node.title = "";
  }
}

function setStatus(text) {
  el("status").textContent = text || "";
}

function setBaseUrlConnectivity(ok, message = "", detail = "") {
  isDsxaReachable = !!ok;
  const input = el("baseUrl");
  const health = el("baseUrlHealth");
  input.classList.toggle("url-unreachable", !ok);
  health.classList.remove("ok", "bad");
  if (message) {
    health.textContent = message;
    health.classList.add(ok ? "ok" : "bad");
    health.title = detail || "";
  } else {
    health.textContent = "";
    health.title = "";
  }
  if (!ok) {
    forceConnectionPanelExpanded = true;
  }
  syncConnectionHeaderStatus();
  applyConnectionPanelState();
  updateScanButtonsEnabledState();
}

function setBaseUrlConnectivityPending(message = "", detail = "") {
  isDsxaReachable = false;
  const input = el("baseUrl");
  const health = el("baseUrlHealth");
  input.classList.remove("url-unreachable");
  health.classList.remove("ok", "bad");
  health.textContent = message || "";
  health.title = detail || "";
  syncConnectionHeaderStatus();
  applyConnectionPanelState();
  updateScanButtonsEnabledState();
}

function readinessMessageFromReason(reason) {
  switch (String(reason || "").toLowerCase()) {
    case "ready":
      return "Ready to scan ✓";
    case "auth_failed":
      return "Not ready: auth failed";
    case "invalid_entity":
      return "Not ready: invalid entity";
    case "tls_error":
      return "Not ready: TLS error";
    case "endpoint_unavailable":
      return "Not ready: endpoint unavailable";
    case "timeout":
      return "Not ready: timeout";
    case "server_error":
      return "Not ready: scanner error";
    case "bad_request":
      return "Not ready: bad request";
    case "connection_error":
      return "Not ready: connection failed";
    case "invalid_url":
      return "Not ready: invalid URL";
    default:
      return "Not ready";
  }
}

function syncConnectionHeaderStatus() {
  const main = el("baseUrlHealth");
  const link = el("headerBaseUrl");
  if (link) {
    const baseUrl = el("baseUrl")?.value?.trim() || "";
    link.textContent = baseUrl;
    link.href = baseUrl || "#";
    link.title = baseUrl;
  }
}

async function persistUiState() {
  await invoke("save_state", {
    state: {
      selected_context: state.selectedContext,
      contexts: state.contexts,
      settings: state.settings
    }
  });
}

function isConnectionPanelCollapsed() {
  return !forceConnectionPanelExpanded &&
    !!state.settings.connection_panel_collapsed &&
    isDsxaReachable;
}

function applyConnectionPanelState() {
  const panel = el("connectionPanel");
  const body = el("connectionPanelBody");
  const toggle = el("toggleConnectionPanel");
  if (!panel || !body || !toggle) return;

  const collapsed = isConnectionPanelCollapsed();
  panel.classList.toggle("collapsed", collapsed);
  body.hidden = collapsed;
  toggle.textContent = collapsed ? "Expand" : "Collapse";
  toggle.setAttribute("aria-expanded", String(!collapsed));
  toggle.disabled = !isDsxaReachable;
  toggle.title = isDsxaReachable ? "" : "Connect to a scanner before collapsing";
}

async function setConnectionPanelCollapsed(collapsed, remember = true) {
  forceConnectionPanelExpanded = false;
  state.settings.connection_panel_collapsed = !!collapsed;
  applyConnectionPanelState();
  if (remember) {
    try {
      await persistUiState();
    } catch (_error) {
      // Non-fatal; UI state persistence can fail silently.
    }
  }
}

function openSettingsModal() {
  el("maxFileSizeMb").value = String(state.settings.max_file_size_mb ?? 2048);
  el("settingsModal").hidden = false;
}

function openContextSelectModal() {
  const picker = el("contextPicker");
  const names = Object.keys(state.contexts);
  picker.innerHTML = names.map((n) => `<option value="${n}">${n}</option>`).join("");
  picker.value = state.selectedContext;
  el("contextSelectModal").hidden = false;
}

function openContextCreateModal() {
  const input = el("contextCreateName");
  if (input) {
    input.value = "";
    input.focus();
  }
  el("contextCreateModal").hidden = false;
}

function openContextDeleteModal() {
  const names = Object.keys(state.contexts).sort();
  const list = el("contextDeleteList");
  if (!list) return;
  list.innerHTML = names
    .map((name) => {
      const checkedLabel = name === state.selectedContext ? " (active)" : "";
      return `
        <label class="profile-delete-row">
          <input type="checkbox" value="${name}" />
          <span>${name}${checkedLabel}</span>
        </label>
      `;
    })
    .join("");
  el("contextDeleteModal").hidden = false;
}

function setActiveTab(tabId) {
  const tabButtons = document.querySelectorAll(".tab-btn");
  const panes = document.querySelectorAll(".tab-pane");
  for (const btn of tabButtons) {
    btn.classList.toggle("active", btn.dataset.tab === tabId);
  }
  for (const pane of panes) {
    pane.classList.toggle("active", pane.id === tabId);
  }
}

// function setFolderProgress(scanned, total, labelPrefix = "Progress") {
//   const progress = el("folderProgress");
//   const label = el("folderProgressLabel");
//   const max = Number(total || 0);
//   const done = Number(scanned || 0);
//   progress.max = max > 0 ? max : 1;
//   progress.value = max > 0 ? Math.min(done, max) : 0;
//   label.textContent = `${labelPrefix}: ${done}/${max || 0}`;
// }

function setFolderProgress(scanned, total, labelPrefix = "Progress") {
    const progress = el("folderProgress");
    const label = el("folderProgressLabel");

    const max = Number(total || 0);
    const done = Number(scanned || 0);

    progress.max = max > 0 ? max : 1;
    progress.value = max > 0 ? Math.min(done, max) : 0;

    const percent = max > 0 ? Math.round((done / max) * 100) : 0;

    let rate = 0;
    if (folderScanStartedAt > 0) {
        const elapsedSeconds = Math.max((Date.now() - folderScanStartedAt) / 1000, 0.001);
        rate = done / elapsedSeconds;
    }

    label.textContent = `${labelPrefix}: ${done}/${max || 0} (${percent}%) • ${rate.toFixed(1)} files/sec`;
}

function setFolderProgressVisible(visible) {
  const placeholder = el("folderProgressPlaceholder");
  const label = el("folderProgressLabel");
  const stats = el("folderStats");
  const bar = el("folderProgress");
  if (placeholder) placeholder.hidden = !!visible;
  if (label) label.hidden = !visible;
  if (stats) stats.hidden = !visible;
  if (bar) bar.hidden = !visible;
}

function resetFolderStats() {
  folderVerdictStats = {
    benign: 0,
    malicious: 0,
    failed: 0,
    encrypted: 0,
    other: 0
  };
  updateFolderStats();
}

function updateFolderStatsFromPayload(stats) {
  if (!stats || typeof stats !== "object") return;
  folderVerdictStats = {
    benign: Number(stats.benign || 0),
    malicious: Number(stats.malicious || 0),
    failed: Number(stats.failed || 0),
    encrypted: Number(stats.encrypted || 0),
    other: Number(stats.other || 0)
  };
  updateFolderStats();
}

function updateFolderStats() {
  const node = el("folderStats");
  if (!node) return;
  node.innerHTML =
    `Benign: ${folderVerdictStats.benign}&nbsp;&nbsp;` +
    `<span style="color:#f87171">Malicious: ${folderVerdictStats.malicious}</span>&nbsp;&nbsp;` +
    `Failed: ${folderVerdictStats.failed}&nbsp;&nbsp;` +
    `Encrypted: ${folderVerdictStats.encrypted}&nbsp;&nbsp;` +
    `Other: ${folderVerdictStats.other}`;
}

function setFolderMeta(text = "") {
  const node = el("folderMeta");
  if (!node) return;
  node.textContent = text ? `• ${text}` : "";
}

async function refreshFolderFileCountPreview(folderPath) {
  if (!folderPath) {
    setFolderMeta("");
    return;
  }
  setFolderMeta("Counting files...");
  try {
    const result = await invoke("preview_folder_file_count", {
      folderPath,
      limit: 500000
    });
    if (result && typeof result.count === "number") {
      if (result.truncated) {
        setFolderMeta("> 500,000 files");
      } else {
        setFolderMeta(`~${result.count.toLocaleString()} files`);
      }
    } else {
      setFolderMeta("");
    }
  } catch (_error) {
    setFolderMeta("");
  }
}

function formatSeconds(value) {
  const num = Number(value || 0);
  if (!Number.isFinite(num)) return "0.00";
  return num.toFixed(2);
}

function renderOutputBlock(title, lines) {
  const out = el("output");
  out.value = `${title}\n${lines.join("\n")}\n`;
}

function renderScanFileResult(result) {
  const lines = [
    `File: ${result?.file || ""}`,
    `Elapsed: ${formatSeconds(result?.elapsed_seconds)}s`,
    "",
    JSON.stringify(result?.result || {}, null, 2)
  ];
  renderOutputBlock("Scan File Result", lines);
}

function renderScanHashResult(result) {
  const lines = [
    `Hash: ${result?.hash || ""}`,
    `Elapsed: ${formatSeconds(result?.elapsed_seconds)}s`,
    "",
    JSON.stringify(result?.result || {}, null, 2)
  ];
  renderOutputBlock("Scan Hash Result", lines);
}

function renderEicarResult(result) {
  const lines = [
    "Payload: EICAR test string (base64)",
    `Endpoint: ${result?.endpoint || "/scan/base64/v2"}`,
    `Elapsed: ${formatSeconds(result?.elapsed_seconds)}s`,
    "",
    JSON.stringify(result?.result || {}, null, 2)
  ];
  renderOutputBlock("EICAR Test Result", lines);
}

function renderOperationFailure(title, details) {
  const lines = [details || "Unknown error"];
  renderOutputBlock(title, lines);
}

function renderFolderSummaryOutput(summary, failuresCount = 0) {
  const stats = summary?.stats || {};
  const concurrency = Number(summary?.concurrency || 0) || normalizeConcurrencyInput();
  const lines = [
    `Folder: ${summary?.folder || ""}`,
    `Pattern: ${summary?.pattern || "**/*"}`,
    `Max Concurrent Scans: ${concurrency}`,
    `Scanned: ${summary?.scanned ?? 0}`,
    `Success: ${summary?.ok ?? 0}`,
    `Failed: ${summary?.failed ?? 0}`,
    `Elapsed: ${formatSeconds(summary?.elapsed_seconds)}s`,
    `DSXA Scan Time (sum): ${formatSeconds(summary?.scan_time_total_seconds)}s`,
    `Benign: ${stats.benign ?? 0}   Malicious: ${stats.malicious ?? 0}   Encrypted: ${stats.encrypted ?? 0}   Other: ${stats.other ?? 0}`,
    `Failure records: ${failuresCount}`,
    "Detailed per-file results are available via JSONL/CSV logging if enabled."
  ];
  renderOutputBlock("Folder Scan Summary", lines);
}

function setFolderControlsRunning(running, complete = false) {
  const scanFolderBtn = el("scanFolder");
  const progressBar = el("folderProgress");
  scanFolderBtn.disabled = running || !isDsxaReachable;
  scanFolderBtn.textContent = running ? "Scanning..." : "Run Scan";
  scanFolderBtn.classList.toggle("is-running", !!running);
  scanFolderBtn.classList.toggle("scanning", !!running);
  if (progressBar) {
    progressBar.classList.toggle("scanning", !!running);
    progressBar.classList.toggle("complete", !running && !!complete);
  }
  el("stopFolder").hidden = !running;
  el("stopFolder").disabled = !running;
}

function updateScanButtonsEnabledState() {
  const canScan = isDsxaReachable;
  el("scanFile").disabled = !canScan;
  el("scanHash").disabled = !canScan;
  el("scanFolder").disabled = !!activeFolderJobId || !canScan;
  const eicarBtn = el("eicarTest");
  if (eicarBtn) eicarBtn.disabled = !canScan;
}

function normalizeConcurrencyInput() {
  const raw = (el("folderConcurrency").value || "").trim();
  const parsed = parseInt(raw, 10);
  const normalized = Number.isFinite(parsed) && parsed > 0 ? parsed : 1;
  el("folderConcurrency").value = String(normalized);
  return normalized;
}

function isAbsolutePath(pathValue) {
  if (!pathValue) return false;
  return /^(\/|[a-zA-Z]:[\\/]|\\\\)/.test(pathValue);
}

function joinPath(basePath, childPath) {
  const base = String(basePath || "").replace(/[\\/]+$/, "");
  const child = String(childPath || "").replace(/^[\\/]+/, "");
  const sep = base.includes("\\") && !base.includes("/") ? "\\" : "/";
  return `${base}${sep}${child}`;
}

function pathTail(pathValue, fallbackName) {
  const value = String(pathValue || "").trim();
  if (!value) return fallbackName;
  const normalized = value.replace(/[\\/]+$/, "");
  if (!normalized) return fallbackName;
  const parts = normalized.split(/[\\/]/).filter(Boolean);
  return parts.length ? parts[parts.length - 1] : fallbackName;
}

function resolvePathUnderFolder(folderPath, rawPath, defaultRelativePath) {
  const folder = String(folderPath || "").trim();
  const value = String(rawPath || "").trim();
  if (!folder) return value || defaultRelativePath;
  if (!value) return joinPath(folder, defaultRelativePath);
  if (isAbsolutePath(value) || value.startsWith("~")) return value;
  return joinPath(folder, value);
}

function applyFolderScopedPaths(folderPath) {
  const folder = String(folderPath || "").trim();
  if (!folder) return;
  // Rebase these outputs under the newly selected folder.
  el("logAllResultsPath").value = joinPath(folder, pathTail(el("logAllResultsPath").value, "scan-results.jsonl"));
  el("logMaliciousCsvPath").value = joinPath(folder, pathTail(el("logMaliciousCsvPath").value, "malicious.csv"));
  el("quarantineDir").value = joinPath(folder, pathTail(el("quarantineDir").value, "quarantine"));
}

function syncVerifyTlsFromBaseUrl() {
  const baseUrl = el("baseUrl").value.trim().toLowerCase();
  if (baseUrl.startsWith("https://")) {
    el("verifyTls").checked = true;
  } else if (baseUrl.startsWith("http://")) {
    el("verifyTls").checked = false;
  }
}

function isPlausibleBaseUrl(value) {
  const raw = String(value || "").trim();
  if (!raw) return false;
  if (!(raw.startsWith("http://") || raw.startsWith("https://"))) return false;
  try {
    const u = new URL(raw);
    return !!u.host;
  } catch (_e) {
    return false;
  }
}

function currentContext() {
  const peRaw = el("protectedEntity").value.trim();
  const pe = parseInt(peRaw || "1", 10);
  const customMetadataEl = el("customMetadata");
  return {
    baseUrl: el("baseUrl").value.trim(),
    authToken: el("authToken").value,
    protectedEntity: Number.isFinite(pe) ? pe : 1,
    customMetadata: customMetadataEl ? (customMetadataEl.value || "") : "",
    verifyTls: !!el("verifyTls").checked,
    base64Mode: !!el("base64Mode").checked
  };
}

function currentMaxFileSizeBytes() {
  const mbRaw = (state.settings?.max_file_size_mb ?? 2048);
  const mb = Number.isFinite(Number(mbRaw)) && Number(mbRaw) > 0 ? Number(mbRaw) : 2048;
  return Math.floor(mb * 1024 * 1024);
}

function updateCurrentContextLabel() {
  const label = el("currentContextName");
  if (label) label.textContent = `Profile: ${state.selectedContext || "default"} ▼`;
}

function applyContext(name) {
  const ctx = state.contexts[name];
  if (!ctx) return;
  state.selectedContext = name;
  el("baseUrl").value = ctx.baseUrl || "http://127.0.0.1:5000";
  el("authToken").value = ctx.authToken || "";
  el("protectedEntity").value = String(ctx.protectedEntity ?? 1);
  const customMetadataEl = el("customMetadata");
  if (customMetadataEl) {
    customMetadataEl.value = typeof ctx.customMetadata === "string" ? ctx.customMetadata : "";
  }
  el("verifyTls").checked = !!ctx.verifyTls;
  el("base64Mode").checked = !!ctx.base64Mode;
  updateCurrentContextLabel();
  if (ctx.baseUrl) {
    syncVerifyTlsFromBaseUrl();
  }
  syncConnectionHeaderStatus();
  applyConnectionPanelState();
}

function refreshContextSelect() {
  const names = Object.keys(state.contexts);
  if (!names.length) {
    state.contexts.default = currentContext();
  }
  const finalNames = Object.keys(state.contexts);
  if (finalNames.length && !state.contexts[state.selectedContext]) {
    state.selectedContext = finalNames[0];
  }
  if (finalNames.length) applyContext(state.selectedContext);
}

async function createContextFlow(profileName) {
  const fallback = `profile-${new Date().toISOString().replace(/[:.]/g, "-")}`;
  const name = (String(profileName || "").trim() || fallback).trim();
  if (!name) {
    setStatus("Create profile canceled");
    return;
  }
  if (state.contexts[name]) {
    setStatus(`Profile '${name}' already exists`);
    return;
  }
  state.contexts[name] = currentContext();
  state.selectedContext = name;
  refreshContextSelect();
  await persist();
  setStatus(`Created profile '${name}'`);
}

async function deleteProfilesFlow() {
  const list = el("contextDeleteList");
  if (!list) return;
  const checked = Array.from(list.querySelectorAll("input[type='checkbox']:checked")).map((n) => String(n.value));
  if (!checked.length) {
    setStatus("Select one or more profiles to delete");
    return;
  }
  const names = Object.keys(state.contexts);
  if (checked.length >= names.length) {
    setStatus("At least one profile must remain");
    return;
  }

  for (const name of checked) {
    delete state.contexts[name];
  }

  if (!state.contexts[state.selectedContext]) {
    const remaining = Object.keys(state.contexts).sort();
    state.selectedContext = remaining[0] || "default";
  }

  refreshContextSelect();
  await persist();
  scheduleConnectivityCheck(100);
  el("contextDeleteModal").hidden = true;
  setStatus(`Deleted ${checked.length} profile(s)`);
}

async function selectContextFlow() {
  const name = (el("contextPicker").value || "").trim();
  if (!name || !state.contexts[name]) {
    setStatus("Select a valid profile");
    return;
  }
  applyContext(name);
  forceConnectionPanelExpanded = true;
  applyConnectionPanelState();
  el("contextSelectModal").hidden = true;
  scheduleConnectivityCheck(100);
  setStatus(`Selected profile '${name}'`);
}

async function saveContextFlow() {
  await persist();
  setStatus(`Saved profile '${state.selectedContext}'`);
  scheduleConnectivityCheck(100);
}

function refreshContextsMenuHint() {
  const names = Object.keys(state.contexts);
  if (names.length && !state.contexts[state.selectedContext]) {
    state.selectedContext = names[0];
  }
  updateCurrentContextLabel();
}

async function persist() {
  state.contexts[state.selectedContext] = currentContext();
  await invoke("save_state", {
    state: {
      selected_context: state.selectedContext,
      contexts: state.contexts,
      settings: state.settings
    }
  });
  await syncContextMenu();
}

async function syncContextMenu() {
  try {
    await invoke("sync_context_menu", {
      req: {
        names: Object.keys(state.contexts),
        selected: state.selectedContext
      }
    });
  } catch (error) {
    setStatus(`Profile menu sync failed: ${error}`);
  }
}

function handleFolderProgress(payload) {
  if (!payload || !payload.job_id) return;
  if (!activeFolderJobId || payload.job_id !== activeFolderJobId) return;

  if (payload.type === "start" || payload.type === "progress") {
    updateFolderStatsFromPayload(payload.stats);
    const scanned = Number(payload.scanned || 0);
    const total = Number(payload.total || 0);
    const percent = total > 0 ? Math.round((scanned / total) * 100) : 0;

    let rate = 0;
    if (folderScanStartedAt > 0) {
        const elapsedSeconds = Math.max((Date.now() - folderScanStartedAt) / 1000, 0.001);
        rate = scanned / elapsedSeconds;
    }

  setFolderProgress(scanned, total, "Scanning");
    setFolderProgressVisible(true);
    setStatus(`Scanning folder... ${scanned}/${total} (${percent}%) • ${rate.toFixed(1)} files/sec`);
    return;
  }

  if (payload.type === "done" || payload.type === "canceled") {
    updateFolderStatsFromPayload(payload.stats || payload.summary?.stats);
    const failuresCount = Array.isArray(payload.failures) ? payload.failures.length : 0;
    if (payload.summary) {
      renderFolderSummaryOutput(payload.summary, failuresCount);
    } else {
      renderFolderSummaryOutput(
        {
          folder: selectedPathValue("folderPath"),
          pattern: "**/*",
          scanned: payload.scanned || 0,
          ok: payload.ok || 0,
          failed: payload.failed || 0,
          elapsed_seconds: 0,
          scan_time_total_seconds: 0,
          stats: payload.stats || {}
        },
        failuresCount
      );
    }
    const scanned = Number(payload.scanned || 0);
    const total = Number(payload.total || payload.scanned || 0);
    setFolderProgress(scanned, total, payload.type === "canceled" ? "Canceled" : "Complete");
    setFolderProgressVisible(true);
    setStatus(payload.type === "canceled" ? "Folder scan canceled" : "Folder scan complete");
    activeFolderJobId = null;
    setFolderControlsRunning(false, payload.type === "done");
    folderScanStartedAt = 0;
    return;
  }

  if (payload.type === "error") {
    renderOutputBlock("Folder Scan Summary", [
      `Error: ${payload.error || "unknown error"}`,
      "Detailed per-file results are available via JSONL/CSV logging if enabled."
    ]);
    setStatus("Folder scan failed");
    activeFolderJobId = null;
    setFolderControlsRunning(false, false);
    setFolderProgress(0, 0, "Progress");
    setFolderProgressVisible(true);
    resetFolderStats();
    folderScanStartedAt = 0;
  }
}

async function boot() {
  const loaded = await invoke("get_state");
  state.selectedContext = loaded.selected_context || "default";
  state.contexts = loaded.contexts || {};
  state.settings = loaded.settings || { max_file_size_mb: 2048, connection_panel_collapsed: true };
  if (typeof state.settings.connection_panel_collapsed !== "boolean") {
    state.settings.connection_panel_collapsed = true;
  }
  el("maxFileSizeMb").value = String(state.settings.max_file_size_mb ?? 2048);
  refreshContextSelect();
  await syncContextMenu();
  unlistenFolderProgress = await tauri.event.listen("scan-folder-progress", (event) => handleFolderProgress(event.payload));
  setFolderControlsRunning(false, false);
  setFolderProgressVisible(false);
  setFolderProgress(0, 0, "Progress");
  resetFolderStats();
  syncConnectionHeaderStatus();
  applyConnectionPanelState();
  updateScanButtonsEnabledState();
  scheduleConnectivityCheck(50);
}

async function checkConnectivityNow() {
  const baseUrl = el("baseUrl").value.trim();
  if (!isPlausibleBaseUrl(baseUrl)) {
    setBaseUrlConnectivity(false, readinessMessageFromReason("invalid_url"), "Base URL is invalid");
    return;
  }
  try {
    const res = await invoke("check_dsxa_connectivity", {
      req: { context: currentContext() }
    });
    const detail = res?.detail || (res?.status ? `HTTP ${res.status}` : "");
    setBaseUrlConnectivity(!!res.reachable, readinessMessageFromReason(res?.reason), detail);
  } catch (error) {
    setBaseUrlConnectivity(false, readinessMessageFromReason("connection_error"), String(error || ""));
  }
}

function scheduleConnectivityCheck(delayMs = 700, force = false) {
  if (connectivityCheckTimer) clearTimeout(connectivityCheckTimer);
  const baseUrl = el("baseUrl").value.trim();
  if (!isPlausibleBaseUrl(baseUrl) && !force) {
    setBaseUrlConnectivityPending("Not ready: invalid URL");
    return;
  }
  setBaseUrlConnectivityPending("Validating...");
  connectivityCheckTimer = setTimeout(() => {
    connectivityCheckTimer = null;
    checkConnectivityNow();
  }, delayMs);
}

function bindHandlers() {
  const profileBtn = el("currentContextName");
  if (profileBtn) {
    profileBtn.addEventListener("click", () => openContextSelectModal());
  }
  const toggleConnectionPanel = el("toggleConnectionPanel");
  if (toggleConnectionPanel) {
    toggleConnectionPanel.addEventListener("click", async () => {
      await setConnectionPanelCollapsed(!isConnectionPanelCollapsed(), true);
    });
  }

  el("baseUrl").addEventListener("input", () => {
    syncVerifyTlsFromBaseUrl();
    scheduleConnectivityCheck(700);
  });
  el("baseUrl").addEventListener("blur", () => {
    scheduleConnectivityCheck(0, true);
  });
  el("authToken").addEventListener("input", () => {
    scheduleConnectivityCheck(700);
  });
  el("protectedEntity").addEventListener("input", () => {
    scheduleConnectivityCheck(700);
  });
  el("verifyTls").addEventListener("change", () => {
    scheduleConnectivityCheck(200);
  });
  el("base64Mode").addEventListener("change", () => {
    scheduleConnectivityCheck(200);
  });

  const openSettingsBtn = el("openSettings");
  if (openSettingsBtn) {
    openSettingsBtn.addEventListener("click", () => openSettingsModal());
  }

  el("closeSettings").addEventListener("click", () => {
    el("settingsModal").hidden = true;
  });

  el("closeContextSelect").addEventListener("click", () => {
    el("contextSelectModal").hidden = true;
  });
  el("closeContextCreate").addEventListener("click", () => {
    el("contextCreateModal").hidden = true;
  });
  el("closeContextDelete").addEventListener("click", () => {
    el("contextDeleteModal").hidden = true;
  });

  el("settingsModal").addEventListener("click", (event) => {
    if (event.target && event.target.id === "settingsModal") {
      el("settingsModal").hidden = true;
    }
  });

  el("contextSelectModal").addEventListener("click", (event) => {
    if (event.target && event.target.id === "contextSelectModal") {
      el("contextSelectModal").hidden = true;
    }
  });
  el("contextCreateModal").addEventListener("click", (event) => {
    if (event.target && event.target.id === "contextCreateModal") {
      el("contextCreateModal").hidden = true;
    }
  });
  el("contextDeleteModal").addEventListener("click", (event) => {
    if (event.target && event.target.id === "contextDeleteModal") {
      el("contextDeleteModal").hidden = true;
    }
  });

  el("applyContextSelection").addEventListener("click", async () => {
    try {
      await selectContextFlow();
    } catch (error) {
      setStatus(`Select profile failed: ${error}`);
    }
  });
  el("applyContextCreate").addEventListener("click", async () => {
    try {
      await createContextFlow(el("contextCreateName").value);
      el("contextCreateModal").hidden = true;
      refreshContextsMenuHint();
    } catch (error) {
      setStatus(`Create profile failed: ${error}`);
    }
  });
  el("applyContextDelete").addEventListener("click", async () => {
    try {
      await deleteProfilesFlow();
      refreshContextsMenuHint();
    } catch (error) {
      setStatus(`Delete profile failed: ${error}`);
    }
  });

  el("saveSettings").addEventListener("click", async () => {
    const raw = (el("maxFileSizeMb").value || "").trim();
    const parsed = parseInt(raw, 10);
    const mb = Number.isFinite(parsed) && parsed > 0 ? parsed : 2048;
    state.settings.max_file_size_mb = mb;
    el("maxFileSizeMb").value = String(mb);
    try {
      await persistUiState();
      setStatus(`Saved settings (max file size ${mb} MB)`);
      el("settingsModal").hidden = true;
    } catch (error) {
      setStatus(`Save settings failed: ${error}`);
    }
  });

  for (const btn of document.querySelectorAll(".tab-btn")) {
    btn.addEventListener("click", () => setActiveTab(btn.dataset.tab));
  }

  el("pickFile").addEventListener("click", async () => {
    const path = await tauri.dialog.open({ multiple: false, directory: false });
    if (typeof path === "string" && path) setPathDisplay("filePath", path, "No file selected yet");
  });

  el("pickFolder").addEventListener("click", async () => {
    const path = await tauri.dialog.open({ multiple: false, directory: true });
    if (typeof path === "string" && path) {
      setPathDisplay("folderPath", path, "No folder selected yet");
      applyFolderScopedPaths(path);
      await refreshFolderFileCountPreview(path);
      if (!activeFolderJobId) {
        setFolderControlsRunning(false, false);
        setFolderProgressVisible(false);
        setFolderProgress(0, 0, "Progress");
        resetFolderStats();
      }
    }
  });

  el("pickLogAllResultsPath").addEventListener("click", async () => {
    const path = await tauri.dialog.save({ defaultPath: "results.jsonl" });
    if (typeof path === "string" && path) el("logAllResultsPath").value = path;
  });

  el("pickLogMaliciousCsvPath").addEventListener("click", async () => {
    const path = await tauri.dialog.save({ defaultPath: "malicious.csv" });
    if (typeof path === "string" && path) el("logMaliciousCsvPath").value = path;
  });

  el("pickQuarantineDir").addEventListener("click", async () => {
    const path = await tauri.dialog.open({ multiple: false, directory: true });
    if (typeof path === "string" && path) el("quarantineDir").value = path;
  });

  el("folderConcurrency").addEventListener("blur", () => normalizeConcurrencyInput());

  el("scanFile").addEventListener("click", async () => {
    const filePath = selectedPathValue("filePath");
    if (!filePath) return setStatus("Pick a file first");
    setStatus("Scanning file...");
    try {
      const result = await invoke("scan_file", {
        req: {
          context: currentContext(),
          file_path: filePath,
          password: el("filePassword").value || null,
          metadata: el("fileMetadata").value || null,
          max_file_size_bytes: currentMaxFileSizeBytes()
        }
      });
      renderScanFileResult(result);
      setStatus("File scan complete");
    } catch (error) {
      renderOperationFailure("Scan File Result", `Error: ${String(error)}`);
      setStatus("Scan file failed");
    }
  });

  el("scanHash").addEventListener("click", async () => {
    const hashValue = el("hashValue").value.trim();
    if (!hashValue) return setStatus("Provide a hash first");
    setStatus("Scanning hash...");
    try {
      const result = await invoke("scan_hash", {
        req: {
          context: currentContext(),
          file_hash: hashValue,
          metadata: el("hashMetadata").value || null
        }
      });
      renderScanHashResult(result);
      setStatus("Hash scan complete");
    } catch (error) {
      renderOperationFailure("Scan Hash Result", `Error: ${String(error)}`);
      setStatus("Scan hash failed");
    }
  });

  el("eicarTest").addEventListener("click", async () => {
    setStatus("Running EICAR test...");
    try {
      const result = await invoke("scan_eicar_test", {
        req: {
          context: currentContext()
        }
      });
      renderEicarResult(result);
      setStatus("EICAR test complete");
    } catch (error) {
      renderOperationFailure("EICAR Test Result", `Error: ${String(error)}`);
      setStatus("EICAR test failed");
    }
  });

  el("scanFolder").addEventListener("click", async () => {
    const folderPath = selectedPathValue("folderPath");
    if (!folderPath) return setStatus("Pick a folder first");
    if (activeFolderJobId) return setStatus("Folder scan already running");
    const logAllEnabled = !!el("logAllResults").checked;
    const logCsvEnabled = !!el("logMaliciousCsv").checked;

    const resolvedLogAllPath = resolvePathUnderFolder(folderPath, el("logAllResultsPath").value, "scan-results.jsonl");
    const resolvedLogCsvPath = resolvePathUnderFolder(folderPath, el("logMaliciousCsvPath").value, "malicious.csv");
    const resolvedQuarantineDir = resolvePathUnderFolder(folderPath, el("quarantineDir").value, "quarantine");
    el("logAllResultsPath").value = resolvedLogAllPath;
    el("logMaliciousCsvPath").value = resolvedLogCsvPath;
    el("quarantineDir").value = resolvedQuarantineDir;

    setStatus("Scanning folder...");
    folderScanStartedAt = Date.now();
    setFolderControlsRunning(true, false);
    setFolderProgressVisible(true);
    setFolderProgress(0, 0, "Starting");
    resetFolderStats();

    try {
      const res = await invoke("scan_folder_start", {
        req: {
          context: currentContext(),
          folder_path: folderPath,
          concurrency: normalizeConcurrencyInput(),
          password: el("folderPassword").value || null,
          metadata: el("folderMetadata").value || null,
          pattern: "**/*",
          log_all_results: logAllEnabled,
          log_all_results_path: logAllEnabled ? resolvedLogAllPath : null,
          log_malicious_csv: logCsvEnabled,
          log_malicious_csv_path: logCsvEnabled ? resolvedLogCsvPath : null,
          quarantine_enabled: !!el("quarantineEnabled").checked,
          quarantine_dir: !!el("quarantineEnabled").checked ? resolvedQuarantineDir : null,
          max_file_size_bytes: currentMaxFileSizeBytes()
        }
      });
      activeFolderJobId = res.job_id;
      setStatus(`Folder scan running (job ${String(activeFolderJobId).slice(0, 8)})`);
    } catch (error) {
      renderOperationFailure("Folder Scan Summary", `Error: ${String(error)}`);
      setStatus("Folder scan failed");
      setFolderControlsRunning(false, false);
      setFolderProgress(0, 0, "Progress");
    }
  });

  el("stopFolder").addEventListener("click", async () => {
    if (!activeFolderJobId) return;
    try {
      await invoke("scan_folder_stop", { jobId: activeFolderJobId });
      setStatus("Stopping folder scan...");
    } catch (error) {
      setStatus(`stop failed: ${error}`);
    }
  });
}

window.addEventListener("beforeunload", () => {
  if (typeof unlistenFolderProgress === "function") {
    unlistenFolderProgress();
    unlistenFolderProgress = null;
  }
});

window.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !el("settingsModal").hidden) {
    el("settingsModal").hidden = true;
  }
  if (event.key === "Escape" && !el("contextSelectModal").hidden) {
    el("contextSelectModal").hidden = true;
  }
  if (event.key === "Escape" && !el("contextCreateModal").hidden) {
    el("contextCreateModal").hidden = true;
  }
  if (event.key === "Escape" && !el("contextDeleteModal").hidden) {
    el("contextDeleteModal").hidden = true;
  }
});

window.addEventListener("DOMContentLoaded", async () => {
  try {
    bindHandlers();
    await tauri.event.listen("open-settings", () => {
      openSettingsModal();
    });
    await tauri.event.listen("open-new-context", async () => {
      try {
        openContextCreateModal();
      } catch (error) {
        setStatus(`Create profile failed: ${error}`);
      }
    });
    await tauri.event.listen("open-delete-context", async () => {
      try {
        openContextDeleteModal();
      } catch (error) {
        setStatus(`Delete profile failed: ${error}`);
      }
    });
    await tauri.event.listen("open-select-context", async () => {
      try {
        openContextSelectModal();
        refreshContextsMenuHint();
      } catch (error) {
        setStatus(`Select profile failed: ${error}`);
      }
    });
    await tauri.event.listen("open-select-context-by-name", async (event) => {
      try {
        const name = String(event?.payload || "").trim();
        if (!name || !state.contexts[name]) {
          setStatus(`Profile '${name}' not found`);
          return;
        }
        applyContext(name);
        await syncContextMenu();
        scheduleConnectivityCheck(100);
        setStatus(`Selected profile '${name}'`);
      } catch (error) {
        setStatus(`Select profile failed: ${error}`);
      }
    });
    await tauri.event.listen("save-context", async () => {
      try {
        await saveContextFlow();
      } catch (error) {
        setStatus(`Save profile failed: ${error}`);
      }
    });
    await boot();
  } catch (error) {
    setStatus(`UI init failed: ${error}`);
  }
});
