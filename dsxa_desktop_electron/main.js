const { app, BrowserWindow, dialog, ipcMain } = require("electron");
const fs = require("node:fs/promises");
const path = require("node:path");
const crypto = require("node:crypto");

const APP_NAME = "DSXA Desktop";
const PROFILES_FILE = "profiles.json";
const FOLDER_PROGRESS_CHANNEL = "dsxa-desktop:folder-progress";

function defaultProfilesState() {
  return {
    selectedProfile: "default",
    profiles: {
      default: {
        baseUrl: "http://127.0.0.1:5000",
        authToken: "",
        protectedEntity: 1,
        verifyTls: false,
        timeoutMs: 30000,
        customMetadata: ""
      }
    }
  };
}

function profilesPath() {
  return path.join(app.getPath("userData"), PROFILES_FILE);
}

async function readProfiles() {
  try {
    const raw = await fs.readFile(profilesPath(), "utf8");
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return defaultProfilesState();
    if (!parsed.profiles || typeof parsed.profiles !== "object") return defaultProfilesState();
    return {
      selectedProfile: String(parsed.selectedProfile || "default"),
      profiles: parsed.profiles
    };
  } catch {
    return defaultProfilesState();
  }
}

async function writeProfiles(state) {
  const target = profilesPath();
  await fs.mkdir(path.dirname(target), { recursive: true });
  await fs.writeFile(target, JSON.stringify(state, null, 2), "utf8");
  return state;
}

async function loadSdkNodeModule() {
  return import("@deep-instinct/dsxa-sdk-js/node");
}

async function walkFiles(dir, out) {
  const entries = await fs.readdir(dir, { withFileTypes: true });
  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      await walkFiles(fullPath, out);
    } else if (entry.isFile()) {
      out.push(fullPath);
    }
  }
}

function emitFolderProgress(sender, payload) {
  if (!sender || sender.isDestroyed?.()) return;
  sender.send(FOLDER_PROGRESS_CHANNEL, payload);
}

function verdictBucketFromResult(result) {
  const verdict = String(result?.verdict || "").trim().toLowerCase();
  const reason = String(result?.verdictDetails?.reason || "").trim().toLowerCase();
  if (verdict === "benign") return "benign";
  if (verdict === "malicious") return "malicious";
  if (verdict === "failed") return "failed";
  if (verdict === "encrypted" || reason.includes("encrypted")) return "encrypted";
  return "other";
}

function shellQuote(value) {
  if (!value) return "''";
  return `'${String(value).replace(/'/g, `'\"'\"'`)}'`;
}

function buildCurlCommand({ baseUrl, authToken, protectedEntity, customMetadata, password, filePath }) {
  const url = `${String(baseUrl || "").replace(/\/+$/, "")}/scan/binary/v2`;
  const parts = [
    "curl",
    "-sS",
    "-X",
    "POST",
    shellQuote(url),
    "-H",
    shellQuote("Content-Type: application/octet-stream"),
    "-H",
    shellQuote(`protected_entity: ${protectedEntity ?? 1}`)
  ];
  if (customMetadata) {
    parts.push("-H", shellQuote(`X-Custom-Metadata: ${customMetadata}`));
  }
  if (password) {
    const encoded = Buffer.from(String(password), "utf8").toString("base64");
    parts.push("-H", shellQuote(`scan_password: ${encoded}`));
  }
  if (authToken) {
    parts.push("-H", shellQuote(`AUTH: ${authToken}`));
    parts.push("-H", shellQuote(`AUTH_TOKEN: ${authToken}`));
  }
  parts.push("--data-binary", `@${shellQuote(filePath)}`);
  return parts.join(" ");
}

async function createMainWindow() {
  const win = new BrowserWindow({
    width: 1100,
    height: 860,
    minWidth: 920,
    minHeight: 700,
    title: APP_NAME,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    }
  });

  await win.loadFile(path.join(__dirname, "index.html"));
}

ipcMain.handle("dsxa-desktop:pick-file", async () => {
  const picked = await dialog.showOpenDialog({
    title: "Select File to Scan",
    properties: ["openFile"]
  });
  if (picked.canceled || !picked.filePaths?.length) return null;
  return picked.filePaths[0];
});

ipcMain.handle("dsxa-desktop:pick-folder", async () => {
  const picked = await dialog.showOpenDialog({
    title: "Select Folder to Scan",
    properties: ["openDirectory", "createDirectory"]
  });
  if (picked.canceled || !picked.filePaths?.length) return null;
  return picked.filePaths[0];
});

ipcMain.handle("dsxa-desktop:load-profiles", async () => {
  return readProfiles();
});

ipcMain.handle("dsxa-desktop:save-profiles", async (_event, state) => {
  return writeProfiles(state);
});

ipcMain.handle("dsxa-desktop:scan-file", async (_event, req) => {
  const started = Date.now();
  const filePath = String(req?.filePath || "").trim();
  if (!filePath) {
    throw new Error("filePath is required");
  }

  const profile = req?.profile || {};
  const { DSXAClient, scanFilePath } = await loadSdkNodeModule();
  const client = new DSXAClient({
    baseUrl: profile.baseUrl,
    authToken: profile.authToken || "",
    defaultProtectedEntity: Number.isFinite(Number(profile.protectedEntity))
      ? Number(profile.protectedEntity)
      : 1,
    timeoutMs: Number.isFinite(Number(profile.timeoutMs)) ? Number(profile.timeoutMs) : 30000,
    fetchImpl: global.fetch
  });

  const customMetadata = String(req?.metadata ?? profile.customMetadata ?? "").trim();
  const password = String(req?.password || "").trim();

  try {
    const result = await scanFilePath(client, filePath, {
      customMetadata: customMetadata || undefined,
      password: password || undefined
    });
    return {
      operation: "scan-file",
      file: filePath,
      curlCommand: buildCurlCommand({
        baseUrl: profile.baseUrl,
        authToken: profile.authToken || "",
        protectedEntity: Number.isFinite(Number(profile.protectedEntity))
          ? Number(profile.protectedEntity)
          : 1,
        customMetadata: customMetadata || "",
        password: password || "",
        filePath
      }),
      elapsedSeconds: (Date.now() - started) / 1000,
      result: typeof result?.toJSON === "function" ? result.toJSON() : result
    };
  } catch (error) {
    const detail = {
      message: error?.message || String(error),
      status: error?.status ?? null,
      body: error?.body ?? null
    };
    throw new Error(JSON.stringify(detail));
  }
});

ipcMain.handle("dsxa-desktop:scan-folder", async (_event, req) => {
  const started = Date.now();
  const folderPath = String(req?.folderPath || "").trim();
  if (!folderPath) {
    throw new Error("folderPath is required");
  }

  const profile = req?.profile || {};
  const { DSXAClient, scanFilePath } = await loadSdkNodeModule();
  const client = new DSXAClient({
    baseUrl: profile.baseUrl,
    authToken: profile.authToken || "",
    defaultProtectedEntity: Number.isFinite(Number(profile.protectedEntity))
      ? Number(profile.protectedEntity)
      : 1,
    timeoutMs: Number.isFinite(Number(profile.timeoutMs)) ? Number(profile.timeoutMs) : 30000,
    fetchImpl: global.fetch
  });

  const customMetadata = String(req?.metadata ?? profile.customMetadata ?? "").trim();
  const password = String(req?.password || "").trim();
  const concurrency = Math.max(1, Number.parseInt(String(req?.concurrency || "4"), 10) || 4);
  const sender = _event.sender;
  const jobId = String(req?.jobId || "").trim() || crypto.randomUUID();

  try {
    const files = [];
    await walkFiles(folderPath, files);

    const progressState = {
      total: files.length,
      scanned: 0,
      ok: 0,
      failed: 0,
      scanTimeTotalMicros: 0,
      stats: {
        benign: 0,
        malicious: 0,
        failed: 0,
        encrypted: 0,
        other: 0
      }
    };

    emitFolderProgress(sender, {
      jobId,
      type: "start",
      total: progressState.total,
      scanned: 0,
      ok: 0,
      failed: 0,
      stats: progressState.stats
    });

    const results = new Array(files.length);
    let cursor = 0;

    async function worker() {
      while (cursor < files.length) {
        const idx = cursor++;
        const file = files[idx];
        try {
          const result = await scanFilePath(client, file, {
            customMetadata: customMetadata || undefined,
            password: password || undefined
          });
          const json = typeof result?.toJSON === "function" ? result.toJSON() : result;
          results[idx] = { file, status: "ok", result: json };
          progressState.scanned += 1;
          progressState.ok += 1;
          progressState.scanTimeTotalMicros += Number(result?.scanDurationInMicroseconds || 0);
          progressState.stats[verdictBucketFromResult(result)] += 1;
        } catch (error) {
          results[idx] = {
            file,
            status: "failed",
            error: error?.message || String(error)
          };
          progressState.scanned += 1;
          progressState.failed += 1;
          progressState.stats.failed += 1;
        }

        emitFolderProgress(sender, {
          jobId,
          type: "progress",
          total: progressState.total,
          scanned: progressState.scanned,
          ok: progressState.ok,
          failed: progressState.failed,
          stats: progressState.stats
        });
      }
    }

    await Promise.all(Array.from({ length: concurrency }, () => worker()));

    const summary = {
      operation: "scan-folder-summary",
      jobId,
      folder: folderPath,
      concurrency,
      scanned: progressState.scanned,
      ok: progressState.ok,
      failed: progressState.failed,
      elapsed_seconds: (Date.now() - started) / 1000,
      scan_time_total_microseconds: progressState.scanTimeTotalMicros,
      scan_time_total_seconds: progressState.scanTimeTotalMicros / 1_000_000,
      stats: progressState.stats,
      results
    };

    emitFolderProgress(sender, {
      jobId,
      type: "done",
      total: progressState.total,
      scanned: progressState.scanned,
      ok: progressState.ok,
      failed: progressState.failed,
      stats: progressState.stats,
      summary
    });

    return {
      operation: "scan-folder",
      folder: folderPath,
      jobId,
      concurrency,
      elapsedSeconds: (Date.now() - started) / 1000,
      summary
    };
  } catch (error) {
    const detail = {
      message: error?.message || String(error),
      status: error?.status ?? null,
      body: error?.body ?? null
    };
    emitFolderProgress(sender, {
      jobId,
      type: "error",
      total: 0,
      scanned: 0,
      ok: 0,
      failed: 0,
      stats: {
        benign: 0,
        malicious: 0,
        failed: 0,
        encrypted: 0,
        other: 0
      },
      error: detail
    });
    throw new Error(JSON.stringify(detail));
  }
});

ipcMain.handle("dsxa-desktop:scan-hash", async (_event, req) => {
  const started = Date.now();
  const hashValue = String(req?.hashValue || "").trim();
  if (!hashValue) {
    throw new Error("hashValue is required");
  }

  const profile = req?.profile || {};
  const { DSXAClient } = await loadSdkNodeModule();
  const client = new DSXAClient({
    baseUrl: profile.baseUrl,
    authToken: profile.authToken || "",
    defaultProtectedEntity: Number.isFinite(Number(profile.protectedEntity))
      ? Number(profile.protectedEntity)
      : 1,
    timeoutMs: Number.isFinite(Number(profile.timeoutMs)) ? Number(profile.timeoutMs) : 30000,
    fetchImpl: global.fetch
  });

  const customMetadata = String(req?.metadata ?? profile.customMetadata ?? "").trim();

  try {
    const result = await client.scanHash(hashValue, {
      customMetadata: customMetadata || undefined
    });
    return {
      operation: "scan-hash",
      hash: hashValue,
      elapsedSeconds: (Date.now() - started) / 1000,
      result: typeof result?.toJSON === "function" ? result.toJSON() : result
    };
  } catch (error) {
    const detail = {
      message: error?.message || String(error),
      status: error?.status ?? null,
      body: error?.body ?? null
    };
    throw new Error(JSON.stringify(detail));
  }
});

app.whenReady().then(async () => {
  app.setName(APP_NAME);
  await createMainWindow();

  app.on("activate", async () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      await createMainWindow();
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
