const fs = require("node:fs");
const path = require("node:path");
const vscode = require("vscode");

let output;
let scanResultsProvider;
let integrationPointsProvider;

class StaticTreeProvider {
  constructor(emptyLabel) {
    this.emptyLabel = emptyLabel;
    this.items = [];
    this._onDidChangeTreeData = new vscode.EventEmitter();
    this.onDidChangeTreeData = this._onDidChangeTreeData.event;
  }

  setItems(items) {
    this.items = items;
    this._onDidChangeTreeData.fire();
  }

  getTreeItem(item) {
    if (item.kind === "empty") {
      const treeItem = new vscode.TreeItem(item.label, vscode.TreeItemCollapsibleState.None);
      treeItem.contextValue = "empty";
      return treeItem;
    }
    const treeItem = new vscode.TreeItem(item.label, item.children?.length ? vscode.TreeItemCollapsibleState.Collapsed : vscode.TreeItemCollapsibleState.None);
    treeItem.description = item.description;
    treeItem.tooltip = item.tooltip || item.description || item.label;
    treeItem.contextValue = item.contextValue;
    if (item.resourceUri) {
      treeItem.resourceUri = item.resourceUri;
      treeItem.command = {
        command: "vscode.open",
        title: "Open",
        arguments: [item.resourceUri],
      };
    }
    return treeItem;
  }

  getChildren(item) {
    if (item) {
      return item.children || [];
    }
    if (this.items.length) {
      return this.items;
    }
    return [{ kind: "empty", label: this.emptyLabel }];
  }
}

function config() {
  return vscode.workspace.getConfiguration("dsxa");
}

function getConnectionConfig() {
  const cfg = config();
  return {
    baseUrl: String(cfg.get("baseUrl") || "").replace(/\/$/, ""),
    authToken: String(cfg.get("authToken") || ""),
    concurrency: Number(cfg.get("scanConcurrency") || 4),
    maxFileSizeBytes: Number(cfg.get("maxFileSizeBytes") || 2147483648),
    includeGlob: String(cfg.get("workspaceIncludeGlob") || "**/*"),
    excludeGlob: String(cfg.get("workspaceExcludeGlob") || ""),
    integrationMode: String(cfg.get("integrationMode") || "direct-dsxa"),
    dsxConnectNgBaseUrl: String(cfg.get("dsxConnectNgBaseUrl") || "").replace(/\/$/, ""),
  };
}

async function loadDsxaSdk() {
  try {
    return await import("@deep-instinct/dsxa-sdk-js/node");
  } catch (error) {
    throw new Error(`Unable to load @deep-instinct/dsxa-sdk-js. Run npm install in dsxa_assistant_vscode_ext. ${error.message}`);
  }
}

async function configureConnection() {
  const current = getConnectionConfig();
  const baseUrl = await vscode.window.showInputBox({
    title: "DSXA Base URL",
    value: current.baseUrl,
    prompt: "Example: http://127.0.0.1:5000",
    ignoreFocusOut: true,
  });
  if (!baseUrl) return;
  const authToken = await vscode.window.showInputBox({
    title: "DSXA Auth Token",
    value: current.authToken,
    password: true,
    prompt: "Optional",
    ignoreFocusOut: true,
  });
  await config().update("baseUrl", baseUrl, vscode.ConfigurationTarget.Workspace);
  await config().update("authToken", authToken || "", vscode.ConfigurationTarget.Workspace);
  vscode.window.showInformationMessage("DSXA connection settings updated.");
}

async function healthCheck() {
  const { baseUrl, authToken } = getConnectionConfig();
  if (!baseUrl) {
    vscode.window.showWarningMessage("Configure dsxa.baseUrl first.");
    return;
  }
  const headers = {};
  if (authToken) {
    headers.AUTH = authToken;
    headers.AUTH_TOKEN = authToken;
    headers.Authorization = `Bearer ${authToken}`;
  }
  const candidates = ["/health", "/healthz", "/api/v1/health"];
  for (const candidate of candidates) {
    const url = `${baseUrl}${candidate}`;
    try {
      const response = await fetch(url, { headers });
      const body = await response.text();
      if (response.ok) {
        output.appendLine(`health ok ${url}`);
        output.appendLine(body);
        vscode.window.showInformationMessage(`DSXA health check passed: ${candidate}`);
        return;
      }
      output.appendLine(`health failed ${url}: ${response.status} ${body}`);
    } catch (error) {
      output.appendLine(`health failed ${url}: ${error.message}`);
    }
  }
  vscode.window.showErrorMessage("DSXA health check failed. See DSXA Assistant output.");
}

function normalizeScanResponse(result) {
  if (!result) return {};
  if (typeof result.toJSON === "function") {
    return result.toJSON();
  }
  return result;
}

function verdictFromResult(result) {
  const raw = normalizeScanResponse(result);
  return raw.verdict || raw.Verdict || raw.scanResult || raw.status || "unknown";
}

async function scanFilePath(filePath) {
  const { baseUrl, authToken, maxFileSizeBytes } = getConnectionConfig();
  if (!baseUrl) {
    throw new Error("Configure dsxa.baseUrl first.");
  }
  const stat = await fs.promises.stat(filePath);
  if (!stat.isFile()) {
    throw new Error(`${filePath} is not a file.`);
  }
  if (stat.size > maxFileSizeBytes) {
    return {
      file: filePath,
      status: "skipped",
      verdict: "too_large",
      size: stat.size,
      result: { reason: "max_file_size_exceeded" },
    };
  }
  const { DSXAClient, scanFilePath: sdkScanFilePath } = await loadDsxaSdk();
  const client = new DSXAClient({ baseUrl, authToken: authToken || undefined });
  const started = Date.now();
  const result = await sdkScanFilePath(client, filePath, { customMetadata: "source=dsxa_assistant_vscode_ext" });
  const elapsedMs = Date.now() - started;
  return {
    file: filePath,
    status: "ok",
    verdict: verdictFromResult(result),
    elapsedMs,
    result: normalizeScanResponse(result),
  };
}

function resultTreeItems(results) {
  return results.map((entry) => {
    const label = path.basename(entry.file);
    const description = `${entry.verdict || entry.status} ${entry.elapsedMs ? `${entry.elapsedMs}ms` : ""}`.trim();
    const children = [
      { label: `Path: ${entry.file}`, description: "", tooltip: entry.file },
      { label: `Verdict: ${entry.verdict || "unknown"}`, description: entry.status },
    ];
    if (entry.result) {
      children.push({ label: "Raw response", description: JSON.stringify(entry.result).slice(0, 80), tooltip: JSON.stringify(entry.result, null, 2) });
    }
    if (entry.error) {
      children.push({ label: "Error", description: entry.error, tooltip: entry.error });
    }
    return {
      label,
      description,
      tooltip: JSON.stringify(entry, null, 2),
      resourceUri: vscode.Uri.file(entry.file),
      children,
    };
  });
}

async function scanFiles(filePaths) {
  if (!filePaths.length) return;
  output.show(true);
  const { concurrency } = getConnectionConfig();
  const results = [];
  let nextIndex = 0;
  let completed = 0;
  await vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: `DSXA scanning ${filePaths.length} file(s)`,
      cancellable: false,
    },
    async (progress) => {
      async function worker() {
        while (nextIndex < filePaths.length) {
          const index = nextIndex;
          nextIndex += 1;
          const filePath = filePaths[index];
          progress.report({ message: path.basename(filePath) });
          try {
            const result = await scanFilePath(filePath);
            results[index] = result;
            output.appendLine(`${result.status} ${result.verdict} ${filePath}`);
          } catch (error) {
            const failed = { file: filePath, status: "failed", verdict: "error", error: error.message };
            results[index] = failed;
            output.appendLine(`failed ${filePath}: ${error.message}`);
          } finally {
            completed += 1;
            progress.report({ increment: 100 / filePaths.length, message: `${completed}/${filePaths.length}` });
          }
        }
      }
      const workerCount = Math.max(1, Math.min(Number(concurrency) || 1, filePaths.length));
      await Promise.all(Array.from({ length: workerCount }, () => worker()));
    }
  );
  const compactResults = results.filter(Boolean);
  scanResultsProvider.setItems(resultTreeItems(compactResults));
  const malicious = compactResults.filter((item) => String(item.verdict).toLowerCase().includes("malicious")).length;
  vscode.window.showInformationMessage(`DSXA scan complete: ${compactResults.length} files, ${malicious} malicious.`);
}

async function scanCurrentFile() {
  const editor = vscode.window.activeTextEditor;
  if (!editor?.document?.uri || editor.document.uri.scheme !== "file") {
    vscode.window.showWarningMessage("Open a local file first.");
    return;
  }
  await scanFiles([editor.document.uri.fsPath]);
}

async function scanSelectedFiles(firstUri, selectedUris = []) {
  const uris = selectedUris.length ? selectedUris : firstUri ? [firstUri] : [];
  const files = [];
  for (const uri of uris) {
    if (uri.scheme !== "file") continue;
    const stat = await fs.promises.stat(uri.fsPath);
    if (stat.isFile()) {
      files.push(uri.fsPath);
    } else if (stat.isDirectory()) {
      const found = await collectFilesInFolder(uri.fsPath);
      files.push(...found);
    }
  }
  await scanFiles(files);
}

async function collectFilesInFolder(folderPath) {
  const out = [];
  async function walk(current) {
    const entries = await fs.promises.readdir(current, { withFileTypes: true });
    for (const entry of entries) {
      if (entry.name === ".git" || entry.name === "node_modules" || entry.name === ".venv" || entry.name === "venv") continue;
      const full = path.join(current, entry.name);
      if (entry.isDirectory()) {
        await walk(full);
      } else if (entry.isFile()) {
        out.push(full);
      }
    }
  }
  await walk(folderPath);
  return out;
}

async function scanWorkspaceFolder() {
  const folders = vscode.workspace.workspaceFolders || [];
  if (!folders.length) {
    vscode.window.showWarningMessage("Open a workspace folder first.");
    return;
  }
  const { includeGlob, excludeGlob } = getConnectionConfig();
  const files = await vscode.workspace.findFiles(includeGlob, excludeGlob || undefined);
  const picked = await vscode.window.showWarningMessage(
    `Scan ${files.length} workspace file(s) with DSXA?`,
    { modal: true },
    "Scan"
  );
  if (picked !== "Scan") return;
  await scanFiles(files.map((uri) => uri.fsPath));
}

const integrationPatterns = [
  {
    language: "Node/Express",
    glob: "**/*.{js,ts,mjs,cjs}",
    patterns: [
      { regex: /multer\s*\(|upload\.single\s*\(|upload\.array\s*\(|req\.file|req\.files/g, reason: "Express multipart upload handler" },
      { regex: /busboy|formidable|express-fileupload/g, reason: "Node multipart parser" },
      { regex: /\.putObject\s*\(|\.upload\s*\(|PutObjectCommand/g, reason: "Object storage write" },
    ],
  },
  {
    language: "Python",
    glob: "**/*.py",
    patterns: [
      { regex: /UploadFile|File\s*\(|request\.FILES|request\.files/g, reason: "HTTP file upload handler" },
      { regex: /\.save\s*\(|upload_file\s*\(|put_object\s*\(/g, reason: "Local or object storage write" },
    ],
  },
  {
    language: "Java",
    glob: "**/*.java",
    patterns: [
      { regex: /MultipartFile|@RequestPart|@RequestParam\s*\([^)]*file/g, reason: "Spring multipart upload handler" },
      { regex: /putObject\s*\(|Files\.copy\s*\(/g, reason: "Storage write" },
    ],
  },
  {
    language: ".NET",
    glob: "**/*.{cs,fs}",
    patterns: [
      { regex: /IFormFile|Request\.Form\.Files|FromForm/g, reason: ".NET multipart upload handler" },
      { regex: /CopyToAsync|UploadAsync|PutObjectAsync/g, reason: "Storage write" },
    ],
  },
  {
    language: "Go",
    glob: "**/*.go",
    patterns: [
      { regex: /FormFile\s*\(|MultipartReader\s*\(/g, reason: "Go multipart upload handler" },
      { regex: /PutObject|io\.Copy\s*\(/g, reason: "Storage write" },
    ],
  },
];

async function findIntegrationPoints() {
  const findings = [];
  const exclude = "**/{node_modules,.git,.venv,venv,dist,build,target,__pycache__}/**";
  for (const group of integrationPatterns) {
    const files = await vscode.workspace.findFiles(group.glob, exclude, 2000);
    for (const uri of files) {
      let text;
      try {
        text = await fs.promises.readFile(uri.fsPath, "utf8");
      } catch {
        continue;
      }
      const lines = text.split(/\r?\n/);
      for (let lineIndex = 0; lineIndex < lines.length; lineIndex += 1) {
        const line = lines[lineIndex];
        for (const pattern of group.patterns) {
          pattern.regex.lastIndex = 0;
          if (pattern.regex.test(line)) {
            findings.push({
              file: uri.fsPath,
              line: lineIndex + 1,
              language: group.language,
              reason: pattern.reason,
              preview: line.trim().slice(0, 180),
            });
          }
        }
      }
    }
  }
  integrationPointsProvider.setItems(findings.map((finding) => ({
    label: `${path.basename(finding.file)}:${finding.line}`,
    description: `${finding.language} - ${finding.reason}`,
    tooltip: `${finding.file}:${finding.line}\n${finding.preview}`,
    resourceUri: vscode.Uri.file(finding.file),
    children: [
      { label: finding.reason, description: finding.language },
      { label: "Preview", description: finding.preview, tooltip: finding.preview },
    ],
  })));
  output.appendLine(`found ${findings.length} possible DSXA integration point(s)`);
  vscode.window.showInformationMessage(`Found ${findings.length} possible DSXA integration point(s).`);
  return findings;
}

function directDsxaSnippet(language) {
  if (language === "Node/Express") {
    return [
      "import { DSXAClient } from \"@deep-instinct/dsxa-sdk-js\";",
      "import { scanFilePath } from \"@deep-instinct/dsxa-sdk-js/node\";",
      "",
      "const dsxa = new DSXAClient({ baseUrl: process.env.DSXA_BASE_URL, authToken: process.env.DSXA_AUTH_TOKEN });",
      "const scan = await scanFilePath(dsxa, req.file.path, { customMetadata: \"source=app-upload\" });",
      "if (String(scan.verdict).toLowerCase().includes(\"malicious\")) {",
      "  return res.status(422).json({ error: \"file_rejected\" });",
      "}",
    ].join("\n");
  }
  if (language === "Python") {
    return [
      "from dsxa_sdk_py import DSXAClient",
      "",
      "client = DSXAClient(base_url=os.environ[\"DSXA_BASE_URL\"], auth_token=os.getenv(\"DSXA_AUTH_TOKEN\"))",
      "scan = client.scan_binary(open(path, \"rb\"))",
      "if str(scan.verdict).lower() == \"malicious\":",
      "    raise ValueError(\"file_rejected\")",
    ].join("\n");
  }
  return "Add a DSXA scan call after receiving the file and before making it visible to users.";
}

async function generateIntegrationPlan() {
  const findings = await findIntegrationPoints();
  const { integrationMode, dsxConnectNgBaseUrl } = getConnectionConfig();
  const grouped = new Map();
  for (const finding of findings) {
    const key = finding.language;
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key).push(finding);
  }
  const lines = [
    "# DSXA Application Integration Plan",
    "",
    `Mode: ${integrationMode}`,
    "",
    "## Recommended Flow",
    "",
    "- Scan after file receipt and before the file becomes visible or executable.",
    "- Quarantine or reject malicious files.",
    "- Treat scanner timeout/unavailable as a policy decision, not as an unhandled exception.",
    "- Add tests for benign, malicious, timeout, and scanner-unavailable cases.",
    "",
  ];
  if (integrationMode === "dsx-connect-ng") {
    lines.push("## DSX-Connect NG Mode", "", `Submit scan jobs to ${dsxConnectNgBaseUrl || "DSX_CONNECT_NG_BASE_URL"}.`, "");
  }
  for (const [language, items] of grouped.entries()) {
    lines.push(`## ${language}`, "");
    for (const item of items.slice(0, 20)) {
      lines.push(`- \`${path.relative(vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || process.cwd(), item.file)}:${item.line}\` - ${item.reason}`);
      lines.push(`  - \`${item.preview}\``);
    }
    lines.push("", "Suggested direct DSXA snippet:", "", "```", directDsxaSnippet(language), "```", "");
  }
  if (!findings.length) {
    lines.push("No obvious upload handlers were detected. Start by searching for the code path that first receives or persists user-controlled files.");
  }
  const doc = await vscode.workspace.openTextDocument({
    language: "markdown",
    content: lines.join("\n"),
  });
  await vscode.window.showTextDocument(doc, { preview: false });
}

function activate(context) {
  output = vscode.window.createOutputChannel("DSXA Assistant");
  scanResultsProvider = new StaticTreeProvider("No scan results yet.");
  integrationPointsProvider = new StaticTreeProvider("No integration points scanned yet.");
  context.subscriptions.push(output);
  context.subscriptions.push(vscode.window.registerTreeDataProvider("dsxaScanResults", scanResultsProvider));
  context.subscriptions.push(vscode.window.registerTreeDataProvider("dsxaIntegrationPoints", integrationPointsProvider));
  context.subscriptions.push(vscode.commands.registerCommand("dsxa.configure", configureConnection));
  context.subscriptions.push(vscode.commands.registerCommand("dsxa.healthCheck", healthCheck));
  context.subscriptions.push(vscode.commands.registerCommand("dsxa.scanCurrentFile", scanCurrentFile));
  context.subscriptions.push(vscode.commands.registerCommand("dsxa.scanSelectedFiles", scanSelectedFiles));
  context.subscriptions.push(vscode.commands.registerCommand("dsxa.scanWorkspaceFolder", scanWorkspaceFolder));
  context.subscriptions.push(vscode.commands.registerCommand("dsxa.findIntegrationPoints", findIntegrationPoints));
  context.subscriptions.push(vscode.commands.registerCommand("dsxa.generateIntegrationPlan", generateIntegrationPlan));
}

function deactivate() {}

module.exports = {
  activate,
  deactivate,
};
