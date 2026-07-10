"use strict";
const vscode = require("vscode");
const { execSync } = require("child_process");

function cli(args, cwd) {
  const cfg = vscode.workspace.getConfiguration("opennavicat");
  const bin = cfg.get("cliPath", "opennavicat");
  try {
    return execSync(`"${bin}" ${args}`, { cwd, encoding: "utf-8", timeout: 30000 });
  } catch (e) {
    vscode.window.showErrorMessage(`OpenNavicat: ${e.stderr || e.message}`);
    return null;
  }
}

function activate(context) {
  const output = vscode.window.createOutputChannel("OpenNavicat");

  context.subscriptions.push(
    vscode.commands.registerCommand("opennavicat.connect", async () => {
      const conn = await vscode.window.showInputBox({ prompt: "Connection name (or 'new' to create one)" });
      if (!conn) return;
      if (conn === "new") {
        const result = cli("init");
        if (result) output.appendLine(result);
      } else {
        const result = cli(`conn info "${conn}"`);
        if (result) vscode.window.showInformationMessage(result.trim());
      }
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("opennavicat.execute", async () => {
      const editor = vscode.window.activeTextEditor;
      if (!editor) return;
      const sql = editor.selection.isEmpty ? editor.document.getText() : editor.document.getText(editor.selection);
      if (!sql.trim()) return;

      const conn = await vscode.window.showQuickPick(getConnections(), { placeHolder: "Select connection" });
      if (!conn) return;

      output.clear();
      output.appendLine(`-- Executing on ${conn}...`);
      const result = cli(`query exec "${conn}" --sql "${sql.replace(/"/g, '\\"')}"`, vscode.workspace.rootPath);
      if (result) {
        output.appendLine(result);
        output.show();
      }
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("opennavicat.ai", async () => {
      const editor = vscode.window.activeTextEditor;
      if (!editor) return;
      const selection = editor.selection.isEmpty ? "" : editor.document.getText(editor.selection);
      const question = await vscode.window.showInputBox({
        prompt: "Ask AI about this SQL or database",
        value: selection ? `Explain: ${selection.substring(0, 200)}` : "",
      });
      if (!question) return;

      const conn = await vscode.window.showQuickPick(getConnections(), { placeHolder: "Connection (optional)" });
      const connArg = conn ? `--conn "${conn}"` : "";
      output.clear();
      output.appendLine(`-- AI: ${question}`);
      const result = cli(`ai ask "${question.replace(/"/g, '\\"')}" ${connArg}`);
      if (result) {
        output.appendLine(result);
        output.show();
      }
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("opennavicat.tables", async () => {
      const conn = await vscode.window.showQuickPick(getConnections(), { placeHolder: "Select connection" });
      if (!conn) return;
      const db = await vscode.window.showInputBox({ prompt: "Database name" });
      const result = cli(`query tables "${conn}" --db "${db || ''}"`);
      if (result) {
        output.appendLine(result);
        output.show();
      }
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("opennavicat.schema", async () => {
      const conn = await vscode.window.showQuickPick(getConnections(), { placeHolder: "Select connection" });
      if (!conn) return;
      const table = await vscode.window.showInputBox({ prompt: "Table name" });
      if (!table) return;
      const result = cli(`query describe "${conn}" "${table}"`);
      if (result) {
        output.appendLine(result);
        output.show();
      }
    })
  );
}

function getConnections() {
  const result = cli("conn list --format json");
  if (!result) return [];
  try {
    return JSON.parse(result).map((c) => c.name || c.id);
  } catch {
    return [];
  }
}

module.exports = { activate };
