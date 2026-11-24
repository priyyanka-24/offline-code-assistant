import * as path from 'path';
import * as vscode from 'vscode';
import { InlineProvider } from './inline';
import { registerEdit } from './edit';

type Mode = 'explain' | 'debug';

/** What the side panel shows. We always send the whole state, so nothing is lost if the panel reloads. */
interface PanelState {
  title: string;
  subtitle: string;
  text: string;
  status: string;
  busy: boolean;
  sources: string[]; // v2: project code the server added to the prompt
}

const MAX_CHARS = 8000;   // small local models have a small context window
const CONTEXT_LINES = 30; // lines above/below the selection sent as context

let panel: vscode.WebviewPanel | undefined;
let state: PanelState = { title: 'Local AI', subtitle: '', text: '', status: '', busy: false, sources: [] };
let current: AbortController | undefined;
let statusItem: vscode.StatusBarItem;

const serverUrl = () =>
  vscode.workspace.getConfiguration('localAssistant').get<string>('serverUrl', 'http://127.0.0.1:8000');
const projectRoot = () => vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;

export function activate(ctx: vscode.ExtensionContext) {
  statusItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  statusItem.tooltip = 'Local AI project index (click to rebuild)';
  statusItem.command = 'localAssistant.reindex';
  ctx.subscriptions.push(
    statusItem,
    vscode.commands.registerCommand('localAssistant.explain', () => run('explain')),
    vscode.commands.registerCommand('localAssistant.debug', () => run('debug')),
    vscode.commands.registerCommand('localAssistant.reindex', () => reindex()),
    // v2: keep the project index fresh; only the saved file is re-embedded
    vscode.workspace.onDidSaveTextDocument((doc) => reindex(doc.uri.fsPath)),
  );
  reindex();

  // v4: Change Code (select, describe the change, review a diff, accept or reject)
  registerEdit(ctx, serverUrl, projectRoot);

  // v3: grey inline suggestions
  const acItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 99);
  acItem.command = 'localAssistant.toggleAutocomplete';
  const inline = new InlineProvider(serverUrl, () => updateAcItem());
  const updateAcItem = () => {
    if (!inline.enabled()) {
      acItem.text = '$(circle-slash) Autocomplete off';
      acItem.tooltip = 'Click to turn Local AI autocomplete on';
    } else {
      const ms = inline.lastLatency === undefined ? '' : ` ${inline.lastLatency} ms`;
      const rate = inline.shown ? ` · ${inline.accepted}/${inline.shown} accepted` : '';
      acItem.text = `$(zap)${ms}${rate}`;
      acItem.tooltip = 'Local AI autocomplete: last suggestion time and how many you accepted (click to turn off)';
    }
    acItem.show();
  };
  updateAcItem();
  ctx.subscriptions.push(
    acItem,
    vscode.languages.registerInlineCompletionItemProvider({ pattern: '**' }, inline),
    vscode.commands.registerCommand('localAssistant.suggestionAccepted',
      (id: string, latency: number, chars: number, lang: string) => inline.markAccepted(id, latency, chars, lang)),
    vscode.commands.registerCommand('localAssistant.toggleAutocomplete', async () => {
      const cfg = vscode.workspace.getConfiguration('localAssistant');
      await cfg.update('autocomplete', !inline.enabled(), vscode.ConfigurationTarget.Global);
      updateAcItem();
    }),
  );
  // load both models in the background so the first answer / suggestion is quick
  // v4: if Ollama could not keep both in memory, say so (otherwise answers are mysteriously slow)
  fetch(`${serverUrl()}/health`)
    .then(r => r.json())
    .then((h: any) => { if (h?.warning) { vscode.window.showWarningMessage(`Local AI: ${h.warning}`); } })
    .catch(() => undefined);
}

/** v2: ask the server to (re)index the whole project, or just one saved file. */
async function reindex(filePath?: string) {
  const root = projectRoot();
  if (!root) return;
  if (filePath && !filePath.toLowerCase().startsWith(root.toLowerCase())) return;
  if (!filePath) {
    statusItem.text = '$(sync~spin) Local AI: indexing…';
    statusItem.show();
  }
  try {
    const res = await fetch(`${serverUrl()}/index`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project_root: root, file_path: filePath }),
    });
    if (!res.ok) throw new Error(await res.text());
    const stats = (await res.json()) as { chunks: number; files: number; seconds: number };
    statusItem.text = `$(database) Local AI: ${stats.files} files · ${stats.chunks} chunks`;
  } catch {
    statusItem.text = '$(warning) Local AI: index offline';
  }
  statusItem.show();
}

export function deactivate() {
  current?.abort();
}

/** Selection plus ±30 lines around it; or the whole file (trimmed around the cursor) if nothing is selected. */
function collectCode(editor: vscode.TextEditor) {
  const doc = editor.document;
  const sel = editor.selection;
  const lastLine = doc.lineCount - 1;
  const lineRange = (a: number, b: number) =>
    new vscode.Range(a, 0, b, doc.lineAt(b).text.length);

  if (!sel.isEmpty) {
    const start = Math.max(0, sel.start.line - CONTEXT_LINES);
    const end = Math.min(lastLine, sel.end.line + CONTEXT_LINES);
    return {
      code: doc.getText(sel).slice(0, MAX_CHARS),
      context: doc.getText(lineRange(start, end)).slice(0, MAX_CHARS),
      where: `lines ${sel.start.line + 1}–${sel.end.line + 1}`,
      lines: [sel.start.line + 1, sel.end.line + 1],
    };
  }
  const whole = doc.getText();
  if (whole.length <= MAX_CHARS) {
    return { code: whole, context: undefined, where: 'whole file', lines: [1, lastLine + 1] };
  }
  const c = sel.active.line;
  const start = Math.max(0, c - 60);
  const end = Math.min(lastLine, c + 60);
  return { code: doc.getText(lineRange(start, end)), context: undefined, where: `lines ${start + 1}–${end + 1} (file too long)`,
           lines: [start + 1, end + 1] };
}

async function run(mode: Mode) {
  const editor = vscode.window.activeTextEditor;
  if (!editor) {
    vscode.window.showWarningMessage('Open a file first.');
    return;
  }
  const doc = editor.document;
  const { code, context, where, lines } = collectCode(editor);
  if (!code.trim()) {
    vscode.window.showWarningMessage('There is no code to send.');
    return;
  }

  current?.abort(); // a new question cancels the old one
  const controller = new AbortController();
  current = controller;

  update({
    title: mode === 'explain' ? 'Explain Code' : 'Find Bug',
    subtitle: `${path.basename(doc.fileName)} · ${where}`,
    text: '',
    status: 'Searching project & thinking…',
    busy: true,
    sources: [],
  });

  const t0 = Date.now();
  let first: number | undefined;
  try {
    const res = await fetch(`${serverUrl()}/${mode}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        code,
        context,
        language: doc.languageId,
        file_path: doc.fileName,
        project_root: projectRoot(),
        start_line: lines[0], // v4: lets the server skip same-file chunks the model already sees
        end_line: lines[1],
      }),
      signal: controller.signal,
    });
    if (!res.ok || !res.body) {
      throw new Error(`Server answered ${res.status}: ${await res.text()}`);
    }
    try {
      state.sources = JSON.parse(res.headers.get('x-context-sources') ?? '[]');
    } catch {
      state.sources = [];
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let text = '';
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      if (first === undefined) first = Date.now() - t0;
      text += decoder.decode(value, { stream: true });
      update({ ...state, text, status: `Writing… first words after ${(first / 1000).toFixed(1)} s` });
    }
    const total = (Date.now() - t0) / 1000;
    update({ ...state, busy: false, status: `Done · first words ${((first ?? 0) / 1000).toFixed(1)} s · total ${total.toFixed(1)} s` });
  } catch (err: any) {
    if (controller.signal.aborted) return; // replaced by a newer request
    const offline = String(err?.cause?.code ?? err?.message ?? '').includes('ECONNREFUSED');
    update({
      ...state,
      busy: false,
      status: offline
        ? 'Cannot reach the backend. Start it with: .\\.venv\\Scripts\\python.exe -m uvicorn server.app:app --port 8000'
        : `Error: ${err?.message ?? err}`,
    });
  } finally {
    if (current === controller) current = undefined;
  }
}

function update(next: PanelState) {
  state = next;
  if (!panel) {
    panel = vscode.window.createWebviewPanel('localAssistant', 'Local AI', {
      viewColumn: vscode.ViewColumn.Beside,
      preserveFocus: true,
    }, { enableScripts: true, retainContextWhenHidden: true });
    panel.webview.html = html();
    panel.webview.onDidReceiveMessage((m) => {
      if (m?.type === 'ready') panel?.webview.postMessage(state);
    });
    panel.onDidDispose(() => {
      panel = undefined;
      current?.abort();
    });
  } else if (!panel.visible) {
    panel.reveal(vscode.ViewColumn.Beside, true);
  }
  panel.title = `Local AI: ${state.title}`;
  panel.webview.postMessage(state);
}

function html(): string {
  const nonce = Math.random().toString(36).slice(2);
  return /* html */ `<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${nonce}';">
<style>
  body { font-family: var(--vscode-font-family); font-size: var(--vscode-font-size); color: var(--vscode-foreground); padding: 0 14px 40px; line-height: 1.5; }
  header { position: sticky; top: 0; background: var(--vscode-editor-background); padding: 10px 0 8px; border-bottom: 1px solid var(--vscode-panel-border); }
  h1 { font-size: 1.15em; margin: 0; }
  .sub { opacity: .7; font-size: .9em; }
  pre { background: var(--vscode-textCodeBlock-background); padding: 10px; border-radius: 4px; overflow-x: auto; }
  code { font-family: var(--vscode-editor-font-family); font-size: var(--vscode-editor-font-size); }
  p code { background: var(--vscode-textCodeBlock-background); padding: 1px 4px; border-radius: 3px; }
  #status { position: fixed; bottom: 0; left: 0; right: 0; padding: 6px 14px; font-size: .85em;
            background: var(--vscode-statusBar-background); color: var(--vscode-statusBar-foreground); }
  .busy::before { content: '● '; animation: blink 1s infinite; }
  #src { margin-top: 6px; font-size: .85em; opacity: .85; }
  #src span { display: inline-block; margin: 2px 4px 0 0; padding: 0 6px; border-radius: 3px;
              background: var(--vscode-badge-background); color: var(--vscode-badge-foreground); }
  @keyframes blink { 50% { opacity: .2; } }
</style></head>
<body>
<header><h1 id="title">Local AI</h1><div class="sub" id="sub">Select code, right-click, then choose Explain Code or Find Bug.</div><div id="src"></div></header>
<div id="out"></div>
<div id="status"></div>
<script nonce="${nonce}">
  const vscode = acquireVsCodeApi();
  const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const inline = s => esc(s).replace(/\`([^\`]+)\`/g, '<code>$1</code>').replace(/\\*\\*([^*]+)\\*\\*/g, '<b>$1</b>');
  function render(md) {
    // split into text / code-fence parts; an unfinished fence still renders as code while streaming
    return md.split(/\`\`\`/).map((part, i) => {
      if (i % 2) { const nl = part.indexOf('\\n'); return '<pre><code>' + esc(nl >= 0 ? part.slice(nl + 1) : '') + '</code></pre>'; }
      return part.split(/\\n{2,}/).filter(p => p.trim()).map(p => '<p>' + inline(p).replace(/\\n/g, '<br>') + '</p>').join('');
    }).join('');
  }
  window.addEventListener('message', e => {
    const s = e.data;
    document.getElementById('title').textContent = s.title;
    document.getElementById('sub').textContent = s.subtitle;
    document.getElementById('out').innerHTML = render(s.text);
    const src = document.getElementById('src');
    src.innerHTML = s.sources && s.sources.length
      ? 'Used project code: ' + s.sources.map(x => '<span>' + esc(x) + '</span>').join('') : '';
    const st = document.getElementById('status');
    st.textContent = s.status;
    st.className = s.busy ? 'busy' : '';
    if (s.busy) window.scrollTo(0, document.body.scrollHeight);
  });
  vscode.postMessage({ type: 'ready' });
</script>
</body></html>`;
}
