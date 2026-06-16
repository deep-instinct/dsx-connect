const $ = (id) => document.getElementById(id);
const RESULT_DISPLAY_LIMIT = 100;
let currentThemeMode = "auto";

const fields = {
  dsxaBaseUrl: $("dsxaBaseUrl"),
  dsxaAuthToken: $("dsxaAuthToken"),
  dsxaProtectedEntity: $("dsxaProtectedEntity"),
  dsxaVerifyTls: $("dsxaVerifyTls"),
  sourcePath: $("sourcePath"),
  destinationPath: $("destinationPath"),
  actionBenign: $("actionBenign"),
  actionMalicious: $("actionMalicious"),
  actionUnknown: $("actionUnknown"),
  actionError: $("actionError")
};

function systemPrefersDark() {
  return window.matchMedia?.("(prefers-color-scheme: dark)")?.matches ?? false;
}

function effectiveTheme() {
  if (currentThemeMode === "operations" || currentThemeMode === "security" || currentThemeMode === "light") {
    return currentThemeMode;
  }
  return systemPrefersDark() ? "operations" : "light";
}

function applyTheme() {
  document.documentElement.setAttribute("data-theme", effectiveTheme());
}

function setThemeMode(themeMode) {
  currentThemeMode = ["auto", "light", "operations", "security"].includes(themeMode) ? themeMode : "auto";
  applyTheme();
}

function setStatus(message, tone = "neutral") {
  const status = $("status");
  status.textContent = message;
  status.dataset.tone = tone;
}

function settingsFromForm() {
  return {
    scannerMode: "dsxa",
    defaultVerdict: "benign",
    detectEicarTestFile: false,
    dsxaBaseUrl: fields.dsxaBaseUrl.value.trim(),
    dsxaAuthToken: fields.dsxaAuthToken.value,
    dsxaProtectedEntity: Number.parseInt(fields.dsxaProtectedEntity.value, 10) || 1,
    dsxaVerifyTls: fields.dsxaVerifyTls.checked,
    sourcePath: fields.sourcePath.value.trim(),
    destinationPath: fields.destinationPath.value.trim(),
    verdictActions: {
      benign: fields.actionBenign.value,
      malicious: fields.actionMalicious.value,
      suspicious: "block",
      unknown: fields.actionUnknown.value,
      error: fields.actionError.value
    }
  };
}

function applySettings(settings) {
  setThemeMode(settings.themeMode || "auto");
  const verdictActions = settings.verdictActions || {};
  fields.dsxaBaseUrl.value = settings.dsxaBaseUrl || "http://127.0.0.1:5000";
  fields.dsxaAuthToken.value = settings.dsxaAuthToken || "";
  fields.dsxaProtectedEntity.value = settings.dsxaProtectedEntity || 1;
  fields.dsxaVerifyTls.checked = Boolean(settings.dsxaVerifyTls);
  fields.sourcePath.value = settings.sourcePath || "";
  fields.destinationPath.value = settings.destinationPath || "";
  fields.actionBenign.value = verdictActions.benign || "allow";
  fields.actionMalicious.value = verdictActions.malicious || "block";
  fields.actionUnknown.value = verdictActions.unknown || "block";
  fields.actionError.value = verdictActions.error || "block";
}

function setMetrics(summary = {}) {
  $("metricPlanned").textContent = String(summary.planned || 0);
  $("metricAllowed").textContent = String(summary.allowed || 0);
  $("metricBlocked").textContent = String(summary.blocked || 0);
  $("metricFailed").textContent = String(summary.failed || 0);
}

function resetProgress() {
  $("progressPanel").hidden = false;
  $("progressLabel").textContent = "Preparing transfer";
  $("progressPercent").textContent = "0%";
  $("transferProgress").value = 0;
}

function updateProgress(event) {
  const total = Number(event?.total_items || 0);
  const completed = Number(event?.completed_items || 0);
  const percent = total > 0 ? Math.min(100, Math.max(0, (completed / total) * 100)) : 0;
  $("progressPanel").hidden = false;
  $("transferProgress").value = percent;
  $("progressPercent").textContent = `${Math.round(percent)}%`;
  $("progressLabel").textContent = total > 0 ? `${completed} of ${total} files` : "Preparing transfer";
}

function completeProgress() {
  $("progressPanel").hidden = false;
  $("transferProgress").value = 100;
  $("progressPercent").textContent = "100%";
}

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const idx = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** idx).toFixed(idx === 0 ? 0 : 1)} ${units[idx]}`;
}

function renderResults(report) {
  const body = $("resultsBody");
  const outcomes = Array.isArray(report?.outcomes) ? report.outcomes : [];
  $("resultCount").textContent = outcomes.length
    ? `${outcomes.length} item outcomes. Showing first ${Math.min(outcomes.length, RESULT_DISPLAY_LIMIT)}.`
    : "No item outcomes returned.";
  body.innerHTML = "";

  if (!outcomes.length) {
    const row = document.createElement("tr");
    row.innerHTML = '<td colspan="5" class="empty">No files were found or no report was returned.</td>';
    body.appendChild(row);
    return;
  }

  for (const outcome of outcomes.slice(0, RESULT_DISPLAY_LIMIT)) {
    const decision = outcome.decision || {};
    const item = outcome.item || {};
    const row = document.createElement("tr");
    row.innerHTML = `
      <td><span class="pill state-${escapeHtml(outcome.state || "unknown")}">${escapeHtml(outcome.state || "-")}</span></td>
      <td>${escapeHtml(decision.verdict || "-")}</td>
      <td>${escapeHtml(decision.action || "-")}</td>
      <td><div class="object-cell" title="${escapeHtml(item.object_identity || "")}">${escapeHtml(item.object_identity || item.source_uri || "-")}</div></td>
      <td>${formatBytes(outcome.bytes_written || item.size_bytes || 0)}</td>
    `;
    body.appendChild(row);
  }

  if (outcomes.length > RESULT_DISPLAY_LIMIT) {
    const row = document.createElement("tr");
    row.innerHTML = `<td colspan="5" class="empty">Showing first ${RESULT_DISPLAY_LIMIT} of ${outcomes.length} outcomes. Full details are available from the audit file in the File menu.</td>`;
    body.appendChild(row);
  }
}

function renderError(message) {
  const body = $("resultsBody");
  $("resultCount").textContent = "Transfer failed.";
  body.innerHTML = "";
  const row = document.createElement("tr");
  row.innerHTML = `<td colspan="5" class="empty">${escapeHtml(message || "Transfer failed.")}</td>`;
  body.appendChild(row);
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

async function pickFolder(purpose, target) {
  const picked = await window.dsxTransferDesktop.pickFolder(purpose);
  if (picked) {
    target.value = picked;
  }
}

async function saveSettings() {
  const saved = await window.dsxTransferDesktop.saveSettings(settingsFromForm());
  applySettings(saved);
  setStatus("Settings saved", "ok");
}

async function runTransfer() {
  const button = $("runTransfer");
  button.disabled = true;
  setStatus("Running transfer", "busy");
  resetProgress();
  try {
    await window.dsxTransferDesktop.saveSettings(settingsFromForm());
    const result = await window.dsxTransferDesktop.runTransfer(settingsFromForm());
    setMetrics(result.summary);
    renderResults(result.report);
    completeProgress();
    setStatus(result.ok ? "Completed" : "Completed with errors", result.ok ? "ok" : "error");
  } catch (error) {
    setStatus("Failed", "error");
    renderError(error?.message || String(error));
  } finally {
    button.disabled = false;
  }
}

async function init() {
  applySettings(await window.dsxTransferDesktop.loadSettings());
  window.matchMedia?.("(prefers-color-scheme: dark)")?.addEventListener?.("change", () => {
    if (currentThemeMode === "auto") applyTheme();
  });
  window.dsxTransferDesktop.onThemeChanged((payload) => setThemeMode(payload?.themeMode));
  window.dsxTransferDesktop.onTransferProgress(updateProgress);
  $("pickSource").addEventListener("click", () => pickFolder("source", fields.sourcePath));
  $("pickDestination").addEventListener("click", () => pickFolder("destination", fields.destinationPath));
  $("saveSettings").addEventListener("click", saveSettings);
  $("runTransfer").addEventListener("click", runTransfer);
}

init().catch((error) => {
  setStatus("Initialization failed", "error");
  renderError(error?.stack || error?.message || String(error));
});
