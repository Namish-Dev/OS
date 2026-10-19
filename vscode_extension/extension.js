// Personal OS VS Code Bridge — Extended Edition
//
// Sends metadata to Personal OS running locally. Never sends document text.
//
// Endpoints used:
//   POST http://127.0.0.1:8766/v1/context         (existing — active editor/workspace)
//   POST http://127.0.0.1:8767/v1/terminal-event  (NEW — terminal command executions)
//   POST http://127.0.0.1:8766/v1/dev-event       (NEW — file open/save/create/delete)
//
// Shell Integration note:
//   VS Code's terminal shell integration API became stable in VS Code 1.93.
//   When unavailable (older VS Code), terminal capture degrades gracefully to
//   'unsupported' with a capture_note explaining the limitation.

const http = require("http");
const vscode = require("vscode");

// ── Helpers ──────────────────────────────────────────────────────────────────

function post(port, path, payload) {
  const body = JSON.stringify(payload);
  const req = http.request({
    hostname: "127.0.0.1",
    port,
    path,
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Content-Length": Buffer.byteLength(body),
    },
    timeout: 1500,
  });
  req.on("error", () => {}); // Tracker may not be running.
  req.write(body);
  req.end();
}

function workspaceRoot() {
  const folder = vscode.workspace.workspaceFolders?.[0];
  return folder ? { workspace: folder.name, workspace_path: folder.uri.fsPath } : {};
}

function nowIso() {
  return new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
}

// ── Context report (existing) ─────────────────────────────────────────────────

function reportContext() {
  const ws = workspaceRoot();
  const editor = vscode.window.activeTextEditor;
  const payload = {
    workspace_path: ws.workspace_path,
    workspace: ws.workspace,
    file_path:
      editor?.document?.uri.scheme === "file"
        ? editor.document.uri.fsPath
        : undefined,
    language: editor?.document?.languageId,
  };
  post(8766, "/v1/context", payload);
}

// ── File event report (new) ───────────────────────────────────────────────────

function reportFileEvent(eventType, document) {
  if (!document || document.uri.scheme !== "file") return;
  const ws = workspaceRoot();
  const payload = {
    event_type: eventType,         // 'file_opened' | 'file_saved' | 'file_created' | 'file_deleted'
    file_path: document.uri.fsPath,
    language: document.languageId,
    workspace: ws.workspace,
    workspace_path: ws.workspace_path,
    timestamp: nowIso(),
  };
  post(8766, "/v1/dev-event", payload);
}

// ── Terminal event report (new) ───────────────────────────────────────────────

// Tracks per-execution start times to compute duration
const _executionStartTimes = new WeakMap();

function hookTerminalShellIntegration(context) {
  // onDidStartTerminalShellExecution — stable in VS Code 1.93
  if (typeof vscode.window.onDidStartTerminalShellExecution !== "function") {
    // Degrade gracefully: log limitation but don't throw
    console.log(
      "[Personal OS] Terminal shell integration API not available in this VS Code version."
    );
    return;
  }

  context.subscriptions.push(
    vscode.window.onDidStartTerminalShellExecution((event) => {
      _executionStartTimes.set(event.execution, nowIso());
    }),

    vscode.window.onDidEndTerminalShellExecution(async (event) => {
      const term = event.terminal;
      const exec = event.execution;
      const exitCode = event.exitCode;
      const startTime = _executionStartTimes.get(exec) ?? nowIso();
      const completionTime = nowIso();

      // Collect cwd from shell integration when available
      const cwd = term.shellIntegration?.cwd?.fsPath ?? null;

      // Read command text
      const commandLine = exec.commandLine?.value ?? null;

      // Read output stream (limited)
      let output = null;
      try {
        const stream = exec.read();
        const chunks = [];
        let totalChars = 0;
        const MAX_OUTPUT_CHARS = 8192;
        for await (const chunk of stream) {
          if (totalChars + chunk.length > MAX_OUTPUT_CHARS) {
            chunks.push(chunk.substring(0, MAX_OUTPUT_CHARS - totalChars));
            chunks.push("\n[... output truncated by Personal OS ...]");
            break;
          }
          chunks.push(chunk);
          totalChars += chunk.length;
        }
        output = chunks.join("") || null;
      } catch (_) {
        output = null;
      }

      const ws = workspaceRoot();
      const payload = {
        command: commandLine,
        cwd: cwd,
        exit_code: exitCode ?? null,
        output: output,
        shell: term.name ?? null,
        terminal_host: "VS Code",
        session_id: `vscode-${term.processId ?? Math.random().toString(36).slice(2)}`,
        start_time: startTime,
        completion_time: completionTime,
        status:
          exitCode === undefined || exitCode === null
            ? "unknown"
            : exitCode === 0
            ? "completed"
            : "failed",
        source: "vscode_shell_integration",
        workspace: ws.workspace,
        workspace_path: ws.workspace_path,
      };
      post(8767, "/v1/terminal-event", payload);
    })
  );
}

// ── Activation ────────────────────────────────────────────────────────────────

function activate(context) {
  // Initial context report
  reportContext();

  // Context: active editor and workspace changes
  context.subscriptions.push(
    vscode.window.onDidChangeActiveTextEditor(reportContext),
    vscode.workspace.onDidChangeWorkspaceFolders(reportContext)
  );

  // File events
  context.subscriptions.push(
    vscode.workspace.onDidOpenTextDocument((doc) => reportFileEvent("file_opened", doc)),
    vscode.workspace.onDidSaveTextDocument((doc) => reportFileEvent("file_saved", doc)),
    vscode.workspace.onDidCreateFiles((e) => {
      e.files.forEach((uri) =>
        reportFileEvent("file_created", { uri, uri: uri, languageId: null, scheme: uri.scheme })
      );
    }),
    vscode.workspace.onDidDeleteFiles((e) => {
      e.files.forEach((uri) =>
        reportFileEvent("file_deleted", { uri, uri: uri, languageId: null, scheme: uri.scheme })
      );
    })
  );

  // Terminal shell integration (VS Code 1.93+, degrades gracefully)
  hookTerminalShellIntegration(context);
}

function deactivate() {}
module.exports = { activate, deactivate };
