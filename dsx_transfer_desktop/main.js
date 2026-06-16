const { app, BrowserWindow, dialog, ipcMain, Menu, shell } = require("electron");
const fs = require("node:fs/promises");
const fsSync = require("node:fs");
const path = require("node:path");
const { spawn } = require("node:child_process");
const crypto = require("node:crypto");

const APP_NAME = "DSX-Transfer Desktop";
const SETTINGS_FILE = "settings.json";
const APP_ICON_PATH = path.join(__dirname, "build", "icons", "icon.png");
let lastRunArtifacts = null;
let mainWindow = null;

function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1180,
    height: 820,
    minWidth: 960,
    minHeight: 680,
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

  return mainWindow.loadFile(path.join(__dirname, "index.html"));
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

function repoRoot() {
  if (app.isPackaged) {
    return process.resourcesPath;
  }
  return path.resolve(__dirname, "..");
}

function pythonCandidates() {
  const root = repoRoot();
  const candidates = [];
  if (process.env.DSX_TRANSFER_DESKTOP_PYTHON) {
    candidates.push(process.env.DSX_TRANSFER_DESKTOP_PYTHON);
  }
  candidates.push(path.join(root, ".venv", "bin", "python"));
  candidates.push(path.join(root, ".venv", "Scripts", "python.exe"));
  candidates.push("python3");
  candidates.push("python");
  return candidates;
}

function commandExists(command) {
  if (path.isAbsolute(command) || command.includes(path.sep)) {
    return fsSync.existsSync(command);
  }
  return true;
}

function resolvePython() {
  const candidate = pythonCandidates().find(commandExists);
  if (!candidate) {
    throw new Error("No Python runtime found. Set DSX_TRANSFER_DESKTOP_PYTHON or run from a repo with .venv.");
  }
  return candidate;
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
    checkpointPath: path.join(runDir, "checkpoint.json")
  };
  const config = buildTransferConfig({ ...effectiveRequest, sourcePath, destinationPath }, paths);
  await fs.writeFile(paths.configPath, config, "utf8");

  const python = resolvePython();
  const root = repoRoot();
  const pythonPathParts = [
    path.join(root, "dsx_transfer"),
    path.join(root, "dsxa_sdk_py"),
    root,
    process.env.PYTHONPATH || ""
  ].filter(Boolean);

  const started = Date.now();
  const child = spawn(python, ["-m", "dsx_transfer.cli", "migrate", "--config", paths.configPath, "--progress-jsonl"], {
    cwd: root,
    env: {
      ...process.env,
      PYTHONPATH: pythonPathParts.join(path.delimiter)
    },
    windowsHide: true
  });

  let stdout = "";
  let stderr = "";
  let progressBuffer = "";
  child.stdout.on("data", (chunk) => {
    stdout += chunk.toString();
  });
  child.stderr.on("data", (chunk) => {
    const text = chunk.toString();
    stderr += text;
    progressBuffer += text;
    const lines = progressBuffer.split(/\r?\n/);
    progressBuffer = lines.pop() || "";
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      try {
        const event = JSON.parse(trimmed);
        if (event?.event === "transfer_progress") {
          emitTransferProgress(sender, event);
        }
      } catch {
        // Non-JSON stderr is retained for diagnostics but ignored by the progress UI.
      }
    }
  });

  const code = await new Promise((resolve, reject) => {
    child.on("error", reject);
    child.on("close", resolve);
  });

  const report = parseJsonReport(stdout);
  const result = {
    ok: code === 0,
    code,
    python,
    configPath: paths.configPath,
    auditPath: paths.auditPath,
    checkpointPath: paths.checkpointPath,
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

async function openArtifact(kind) {
  if (!lastRunArtifacts) return;
  const target = lastRunArtifacts[kind];
  if (target) {
    await shell.openPath(target);
  }
}

async function rebuildApplicationMenu() {
  if (!app.isReady()) return;
  const settings = await readSettings();
  const selectedConcurrency = Math.max(1, Number.parseInt(String(settings.transferConcurrency || 4), 10) || 4);
  const selectedTheme = ["auto", "light", "operations", "security"].includes(settings.themeMode) ? settings.themeMode : "auto";
  const hasArtifacts = Boolean(lastRunArtifacts);
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
