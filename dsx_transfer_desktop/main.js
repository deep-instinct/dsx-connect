const { app, BrowserWindow, dialog, ipcMain, Menu, shell } = require("electron");
const fs = require("node:fs/promises");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const crypto = require("node:crypto");
const { runGuardedTransfer } = require("./transfer_runner");

const APP_NAME = "DSX-Transfer Desktop";
const SETTINGS_FILE = "settings.json";
const APP_ICON_PATH = path.join(__dirname, "build", "icons", "icon.png");
let lastRunArtifacts = null;
let mainWindow = null;

function createMainWindow() {
  const indexUrl = pathToFileURL(path.join(__dirname, "index.html")).toString();
  mainWindow = new BrowserWindow({
    width: 1180,
    height: 740,
    minWidth: 960,
    minHeight: 600,
    title: APP_NAME,
    icon: APP_ICON_PATH,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    }
  });

  mainWindow.on("closed", () => {
    mainWindow = null;
  });

  mainWindow.webContents.on("did-fail-load", (_event, errorCode, errorDescription, validatedUrl, isMainFrame) => {
    if (!isMainFrame) return;
    const detail = escapeHtml(
      [
        `Failed to load DSX-Transfer Desktop UI.`,
        `URL: ${validatedUrl || indexUrl}`,
        `Error ${errorCode}: ${errorDescription}`,
        `App path: ${__dirname}`
      ].join("\n")
    );
    mainWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(`<pre>${detail}</pre>`)}`);
  });

  return mainWindow.loadURL(indexUrl);
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function userDataPath(...parts) {
  return path.join(app.getPath("userData"), ...parts);
}

function settingsPath() {
  return userDataPath(SETTINGS_FILE);
}

function defaultSettings() {
  return {
    scannerMode: "dsxa",
    defaultVerdict: "benign",
    detectEicarTestFile: false,
    dsxaBaseUrl: "http://127.0.0.1:5000",
    dsxaAuthToken: "",
    dsxaProtectedEntity: 1,
    dsxaVerifyTls: false,
    verdictActions: {
      benign: "allow",
      malicious: "block",
      suspicious: "block",
      unknown: "block",
      error: "block"
    },
    fileTypeBlocks: {
      windowsExecutables: true
    },
    transferConcurrency: 4,
    themeMode: "auto",
    sourcePath: "",
    destinationPath: ""
  };
}

async function readRawSettings() {
  try {
    const raw = await fs.readFile(settingsPath(), "utf8");
    return JSON.parse(raw);
  } catch {
    return {};
  }
}

async function readSettings() {
  return { ...defaultSettings(), ...(await readRawSettings()) };
}

async function writeSettings(settings) {
  const target = settingsPath();
  await fs.mkdir(path.dirname(target), { recursive: true });
  const merged = { ...defaultSettings(), ...(await readRawSettings()), ...(settings || {}), scannerMode: "dsxa" };
  await fs.writeFile(target, JSON.stringify(merged, null, 2), "utf8");
  await rebuildApplicationMenu();
  return merged;
}

function transferRunDir() {
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  return userDataPath("runs", `${stamp}-${crypto.randomUUID().slice(0, 8)}`);
}

function yamlString(value) {
  return JSON.stringify(String(value ?? ""));
}

function yamlBool(value) {
  return value ? "true" : "false";
}

function buildTransferConfig(request, paths) {
  const settings = { ...defaultSettings(), ...(request || {}), scannerMode: "dsxa" };
  const verdictActions = { ...defaultSettings().verdictActions, ...(settings.verdictActions || {}) };
  const lines = [
    "version: 1",
    "",
    "transfer:",
    `  id: ${yamlString(paths.transferId)}`,
    `  policy_id: ${yamlString("desktop-default")}`,
    "",
    "source:",
    "  kind: filesystem",
    `  path: ${yamlString(settings.sourcePath)}`,
    "",
    "destination:",
    "  kind: filesystem",
    `  uri: ${yamlString(settings.destinationPath)}`,
    "",
    "scanner:",
    `  mode: ${yamlString("dsxa")}`,
    `  default_verdict: ${yamlString(settings.defaultVerdict || "benign")}`,
    `  detect_eicar_test_file: ${yamlBool(Boolean(settings.detectEicarTestFile))}`
  ];

  lines.push("  dsxa:");
  lines.push(`    base_url: ${yamlString(settings.dsxaBaseUrl)}`);
  if (settings.dsxaAuthToken) {
    lines.push(`    auth_token: ${yamlString(settings.dsxaAuthToken)}`);
  }
  if (settings.dsxaProtectedEntity !== "" && settings.dsxaProtectedEntity != null) {
    lines.push(`    protected_entity: ${Number.parseInt(String(settings.dsxaProtectedEntity), 10) || 1}`);
  }
  lines.push(`    verify_tls: ${yamlBool(Boolean(settings.dsxaVerifyTls))}`);

  lines.push("");
  lines.push("policy:");
  lines.push("  verdict_actions:");
  for (const verdict of ["benign", "malicious", "suspicious", "unknown", "error"]) {
    lines.push(`    ${verdict}: ${yamlString(verdictActions[verdict] || "block")}`);
  }
  lines.push("  file_type_blocks:");
  lines.push(`    windows_executables: ${yamlBool(Boolean(settings.fileTypeBlocks?.windowsExecutables))}`);
  lines.push("");
  lines.push("runtime:");
  lines.push(`  audit_jsonl: ${yamlString(paths.auditPath)}`);
  lines.push(`  checkpoint: ${yamlString(paths.checkpointPath)}`);
  lines.push(`  concurrency: ${Math.max(1, Number.parseInt(String(settings.transferConcurrency || 4), 10) || 4)}`);
  lines.push("");
  return lines.join("\n");
}

async function assertDirectory(targetPath, label) {
  const normalized = String(targetPath || "").trim();
  if (!normalized) {
    throw new Error(`${label} is required.`);
  }
  let stat;
  try {
    stat = await fs.stat(normalized);
  } catch (error) {
    if (label === "Destination folder") {
      await fs.mkdir(normalized, { recursive: true });
      return path.resolve(normalized);
    }
    throw new Error(`${label} does not exist: ${normalized}`);
  }
  if (!stat.isDirectory()) {
    throw new Error(`${label} is not a directory: ${normalized}`);
  }
  return path.resolve(normalized);
}

function parseJsonReport(stdout) {
  const trimmed = String(stdout || "").trim();
  if (!trimmed) return null;
  try {
    return JSON.parse(trimmed);
  } catch {
    const lines = trimmed.split(/\r?\n/).map((line) => line.trim()).filter(Boolean).reverse();
    for (const line of lines) {
      try {
        return JSON.parse(line);
      } catch {
        // Keep looking for the final JSON payload.
      }
    }
  }
  return null;
}

function reportSummary(report) {
  if (!report) {
    return {
      planned: 0,
      allowed: 0,
      blocked: 0,
      failed: 0,
      skipped: 0,
      excluded: 0
    };
  }
  return {
    planned: Number(report.planned_count || report.outcomes?.length || 0),
    allowed: Number(report.allowed_count || 0),
    blocked: Number(report.blocked_count || 0),
    failed: Number(report.failed_count || 0),
    skipped: Number(report.skipped_count || 0),
    excluded: Number(report.excluded_count || 0)
  };
}

function emitTransferProgress(sender, payload) {
  if (!sender || sender.isDestroyed?.()) return;
  sender.send("dsx-transfer-desktop:transfer-progress", payload);
}

async function runTransfer(request, sender) {
  const persisted = await readSettings();
  const effectiveRequest = { ...persisted, ...(request || {}), transferConcurrency: persisted.transferConcurrency || 4 };
  const sourcePath = await assertDirectory(effectiveRequest.sourcePath, "Source folder");
  const destinationPath = await assertDirectory(effectiveRequest.destinationPath, "Destination folder");
  if (sourcePath === destinationPath) {
    throw new Error("Source and destination must be different folders.");
  }
  if (!String(effectiveRequest.dsxaBaseUrl || "").trim()) {
    throw new Error("DSXA scanner URL is required when scanner mode is DSXA.");
  }

  const runDir = transferRunDir();
  await fs.mkdir(runDir, { recursive: true });

  const paths = {
    transferId: `desktop-${crypto.randomUUID()}`,
    configPath: path.join(runDir, "dsx-transfer.yaml"),
    auditPath: path.join(runDir, "audit.jsonl"),
    checkpointPath: path.join(runDir, "checkpoint.json"),
    runLogPath: path.join(runDir, "run.log")
  };
  const config = buildTransferConfig({ ...effectiveRequest, sourcePath, destinationPath }, paths);
  await fs.writeFile(paths.configPath, config, "utf8");

  const started = Date.now();
  await fs.writeFile(
    paths.runLogPath,
    [
      `started_at=${new Date(started).toISOString()}`,
      `run_dir=${runDir}`,
      `runner=node`,
      `app_path=${__dirname}`,
      `config=${paths.configPath}`,
      `audit=${paths.auditPath}`,
      `checkpoint=${paths.checkpointPath}`,
      "",
      "stderr:",
      ""
    ].join("\n"),
    "utf8"
  );

  let stdout = "";
  let stderr = "";
  let code = 0;
  let report = null;
  try {
    report = await runGuardedTransfer({
      settings: { ...effectiveRequest, sourcePath, destinationPath },
      paths,
      onProgress: (event) => emitTransferProgress(sender, event)
    });
    stdout = JSON.stringify(report, null, 2);
  } catch (error) {
    code = 1;
    stderr = `${error?.stack || error?.message || String(error)}\n`;
  }
  const completed = Date.now();
  await fs.appendFile(
    paths.runLogPath,
    [
      stderr,
      "",
      "stdout:",
      stdout,
      "",
      `exit_code=${code}`,
      `elapsed_seconds=${((completed - started) / 1000).toFixed(3)}`,
      `completed_at=${new Date(completed).toISOString()}`,
      ""
    ].join("\n"),
    "utf8"
  );
  const result = {
    ok: code === 0,
    code,
    commandKind: "node",
    executable: process.execPath,
    configPath: paths.configPath,
    auditPath: paths.auditPath,
    checkpointPath: paths.checkpointPath,
    runLogPath: paths.runLogPath,
    elapsedSeconds: (Date.now() - started) / 1000,
    stdout,
    stderr,
    report,
    summary: reportSummary(report)
  };
  lastRunArtifacts = {
    configPath: result.configPath,
    auditPath: result.auditPath,
    checkpointPath: result.checkpointPath,
    runLogPath: result.runLogPath,
    runDir: path.dirname(result.configPath)
  };
  await rebuildApplicationMenu();
  return result;
}

async function setTransferConcurrency(concurrency) {
  await writeSettings({ transferConcurrency: Math.max(1, Number.parseInt(String(concurrency), 10) || 4) });
}

async function setThemeMode(themeMode) {
  const allowed = new Set(["auto", "light", "operations", "security"]);
  const nextThemeMode = allowed.has(themeMode) ? themeMode : "auto";
  await writeSettings({ themeMode: nextThemeMode });
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send("dsx-transfer-desktop:theme-changed", { themeMode: nextThemeMode });
  }
}

async function pathExists(target) {
  try {
    await fs.access(target);
    return true;
  } catch {
    return false;
  }
}

async function latestRunArtifacts() {
  if (lastRunArtifacts) {
    return lastRunArtifacts;
  }

  const runsDir = userDataPath("runs");
  let entries;
  try {
    entries = await fs.readdir(runsDir, { withFileTypes: true });
  } catch {
    return null;
  }

  const candidates = [];
  for (const entry of entries) {
    if (!entry.isDirectory()) continue;
    const runDir = path.join(runsDir, entry.name);
    try {
      const stat = await fs.stat(runDir);
      candidates.push({ runDir, mtimeMs: stat.mtimeMs });
    } catch {
      // Ignore partially removed run folders.
    }
  }

  candidates.sort((a, b) => b.mtimeMs - a.mtimeMs);
  for (const candidate of candidates) {
    const artifacts = {
      configPath: path.join(candidate.runDir, "dsx-transfer.yaml"),
      auditPath: path.join(candidate.runDir, "audit.jsonl"),
      checkpointPath: path.join(candidate.runDir, "checkpoint.json"),
      runLogPath: path.join(candidate.runDir, "run.log"),
      runDir: candidate.runDir
    };
    if ((await pathExists(artifacts.auditPath)) || (await pathExists(artifacts.runLogPath)) || (await pathExists(artifacts.configPath))) {
      lastRunArtifacts = artifacts;
      return artifacts;
    }
  }

  return null;
}

async function reportOpenFailure(target, message) {
  const detail = message ? `${target}\n\n${message}` : target;
  await dialog.showMessageBox(mainWindow || undefined, {
    type: "error",
    title: "Unable to Open Artifact",
    message: "DSX-Transfer Desktop could not open the selected artifact.",
    detail
  });
}

async function openArtifact(kind) {
  const artifacts = await latestRunArtifacts();
  const target = artifacts?.[kind];
  if (!target) {
    await reportOpenFailure("No run artifact found.", "Run a transfer first, then try again.");
    return;
  }
  if (!(await pathExists(target))) {
    if (kind === "auditPath" && artifacts?.runLogPath && (await pathExists(artifacts.runLogPath))) {
      const message = await shell.openPath(artifacts.runLogPath);
      if (message) {
        await reportOpenFailure(artifacts.runLogPath, message);
      }
      return;
    }
    await reportOpenFailure(target, "The artifact does not exist on disk.");
    return;
  }
  const message = await shell.openPath(target);
  if (message) {
    await reportOpenFailure(target, message);
  }
}

async function rebuildApplicationMenu() {
  if (!app.isReady()) return;
  const settings = await readSettings();
  const selectedConcurrency = Math.max(1, Number.parseInt(String(settings.transferConcurrency || 4), 10) || 4);
  const selectedTheme = ["auto", "light", "operations", "security"].includes(settings.themeMode) ? settings.themeMode : "auto";
  const hasArtifacts = Boolean(await latestRunArtifacts());
  const template = [
    ...(process.platform === "darwin"
      ? [
          {
            label: APP_NAME,
            submenu: [{ role: "about" }, { type: "separator" }, { role: "hide" }, { role: "hideOthers" }, { role: "quit" }]
          }
        ]
      : []),
    {
      label: "File",
      submenu: [
        { label: "Open Last Audit", enabled: hasArtifacts, click: () => openArtifact("auditPath") },
        { label: "Open Last Run Log", enabled: hasArtifacts, click: () => openArtifact("runLogPath") },
        { label: "Open Last Config", enabled: hasArtifacts, click: () => openArtifact("configPath") },
        { label: "Reveal Last Run Folder", enabled: hasArtifacts, click: () => openArtifact("runDir") },
        { type: "separator" },
        process.platform === "darwin" ? { role: "close" } : { role: "quit" }
      ]
    },
    {
      label: "Settings",
      submenu: [
        {
          label: "Transfer Concurrency",
          submenu: [1, 2, 4, 6, 8, 12, 16].map((value) => ({
            label: String(value),
            type: "radio",
            checked: selectedConcurrency === value,
            click: () => setTransferConcurrency(value)
          }))
        }
      ]
    },
    {
      label: "View",
      submenu: [
        {
          label: "Theme",
          submenu: [
            { label: "Auto", value: "auto" },
            { label: "Light", value: "light" },
            { label: "Operations", value: "operations" },
            { label: "Security Console", value: "security" }
          ].map((item) => ({
            label: item.label,
            type: "radio",
            checked: selectedTheme === item.value,
            click: () => setThemeMode(item.value)
          }))
        },
        { type: "separator" },
        { role: "reload" },
        { role: "toggleDevTools" },
        { type: "separator" },
        { role: "resetZoom" },
        { role: "zoomIn" },
        { role: "zoomOut" }
      ]
    }
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

ipcMain.handle("dsx-transfer-desktop:pick-folder", async (_event, purpose) => {
  const picked = await dialog.showOpenDialog({
    title: purpose === "destination" ? "Select Destination File Share" : "Select Source File Share",
    properties: ["openDirectory", "createDirectory"]
  });
  if (picked.canceled || !picked.filePaths?.length) return null;
  return picked.filePaths[0];
});

ipcMain.handle("dsx-transfer-desktop:load-settings", async () => readSettings());
ipcMain.handle("dsx-transfer-desktop:save-settings", async (_event, settings) => writeSettings(settings));
ipcMain.handle("dsx-transfer-desktop:run-transfer", async (_event, request) => runTransfer(request, _event.sender));
ipcMain.handle("dsx-transfer-desktop:open-path", async (_event, targetPath) => {
  if (!targetPath) return { ok: false, message: "No path provided." };
  const message = await shell.openPath(String(targetPath));
  return { ok: !message, message };
});

app.whenReady().then(async () => {
  await rebuildApplicationMenu();
  await createMainWindow();
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createMainWindow();
  }
});
