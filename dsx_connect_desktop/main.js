const { app, BrowserWindow, dialog, Menu, shell, ipcMain } = require('electron');
const { spawn, spawnSync } = require('child_process');
const path = require('path');
const fs = require('fs');
const http = require('http');
const net = require('net');
const os = require('os');

const API_PORT = process.env.DSXCONNECT_LOCAL_PORT || '8586';
const API_URL = `http://127.0.0.1:${API_PORT}/`;
const REPO_ROOT = path.resolve(__dirname, '..');
const CORE_MANAGER = path.join(REPO_ROOT, 'dsx_connect', 'local', 'dsx_connect_local.py');
const FS_MANAGER = path.join(REPO_ROOT, 'connectors', 'filesystem', 'local', 'filesystem_local.py');
const SP_MANAGER = path.join(REPO_ROOT, 'connectors', 'sharepoint', 'local', 'sharepoint_local.py');
const AWS_MANAGER = path.join(REPO_ROOT, 'connectors', 'aws_s3', 'local', 'aws_s3_local.py');
const AZURE_MANAGER = path.join(REPO_ROOT, 'connectors', 'azure_blob_storage', 'local', 'azure_blob_storage_local.py');
const SALESFORCE_MANAGER = path.join(REPO_ROOT, 'connectors', 'salesforce', 'local', 'salesforce_local.py');

const CORE_STATE_DIR = path.join(os.homedir(), '.dsx-connect-local', 'dsx-connect-desktop');
const CORE_ENV_FILE = path.join(CORE_STATE_DIR, '.env.local');
const LAUNCHER_STATE_DIR = path.join(CORE_STATE_DIR, 'launcher');
const LAUNCHED_CONNECTORS_FILE = path.join(LAUNCHER_STATE_DIR, 'launched-connectors.json');
const APP_DISPLAY_NAME = 'DSX-Connect Desktop';

app.setName(APP_DISPLAY_NAME);

ipcMain.handle('dsx-desktop:pick-folder', async () => {
  const picked = await dialog.showOpenDialog({
    title: 'Select Asset Folder',
    properties: ['openDirectory', 'createDirectory'],
  });
  if (picked.canceled || !picked.filePaths || !picked.filePaths.length) return null;
  return picked.filePaths[0] || null;
});

let mainWindow = null;
let shutdownWindow = null;
let coreProcess = null;
const launchedConnectors = [];
const pendingConnectorPorts = new Set();

function refreshEmbeddedUi() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  mainWindow.webContents.reloadIgnoringCache();
}

async function showEmbeddedNotification(message, type = 'info') {
  if (!mainWindow || mainWindow.isDestroyed()) return false;
  const safeMessage = JSON.stringify(String(message || ''));
  const safeType = JSON.stringify(String(type || 'info'));
  try {
    await mainWindow.webContents.executeJavaScript(`
      (() => {
        if (typeof showNotification !== 'function') return false;
        showNotification(${safeMessage}, ${safeType});
        return true;
      })()
    `, true);
    return true;
  } catch {
    return false;
  }
}

async function resetEmbeddedUiState() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  try {
    await mainWindow.webContents.executeJavaScript(`
      try { localStorage.removeItem('lastScansByConnector'); } catch {}
      try { localStorage.removeItem('activeJobs'); } catch {}
      true;
    `, true);
  } catch {}
  try {
    const ses = mainWindow.webContents.session;
    await ses.clearCache();
  } catch {}
  refreshEmbeddedUi();
}

function exists(p) {
  try {
    return fs.existsSync(p);
  } catch {
    return false;
  }
}

function resolvePython() {
  const candidates = [
    path.join(REPO_ROOT, '.venv', 'bin', 'python'),
    path.join(REPO_ROOT, '.venv', 'Scripts', 'python.exe'),
    'python3',
    'python'
  ];
  for (const c of candidates) {
    if (c.includes(path.sep)) {
      if (exists(c)) return c;
    } else {
      return c;
    }
  }
  return 'python3';
}

function checkCommandAvailable(cmd, args = ['--version']) {
  try {
    const result = spawnSync(cmd, args, { stdio: 'ignore', shell: false });
    return result && result.status === 0;
  } catch {
    return false;
  }
}

function ensureDesktopPrereqs() {
  if (!checkCommandAvailable('redis-server', ['--version'])) {
    dialog.showErrorBox(
      'DSX-Connect Desktop',
      'redis-server is required but was not found on PATH.\n\n' +
      'Install Redis (for example: `brew install redis`) or set\n' +
      '`DSXCONNECT_LOCAL_REDIS_SERVER=/full/path/to/redis-server` and relaunch.'
    );
    return false;
  }
  return true;
}

function scriptForKind(kind) {
  if (kind === 'filesystem') return FS_MANAGER;
  if (kind === 'sharepoint') return SP_MANAGER;
  if (kind === 'aws_s3') return AWS_MANAGER;
  if (kind === 'azure_blob_storage') return AZURE_MANAGER;
  if (kind === 'salesforce') return SALESFORCE_MANAGER;
  throw new Error(`Unsupported connector kind: ${kind}`);
}

function displayForKind(kind) {
  if (kind === 'filesystem') return 'Filesystem';
  if (kind === 'sharepoint') return 'SharePoint';
  if (kind === 'aws_s3') return 'AWS S3';
  if (kind === 'azure_blob_storage') return 'Azure Blob';
  if (kind === 'salesforce') return 'Salesforce';
  throw new Error(`Unsupported connector kind: ${kind}`);
}

function defaultPortForKind(kind) {
  if (kind === 'filesystem') return 8620;
  if (kind === 'sharepoint') return 8640;
  if (kind === 'aws_s3') return 8600;
  if (kind === 'azure_blob_storage') return 8610;
  if (kind === 'salesforce') return 8670;
  throw new Error(`Unsupported connector kind: ${kind}`);
}

function connectorStateDirForKind(kind) {
  let root = 'connector';
  if (kind === 'filesystem') root = 'filesystem-connector';
  else if (kind === 'sharepoint') root = 'sharepoint-connector';
  else if (kind === 'aws_s3') root = 'aws-s3-connector';
  else if (kind === 'azure_blob_storage') root = 'azure-blob-storage-connector';
  else if (kind === 'salesforce') root = 'salesforce-connector';
  else throw new Error(`Unsupported connector kind: ${kind}`);
  return path.join(os.homedir(), '.dsx-connect-local', `${root}-desktop`);
}

function connectorStableIdForKind(kind) {
  return `${kind}-desktop`;
}

function makeConnectorEntry(kind, stateDir, port) {
  return {
    id: connectorStableIdForKind(kind),
    kind,
    display: displayForKind(kind),
    script: scriptForKind(kind),
    stateDir,
    port,
  };
}

function waitForHttpReady(url, timeoutMs = 45000, intervalMs = 500) {
  const started = Date.now();
  return new Promise((resolve, reject) => {
    const attempt = () => {
      const req = http.get(url, (res) => {
        res.resume();
        if (res.statusCode && res.statusCode < 500) {
          resolve();
          return;
        }
        retry();
      });
      req.on('error', retry);
      req.setTimeout(3000, () => {
        req.destroy();
        retry();
      });
    };

    const retry = () => {
      if (Date.now() - started > timeoutMs) {
        reject(new Error(`Timed out waiting for ${url}`));
        return;
      }
      setTimeout(attempt, intervalMs);
    };

    attempt();
  });
}

function startCore() {
  const python = resolvePython();
  const args = [CORE_MANAGER, '--state-dir', CORE_STATE_DIR, 'start'];

  coreProcess = spawn(python, args, {
    cwd: REPO_ROOT,
    env: process.env,
    stdio: 'inherit',
    detached: false
  });

  coreProcess.on('error', (err) => {
    console.error('Failed to start dsx_connect_local:', err);
  });
}

async function getCoreAppEnv() {
  const res = await httpJson('GET', `${API_URL}dsx-connect/api/v1/config`);
  if (!res.ok || !res.data || typeof res.data !== 'object') return 'unknown';
  return String(res.data.app_env || 'unknown').trim().toLowerCase();
}

async function ensureCoreInAppMode() {
  let appEnv = await getCoreAppEnv();
  if (appEnv === 'app') return true;

  // Best effort: restart the managed core (state dir already pinned to app mode).
  await stopCore();
  await new Promise((r) => setTimeout(r, 500));
  startCore();
  await waitForHttpReady(API_URL, 30000, 500);
  appEnv = await getCoreAppEnv();
  return appEnv === 'app';
}

async function ensureCoreDesktopState() {
  fs.mkdirSync(CORE_STATE_DIR, { recursive: true });
  const init = await runPythonCommand(CORE_MANAGER, 'init', [], ['--state-dir', CORE_STATE_DIR]);
  if (!init.ok) {
    const detail = [init.stdout, init.stderr].filter(Boolean).join('\n');
    throw new Error(`Failed to initialize core state dir.\n${detail || 'Unknown error'}`);
  }
  const envValues = readEnvValues(CORE_ENV_FILE);
  upsertEnvValues(CORE_ENV_FILE, {
    DSXCONNECT_APP_ENV: envValues.DSXCONNECT_APP_ENV || 'app',
    DSXCONNECT_DIANNA__AUTO_ON_MALICIOUS: envValues.DSXCONNECT_DIANNA__AUTO_ON_MALICIOUS || 'false',
    DSXCONNECT_WORKER_POOL: envValues.DSXCONNECT_WORKER_POOL || 'prefork',
    DSXCONNECT_WORKER_CONCURRENCY: envValues.DSXCONNECT_WORKER_CONCURRENCY || '4'
  });
}

function runPythonCommand(scriptPath, command, commandArgs = [], globalArgs = []) {
  return new Promise((resolve) => {
    const python = resolvePython();
    const args = [scriptPath, ...globalArgs, command, ...commandArgs];
    const proc = spawn(python, args, {
      cwd: REPO_ROOT,
      env: process.env,
      stdio: ['ignore', 'pipe', 'pipe']
    });

    let stdout = '';
    let stderr = '';
    proc.stdout.on('data', (d) => {
      stdout += d.toString();
    });
    proc.stderr.on('data', (d) => {
      stderr += d.toString();
    });
    proc.on('error', (err) => {
      resolve({ ok: false, code: -1, stdout, stderr: `${stderr}\n${String(err)}` });
    });
    proc.on('close', (code) => {
      resolve({ ok: code === 0, code: code || 0, stdout: stdout.trim(), stderr: stderr.trim() });
    });
  });
}

function connectorMenuLabel(item) {
  return `${item.display}`;
}

function saveLaunchedConnectors() {
  try {
    fs.mkdirSync(LAUNCHER_STATE_DIR, { recursive: true });
    const data = launchedConnectors.map((x) => ({
      id: x.id,
      kind: x.kind,
      stateDir: x.stateDir,
      port: x.port
    }));
    fs.writeFileSync(LAUNCHED_CONNECTORS_FILE, JSON.stringify(data, null, 2), 'utf8');
  } catch (err) {
    console.error('Failed to save launched connectors:', err);
  }
}

function upsertEnvValues(envPath, values) {
  let lines = [];
  if (exists(envPath)) {
    lines = fs.readFileSync(envPath, 'utf8').split(/\r?\n/);
  }
  const keys = new Set(Object.keys(values));
  const written = new Set();
  const out = [];

  for (const line of lines) {
    if (!line || line.trim().startsWith('#') || !line.includes('=')) {
      out.push(line);
      continue;
    }
    const idx = line.indexOf('=');
    const key = line.slice(0, idx).trim();
    if (keys.has(key)) {
      out.push(`${key}=${values[key]}`);
      written.add(key);
    } else {
      out.push(line);
    }
  }

  for (const [k, v] of Object.entries(values)) {
    if (!written.has(k)) out.push(`${k}=${v}`);
  }
  if (out.length && out[out.length - 1] !== '') out.push('');
  fs.mkdirSync(path.dirname(envPath), { recursive: true });
  fs.writeFileSync(envPath, out.join('\n'), 'utf8');
}

function readEnvValues(envPath) {
  const values = {};
  if (!exists(envPath)) return values;
  const lines = fs.readFileSync(envPath, 'utf8').split(/\r?\n/);
  for (const line of lines) {
    if (!line || line.trim().startsWith('#') || !line.includes('=')) continue;
    const idx = line.indexOf('=');
    const key = line.slice(0, idx).trim();
    const value = line.slice(idx + 1).trim();
    values[key] = value;
  }
  return values;
}

async function openConnectorSettingsInUi(uuid, connectorName, retries = 12, delayMs = 500) {
  if (!mainWindow || mainWindow.isDestroyed()) return false;
  const safeUuid = JSON.stringify(String(uuid || ''));
  const safeName = JSON.stringify(String(connectorName || 'Connector'));

  for (let attempt = 0; attempt < retries; attempt += 1) {
    try {
      await mainWindow.webContents.executeJavaScript(`
        (() => {
          if (typeof showConnectorConfig !== 'function') return false;
          showConnectorConfig(${safeUuid}, ${safeName});
          return true;
        })()
      `, true);
      return true;
    } catch {}
    await new Promise((r) => setTimeout(r, delayMs));
    try {
      refreshEmbeddedUi();
    } catch {}
  }
  return false;
}

function shouldStopCoreOnExit() {
  return process.env.DSXCONNECT_STOP_ON_EXIT !== '0';
}

function shouldStopConnectorsOnExit() {
  return process.env.DSXCONNECT_STOP_CONNECTORS_ON_EXIT !== '0';
}

function ensureConnectorIdentityEnv(stateDir, extraValues = {}) {
  const envPath = path.join(stateDir, '.env.local');
  const connectorDataDir = path.join(stateDir, 'data');
  upsertEnvValues(envPath, {
    DSXCONNECTOR_DATA_DIR: connectorDataDir,
    DSXCONNECTOR_APP_ENV: 'app',
    ...extraValues,
  });
}

function connectorEnvDefaults(kind, port) {
  const base = {
    DSXCONNECTOR_DISPLAY_NAME: `${displayForKind(kind)} :${port}`,
  };
  if (kind === 'sharepoint') {
    // Align desktop launcher behavior with the working local SharePoint integration profile.
    base.RUN_SP_INTEGRATION = 'true';
  }
  return base;
}

function connectorBaseUrl(item) {
  let pathPart = 'connector';
  if (item.kind === 'filesystem') pathPart = 'filesystem-connector';
  else if (item.kind === 'sharepoint') pathPart = 'sharepoint-connector';
  else if (item.kind === 'aws_s3') pathPart = 'aws-s3-connector';
  else if (item.kind === 'azure_blob_storage') pathPart = 'azure-blob-storage-connector';
  else if (item.kind === 'salesforce') pathPart = 'salesforce-connector';
  return `http://127.0.0.1:${item.port}/${pathPart}`;
}

async function isConnectorResponsive(item) {
  try {
    const ready = await httpJson('GET', `${connectorBaseUrl(item)}/readyz`, null, 1500);
    return ready.ok;
  } catch {
    return false;
  }
}

async function getRegisteredConnectorForItem(item) {
  const list = await httpJson('GET', `${API_URL}dsx-connect/api/v1/connectors/list`, null, 4000);
  if (!list.ok || !Array.isArray(list.data)) return null;
  const targetBase = connectorBaseUrl(item).replace(/\/+$/, '');
  return list.data.find((conn) => {
    const connUrl = String((conn && conn.url) || '').replace(/\/+$/, '');
    return connUrl === targetBase;
  }) || null;
}

async function isConnectorConfigReady(item) {
  try {
    const cfg = await httpJson('GET', `${connectorBaseUrl(item)}/config`, null, 2000);
    return cfg.ok;
  } catch {
    return false;
  }
}

async function openLaunchedConnectorSettings(item, retries = 12, delayMs = 500) {
  for (let attempt = 0; attempt < retries; attempt += 1) {
    const registered = await getRegisteredConnectorForItem(item);
    if (registered && registered.uuid && (await isConnectorConfigReady(item))) {
      const displayName = registered.display_name || item.display || item.kind || 'Connector';
      return openConnectorSettingsInUi(registered.uuid, displayName, 1, delayMs);
    }
    await new Promise((r) => setTimeout(r, delayMs));
  }
  return false;
}

function readPidFromFile(pidfile) {
  try {
    if (!exists(pidfile)) return null;
    const raw = String(fs.readFileSync(pidfile, 'utf8') || '').trim();
    const pid = Number(raw);
    if (!Number.isInteger(pid) || pid <= 0) return null;
    return pid;
  } catch {
    return null;
  }
}

function isPidAlive(pid) {
  if (!pid || !Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function httpJson(method, url, payload = null, timeoutMs = 8000) {
  return new Promise((resolve) => {
    const u = new URL(url);
    const body = payload == null ? null : Buffer.from(JSON.stringify(payload));
    const req = http.request(
      {
        method,
        hostname: u.hostname,
        port: u.port,
        path: `${u.pathname}${u.search}`,
        headers: body
          ? {
              'Content-Type': 'application/json',
              'Content-Length': String(body.length)
            }
          : {}
      },
      (res) => {
        let data = '';
        res.on('data', (chunk) => {
          data += chunk.toString();
        });
        res.on('end', () => {
          let parsed = {};
          try {
            parsed = data ? JSON.parse(data) : {};
          } catch {
            parsed = { raw: data };
          }
          const ok = (res.statusCode || 500) >= 200 && (res.statusCode || 500) < 300;
          resolve({ ok, statusCode: res.statusCode || 0, data: parsed });
        });
      }
    );
    req.on('error', (err) => resolve({ ok: false, statusCode: 0, data: { error: String(err) } }));
    req.setTimeout(timeoutMs, () => {
      req.destroy(new Error('request timeout'));
    });
    if (body) req.write(body);
    req.end();
  });
}

async function setFilesystemAssetFolder(item) {
  const picked = await dialog.showOpenDialog({
    title: 'Select Filesystem Asset Folder',
    properties: ['openDirectory', 'createDirectory']
  });
  if (picked.canceled || !picked.filePaths || !picked.filePaths.length) return;

  const folder = picked.filePaths[0];
  const cfgRes = await httpJson('GET', `${connectorBaseUrl(item)}/config`);
  if (!cfgRes.ok) {
    const detail = JSON.stringify(cfgRes.data, null, 2);
    dialog.showErrorBox('Set Asset Folder', `Failed to read connector config.\n\n${detail}`);
    return;
  }

  const current = cfgRes.data || {};
  const updated = {
    ...current,
    asset: folder,
    asset_display_name: folder
  };
  const putRes = await httpJson('PUT', `${connectorBaseUrl(item)}/config`, updated);
  if (!putRes.ok) {
    const detail = JSON.stringify(putRes.data, null, 2);
    dialog.showErrorBox('Set Asset Folder', `Failed to update connector config.\n\n${detail}`);
    return;
  }

  // Keep local state file in sync for this launched instance.
  upsertEnvValues(path.join(item.stateDir, '.env.local'), {
    DSXCONNECTOR_ASSET: folder,
    DSXCONNECTOR_ASSET_DISPLAY_NAME: folder
  });
}

function readEnvFileRedacted(envPath) {
  try {
    if (!exists(envPath)) return `(missing) ${envPath}`;
    const lines = fs.readFileSync(envPath, 'utf8').split(/\r?\n/);
    return lines
      .map((line) => {
        if (!line.includes('=')) return line;
        const idx = line.indexOf('=');
        const key = line.slice(0, idx).trim();
        const val = line.slice(idx + 1);
        if (/secret|token|password/i.test(key)) {
          if (!val) return `${key}=`;
          return `${key}=********`;
        }
        return line;
      })
      .join('\n');
  } catch (err) {
    return `(error reading ${envPath}) ${String(err && err.message ? err.message : err)}`;
  }
}

async function showConnectorDebugInfo(item) {
  const base = connectorBaseUrl(item);
  const envPath = path.join(item.stateDir, '.env.local');

  const [ready, repo, cfg] = await Promise.all([
    httpJson('GET', `${base}/readyz`, null, 4000),
    httpJson('GET', `${base}/repo_check?preview=5`, null, 8000),
    httpJson('GET', `${base}/config`, null, 4000),
  ]);

  const detail = [
    `Connector: ${connectorMenuLabel(item)}`,
    `State dir: ${item.stateDir}`,
    '',
    `readyz: HTTP ${ready.statusCode || 0}`,
    `${JSON.stringify(ready.data || {}, null, 2)}`,
    '',
    `repo_check: HTTP ${repo.statusCode || 0}`,
    `${JSON.stringify(repo.data || {}, null, 2)}`,
    '',
    `config: HTTP ${cfg.statusCode || 0}`,
    `${JSON.stringify(cfg.data || {}, null, 2)}`,
    '',
    `.env.local (${envPath})`,
    `${readEnvFileRedacted(envPath)}`,
  ].join('\n');

  dialog.showMessageBox({
    type: 'info',
    title: 'Connector Debug Info',
    message: connectorMenuLabel(item),
    detail,
  });
}

function loadLaunchedConnectors() {
  try {
    const byKind = new Map();
    if (exists(LAUNCHED_CONNECTORS_FILE)) {
      const raw = fs.readFileSync(LAUNCHED_CONNECTORS_FILE, 'utf8');
      const data = JSON.parse(raw);
      if (Array.isArray(data)) {
        for (const item of data) {
          if (!item || !['filesystem', 'sharepoint', 'aws_s3', 'azure_blob_storage', 'salesforce'].includes(item.kind)) continue;
          const port = Number(item.port);
          byKind.set(item.kind, {
            stateDir: typeof item.stateDir === 'string' && item.stateDir ? item.stateDir : connectorStateDirForKind(item.kind),
            port: Number.isInteger(port) && port > 0 ? port : defaultPortForKind(item.kind),
          });
        }
      }
    }

    for (const kind of ['filesystem', 'sharepoint', 'aws_s3', 'azure_blob_storage', 'salesforce']) {
      const fromFile = byKind.get(kind);
      if (!fromFile) continue;
      const canonicalDir = connectorStateDirForKind(kind);
      const oldDir = String(fromFile.stateDir || canonicalDir);
      let stateDir = canonicalDir;

      // Best-effort migrate legacy per-instance dirs into canonical desktop dir.
      try {
        if (oldDir !== canonicalDir && exists(oldDir) && !exists(canonicalDir)) {
          fs.mkdirSync(canonicalDir, { recursive: true });
          const oldEnv = path.join(oldDir, '.env.local');
          const oldData = path.join(oldDir, 'data');
          if (exists(oldEnv)) fs.copyFileSync(oldEnv, path.join(canonicalDir, '.env.local'));
          if (exists(oldData)) fs.cpSync(oldData, path.join(canonicalDir, 'data'), { recursive: true });
        } else if (oldDir !== canonicalDir && exists(oldDir) && exists(canonicalDir)) {
          // Keep canonical path; old dir is ignored.
        } else if (!exists(canonicalDir) && exists(oldDir)) {
          // Fallback to old location when canonical does not exist yet.
          stateDir = oldDir;
        }
      } catch {}

      launchedConnectors.push(makeConnectorEntry(kind, stateDir, fromFile.port));
    }
  } catch (err) {
    console.error('Failed to load launched connectors:', err);
  }
}

async function rehydrateLaunchedConnectorsOnStartup() {
  if (!launchedConnectors.length) return { started: 0, failed: [] };
  let started = 0;
  const failed = [];
  for (const item of launchedConnectors) {
    try {
      if (await isConnectorResponsive(item)) {
        started += 1;
        continue;
      }
      ensureConnectorIdentityEnv(item.stateDir, {
        ...connectorEnvDefaults(item.kind, item.port),
      });
      const result = await runPythonCommand(item.script, 'start', [], [
        '--state-dir',
        item.stateDir,
        '--port',
        String(item.port),
      ]);
      if (result.ok || (await isConnectorResponsive(item))) {
        started += 1;
      } else {
        failed.push({
          kind: item.kind,
          detail: [result.stdout, result.stderr].filter(Boolean).join('\n'),
        });
      }
    } catch (e) {
      failed.push({ kind: item.kind, detail: String(e && e.message ? e.message : e) });
    }
  }
  return { started, failed };
}

async function cleanupConnectorRegistry() {
  const list = await httpJson('GET', `${API_URL}dsx-connect/api/v1/connectors/list`);
  if (!list.ok || !Array.isArray(list.data)) {
    const detail = JSON.stringify(list.data, null, 2);
    dialog.showErrorBox('Cleanup Connector Registry', `Failed to list connectors.\n\n${detail}`);
    return;
  }

  const connectors = list.data;
  let removed = 0;
  const failed = [];
  for (const item of connectors) {
    const uuid = item && item.uuid ? String(item.uuid) : '';
    if (!uuid) continue;
    const del = await httpJson('DELETE', `${API_URL}dsx-connect/api/v1/connectors/unregister/${uuid}`);
    if (del.ok) {
      removed += 1;
    } else {
      failed.push({
        uuid,
        status: del.statusCode,
        detail: del.data,
      });
    }
  }

  // Refresh UI cards after cleanup attempts.
  if (mainWindow && !mainWindow.isDestroyed()) {
    refreshEmbeddedUi();
  }

  const failedSummary = failed
    .slice(0, 5)
    .map((f) => `- ${f.uuid}: HTTP ${f.status} ${JSON.stringify(f.detail)}`)
    .join('\n');
  const more = failed.length > 5 ? `\n...and ${failed.length - 5} more failures` : '';
  const detail = [
    `Unregister requests succeeded for ${removed} connector(s).`,
    `Failed for ${failed.length} connector(s).`,
    failed.length ? `\nFailure details:\n${failedSummary}${more}` : '',
  ].join('\n');

  dialog.showMessageBox({
    type: 'info',
    title: 'Cleanup Connector Registry',
    message: `Attempted cleanup for ${connectors.length} connector(s).`,
    detail,
  });
}

async function stopAllLaunchedConnectors() {
  return stopAllLaunchedConnectorsInternal({ showDialog: true });
}

async function stopAllLaunchedConnectorsInternal({ showDialog = false, removeFromLauncher = true } = {}) {
  const items = [...launchedConnectors];
  let stopped = 0;
  const failed = [];

  for (const item of items) {
    const result = await runPythonCommand(item.script, 'stop', [], [
      '--state-dir',
      item.stateDir,
      '--port',
      String(item.port),
    ]);
    if (result.ok) {
      stopped += 1;
      if (removeFromLauncher) {
        const idx = launchedConnectors.findIndex((x) => x.id === item.id);
        if (idx >= 0) launchedConnectors.splice(idx, 1);
      }
    } else {
      failed.push({
        id: item.id,
        detail: [result.stdout, result.stderr].filter(Boolean).join('\n'),
      });
    }
  }

  if (showDialog) {
    const failedSummary = failed
      .slice(0, 5)
      .map((f) => `- ${f.id}: ${f.detail || 'unknown error'}`)
      .join('\n');
    const more = failed.length > 5 ? `\n...and ${failed.length - 5} more failures` : '';

    dialog.showMessageBox({
      type: 'info',
      title: 'Stop All Launched Connectors',
      message: `Stopped ${stopped}/${items.length} connector(s).`,
      detail: failed.length ? `Failures:\n${failedSummary}${more}` : 'All connectors stopped successfully.',
    });
  } else if (failed.length) {
    console.error(`Failed to stop ${failed.length} launched connector(s):`, failed.slice(0, 5));
  }

  if (removeFromLauncher) {
    saveLaunchedConnectors();
    buildAppMenu();
    refreshEmbeddedUi();
  }

  return { stopped, total: items.length, failed };
}

function forgetAllLaunchedConnectors() {
  launchedConnectors.length = 0;
  saveLaunchedConnectors();
  buildAppMenu();
  refreshEmbeddedUi();
}

async function stopLaunchedConnector(item, { removeFromLauncher = true } = {}) {
  const result = await runPythonCommand(item.script, 'stop', [], [
    '--state-dir',
    item.stateDir,
    '--port',
    String(item.port)
  ]);
  if (!result.ok) {
    const detail = [result.stdout, result.stderr].filter(Boolean).join('\n');
    throw new Error(detail || 'Unknown error');
  }

  if (removeFromLauncher) {
    const idx = launchedConnectors.findIndex((x) => x.id === item.id);
    if (idx >= 0) launchedConnectors.splice(idx, 1);
    saveLaunchedConnectors();
    buildAppMenu();
    refreshEmbeddedUi();
  }
}

async function forgetConnectorDeployment(item) {
  const choice = await dialog.showMessageBox({
    type: 'warning',
    buttons: ['Cancel', 'Forget Deployment'],
    defaultId: 0,
    cancelId: 0,
    noLink: true,
    title: 'Forget Connector Deployment',
    message: `Forget ${connectorMenuLabel(item)}?`,
    detail: [
      'This stops the connector, removes it from the launcher, and deletes its local Desktop state.',
      'Launching it again later will start from a fresh local deployment.'
    ].join('\n\n'),
  });
  if (choice.response !== 1) return;

  try {
    await stopLaunchedConnector(item, { removeFromLauncher: true });
  } catch (err) {
    dialog.showErrorBox('Forget Connector Deployment', `${connectorMenuLabel(item)}\n\n${String(err && err.message ? err.message : err)}`);
    return;
  }

  try {
    fs.rmSync(item.stateDir, { recursive: true, force: true });
  } catch (err) {
    dialog.showErrorBox('Forget Connector Deployment', `Stopped connector but failed to remove state directory.\n\n${String(err && err.message ? err.message : err)}`);
    return;
  }

  refreshEmbeddedUi();
}

function listStrayConnectorProcesses() {
  return new Promise((resolve) => {
    const proc = spawn('ps', ['-ax', '-o', 'pid=,command='], {
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    let out = '';
    let err = '';
    proc.stdout.on('data', (d) => {
      out += d.toString();
    });
    proc.stderr.on('data', (d) => {
      err += d.toString();
    });
    proc.on('close', (code) => {
      if (code !== 0) {
        resolve({ ok: false, error: err || `ps exited with ${code}`, rows: [] });
        return;
      }
      const rows = out
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter(Boolean)
        .map((line) => {
          const m = line.match(/^(\d+)\s+(.+)$/);
          if (!m) return null;
          return { pid: Number(m[1]), cmd: m[2] };
        })
        .filter(Boolean)
        .filter((r) => Number.isInteger(r.pid) && r.pid > 0);
      resolve({ ok: true, rows });
    });
    proc.on('error', (e) => resolve({ ok: false, error: String(e), rows: [] }));
  });
}

async function stopStrayConnectorProcesses() {
  const listed = await listStrayConnectorProcesses();
  if (!listed.ok) {
    dialog.showErrorBox('Stop Stray Connector Processes', `Failed to list processes.\n\n${listed.error || 'Unknown error'}`);
    return;
  }

  const patterns = [
    '/connectors/filesystem/local/filesystem_local.py',
    '/connectors/sharepoint/local/sharepoint_local.py',
    '/connectors/aws_s3/local/aws_s3_local.py',
    '/connectors/azure_blob_storage/local/azure_blob_storage_local.py',
    '/connectors/salesforce/local/salesforce_local.py',
  ];

  const targets = listed.rows.filter((r) => patterns.some((p) => r.cmd.includes(p)));
  if (!targets.length) {
    dialog.showMessageBox({
      type: 'info',
      title: 'Stop Stray Connector Processes',
      message: 'No stray connector processes found.',
    });
    return;
  }

  const killed = [];
  for (const t of targets) {
    try {
      process.kill(t.pid, 'SIGTERM');
      killed.push(t);
    } catch {
      // ignore
    }
  }

  await new Promise((r) => setTimeout(r, 800));

  // Follow with registry cleanup and UI refresh.
  await cleanupConnectorRegistry();
  refreshEmbeddedUi();

  dialog.showMessageBox({
    type: 'info',
    title: 'Stop Stray Connector Processes',
    message: `Signaled ${killed.length}/${targets.length} process(es).`,
    detail: killed.slice(0, 10).map((k) => `${k.pid} ${k.cmd}`).join('\n'),
  });
}

function isPortFree(port, host = '127.0.0.1') {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.unref();
    server.on('error', () => resolve(false));
    server.listen({ port, host }, () => {
      server.close(() => resolve(true));
    });
  });
}

async function launchConnectorInstance(kind) {
  const stateDir = connectorStateDirForKind(kind);
  const fixedPort = defaultPortForKind(kind);
  const script = scriptForKind(kind);
  const display = displayForKind(kind);
  await showEmbeddedNotification(`Launching ${display} connector...`, 'info');
  const globalArgs = ['--state-dir', stateDir, '--port', String(fixedPort)];
  let existing = launchedConnectors.find((x) => x.kind === kind);
  if (!existing) {
    existing = makeConnectorEntry(kind, stateDir, fixedPort);
    launchedConnectors.push(existing);
    saveLaunchedConnectors();
    buildAppMenu();
  }

  if (await isConnectorResponsive(existing)) {
    return;
  }

  const portFree = await isPortFree(fixedPort);
  if (!portFree) {
    const detail = [
      `${display} connector fixed port ${fixedPort} is already in use.`,
      `This desktop launcher supports one ${display} instance.`,
      `Stop the existing process using that port, then launch again.`
    ].join('\n');
    dialog.showErrorBox(`Launch ${display} Connector`, detail);
    return;
  }

  pendingConnectorPorts.add(fixedPort);

  try {
    const init = await runPythonCommand(script, 'init', [], globalArgs);
    if (!init.ok) {
      const detail = [init.stdout, init.stderr].filter(Boolean).join('\n');
      dialog.showErrorBox(`Launch ${display} Connector`, `Init failed.\n\n${detail || 'Unknown error'}`);
      return;
    }

    ensureConnectorIdentityEnv(stateDir, {
      ...connectorEnvDefaults(kind, fixedPort),
    });

    const start = await runPythonCommand(script, 'start', [], globalArgs);
    if (!start.ok && !(await isConnectorResponsive(existing))) {
      const detail = [start.stdout, start.stderr].filter(Boolean).join('\n');
      dialog.showErrorBox(`Launch ${display} Connector`, `Start failed.\n\n${detail || 'Unknown error'}`);
      return;
    }
    await openLaunchedConnectorSettings(existing);
  } finally {
    pendingConnectorPorts.delete(fixedPort);
  }
}

function buildConnectorItemSubmenu(item) {
  return [
    {
      label: 'Stop',
      click: async () => {
        try {
          await stopLaunchedConnector(item, { removeFromLauncher: true });
        } catch (err) {
          dialog.showErrorBox('Stop Connector', `${connectorMenuLabel(item)}\n\n${String(err && err.message ? err.message : err)}`);
        }
      }
    },
    {
      label: 'Forget Deployment...',
      click: async () => {
        await forgetConnectorDeployment(item);
      }
    }
  ];
}

function buildAppMenu() {
  const hasFilesystemLaunched = launchedConnectors.some((x) => x.kind === 'filesystem');
  const hasSharepointLaunched = launchedConnectors.some((x) => x.kind === 'sharepoint');
  const hasAwsLaunched = launchedConnectors.some((x) => x.kind === 'aws_s3');
  const hasAzureLaunched = launchedConnectors.some((x) => x.kind === 'azure_blob_storage');
  const hasSalesforceLaunched = launchedConnectors.some((x) => x.kind === 'salesforce');
  const activeItems = launchedConnectors.length
    ? launchedConnectors.map((item) => ({
        label: connectorMenuLabel(item),
        submenu: buildConnectorItemSubmenu(item)
      }))
    : [{ label: 'No active connectors', enabled: false }];

  const template = [
    {
      label: APP_DISPLAY_NAME,
      submenu: [
        { role: 'about' },
        { type: 'separator' },
        { role: 'services' },
        { type: 'separator' },
        { role: 'hide' },
        { role: 'hideOthers' },
        { role: 'unhide' },
        { type: 'separator' },
        {
          label: `Quit ${APP_DISPLAY_NAME}`,
          role: 'quit'
        }
      ]
    },
    {
      label: 'File',
      submenu: [
        { role: 'close' }
      ]
    },
    {
      label: 'Edit',
      submenu: [
        { role: 'undo' },
        { role: 'redo' },
        { type: 'separator' },
        { role: 'cut' },
        { role: 'copy' },
        { role: 'paste' },
        { role: 'delete' },
        { role: 'selectAll' }
      ]
    },
    {
      label: 'Connectors',
      submenu: [
        {
          label: 'Launch',
          submenu: [
            {
              label: hasFilesystemLaunched ? 'Filesystem (Launched)' : 'Filesystem',
              enabled: !hasFilesystemLaunched,
              click: () => {
                launchConnectorInstance('filesystem').catch((err) => {
                  dialog.showErrorBox('Launch Filesystem Connector', String(err && err.message ? err.message : err));
                });
              }
            },
            {
              label: hasSharepointLaunched ? 'SharePoint (Launched)' : 'SharePoint',
              enabled: !hasSharepointLaunched,
              click: () => {
                launchConnectorInstance('sharepoint').catch((err) => {
                  dialog.showErrorBox('Launch SharePoint Connector', String(err && err.message ? err.message : err));
                });
              }
            },
            {
              label: hasAwsLaunched ? 'AWS S3 (Launched)' : 'AWS S3',
              enabled: !hasAwsLaunched,
              click: () => {
                launchConnectorInstance('aws_s3').catch((err) => {
                  dialog.showErrorBox('Launch AWS S3 Connector', String(err && err.message ? err.message : err));
                });
              }
            },
            {
              label: hasAzureLaunched ? 'Azure Blob (Launched)' : 'Azure Blob',
              enabled: !hasAzureLaunched,
              click: () => {
                launchConnectorInstance('azure_blob_storage').catch((err) => {
                  dialog.showErrorBox('Launch Azure Blob Connector', String(err && err.message ? err.message : err));
                });
              }
            },
            {
              label: hasSalesforceLaunched ? 'Salesforce (Launched)' : 'Salesforce',
              enabled: !hasSalesforceLaunched,
              click: () => {
                launchConnectorInstance('salesforce').catch((err) => {
                  dialog.showErrorBox('Launch Salesforce Connector', String(err && err.message ? err.message : err));
                });
              }
            }
          ]
        },
        { type: 'separator' },
        {
          label: 'Active',
          enabled: false
        },
        ...activeItems
      ]
    },
    {
      label: 'View',
      submenu: [
        { role: 'reload' },
        { role: 'forceReload' },
        {
          label: 'Reset UI State',
          click: () => {
            resetEmbeddedUiState().catch((err) => {
              dialog.showErrorBox('Reset UI State', String(err && err.message ? err.message : err));
            });
          }
        },
        { type: 'separator' },
        { role: 'toggleDevTools' },
        { role: 'resetZoom' },
        { role: 'zoomIn' },
        { role: 'zoomOut' },
        { type: 'separator' },
        { role: 'togglefullscreen' }
      ]
    },
    {
      label: 'Window',
      submenu: [
        { role: 'minimize' },
        { role: 'zoom' },
        { type: 'separator' },
        { role: 'front' }
      ]
    },
    {
      label: 'Help',
      submenu: [
        {
          label: 'DSX-Connect Documentation',
          click: () => {
            shell.openExternal('https://deep-instinct.github.io/dsx-connect/');
          }
        }
      ]
    }
  ];

  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

function stopCore() {
  return new Promise((resolve) => {
    const python = resolvePython();
    const args = [CORE_MANAGER, '--state-dir', CORE_STATE_DIR, 'stop'];
    const proc = spawn(python, args, {
      cwd: REPO_ROOT,
      env: process.env,
      stdio: 'inherit'
    });
    proc.on('exit', () => resolve());
    proc.on('error', () => resolve());
  });
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 920,
    minWidth: 1100,
    minHeight: 700,
    backgroundColor: '#0f1720',
    title: 'DSX-Connect Desktop',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  });

  mainWindow.loadURL(API_URL);

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

function showShutdownWindow() {
  if (shutdownWindow && !shutdownWindow.isDestroyed()) {
    shutdownWindow.focus();
    return;
  }

  shutdownWindow = new BrowserWindow({
    width: 460,
    height: 170,
    resizable: false,
    minimizable: false,
    maximizable: false,
    closable: false,
    fullscreenable: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    frame: false,
    modal: !!mainWindow,
    parent: mainWindow || undefined,
    backgroundColor: '#0f1720',
    title: 'Shutting Down',
    webPreferences: {
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false
    }
  });

  const html = `
    <!doctype html>
    <html>
      <head>
        <meta charset="utf-8" />
        <style>
          body {
            margin: 0;
            padding: 0;
            background: #0f1720;
            color: #e5e7eb;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
          }
          .wrap {
            height: 100vh;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            gap: 10px;
          }
          .spinner {
            width: 20px;
            height: 20px;
            border: 3px solid rgba(148, 163, 184, 0.35);
            border-top-color: #93c5fd;
            border-radius: 50%;
            animation: spin 0.9s linear infinite;
          }
          .title {
            font-size: 15px;
            font-weight: 600;
          }
          .sub {
            font-size: 12px;
            color: #94a3b8;
          }
          @keyframes spin {
            to { transform: rotate(360deg); }
          }
        </style>
      </head>
      <body>
        <div class="wrap">
          <div class="spinner"></div>
          <div class="title">DSX-Connect Desktop is shutting down...</div>
          <div class="sub">Stopping connectors and local services</div>
        </div>
      </body>
    </html>
  `;
  shutdownWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(html)}`);
  shutdownWindow.once('closed', () => {
    shutdownWindow = null;
  });
}

app.whenReady().then(async () => {
  if (!ensureDesktopPrereqs()) {
    app.quit();
    return;
  }

  loadLaunchedConnectors();
  saveLaunchedConnectors();
  buildAppMenu();
  await ensureCoreDesktopState();
  startCore();

  try {
    await waitForHttpReady(API_URL);
    const appModeOk = await ensureCoreInAppMode();
    if (!appModeOk) {
      dialog.showErrorBox(
        'DSX-Connect Desktop',
        `Detected core app_env is not "app".\n\n` +
        `Desktop uses app mode features and expects app_env=app.\n` +
        `Port ${API_PORT} may already be serving another DSX-Connect instance.`
      );
    }
    const rehydrated = await rehydrateLaunchedConnectorsOnStartup();
    if (rehydrated.failed && rehydrated.failed.length) {
      console.error('Connector rehydrate failures:', rehydrated.failed);
    }
    createWindow();
  } catch (err) {
    dialog.showErrorBox(
      'DSX Connect Local Launcher',
      `Could not start DSX Connect API at ${API_URL}.\n\n${err.message}`
    );
    app.quit();
  }

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', async () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('before-quit', async (event) => {
  if (app.__stopping) {
    if (shutdownWindow && !shutdownWindow.isDestroyed()) shutdownWindow.focus();
    return;
  }
  app.__stopping = true;
  event.preventDefault();
  showShutdownWindow();
  try {
    if (shouldStopConnectorsOnExit()) {
      await stopAllLaunchedConnectorsInternal({ showDialog: false, removeFromLauncher: false });
    }
  } catch {}
  try {
    if (shouldStopCoreOnExit()) {
      await stopCore();
    }
  } catch {}
  app.quit();
});
