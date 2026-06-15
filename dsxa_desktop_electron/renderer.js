const state = {
  selectedProfile: "default",
  profiles: {},
  activeTab: "scanFilePane",
  themeMode: "auto",
  activeFolderJobId: null,
  folderScanStartedAt: 0,
  folderVerdictStats: {
    benign: 0,
    malicious: 0,
    failed: 0,
    encrypted: 0,
    other: 0
  }
};

const THEME_STORAGE_KEY = "dsxa-desktop-electron.theme-mode";
let systemThemeMediaQuery = null;

const TAB_COPY = {
  scanFilePane: {
    title: "Scan File",
    description: "Run DSXA file scans through the Electron main process using `@deep-instinct/dsxa-sdk-js`."
  },
  scanFolderPane: {
    title: "Scan Folder",
    description: "Batch a folder scan with configurable concurrency and review the aggregate summary in one place."
  },
  scanHashPane: {
    title: "Scan Hash",
    description: "Send a known hash for lookup when you want a verdict without uploading file content."
  }
};

function el(id) {
  return document.getElementById(id);
}

function systemPrefersDark() {
  return !!systemThemeMediaQuery?.matches;
}

function effectiveTheme() {
  if (state.themeMode === "dark") return "dark";
  if (state.themeMode === "light") return "light";
  return systemPrefersDark() ? "dark" : "light";
}

function updateThemeHint() {
  const hint = el("themeHint");
  if (!hint) return;
  if (state.themeMode === "auto") {
    hint.textContent = `Following system appearance (${effectiveTheme()}).`;
    return;
  }
  hint.textContent = `Using manual ${state.themeMode} mode.`;
}

function applyTheme() {
  document.documentElement.setAttribute("data-theme", effectiveTheme());
  const modeSelect = el("themeMode");
  if (modeSelect) {
    modeSelect.value = state.themeMode;
  }
  updateThemeHint();
}

function loadThemeMode() {
  const saved = window.localStorage.getItem(THEME_STORAGE_KEY);
  if (saved === "light" || saved === "dark" || saved === "auto") {
    state.themeMode = saved;
  } else {
    state.themeMode = "auto";
  }
}

function saveThemeMode() {
  window.localStorage.setItem(THEME_STORAGE_KEY, state.themeMode);
}

function setStatus(text) {
  el("status").textContent = text;
}

function setFolderProgress(scanned, total, labelPrefix = "Progress") {
  const progress = el("folderProgress");
  const label = el("folderProgressLabel");
  const max = Number(total || 0);
  const done = Number(scanned || 0);
  progress.max = max > 0 ? max : 1;
  progress.value = max > 0 ? Math.min(done, max) : 0;

  const percent = max > 0 ? Math.round((done / max) * 100) : 0;
  let rate = 0;
  if (state.folderScanStartedAt > 0) {
    const elapsedSeconds = Math.max((Date.now() - state.folderScanStartedAt) / 1000, 0.001);
    rate = done / elapsedSeconds;
  }
  label.textContent = `${labelPrefix}: ${done}/${max || 0} (${percent}%) • ${rate.toFixed(1)} files/sec`;
}

function setFolderProgressVisible(visible) {
  el("folderProgressPlaceholder").hidden = !!visible;
  el("folderProgressLabel").hidden = !visible;
  el("folderStats").hidden = !visible;
  el("folderProgress").hidden = !visible;
}

function updateFolderStats() {
  el("folderStats").innerHTML =
    `Benign: ${state.folderVerdictStats.benign}&nbsp;&nbsp;` +
    `<span style="color:#b4432f">Malicious: ${state.folderVerdictStats.malicious}</span>&nbsp;&nbsp;` +
    `Failed: ${state.folderVerdictStats.failed}&nbsp;&nbsp;` +
    `Encrypted: ${state.folderVerdictStats.encrypted}&nbsp;&nbsp;` +
    `Other: ${state.folderVerdictStats.other}`;
}

function resetFolderStats() {
  state.folderVerdictStats = {
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
  state.folderVerdictStats = {
    benign: Number(stats.benign || 0),
    malicious: Number(stats.malicious || 0),
    failed: Number(stats.failed || 0),
    encrypted: Number(stats.encrypted || 0),
    other: Number(stats.other || 0)
  };
  updateFolderStats();
}

function setFolderControlsRunning(running, complete = false) {
  const scanFolderBtn = el("scanFolder");
  const progressBar = el("folderProgress");
  scanFolderBtn.disabled = !!running;
  scanFolderBtn.textContent = running ? "Scanning..." : "Run Folder Scan";
  scanFolderBtn.classList.toggle("is-running", !!running);
  if (progressBar) {
    progressBar.classList.toggle("scanning", !!running);
    progressBar.classList.toggle("complete", !running && !!complete);
  }
}

function renderFolderSummaryOutput(summary) {
  const stats = summary?.stats || {};
  setOutput("Scan Folder Result", [
    `Folder: ${summary?.folder || ""}`,
    `Concurrency: ${summary?.concurrency || 0}`,
    `Elapsed: ${Number(summary?.elapsed_seconds || 0).toFixed(2)}s`,
    `DSXA Scan Time (sum): ${Number(summary?.scan_time_total_seconds || 0).toFixed(2)}s`,
    `Scanned: ${summary?.scanned ?? 0}`,
    `OK: ${summary?.ok ?? 0}`,
    `Failed: ${summary?.failed ?? 0}`,
    `Benign: ${stats.benign ?? 0}   Malicious: ${stats.malicious ?? 0}   Encrypted: ${stats.encrypted ?? 0}   Other: ${stats.other ?? 0}`,
    "",
    JSON.stringify(summary || {}, null, 2)
  ]);
}

function handleFolderProgress(payload) {
  if (!payload || !payload.jobId) return;
  if (!state.activeFolderJobId || payload.jobId !== state.activeFolderJobId) return;

  if (payload.type === "start" || payload.type === "progress") {
    updateFolderStatsFromPayload(payload.stats);
    const scanned = Number(payload.scanned || 0);
    const total = Number(payload.total || 0);
    const percent = total > 0 ? Math.round((scanned / total) * 100) : 0;
    let rate = 0;
    if (state.folderScanStartedAt > 0) {
      const elapsedSeconds = Math.max((Date.now() - state.folderScanStartedAt) / 1000, 0.001);
      rate = scanned / elapsedSeconds;
    }
    setFolderProgress(scanned, total, payload.type === "start" ? "Starting" : "Scanning");
    setFolderProgressVisible(true);
    setStatus(`Scanning folder... ${scanned}/${total} (${percent}%) • ${rate.toFixed(1)} files/sec`);
    return;
  }

  if (payload.type === "done") {
    updateFolderStatsFromPayload(payload.stats || payload.summary?.stats);
    if (payload.summary) {
      renderFolderSummaryOutput(payload.summary);
    }
    setFolderProgress(payload.scanned || 0, payload.total || payload.scanned || 0, "Complete");
    setFolderProgressVisible(true);
    setStatus("Folder scan complete");
    state.activeFolderJobId = null;
    state.folderScanStartedAt = 0;
    setFolderControlsRunning(false, true);
    return;
  }

  if (payload.type === "error") {
    setOutput("Scan Folder Error", [parseErrorMessage(payload.error || "Unknown error")]);
    setFolderProgress(0, 0, "Progress");
    setFolderProgressVisible(true);
    resetFolderStats();
    setStatus("Folder scan failed");
    state.activeFolderJobId = null;
    state.folderScanStartedAt = 0;
    setFolderControlsRunning(false, false);
  }
}

function activateTab(tabId) {
  state.activeTab = tabId;
  document.querySelectorAll(".scan-tab").forEach((button) => {
    const active = button.dataset.tab === tabId;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
  });
  document.querySelectorAll(".scan-pane").forEach((pane) => {
    const active = pane.id === tabId;
    pane.classList.toggle("active", active);
    pane.hidden = !active;
  });

  const copy = TAB_COPY[tabId];
  if (copy) {
    el("scanContextTitle").textContent = copy.title;
    el("scanContextDescription").textContent = copy.description;
  }
}

function currentProfile() {
  const protectedEntity = Number.parseInt(el("protectedEntity").value || "1", 10);
  const timeoutMs = Number.parseInt(el("timeoutMs").value || "30000", 10);
  return {
    baseUrl: el("baseUrl").value.trim(),
    authToken: el("authToken").value,
    protectedEntity: Number.isFinite(protectedEntity) ? protectedEntity : 1,
    timeoutMs: Number.isFinite(timeoutMs) ? timeoutMs : 30000,
    customMetadata: el("customMetadata").value || "",
    verifyTls: false
  };
}

function applyProfile(name) {
  const profile = state.profiles[name];
  if (!profile) return;
  state.selectedProfile = name;
  el("profileSelect").value = name;
  el("baseUrl").value = profile.baseUrl || "";
  el("authToken").value = profile.authToken || "";
  el("protectedEntity").value = String(profile.protectedEntity ?? 1);
  el("timeoutMs").value = String(profile.timeoutMs ?? 30000);
  el("customMetadata").value = profile.customMetadata || "";
}

function renderProfileSelect() {
  const select = el("profileSelect");
  const names = Object.keys(state.profiles).sort();
  select.innerHTML = names.map((name) => `<option value="${name}">${name}</option>`).join("");
  if (!state.profiles[state.selectedProfile] && names.length) {
    state.selectedProfile = names[0];
  }
  applyProfile(state.selectedProfile);
}

function setOutput(title, lines) {
  el("output").value = `${title}\n${lines.join("\n")}\n`;
}

function selectedFilePath() {
  return el("filePath").dataset.path || "";
}

function selectedFolderPath() {
  return el("folderPath").dataset.path || "";
}

function createJobId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `job-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

async function loadProfiles() {
  const saved = await window.dsxaDesktop.loadProfiles();
  state.selectedProfile = saved.selectedProfile || "default";
  state.profiles = saved.profiles || {};
  if (!Object.keys(state.profiles).length) {
    state.profiles.default = {
      baseUrl: "http://127.0.0.1:5000",
      authToken: "",
      protectedEntity: 1,
      timeoutMs: 30000,
      customMetadata: ""
    };
  }
  renderProfileSelect();
}

async function saveProfiles() {
  state.profiles[state.selectedProfile] = currentProfile();
  const saved = await window.dsxaDesktop.saveProfiles({
    selectedProfile: state.selectedProfile,
    profiles: state.profiles
  });
  state.selectedProfile = saved.selectedProfile;
  state.profiles = saved.profiles;
  renderProfileSelect();
}

function parseErrorMessage(error) {
  const text = String(error?.message || error || "");
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    return text;
  }
}

window.addEventListener("DOMContentLoaded", async () => {
  systemThemeMediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
  loadThemeMode();
  applyTheme();
  if (typeof systemThemeMediaQuery.addEventListener === "function") {
    systemThemeMediaQuery.addEventListener("change", () => {
      if (state.themeMode === "auto") {
        applyTheme();
      }
    });
  } else if (typeof systemThemeMediaQuery.addListener === "function") {
    systemThemeMediaQuery.addListener(() => {
      if (state.themeMode === "auto") {
        applyTheme();
      }
    });
  }

  await loadProfiles();
  const removeFolderProgressListener = window.dsxaDesktop.onFolderProgress(handleFolderProgress);
  window.addEventListener("beforeunload", () => {
    removeFolderProgressListener();
  });

  document.querySelectorAll(".scan-tab").forEach((button) => {
    button.addEventListener("click", () => {
      activateTab(button.dataset.tab);
    });
  });
  activateTab(state.activeTab);
  setFolderControlsRunning(false, false);
  setFolderProgressVisible(false);
  setFolderProgress(0, 0, "Progress");
  resetFolderStats();

  el("profileSelect").addEventListener("change", (event) => {
    applyProfile(event.target.value);
  });

  el("saveProfile").addEventListener("click", async () => {
    await saveProfiles();
    setStatus("Profile saved");
  });

  el("themeMode").addEventListener("change", (event) => {
    state.themeMode = event.target.value || "auto";
    saveThemeMode();
    applyTheme();
    setStatus(`Theme set to ${state.themeMode}`);
  });

  el("pickFile").addEventListener("click", async () => {
    activateTab("scanFilePane");
    const filePath = await window.dsxaDesktop.pickFile();
    if (!filePath) return;
    el("filePath").dataset.path = filePath;
    el("filePath").textContent = filePath;
    setStatus("File selected");
  });

  el("pickFolder").addEventListener("click", async () => {
    activateTab("scanFolderPane");
    const folderPath = await window.dsxaDesktop.pickFolder();
    if (!folderPath) return;
    el("folderPath").dataset.path = folderPath;
    el("folderPath").textContent = folderPath;
    setStatus("Folder selected");
  });

  el("scanFile").addEventListener("click", async () => {
    activateTab("scanFilePane");
    const filePath = selectedFilePath();
    if (!filePath) {
      setStatus("Pick a file first");
      return;
    }

    setStatus("Scanning file...");
    state.profiles[state.selectedProfile] = currentProfile();

    try {
      const result = await window.dsxaDesktop.scanFile({
        filePath,
        profile: state.profiles[state.selectedProfile],
        password: el("filePassword").value || "",
        metadata: el("fileMetadata").value || ""
      });
      setOutput("Scan File Result", [
        `File: ${result.file || ""}`,
        `Curl: ${result.curlCommand || ""}`,
        `Elapsed: ${Number(result.elapsedSeconds || 0).toFixed(2)}s`,
        "",
        JSON.stringify(result.result || {}, null, 2)
      ]);
      setStatus("Scan complete");
    } catch (error) {
      setOutput("Scan File Error", [parseErrorMessage(error)]);
      setStatus("Scan failed");
    }
  });

  el("scanFolder").addEventListener("click", async () => {
    activateTab("scanFolderPane");
    const folderPath = selectedFolderPath();
    if (!folderPath) {
      setStatus("Pick a folder first");
      return;
    }
    if (state.activeFolderJobId) {
      setStatus("Folder scan already running");
      return;
    }

    setStatus("Scanning folder...");
    state.profiles[state.selectedProfile] = currentProfile();
    state.activeFolderJobId = createJobId();
    state.folderScanStartedAt = Date.now();
    setFolderControlsRunning(true, false);
    setFolderProgressVisible(true);
    setFolderProgress(0, 0, "Starting");
    resetFolderStats();

    try {
      const result = await window.dsxaDesktop.scanFolder({
        jobId: state.activeFolderJobId,
        folderPath,
        profile: state.profiles[state.selectedProfile],
        concurrency: el("folderConcurrency").value || "4",
        password: el("folderPassword").value || "",
        metadata: el("folderMetadata").value || ""
      });
      if (!state.activeFolderJobId && result.summary) {
        renderFolderSummaryOutput(result.summary);
        setFolderControlsRunning(false, true);
        setStatus("Folder scan complete");
        state.folderScanStartedAt = 0;
      }
    } catch (error) {
      state.activeFolderJobId = null;
      state.folderScanStartedAt = 0;
      setFolderControlsRunning(false, false);
      setOutput("Scan Folder Error", [parseErrorMessage(error)]);
      setStatus("Folder scan failed");
    }
  });

  el("scanHash").addEventListener("click", async () => {
    activateTab("scanHashPane");
    const hashValue = (el("hashValue").value || "").trim();
    if (!hashValue) {
      setStatus("Provide a hash first");
      return;
    }

    setStatus("Scanning hash...");
    state.profiles[state.selectedProfile] = currentProfile();

    try {
      const result = await window.dsxaDesktop.scanHash({
        hashValue,
        profile: state.profiles[state.selectedProfile],
        metadata: el("hashMetadata").value || ""
      });
      setOutput("Scan Hash Result", [
        `Hash: ${result.hash || ""}`,
        `Elapsed: ${Number(result.elapsedSeconds || 0).toFixed(2)}s`,
        "",
        JSON.stringify(result.result || {}, null, 2)
      ]);
      setStatus("Hash scan complete");
    } catch (error) {
      setOutput("Scan Hash Error", [parseErrorMessage(error)]);
      setStatus("Hash scan failed");
    }
  });
});
