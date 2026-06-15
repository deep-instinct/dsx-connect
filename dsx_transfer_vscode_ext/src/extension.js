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
    treeItem.contextValue = item.contextValue;
    treeItem.command = item.command;
    return treeItem;
  }

  getChildren(item) {
    if (item) {
      return item.children || [];
    }
    return this.items;
  }
}

function outcomeTreeItem(outcome) {
  const item = outcome.item || {};
  const decision = outcome.decision || {};
  return {
    label: item.object_identity || item.source_uri || "object",
    description: decision.verdict || outcome.state,
    contextValue: "reportOutcome",
    command: {
      command: "dsxTransfer.openReportItemJson",
      title: "Open Report Item JSON",
      arguments: [outcome],
    },
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

function relativeWorkspacePath(filePath) {
  const relative = path.relative(workspaceRoot(), filePath);
  if (relative.startsWith("..") || path.isAbsolute(relative)) {
    return null;
  }
  return relative.split(path.sep).join("/");
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

function localHarnessConfigUri() {
  return vscode.Uri.file(path.join(workspaceRoot(), ".dsx-transfer", "harness", "dsx-transfer.local.yaml"));
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

async function ensureDirectory(dirPath) {
  await vscode.workspace.fs.createDirectory(vscode.Uri.file(dirPath));
}

async function writeTextFile(filePath, content, options = {}) {
  if (!options.overwrite && await pathExists(filePath)) {
    return false;
  }
  await ensureDirectory(path.dirname(filePath));
  await vscode.workspace.fs.writeFile(vscode.Uri.file(filePath), Buffer.from(content, "utf8"));
  return true;
}

async function writeHarnessFiles(targetDir, options = {}) {
  const sourceDir = path.join(targetDir, "source");
  const destinationDir = path.join(targetDir, "destination");
  const auditDir = path.join(targetDir, "audit");
  const checkpointDir = path.join(targetDir, "checkpoints");
  const configPath = path.join(targetDir, "dsx-transfer.local.yaml");
  const readmePath = path.join(targetDir, "README.md");
  const runScriptPath = path.join(targetDir, "run-local-transfer.sh");

  await ensureDirectory(sourceDir);
  await ensureDirectory(destinationDir);
  await ensureDirectory(auditDir);
  await ensureDirectory(checkpointDir);

  const files = [
    {
      path: path.join(sourceDir, "hello.txt"),
      content: "Hello from the DSX-Transfer local harness.\n",
    },
    {
      path: path.join(sourceDir, "blocked-demo.txt"),
      content: "This file is marked suspicious by object identity in the harness config.\n",
    },
    {
      path: configPath,
      content: localHarnessConfig(),
    },
    {
      path: runScriptPath,
      content: localHarnessRunScript(configPath),
    },
    {
      path: readmePath,
      content: localHarnessReadme(configPath, runScriptPath),
    },
  ];

  const written = [];
  const skipped = [];
  for (const file of files) {
    if (await writeTextFile(file.path, file.content, options)) {
      written.push(file.path);
    } else {
      skipped.push(file.path);
    }
  }
  return { configPath, readmePath, runScriptPath, written, skipped };
}

function localHarnessConfig() {
  return `version: 1

transfer:
  id: local-harness
  policy_id: local-static-demo

source:
  kind: filesystem
  path: source

destination:
  kind: filesystem
  uri: destination

scanner:
  mode: static
  default_verdict: benign
  verdicts_by_identity:
    blocked-demo.txt: suspicious

policy:
  verdict_actions:
    benign: allow
    malicious: block
    suspicious: block
    unknown: block

runtime:
  audit_jsonl: audit/local-harness.jsonl
  checkpoint: checkpoints/local-harness.json
`;
}

function localHarnessRunScript(configPath) {
  const relativeConfig = path.relative(workspaceRoot(), configPath).split(path.sep).join("/");
  return `#!/usr/bin/env bash
set -euo pipefail

dsx-transfer migrate --config "${relativeConfig}"
`;
}

function localHarnessReadme(configPath, runScriptPath) {
  const relativeConfig = path.relative(workspaceRoot(), configPath).split(path.sep).join("/");
  const relativeRunScript = path.relative(workspaceRoot(), runScriptPath).split(path.sep).join("/");
  return `# DSX-Transfer Local Harness

This folder is a small local DSX-Transfer integration harness.

It uses:

- filesystem source: \`source/\`
- filesystem destination: \`destination/\`
- static scanner mode
- policy that allows benign files and blocks suspicious files

Run it from the workspace root:

\`\`\`bash
dsx-transfer migrate --config ${relativeConfig}
\`\`\`

Or run:

\`\`\`bash
bash ${relativeRunScript}
\`\`\`

\`hello.txt\` should transfer. \`blocked-demo.txt\` is marked suspicious by config and should be blocked.
`;
}

async function writePythonIntegrationSkeleton(targetDir, options = {}) {
  const activeConfig = relativeWorkspacePath(configUri().fsPath) || settings().configPath;
  const files = [
    {
      path: path.join(targetDir, "run_transfer.py"),
      content: pythonIntegrationRunner(),
    },
    {
      path: path.join(targetDir, "smoke_test.py"),
      content: pythonIntegrationSmokeTest(),
    },
    {
      path: path.join(targetDir, ".env.example"),
      content: pythonIntegrationEnvExample(activeConfig),
    },
    {
      path: path.join(targetDir, "README.md"),
      content: pythonIntegrationReadme(activeConfig),
    },
  ];

  const written = [];
  const skipped = [];
  for (const file of files) {
    if (await writeTextFile(file.path, file.content, options)) {
      written.push(file.path);
    } else {
      skipped.push(file.path);
    }
  }
  return { targetDir, written, skipped };
}

function pythonIntegrationRunner() {
  return `from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def workspace_root() -> Path:
    return Path(os.environ.get("DSX_TRANSFER_WORKSPACE", Path.cwd())).resolve()


def config_path() -> Path:
    value = os.environ.get("DSX_TRANSFER_CONFIG", "dsx-transfer.yaml")
    path = Path(value)
    if not path.is_absolute():
        path = workspace_root() / path
    return path


def command() -> list[str]:
    python = os.environ.get("DSX_TRANSFER_PYTHON", sys.executable)
    if os.environ.get("DSX_TRANSFER_USE_MODULE", "1") == "1":
        return [python, "-m", "dsx_transfer.cli", "migrate", "--config", str(config_path())]
    executable = os.environ.get("DSX_TRANSFER_EXECUTABLE", "dsx-transfer")
    return [executable, "migrate", "--config", str(config_path())]


def run_transfer() -> dict:
    env = os.environ.copy()
    if env.get("DSX_TRANSFER_PYTHONPATH"):
        env["PYTHONPATH"] = env["DSX_TRANSFER_PYTHONPATH"]
    result = subprocess.run(
        command(),
        cwd=workspace_root(),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="")
    if result.stdout:
        print(result.stdout, end="")
    report = parse_report(result.stdout)
    if result.returncode != 0:
        raise SystemExit(result.returncode)
    return report


def parse_report(stdout: str) -> dict:
    for line in reversed([line for line in stdout.splitlines() if line.strip()]):
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and isinstance(parsed.get("outcomes"), list):
            return parsed
    return {}


if __name__ == "__main__":
    report = run_transfer()
    if report:
        print(
            "summary:",
            f"planned={report.get('planned_count', 0)}",
            f"allowed={report.get('allowed_count', 0)}",
            f"blocked={report.get('blocked_count', 0)}",
            f"failed={report.get('failed_count', 0)}",
        )
`;
}

function pythonIntegrationSmokeTest() {
  return `from __future__ import annotations

import os
from pathlib import Path

import run_transfer


def main() -> None:
    os.environ.setdefault(
        "DSX_TRANSFER_WORKSPACE",
        str(Path(__file__).resolve().parents[3]),
    )
    os.environ.setdefault(
        "DSX_TRANSFER_CONFIG",
        ".dsx-transfer/harness/dsx-transfer.local.yaml",
    )
    report = run_transfer.run_transfer()
    assert report.get("planned_count") == 2, report
    assert report.get("allowed_count") == 1, report
    assert report.get("blocked_count") == 1, report
    assert report.get("failed_count") == 0, report
    print("smoke test passed")


if __name__ == "__main__":
    main()
`;
}

function pythonIntegrationEnvExample(activeConfig) {
  return `DSX_TRANSFER_WORKSPACE=${workspaceRoot()}
DSX_TRANSFER_CONFIG=${activeConfig}
DSX_TRANSFER_USE_MODULE=1
DSX_TRANSFER_PYTHON=${settings().pythonPath || ".venv/bin/python"}
DSX_TRANSFER_PYTHONPATH=${settings().modulePythonPath || ".:dsx_transfer:dsxa_sdk_py"}
# DSX_TRANSFER_EXECUTABLE=dsx-transfer
# GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
`;
}

function pythonIntegrationReadme(activeConfig) {
  return `# DSX-Transfer Python Integration Skeleton

This skeleton shows how an application can invoke DSX-Transfer from Python while keeping transfer behavior in a normal \`dsx-transfer.yaml\` config.

Generated files:

- \`run_transfer.py\`: small Python wrapper around the DSX-Transfer CLI or module invocation
- \`smoke_test.py\`: local harness smoke test
- \`.env.example\`: environment variables to copy into your app or process manager

Active config at generation time:

\`\`\`text
${activeConfig}
\`\`\`

Run from the workspace root:

\`\`\`bash
cd ${path.relative(workspaceRoot(), path.join(workspaceRoot(), ".dsx-transfer", "integration", "python")).split(path.sep).join("/")}
DSX_TRANSFER_WORKSPACE=${workspaceRoot()} DSX_TRANSFER_CONFIG=${activeConfig} python run_transfer.py
\`\`\`

Smoke test against the local harness:

\`\`\`bash
python smoke_test.py
\`\`\`

Use this as a starting point for a scheduled job, background worker, or API endpoint. Keep source, destination, scanner, policy, audit, and checkpoint behavior in the DSX-Transfer config file.
`;
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

async function openConfig() {
  const target = configUri();
  if (!await pathExists(target.fsPath)) {
    const choice = await vscode.window.showWarningMessage(
      `${path.basename(target.fsPath)} does not exist.`,
      "Create Config",
      "Cancel"
    );
    if (choice !== "Create Config") {
      return;
    }
    await createConfig();
    return;
  }
  const doc = await vscode.workspace.openTextDocument(target);
  await vscode.window.showTextDocument(doc, { preview: false });
}

async function useActiveFileAsConfig(uri) {
  const target = uri?.fsPath
    ? uri
    : vscode.window.activeTextEditor?.document?.uri;
  if (!target || target.scheme !== "file") {
    vscode.window.showWarningMessage("Open a dsx-transfer YAML file first.");
    return;
  }

  const relative = relativeWorkspacePath(target.fsPath);
  if (!relative) {
    vscode.window.showWarningMessage("DSX-Transfer config must be inside the current workspace.");
    return;
  }

  await config().update("configPath", relative, vscode.ConfigurationTarget.Workspace);
  output.appendLine(`DSX-Transfer active config: ${relative}`);
  vscode.window.showInformationMessage(`DSX-Transfer config set to ${relative}.`);
  await validateConfig({ silent: true });
}

async function addLocalHarness() {
  output.show(true);
  const targetDir = path.join(workspaceRoot(), ".dsx-transfer", "harness");
  const existingConfig = path.join(targetDir, "dsx-transfer.local.yaml");
  const overwrite = await pathExists(existingConfig)
    ? await vscode.window.showWarningMessage(
      "DSX-Transfer local harness already exists.",
      "Open Existing",
      "Overwrite",
      "Cancel"
    )
    : "Overwrite";
  if (overwrite === "Open Existing") {
    const doc = await vscode.workspace.openTextDocument(vscode.Uri.file(existingConfig));
    await vscode.window.showTextDocument(doc, { preview: false });
    return;
  }
  if (overwrite !== "Overwrite") {
    return;
  }

  const result = await writeHarnessFiles(targetDir, { overwrite: true });
  output.appendLine("DSX-Transfer local harness:");
  output.appendLine(`- config: ${result.configPath}`);
  output.appendLine(`- run script: ${result.runScriptPath}`);
  output.appendLine(`- wrote ${result.written.length} file(s)`);

  const doc = await vscode.workspace.openTextDocument(vscode.Uri.file(result.configPath));
  await vscode.window.showTextDocument(doc, { preview: false });
  vscode.window.showInformationMessage("Created DSX-Transfer local harness.");
}

async function openLocalHarness() {
  const target = localHarnessConfigUri();
  if (!await pathExists(target.fsPath)) {
    const choice = await vscode.window.showWarningMessage(
      "DSX-Transfer local harness does not exist.",
      "Create Harness",
      "Cancel"
    );
    if (choice !== "Create Harness") {
      return;
    }
    await addLocalHarness();
    return;
  }
  const doc = await vscode.workspace.openTextDocument(target);
  await vscode.window.showTextDocument(doc, { preview: false });
}

async function addPythonIntegrationSkeleton() {
  output.show(true);
  const targetDir = path.join(workspaceRoot(), ".dsx-transfer", "integration", "python");
  const readmePath = path.join(targetDir, "README.md");
  const overwrite = await pathExists(readmePath)
    ? await vscode.window.showWarningMessage(
      "DSX-Transfer Python integration skeleton already exists.",
      "Open Existing",
      "Overwrite",
      "Cancel"
    )
    : "Overwrite";
  if (overwrite === "Open Existing") {
    const doc = await vscode.workspace.openTextDocument(vscode.Uri.file(readmePath));
    await vscode.window.showTextDocument(doc, { preview: false });
    return;
  }
  if (overwrite !== "Overwrite") {
    return;
  }

  const result = await writePythonIntegrationSkeleton(targetDir, { overwrite: true });
  output.appendLine("DSX-Transfer Python integration skeleton:");
  output.appendLine(`- path: ${result.targetDir}`);
  output.appendLine(`- wrote ${result.written.length} file(s)`);

  const doc = await vscode.workspace.openTextDocument(vscode.Uri.file(readmePath));
  await vscode.window.showTextDocument(doc, { preview: false });
  vscode.window.showInformationMessage("Created DSX-Transfer Python integration skeleton.");
}

async function validateConfigPath(target, options = {}) {
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

async function validateConfig(options = {}) {
  return validateConfigPath(configUri(), options);
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

async function runTransferWithConfig(target, label = "DSX-Transfer") {
  output.show(true);
  const validation = await validateConfigPath(target, { silent: true });
  if (!validation.valid) {
    vscode.window.showErrorMessage(`${label} config is invalid. Fix diagnostics before running.`);
    return;
  }
  const result = await runCli(["migrate", "--config", target.fsPath]);
  const report = parseReport(result.stdout);
  if (report) {
    reportProvider.setReport(report);
    const summary = `planned ${report.planned_count ?? report.outcomes.length}, allowed ${report.allowed_count ?? 0}, blocked ${report.blocked_count ?? 0}, failed ${report.failed_count ?? 0}`;
    output.appendLine(`${label} summary: ${summary}`);
    if (result.ok) {
      vscode.window.showInformationMessage(`${label} complete: ${summary}.`);
    } else {
      vscode.window.showErrorMessage(`${label} finished with failures: ${summary}.`);
    }
    return;
  }
  if (result.ok) {
    vscode.window.showInformationMessage(`${label} command completed.`);
  } else {
    vscode.window.showErrorMessage(`${label} command failed. See DSX-Transfer output.`);
  }
}

async function runTransfer() {
  return runTransferWithConfig(configUri(), "DSX-Transfer");
}

async function runLocalHarness() {
  const target = localHarnessConfigUri();
  if (!await pathExists(target.fsPath)) {
    const choice = await vscode.window.showWarningMessage(
      "DSX-Transfer local harness does not exist.",
      "Create Harness",
      "Cancel"
    );
    if (choice !== "Create Harness") {
      return;
    }
    await addLocalHarness();
    if (!await pathExists(target.fsPath)) {
      return;
    }
  }
  return runTransferWithConfig(target, "DSX-Transfer local harness");
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

async function openReportItemJson(item) {
  if (!item?.item) {
    vscode.window.showWarningMessage("No DSX-Transfer report item selected.");
    return;
  }
  const identity = item.item.object_identity || "report-item";
  const doc = await vscode.workspace.openTextDocument({
    language: "json",
    content: JSON.stringify(item, null, 2),
  });
  await vscode.window.showTextDocument(doc, { preview: false });
  vscode.window.showInformationMessage(`Opened DSX-Transfer report item: ${identity}.`);
}

function activate(context) {
  output = vscode.window.createOutputChannel("DSX-Transfer");
  diagnostics = vscode.languages.createDiagnosticCollection("dsx-transfer");
  reportProvider = new ReportTreeProvider();
  context.subscriptions.push(output);
  context.subscriptions.push(diagnostics);
  context.subscriptions.push(vscode.window.registerTreeDataProvider("dsxTransferReport", reportProvider));
  context.subscriptions.push(vscode.commands.registerCommand("dsxTransfer.openConfig", openConfig));
  context.subscriptions.push(vscode.commands.registerCommand("dsxTransfer.useActiveFileAsConfig", useActiveFileAsConfig));
  context.subscriptions.push(vscode.commands.registerCommand("dsxTransfer.createConfig", createConfig));
  context.subscriptions.push(vscode.commands.registerCommand("dsxTransfer.openLocalHarness", openLocalHarness));
  context.subscriptions.push(vscode.commands.registerCommand("dsxTransfer.addLocalHarness", addLocalHarness));
  context.subscriptions.push(vscode.commands.registerCommand("dsxTransfer.addPythonIntegrationSkeleton", addPythonIntegrationSkeleton));
  context.subscriptions.push(vscode.commands.registerCommand("dsxTransfer.runLocalHarness", runLocalHarness));
  context.subscriptions.push(vscode.commands.registerCommand("dsxTransfer.validateConfig", () => validateConfig()));
  context.subscriptions.push(vscode.commands.registerCommand("dsxTransfer.runTransfer", runTransfer));
  context.subscriptions.push(vscode.commands.registerCommand("dsxTransfer.showSchema", showSchema));
  context.subscriptions.push(vscode.commands.registerCommand("dsxTransfer.checkEnvironment", checkEnvironment));
  context.subscriptions.push(vscode.commands.registerCommand("dsxTransfer.openReportItemJson", openReportItemJson));
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
