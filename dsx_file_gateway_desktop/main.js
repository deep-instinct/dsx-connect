const { app, BrowserWindow, dialog, ipcMain, Menu } = require("electron");
const fs = require("node:fs/promises");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

const APP_NAME = "DSX File Gateway";
const SETTINGS_FILE = "settings.json";
let mainWindow = null;

function defaultSettings() {
  return {
    dsxConnectUrl: "http://dsx-connect.10.2.4.103.nip.io/api/v1",
    gatewayToken: "",
    uploadMode: "destination",
    destinationId: "",
    destinationPath: "",
    selectedFiles: [],
    metadata: {
      application: "desktop-mvp"
    }
  };
}

function settingsPath() {
  return path.join(app.getPath("userData"), SETTINGS_FILE);
}

async function readRawSettings() {
  try {
    return JSON.parse(await fs.readFile(settingsPath(), "utf8"));
  } catch {
    return {};
  }
}

async function loadSettings() {
  return { ...defaultSettings(), ...(await readRawSettings()) };
}

async function saveSettings(settings) {
  const merged = { ...defaultSettings(), ...(await readRawSettings()), ...(settings || {}) };
  await fs.mkdir(path.dirname(settingsPath()), { recursive: true });
  await fs.writeFile(settingsPath(), JSON.stringify(merged, null, 2), "utf8");
  return merged;
}

function normalizeApiBaseUrl(value) {
  const trimmed = String(value || "").trim().replace(/\/+$/, "");
  if (!trimmed) {
    throw new Error("DSX-Connect URL is required.");
  }
  return trimmed.endsWith("/api/v1") ? trimmed : `${trimmed}/api/v1`;
}

async function pickFiles() {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: "Choose files to submit",
    properties: ["openFile", "multiSelections"]
  });
  return result.canceled ? [] : result.filePaths;
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const text = await response.text();
  let body = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = { message: text };
    }
  }
  if (!response.ok) {
    const detail = body?.detail || body?.message || response.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return body;
}

function gatewayHeaders(settings = {}) {
  const token = String(settings?.gatewayToken || "").trim();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function listDestinations(settings) {
  const baseUrl = normalizeApiBaseUrl(settings?.dsxConnectUrl || (await loadSettings()).dsxConnectUrl);
  return fetchJson(`${baseUrl}/files/destinations`, {
    headers: gatewayHeaders(settings)
  });
}

async function getTransferStatus(request) {
  const baseUrl = normalizeApiBaseUrl(request?.dsxConnectUrl);
  const jobId = String(request?.jobId || "").trim();
  if (!jobId) {
    throw new Error("jobId is required.");
  }
  return fetchJson(`${baseUrl}/execution/jobs/${encodeURIComponent(jobId)}/progress?item_limit=25`, {
    headers: gatewayHeaders(request)
  });
}

async function getDsxaItems(request) {
  const baseUrl = normalizeApiBaseUrl(request?.dsxConnectUrl);
  const jobId = String(request?.jobId || "").trim();
  if (!jobId) {
    throw new Error("jobId is required.");
  }
  return fetchJson(`${baseUrl}/execution/jobs/${encodeURIComponent(jobId)}/items/dsxa?limit=100`, {
    headers: gatewayHeaders(request)
  });
}

async function submitTransfer(request) {
  const baseUrl = normalizeApiBaseUrl(request?.dsxConnectUrl);
  const uploadMode = request?.uploadMode === "scan_only" ? "scan_only" : "destination";
  const destinationId = String(request?.destinationId || "").trim();
  const selectedFiles = Array.isArray(request?.selectedFiles) ? request.selectedFiles : [];
  if (uploadMode === "destination" && !destinationId) {
    throw new Error("Choose a destination.");
  }
  if (!selectedFiles.length) {
    throw new Error("Choose one or more files.");
  }

  const form = new FormData();
  if (uploadMode === "destination") {
    form.set("destination_id", destinationId);
    form.set("destination_path", String(request?.destinationPath || ""));
  }
  form.set("metadata", JSON.stringify(request?.metadata || {}));
  for (const filePath of selectedFiles) {
    const data = await fs.readFile(filePath);
    const blob = new Blob([data]);
    form.append("files", blob, path.basename(filePath));
  }

  return fetchJson(`${baseUrl}/files/transfers`, {
    method: "POST",
    headers: gatewayHeaders(request),
    body: form
  });
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1080,
    height: 920,
    minWidth: 880,
    minHeight: 760,
    title: APP_NAME,
    titleBarStyle: process.platform === "darwin" ? "hiddenInset" : "default",
    backgroundColor: "#0b121d",
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
  mainWindow.loadURL(pathToFileURL(path.join(__dirname, "index.html")).toString());
}

app.whenReady().then(async () => {
  Menu.setApplicationMenu(null);
  ipcMain.handle("gateway:load-settings", () => loadSettings());
  ipcMain.handle("gateway:save-settings", (_event, settings) => saveSettings(settings));
  ipcMain.handle("gateway:pick-files", () => pickFiles());
  ipcMain.handle("gateway:list-destinations", (_event, settings) => listDestinations(settings));
  ipcMain.handle("gateway:submit-transfer", (_event, request) => submitTransfer(request));
  ipcMain.handle("gateway:get-transfer-status", (_event, request) => getTransferStatus(request));
  ipcMain.handle("gateway:get-dsxa-items", (_event, request) => getDsxaItems(request));
  createWindow();
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});
