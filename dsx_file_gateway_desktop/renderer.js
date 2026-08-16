const $ = (id) => document.getElementById(id);

let settings = {};
let destinations = [];
let selectedFiles = [];
let activeJobId = "";
let pollTimer = null;

function setStatus(message, tone = "neutral") {
  const node = $("statusText");
  node.textContent = message;
  node.dataset.tone = tone;
}

function setConnection(message, tone = "checking") {
  const node = $("connectionState");
  node.textContent = message;
  node.className = `state-pill ${tone}`;
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function fileNameFromPath(filePath) {
  return String(filePath || "").split(/[\\/]/).pop() || String(filePath || "");
}

function cleanRelativePath(value) {
  return String(value || "")
    .trim()
    .replace(/^\/+/, "")
    .replace(/\/+$/, "");
}

function joinPath(...parts) {
  return parts
    .map((part) => String(part || "").trim().replace(/^\/+|\/+$/g, ""))
    .filter(Boolean)
    .join("/");
}

function destinationBaseUri(destination) {
  if (!destination) return "";
  const selector = String(destination.selector || "").trim().replace(/^gs:\/\//, "").replace(/^\/+/, "");
  if (destination.platform === "gcs") {
    return `gs://${selector}`;
  }
  if (destination.platform === "filesystem") {
    return String(destination.selector || "").trim();
  }
  return selector || destination.display_name || destination.id;
}

function destinationTargetForFile(destination, destinationPath, filePath) {
  if (!destination || !filePath) return "";
  const fileName = fileNameFromPath(filePath);
  const relative = cleanRelativePath(destinationPath);
  if (destination.platform === "filesystem") {
    const base = String(destination.selector || "").replace(/\/+$/, "");
    return `${base}/${joinPath(relative, fileName)}`;
  }
  const base = destinationBaseUri(destination).replace(/\/+$/, "");
  return `${base}/${joinPath(relative, fileName)}`;
}

function setSettingsExpanded(expanded) {
  const panel = $("settingsPanel");
  const toggle = $("settingsToggle");
  const backdrop = $("settingsBackdrop");
  panel.classList.toggle("open", expanded);
  backdrop.classList.toggle("open", expanded);
  panel.setAttribute("aria-hidden", expanded ? "false" : "true");
  toggle.setAttribute("aria-expanded", expanded ? "true" : "false");
  toggle.setAttribute("aria-label", expanded ? "Close settings" : "Open settings");
}

function renderSettingsSummary() {
  const node = $("settingsSummary");
  const destination = currentDestination();
  if (!destination) {
    node.textContent = destinations.length
      ? "Choose a protected destination."
      : "No protected destinations available.";
    return;
  }
  const pathValue = cleanRelativePath($("destinationPath").value);
  const label = destination.display_name || destination.id;
  const target = destinationBaseUri(destination);
  node.textContent = `${label} - ${target}${pathValue ? `/${pathValue}` : ""}`;
}

function renderDestinationPreview() {
  const node = $("destinationPreview");
  const destination = currentDestination();
  if (!destination) {
    node.textContent = "Choose a protected destination and file.";
    renderSettingsSummary();
    return;
  }
  const baseUri = destinationBaseUri(destination);
  const pathValue = cleanRelativePath($("destinationPath").value);
  const sampleFiles = selectedFiles.slice(0, 3);
  const previews = sampleFiles.map((filePath) => destinationTargetForFile(destination, pathValue, filePath));
  node.innerHTML = `
    <div><span>Protected target</span><strong>${escapeHtml(baseUri)}</strong></div>
    <div><span>Relative path</span><strong>${escapeHtml(pathValue || "(root)")}</strong></div>
    ${
      previews.length
        ? `<ul>${previews.map((preview) => `<li>${escapeHtml(preview)}</li>`).join("")}</ul>`
        : `<p>Select files to preview delivery paths.</p>`
    }
  `;
  renderSettingsSummary();
}

function setSubmitEnabled() {
  $("submitTransfer").disabled = !currentDestination() || selectedFiles.length === 0;
}

function readForm() {
  return {
    dsxConnectUrl: $("dsxConnectUrl").value.trim(),
    gatewayToken: $("gatewayToken").value.trim(),
    destinationId: $("destinationId").value,
    destinationPath: $("destinationPath").value.trim(),
    selectedFiles,
    metadata: {
      application: "desktop-mvp"
    }
  };
}

async function persistForm() {
  settings = await window.dsxGateway.saveSettings(readForm());
}

function renderDestinations() {
  const select = $("destinationId");
  const previous = select.value || settings.destinationId || "";
  select.innerHTML = "";
  if (!destinations.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No destinations available";
    select.appendChild(option);
    renderDestinationDetail();
    renderDestinationPreview();
    setSubmitEnabled();
    return;
  }
  for (const destination of destinations) {
    const option = document.createElement("option");
    option.value = destination.id;
    const label = destination.display_name || destination.id;
    option.textContent = `${label} (${destination.platform})`;
    select.appendChild(option);
  }
  select.value = destinations.some((row) => row.id === previous) ? previous : destinations[0].id;
  renderDestinationDetail();
  renderDestinationPreview();
  setSubmitEnabled();
}

function currentDestination() {
  return destinations.find((row) => row.id === $("destinationId").value) || null;
}

function renderDestinationDetail() {
  const destination = currentDestination();
  if (!destination) {
    $("destinationDetail").textContent = "No destination selected.";
    return;
  }
  $("destinationDetail").innerHTML = `
    <div class="detail-title">${escapeHtml(destination.display_name || destination.id)}</div>
    <dl>
      <div><dt>Platform</dt><dd>${escapeHtml(destination.platform)} / ${escapeHtml(destination.platform_key)}</dd></div>
      <div><dt>Protected Target</dt><dd title="${escapeHtml(destinationBaseUri(destination))}">${escapeHtml(destinationBaseUri(destination))}</dd></div>
      <div><dt>Scope ID</dt><dd title="${escapeHtml(destination.scope_id)}">${escapeHtml(destination.scope_id)}</dd></div>
      <div><dt>Capabilities</dt><dd>${escapeHtml((destination.capabilities || []).join(" / ") || "scan")}</dd></div>
      <div><dt>Classification</dt><dd>${escapeHtml(destination.classification || "unclassified")}</dd></div>
      <div><dt>Max File</dt><dd>${formatBytes(destination.max_file_size_bytes)}</dd></div>
    </dl>
  `;
}

function renderFiles() {
  const node = $("fileList");
  if (!selectedFiles.length) {
    node.className = "file-list empty";
    node.textContent = "No files selected.";
    $("fileSummary").textContent = "Local files submitted through DSX-Connect governance.";
    renderDestinationPreview();
    setSubmitEnabled();
    return;
  }
  node.className = "file-list";
  $("fileSummary").textContent =
    selectedFiles.length === 1 ? "1 local file selected." : `${selectedFiles.length} local files selected.`;
  node.innerHTML = selectedFiles
    .map(
      (filePath, index) => `
        <div class="file-row" title="${escapeHtml(filePath)}">
          <span>${index + 1}</span>
          <strong>${escapeHtml(fileNameFromPath(filePath))}</strong>
          <small>${escapeHtml(filePath)}</small>
        </div>
      `
    )
    .join("");
  setSubmitEnabled();
  renderDestinationPreview();
}

async function refreshDestinations() {
  setConnection("Connecting", "checking");
  setStatus("Refreshing destinations", "busy");
  try {
    await persistForm();
    const response = await window.dsxGateway.listDestinations(readForm());
    destinations = response.destinations || [];
    renderDestinations();
    setConnection("Connected", "ok");
    setStatus(`${destinations.length} destinations available`, "ok");
  } catch (error) {
    destinations = [];
    renderDestinations();
    setConnection("Unavailable", "error");
    setStatus(error?.message || "Could not load destinations", "error");
  }
}

async function pickFiles() {
  const files = await window.dsxGateway.pickFiles();
  if (!files.length) return;
  selectedFiles = files;
  renderFiles();
  await persistForm();
}

function renderTransferResult(result) {
  activeJobId = result?.job_id || activeJobId;
  $("jobId").textContent = activeJobId || "-";
  $("jobState").textContent = result?.state || result?.job?.job?.state || "-";
  $("jobProgress").textContent = "-";
  $("jobTerminal").textContent = "-";
  $("resultSummary").innerHTML = `
    <strong>Transfer accepted</strong>
    <span>${escapeHtml(result?.submitted_files || 0)} file(s) submitted to DSX-Connect.</span>
  `;
  $("rawResult").textContent = JSON.stringify(result || {}, null, 2);
  $("refreshStatus").disabled = !activeJobId;
}

function renderProgress(progress) {
  $("jobState").textContent = progress?.state || "-";
  $("jobProgress").textContent =
    progress?.percent_complete == null ? "-" : `${Math.round(Number(progress.percent_complete))}%`;
  $("jobTerminal").textContent = `${progress?.terminal_items || 0} / ${progress?.total_items || 0}`;
  $("resultSummary").innerHTML = `
    <strong>${escapeHtml(progress?.state || "unknown")}</strong>
    <span>${escapeHtml(progress?.terminal_items || 0)} of ${escapeHtml(progress?.total_items || 0)} item(s) terminal.</span>
  `;
  $("rawResult").textContent = JSON.stringify(progress || {}, null, 2);
}

function schedulePoll() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(() => {
    if (activeJobId) refreshStatus({ quiet: true });
  }, 5000);
}

async function submitTransfer() {
  const button = $("submitTransfer");
  button.disabled = true;
  setStatus("Submitting files to DSX-Connect", "busy");
  try {
    await persistForm();
    const result = await window.dsxGateway.submitTransfer(readForm());
    renderTransferResult(result);
    setStatus("Transfer accepted by DSX-Connect", "ok");
    await refreshStatus({ quiet: true });
    schedulePoll();
  } catch (error) {
    setStatus(error?.message || "Transfer failed", "error");
  } finally {
    button.disabled = false;
  }
}

async function refreshStatus(options = {}) {
  if (!activeJobId) return;
  if (!options.quiet) setStatus("Refreshing job status", "busy");
  try {
    const progress = await window.dsxGateway.getTransferStatus({
      dsxConnectUrl: $("dsxConnectUrl").value.trim(),
      gatewayToken: $("gatewayToken").value.trim(),
      jobId: activeJobId
    });
    renderProgress(progress);
    const terminal = ["completed", "failed", "cancelled"].includes(progress?.state);
    if (terminal && pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
    if (!options.quiet) setStatus("Job status refreshed", "ok");
  } catch (error) {
    if (!options.quiet) setStatus(error?.message || "Could not refresh job", "error");
  }
}

async function init() {
  settings = await window.dsxGateway.loadSettings();
  $("dsxConnectUrl").value = settings.dsxConnectUrl || "";
  $("gatewayToken").value = settings.gatewayToken || "";
  $("destinationPath").value = settings.destinationPath || "";
  selectedFiles = Array.isArray(settings.selectedFiles) ? settings.selectedFiles : [];
  renderFiles();
  $("settingsToggle").addEventListener("click", () => {
    setSettingsExpanded(!$("settingsPanel").classList.contains("open"));
  });
  $("settingsClose").addEventListener("click", () => setSettingsExpanded(false));
  $("settingsBackdrop").addEventListener("click", () => setSettingsExpanded(false));
  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape") setSettingsExpanded(false);
  });
  $("refreshDestinations").addEventListener("click", refreshDestinations);
  $("destinationId").addEventListener("change", () => {
    renderDestinationDetail();
    renderDestinationPreview();
    setSubmitEnabled();
    persistForm();
  });
  $("destinationPath").addEventListener("input", () => {
    renderDestinationPreview();
    setSubmitEnabled();
  });
  $("destinationPath").addEventListener("blur", persistForm);
  $("dsxConnectUrl").addEventListener("blur", persistForm);
  $("gatewayToken").addEventListener("blur", persistForm);
  $("pickFiles").addEventListener("click", pickFiles);
  $("submitTransfer").addEventListener("click", submitTransfer);
  $("refreshStatus").addEventListener("click", () => refreshStatus());
  await refreshDestinations();
}

init().catch((error) => {
  setConnection("Unavailable", "error");
  setStatus(error?.message || "Initialization failed", "error");
});
