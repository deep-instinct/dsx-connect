const cp = require("node:child_process");
const path = require("node:path");
const vscode = require("vscode");

let output;
let diagnostics;
let reportProvider;

class ReportTreeProvider {
  constructor() {
    this.items = [];
    this._onDidChangeTreeData = new vscode.EventEmitter();
    this.onDidChangeTreeData = this._onDidChangeTreeData.event;
  }

  setReport(report) {
    if (!report) {
      this.items = [];
      this._onDidChangeTreeData.fire();
      return;
    }
    const outcomes = report.outcomes || [];
    const blocked = outcomes.filter((outcome) => outcome.state === "blocked");
    const failed = outcomes.filter((outcome) => outcome.state === "failed");
    this.items = [
      {
        label: report.transfer_id || "Transfer",
        description: `planned ${report.planned_count ?? outcomes.length}, allowed ${report.allowed_count ?? 0}, blocked ${report.blocked_count ?? 0}, failed ${report.failed_count ?? 0}`,
        children: [
          { label: `Source: ${report.source_uri || ""}` },
          { label: `Destination: ${report.destination_uri || ""}` },
          { label: `Policy: ${report.policy_id || "none"}` },
        ],
      },
      {
        label: "Blocked",
        description: String(blocked.length),
        children: blocked.map(outcomeTreeItem),
      },
      {
        label: "Failed",
        description: String(failed.length),
        children: failed.map(outcomeTreeItem),
      },
    ];
    this._onDidChangeTreeData.fire();
  }

  getTreeItem(item) {
    const treeItem = new vscode.TreeItem(
      item.label,
      item.children?.length ? vscode.TreeItemCollapsibleState.Expanded : vscode.TreeItemCollapsibleState.None
    );
    treeItem.description = item.description;
    treeItem.tooltip = item.tooltip || item.description || item.label;
    return treeItem;
  }

  getChildren(item) {
    if (item) {
      return item.children || [];
    }
    return this.items.length ? this.items : [{ label: "No transfer report yet." }];
  }
}

function outcomeTreeItem(outcome) {
  const item = outcome.item || {};
  const decision = outcome.decision || {};
  return {
    label: item.object_identity || item.source_uri || "object",
    description: decision.verdict || outcome.state,
    tooltip: JSON.stringify(outcome, null, 2),
    children: [
      { label: `Action: ${decision.action || outcome.state}` },
      { label: `Reason: ${decision.reason || outcome.error?.message || ""}` },
      { label: `Source: ${item.source_uri || ""}` },
      { label: `Destination: ${item.destination_uri || ""}` },
    ],
  };
}

function config() {
  return vscode.workspace.getConfiguration("dsxTransfer");
}

function workspaceRoot() {
  return vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || process.cwd();
}

function resolveWorkspacePath(value) {
  if (!value) return workspaceRoot();
  return path.isAbsolute(value) ? value : path.join(workspaceRoot(), value);
}

function settings() {
  const cfg = config();
  return {
    executable: String(cfg.get("executable") || "dsx-transfer"),
    configPath: String(cfg.get("configPath") || "dsx-transfer.yaml"),
    pythonPath: String(cfg.get("pythonPath") || ""),
    useModuleInvocation: Boolean(cfg.get("useModuleInvocation") || false),
    modulePythonPath: String(cfg.get("modulePythonPath") || ".:dsx_transfer:dsxa_sdk_py"),
    extraEnv: cfg.get("extraEnv") || {},
  };
}

function configUri() {
  return vscode.Uri.file(resolveWorkspacePath(settings().configPath));
}

function buildCommand(args) {
  const current = settings();
  const env = { ...process.env, ...current.extraEnv };
  if (current.useModuleInvocation) {
    if (current.modulePythonPath) {
      env.PYTHONPATH = current.modulePythonPath;
    }
    return {
      executable: current.pythonPath || "python",
      args: ["-m", "dsx_transfer.cli", ...args],
      env,
    };
  }
  return {
    executable: current.executable,
    args,
    env,
  };
}

function runCli(args) {
  const command = buildCommand(args);
  output.appendLine(`$ ${command.executable} ${command.args.join(" ")}`);
  return new Promise((resolve) => {
    cp.execFile(
      command.executable,
      command.args,
      {
        cwd: workspaceRoot(),
        env: command.env,
        maxBuffer: 20 * 1024 * 1024,
      },
      (error, stdout, stderr) => {
        if (stdout) output.append(stdout);
        if (stderr) output.append(stderr);
        resolve({
          ok: !error,
          code: error?.code || 0,
          error,
          stdout,
          stderr,
        });
      }
    );
  });
}

async function pathExists(filePath) {
  try {
    await vscode.workspace.fs.stat(vscode.Uri.file(filePath));
    return true;
  } catch {
    return false;
  }
}

function diagnostic(uri, message, severity) {
  return new vscode.Diagnostic(
    new vscode.Range(0, 0, 0, Number.MAX_SAFE_INTEGER),
    message,
    severity
  );
}

async function createConfig() {
  output.show(true);
  const target = configUri();
  const args = ["config", "init", "--preset", "filesystem-to-gcs", "--output", target.fsPath];
  if (await pathExists(target.fsPath)) {
    const choice = await vscode.window.showWarningMessage(
      `${path.basename(target.fsPath)} already exists.`,
      "Open Existing",
      "Overwrite",
      "Cancel"
    );
    if (choice === "Open Existing") {
      const doc = await vscode.workspace.openTextDocument(target);
      await vscode.window.showTextDocument(doc, { preview: false });
      return;
    }
    if (choice !== "Overwrite") {
      return;
    }
    args.push("--force");
  }
  const result = await runCli(args);
  if (!result.ok) {
    vscode.window.showErrorMessage("DSX-Transfer config creation failed. See DSX-Transfer output.");
    return;
  }
  const doc = await vscode.workspace.openTextDocument(target);
  await vscode.window.showTextDocument(doc, { preview: false });
  vscode.window.showInformationMessage(`Created ${path.basename(target.fsPath)}.`);
}

async function validateConfig(options = {}) {
  const target = configUri();
  const result = await runCli(["config", "validate", "--config", target.fsPath]);
  let parsed;
  try {
    parsed = JSON.parse(result.stdout || "{}");
  } catch (error) {
    parsed = {
      valid: false,
      errors: [`Unable to parse dsx-transfer config diagnostics: ${error.message}`],
      warnings: [],
    };
  }
  const items = [];
  for (const message of parsed.errors || []) {
    items.push(diagnostic(target, message, vscode.DiagnosticSeverity.Error));
  }
  for (const message of parsed.warnings || []) {
    items.push(diagnostic(target, message, vscode.DiagnosticSeverity.Warning));
  }
  diagnostics.set(target, items);
  if (!options.silent) {
    if (parsed.valid) {
      vscode.window.showInformationMessage(`DSX-Transfer config valid${parsed.warnings?.length ? ` with ${parsed.warnings.length} warning(s)` : ""}.`);
    } else {
      vscode.window.showErrorMessage(`DSX-Transfer config invalid: ${parsed.errors?.length || 0} error(s).`);
    }
  }
  return parsed;
}

function parseReport(stdout) {
  const lines = String(stdout || "").trim().split(/\r?\n/).filter(Boolean);
  for (let index = lines.length - 1; index >= 0; index -= 1) {
    try {
      const parsed = JSON.parse(lines[index]);
      if (parsed && Array.isArray(parsed.outcomes)) {
        return parsed;
      }
    } catch {
      continue;
    }
  }
  return null;
}

async function runTransfer() {
  output.show(true);
  const validation = await validateConfig({ silent: true });
  if (!validation.valid) {
    vscode.window.showErrorMessage("DSX-Transfer config is invalid. Fix diagnostics before running.");
    return;
  }
  const result = await runCli(["migrate", "--config", configUri().fsPath]);
  const report = parseReport(result.stdout);
  if (report) {
    reportProvider.setReport(report);
    const summary = `planned ${report.planned_count ?? report.outcomes.length}, allowed ${report.allowed_count ?? 0}, blocked ${report.blocked_count ?? 0}, failed ${report.failed_count ?? 0}`;
    output.appendLine(`DSX-Transfer summary: ${summary}`);
    if (result.ok) {
      vscode.window.showInformationMessage(`DSX-Transfer complete: ${summary}.`);
    } else {
      vscode.window.showErrorMessage(`DSX-Transfer finished with failures: ${summary}.`);
    }
    return;
  }
  if (result.ok) {
    vscode.window.showInformationMessage("DSX-Transfer command completed.");
  } else {
    vscode.window.showErrorMessage("DSX-Transfer command failed. See DSX-Transfer output.");
  }
}

async function checkEnvironment() {
  output.show(true);
  const checks = [];
  const command = buildCommand(["--help"]);
  checks.push(`workspace: ${workspaceRoot()}`);
  checks.push(`config: ${configUri().fsPath}`);
  checks.push(`invocation: ${command.executable} ${command.args.join(" ")}`);
  checks.push(`GOOGLE_APPLICATION_CREDENTIALS: ${command.env.GOOGLE_APPLICATION_CREDENTIALS ? "set" : "not set"}`);
  const help = await runCli(["--help"]);
  checks.push(`cli: ${help.ok ? "ok" : "failed"}`);
  const configFileExists = await pathExists(configUri().fsPath);
  checks.push(`config file: ${configFileExists ? "exists" : "missing"}`);
  output.appendLine("DSX-Transfer environment:");
  for (const check of checks) {
    output.appendLine(`- ${check}`);
  }
  if (help.ok && configFileExists) {
    vscode.window.showInformationMessage("DSX-Transfer environment check passed.");
  } else {
    vscode.window.showWarningMessage("DSX-Transfer environment check found issues. See output.");
  }
}

async function showSchema() {
  output.show(true);
  const result = await runCli(["config", "schema"]);
  if (!result.ok) {
    vscode.window.showErrorMessage("Unable to load DSX-Transfer schema. See DSX-Transfer output.");
    return;
  }
  const doc = await vscode.workspace.openTextDocument({
    language: "json",
    content: result.stdout,
  });
  await vscode.window.showTextDocument(doc, { preview: false });
}

function activate(context) {
  output = vscode.window.createOutputChannel("DSX-Transfer");
  diagnostics = vscode.languages.createDiagnosticCollection("dsx-transfer");
  reportProvider = new ReportTreeProvider();
  context.subscriptions.push(output);
  context.subscriptions.push(diagnostics);
  context.subscriptions.push(vscode.window.registerTreeDataProvider("dsxTransferReport", reportProvider));
  context.subscriptions.push(vscode.commands.registerCommand("dsxTransfer.createConfig", createConfig));
  context.subscriptions.push(vscode.commands.registerCommand("dsxTransfer.validateConfig", () => validateConfig()));
  context.subscriptions.push(vscode.commands.registerCommand("dsxTransfer.runTransfer", runTransfer));
  context.subscriptions.push(vscode.commands.registerCommand("dsxTransfer.showSchema", showSchema));
  context.subscriptions.push(vscode.commands.registerCommand("dsxTransfer.checkEnvironment", checkEnvironment));
  context.subscriptions.push(vscode.workspace.onDidSaveTextDocument((document) => {
    if (document.uri.scheme !== "file") return;
    if (path.resolve(document.uri.fsPath) !== path.resolve(configUri().fsPath)) return;
    validateConfig({ silent: true });
  }));
}

function deactivate() {}

module.exports = {
  activate,
  deactivate,
};
