// Personal OS VS Code bridge. It sends metadata only; never document text.
const http = require("http");
const vscode = require("vscode");

function report() {
  const folder = vscode.workspace.workspaceFolders?.[0];
  const editor = vscode.window.activeTextEditor;
  const payload = {
    workspace_path: folder?.uri.fsPath,
    workspace: folder?.name,
    file_path: editor?.document?.uri.scheme === "file" ? editor.document.uri.fsPath : undefined,
    language: editor?.document?.languageId,
  };
  const body = JSON.stringify(payload);
  const request = http.request({
    hostname: "127.0.0.1", port: 8766, path: "/v1/context", method: "POST",
    headers: { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body) },
    timeout: 1000,
  });
  request.on("error", () => {}); // Tracker may not be running yet.
  request.write(body);
  request.end();
}

function activate(context) {
  report();
  context.subscriptions.push(
    vscode.window.onDidChangeActiveTextEditor(report),
    vscode.workspace.onDidChangeWorkspaceFolders(report),
  );
}

function deactivate() {}
module.exports = { activate, deactivate };
