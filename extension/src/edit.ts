import * as vscode from 'vscode';

/**
 * v4: Change Code.
 * Select code -> say what to change -> the server returns a new version ->
 * a side-by-side diff opens -> Accept replaces the selection, Reject leaves the file alone.
 */

const SCHEME = 'local-ai-edit';
const CONTEXT_LINES = 30;
const MAX_CHARS = 8000;

interface EditResult {
  code: string;
  valid: boolean | null;   // null = could not be checked (not Python, or a partial selection)
  retried: boolean;
  error: string | null;
  sources: string[];
  seconds: number;
}

/** Holds the text of the two read-only "virtual" documents shown in the diff (never saved to disk). */
class VirtualDocs implements vscode.TextDocumentContentProvider {
  private docs = new Map<string, string>();
  set(uri: vscode.Uri, text: string) { this.docs.set(uri.toString(), text); }
  delete(uri: vscode.Uri) { this.docs.delete(uri.toString()); }
  provideTextDocumentContent(uri: vscode.Uri) { return this.docs.get(uri.toString()) ?? ''; }
}

export function registerEdit(ctx: vscode.ExtensionContext, serverUrl: () => string,
                             projectRoot: () => string | undefined) {
  const docs = new VirtualDocs();
  let busy = false;
  let counter = 0;

  ctx.subscriptions.push(
    vscode.workspace.registerTextDocumentContentProvider(SCHEME, docs),
    vscode.commands.registerCommand('localAssistant.edit', async () => {
      if (busy) {
        vscode.window.showInformationMessage('Local AI is still working on the last change.');
        return;
      }
      busy = true;
      try {
        await changeCode(serverUrl, projectRoot, docs, ++counter);
      } finally {
        busy = false;
      }
    }),
  );
}

async function changeCode(serverUrl: () => string, projectRoot: () => string | undefined,
                          docs: VirtualDocs, n: number) {
  const editor = vscode.window.activeTextEditor;
  if (!editor || editor.selection.isEmpty) {
    vscode.window.showWarningMessage('Select the code you want to change first.');
    return;
  }
  const doc = editor.document;

  // Use whole lines, so the indentation of the new code always fits back in.
  const sel = editor.selection;
  let endLine = sel.end.line;
  if (sel.end.character === 0 && endLine > sel.start.line) endLine--; // selection ended at the start of a line
  const range = new vscode.Range(sel.start.line, 0, endLine, doc.lineAt(endLine).text.length);
  const original = doc.getText(range);
  if (original.length > MAX_CHARS) {
    vscode.window.showWarningMessage(`That selection is too long (${original.length} characters). `
      + `Select less than ${MAX_CHARS} characters, e.g. one function.`);
    return;
  }

  const instruction = await vscode.window.showInputBox({
    title: 'Local AI: Change Code',
    prompt: `What should change in lines ${range.start.line + 1}–${range.end.line + 1}?`,
    placeHolder: 'e.g. return 0 for an empty list',
    ignoreFocusOut: true,
  });
  if (!instruction?.trim()) return;

  const ctxStart = Math.max(0, range.start.line - CONTEXT_LINES);
  const ctxEnd = Math.min(doc.lineCount - 1, range.end.line + CONTEXT_LINES);
  const context = doc.getText(new vscode.Range(ctxStart, 0, ctxEnd, doc.lineAt(ctxEnd).text.length));
  const versionBefore = doc.version;

  // 1. ask the server (cancellable)
  const result = await vscode.window.withProgress<EditResult | undefined>({
    location: vscode.ProgressLocation.Notification,
    title: 'Local AI: changing code…',
    cancellable: true,
  }, async (_progress, token) => {
    const controller = new AbortController();
    token.onCancellationRequested(() => controller.abort());
    try {
      const res = await fetch(`${serverUrl()}/edit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          code: original,
          question: instruction,
          context: context.slice(0, MAX_CHARS),
          language: doc.languageId,
          file_path: doc.fileName,
          project_root: projectRoot(),
          start_line: range.start.line + 1,
          end_line: range.end.line + 1,
        }),
        signal: controller.signal,
      });
      if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
      return (await res.json()) as EditResult;
    } catch (err: any) {
      if (err?.name === 'AbortError') return undefined;
      const offline = String(err?.cause?.code ?? err?.message ?? '').includes('ECONNREFUSED');
      vscode.window.showErrorMessage(offline
        ? 'Local AI: the backend is not running. Start it with: .\\.venv\\Scripts\\python.exe -m uvicorn server.app:app --port 8000'
        : `Local AI: ${err?.message ?? err}`);
      return undefined;
    }
  });
  if (!result) return;
  if (result.code.trim() === original.trim()) {
    vscode.window.showInformationMessage('Local AI: the model returned the same code, nothing to change.');
    return;
  }

  // 2. show old vs new side by side
  const name = doc.fileName.split(/[\\/]/).pop() ?? 'code';
  const left = vscode.Uri.parse(`${SCHEME}:/${n}/before/${name}`);
  const right = vscode.Uri.parse(`${SCHEME}:/${n}/after/${name}`);
  docs.set(left, original);
  docs.set(right, result.code);
  await vscode.commands.executeCommand('vscode.diff', left, right,
    `${name} (lines ${range.start.line + 1}–${range.end.line + 1}): current ↔ suggested`,
    { preview: true, preserveFocus: false });

  // 3. ask Accept / Reject
  const check = result.valid === true ? (result.retried ? '✅ checked (fixed on 2nd try)' : '✅ checked')
    : result.valid === false ? `⚠️ ${result.error}` : 'not checked';
  const used = result.sources.length ? ` · used ${result.sources.join(', ')}` : '';
  const choice = await vscode.window.showInformationMessage(
    `Local AI: apply this change? (${check} · ${result.seconds}s${used})`, 'Accept', 'Reject');

  await closeDiff(right);
  docs.delete(left);
  docs.delete(right);

  let accepted = choice === 'Accept';
  if (accepted) {
    if (doc.isClosed || doc.version !== versionBefore) {
      // the file was edited while we waited: our line numbers may be wrong, so don't touch it
      vscode.window.showWarningMessage('Local AI: the file changed while waiting, so the change was NOT applied. Try again.');
      accepted = false;
    } else {
      const edit = new vscode.WorkspaceEdit();
      edit.replace(doc.uri, range, result.code);
      accepted = await vscode.workspace.applyEdit(edit);
      const shown = await vscode.window.showTextDocument(doc);
      const endPos = doc.positionAt(doc.offsetAt(range.start) + result.code.length);
      shown.selection = new vscode.Selection(range.start, endPos);
      shown.revealRange(new vscode.Range(range.start, endPos));
    }
  }

  // 4. log it, for a real acceptance rate in the report (Ctrl+Z still undoes an accepted change)
  fetch(`${serverUrl()}/edit/event`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      event: accepted ? 'accepted' : 'rejected',
      language: doc.languageId,
      lines: range.end.line - range.start.line + 1,
      instruction_chars: instruction.length,
      seconds: result.seconds,
      valid: result.valid,
      retried: result.retried,
    }),
  }).catch(() => undefined);
}

async function closeDiff(right: vscode.Uri) {
  for (const group of vscode.window.tabGroups.all) {
    for (const tab of group.tabs) {
      if (tab.input instanceof vscode.TabInputTextDiff
          && tab.input.modified.toString() === right.toString()) {
        await vscode.window.tabGroups.close(tab);
      }
    }
  }
}
