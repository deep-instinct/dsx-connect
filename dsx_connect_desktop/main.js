const { app, BrowserWindow, dialog, Menu, shell } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const http = require('http');
const net = require('net');
const os = require('os');
const { randomUUID } = require('crypto');

const API_PORT = process.env.DSXCONNECT_LOCAL_PORT || '8586';
const API_URL = `http://127.0.0.1:${API_PORT}/`;
const REPO_ROOT = path.resolve(__dirname, '..');
const CORE_MANAGER = path.join(REPO_ROOT, 'dsx_connect', 'local', 'dsx_connect_local.py');
const FS_MANAGER = path.join(REPO_ROOT, 'connectors', 'filesystem', 'local', 'filesystem_local.py');
const SP_MANAGER = path.join(REPO_ROOT, 'connectors', 'sharepoint', 'local', 'sharepoint_local.py');

const CORE_STATE_DIR = path.join(os.homedir(), '.dsx-connect-local', 'dsx-connect-desktop');
const CORE_ENV_FILE = path.join(CORE_STATE_DIR, '.env.local');
const LAUNCHER_STATE_DIR = path.join(CORE_STATE_DIR, 'launcher');
const LAUNCHED_CONNECTORS_FILE = path.join(LAUNCHER_STATE_DIR, 'launched-connectors.json');
const APP_DISPLAY_NAME = 'DSX-Connect Desktop';

app.setName(APP_DISPLAY_NAME);

let mainWindow = null;
let coreProcess = null;
const launchedConnectors = [];

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

function scriptForKind(kind) {
  return kind === 'filesystem' ? FS_MANAGER : SP_MANAGER;
}

function displayForKind(kind) {
  return kind === 'filesystem' ? 'Filesystem' : 'SharePoint';
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

async function ensureCoreDesktopState() {
  fs.mkdirSync(CORE_STATE_DIR, { recursive: true });
  const init = await runPythonCommand(CORE_MANAGER, 'init', [], ['--state-dir', CORE_STATE_DIR]);
  if (!init.ok) {
    const detail = [init.stdout, init.stderr].filter(Boolean).join('\n');
    throw new Error(`Failed to initialize core state dir.\n${detail || 'Unknown error'}`);
  }
  upsertEnvValues(CORE_ENV_FILE, {
    DSXCONNECT_APP_ENV: 'app',
    DSXCONNECT_DIANNA__AUTO_ON_MALICIOUS: 'false'
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

function instanceStamp() {
  const now = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  const ts = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
  return `${ts}-${Math.floor(Math.random() * 1000).toString().padStart(3, '0')}`;
}

function connectorMenuLabel(item) {
  return `${item.display} ${item.id.slice(0, 10)}`;
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

function ensureConnectorIdentityEnv(stateDir) {
  const envPath = path.join(stateDir, '.env.local');
  const connectorDataDir = path.join(stateDir, 'data');
  upsertEnvValues(envPath, {
    DSXCONNECTOR_DATA_DIR: connectorDataDir,
    DSXCONNECTOR_APP_ENV: 'app'
  });
}

function connectorBaseUrl(item) {
  const pathPart = item.kind === 'filesystem' ? 'filesystem-connector' : 'sharepoint-connector';
  return `http://127.0.0.1:${item.port}/${pathPart}`;
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

function loadLaunchedConnectors() {
  try {
    if (!exists(LAUNCHED_CONNECTORS_FILE)) return;
    const raw = fs.readFileSync(LAUNCHED_CONNECTORS_FILE, 'utf8');
    const data = JSON.parse(raw);
    if (!Array.isArray(data)) return;

    for (const item of data) {
      if (!item || (item.kind !== 'filesystem' && item.kind !== 'sharepoint')) continue;
      if (typeof item.id !== 'string' || !item.id) continue;
      if (typeof item.stateDir !== 'string' || !item.stateDir) continue;
      const port = Number(item.port);
      if (!Number.isInteger(port) || port <= 0) continue;
      if (!exists(item.stateDir)) continue;

      launchedConnectors.push({
        id: item.id,
        kind: item.kind,
        display: displayForKind(item.kind),
        script: scriptForKind(item.kind),
        stateDir: item.stateDir,
        port
      });
    }
  } catch (err) {
    console.error('Failed to load launched connectors:', err);
  }
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
  for (const item of connectors) {
    const uuid = item && item.uuid ? String(item.uuid) : '';
    if (!uuid) continue;
    const del = await httpJson('DELETE', `${API_URL}dsx-connect/api/v1/connectors/unregister/${uuid}`);
    if (del.ok) removed += 1;
  }

  dialog.showMessageBox({
    type: 'info',
    title: 'Cleanup Connector Registry',
    message: `Attempted cleanup for ${connectors.length} connector(s).`,
    detail: `Unregister requests succeeded for ${removed} connector(s).`
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

async function findAvailablePort(startPort) {
  for (let p = startPort; p < startPort + 400; p += 1) {
    if (await isPortFree(p)) return p;
  }
  throw new Error(`No free port found from ${startPort}`);
}

async function launchConnectorInstance(kind) {
  const script = scriptForKind(kind);
  const display = displayForKind(kind);
  const basePort = kind === 'filesystem' ? 8620 : 8640;
  const root = kind === 'filesystem' ? 'filesystem-connector' : 'sharepoint-connector';
  const stamp = instanceStamp();
  const id = randomUUID();
  const stateDir = path.join(os.homedir(), '.dsx-connect-local', `${root}-${stamp}`);
  const port = await findAvailablePort(basePort);
  const globalArgs = ['--state-dir', stateDir, '--port', String(port)];

  const init = await runPythonCommand(script, 'init', [], globalArgs);
  if (!init.ok) {
    const detail = [init.stdout, init.stderr].filter(Boolean).join('\n');
    dialog.showErrorBox(`Launch ${display} Connector`, `Init failed.\n\n${detail || 'Unknown error'}`);
    return;
  }

  // Ensure each launched instance has its own connector UUID persistence path.
  // Without this, multiple instances of the same connector type can share identity.
  ensureConnectorIdentityEnv(stateDir);

  const start = await runPythonCommand(script, 'start', [], globalArgs);
  if (!start.ok) {
    const detail = [start.stdout, start.stderr].filter(Boolean).join('\n');
    dialog.showErrorBox(`Launch ${display} Connector`, `Start failed.\n\n${detail || 'Unknown error'}`);
    return;
  }

  launchedConnectors.push({
    id,
    kind,
    display,
    script,
    stateDir,
    port
  });
  saveLaunchedConnectors();
  buildAppMenu();
}

function buildConnectorItemSubmenu(item) {
  const extraFilesystemItems =
    item.kind === 'filesystem'
      ? [
          { type: 'separator' },
          {
            label: 'Set Asset Folder...',
            click: async () => {
              await setFilesystemAssetFolder(item);
            }
          }
        ]
      : [];

  return [
    {
      label: 'Start',
      click: async () => {
        ensureConnectorIdentityEnv(item.stateDir);
        const result = await runPythonCommand(item.script, 'start', [], [
          '--state-dir',
          item.stateDir,
          '--port',
          String(item.port)
        ]);
        if (!result.ok) {
          const detail = [result.stdout, result.stderr].filter(Boolean).join('\n');
          dialog.showErrorBox('Start Connector', `${connectorMenuLabel(item)}\n\n${detail || 'Unknown error'}`);
          return;
        }
      }
    },
    {
      label: 'Status',
      click: async () => {
        const result = await runPythonCommand(item.script, 'status', [], [
          '--state-dir',
          item.stateDir,
          '--port',
          String(item.port)
        ]);
        if (!result.ok) {
          const detail = [result.stdout, result.stderr].filter(Boolean).join('\n');
          dialog.showErrorBox('Connector Status', `${connectorMenuLabel(item)}\n\n${detail || 'Unknown error'}`);
          return;
        }
        dialog.showMessageBox({
          type: 'info',
          title: 'Connector Status',
          message: connectorMenuLabel(item),
          detail: [result.stdout, result.stderr].filter(Boolean).join('\n')
        });
      }
    },
    {
      label: 'Stop',
      click: async () => {
        const result = await runPythonCommand(item.script, 'stop', [], [
          '--state-dir',
          item.stateDir,
          '--port',
          String(item.port)
        ]);
        if (!result.ok) {
          const detail = [result.stdout, result.stderr].filter(Boolean).join('\n');
          dialog.showErrorBox('Stop Connector', `${connectorMenuLabel(item)}\n\n${detail || 'Unknown error'}`);
          return;
        }
      }
    },
    {
      label: 'Open State Directory',
      click: () => {
        shell.openPath(item.stateDir);
      }
    },
    ...extraFilesystemItems,
    {
      type: 'separator'
    },
    {
      label: 'Forget from Launcher',
      click: () => {
        const idx = launchedConnectors.findIndex((x) => x.id === item.id);
        if (idx >= 0) launchedConnectors.splice(idx, 1);
        saveLaunchedConnectors();
        buildAppMenu();
      }
    }
  ];
}

function buildAppMenu() {
  const launchedSubmenu = launchedConnectors.length
    ? launchedConnectors.map((item) => ({
        label: connectorMenuLabel(item),
        submenu: buildConnectorItemSubmenu(item)
      }))
    : [{ label: 'No launched connectors', enabled: false }];

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
      label: 'Connectors...',
      submenu: [
        {
          label: 'Launch...',
          submenu: [
            {
              label: 'Filesystem',
              click: () => {
                launchConnectorInstance('filesystem').catch((err) => {
                  dialog.showErrorBox('Launch Filesystem Connector', String(err && err.message ? err.message : err));
                });
              }
            },
            {
              label: 'SharePoint',
              click: () => {
                launchConnectorInstance('sharepoint').catch((err) => {
                  dialog.showErrorBox('Launch SharePoint Connector', String(err && err.message ? err.message : err));
                });
              }
            }
          ]
        },
        {
          label: 'Cleanup Registry (stale)',
          click: () => {
            cleanupConnectorRegistry().catch((err) => {
              dialog.showErrorBox('Cleanup Connector Registry', String(err && err.message ? err.message : err));
            });
          }
        },
        { type: 'separator' },
        {
          label: 'Launched',
          submenu: launchedSubmenu
        }
      ]
    },
    {
      label: 'View',
      submenu: [
        { role: 'reload' },
        { role: 'forceReload' },
        { role: 'toggleDevTools' },
        { type: 'separator' },
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

app.whenReady().then(async () => {
  loadLaunchedConnectors();
  buildAppMenu();
  await ensureCoreDesktopState();
  startCore();

  try {
    await waitForHttpReady(API_URL);
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
    if (process.env.DSXCONNECT_STOP_ON_EXIT === '1') {
      await stopCore();
    }
    app.quit();
  }
});

app.on('before-quit', async (event) => {
  if (process.env.DSXCONNECT_STOP_ON_EXIT !== '1') return;
  if (app.__stopping) return;
  app.__stopping = true;
  event.preventDefault();
  await stopCore();
  app.quit();
});
