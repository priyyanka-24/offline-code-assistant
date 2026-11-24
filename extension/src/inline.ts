import * as vscode from 'vscode';

/**
 * v3: grey inline suggestions ("ghost text"), accepted with Tab.
 *
 * Speed tricks:
 *  - wait DEBOUNCE_MS after the last keystroke before asking (don't ask on every key)
 *  - VS Code cancels the request when you keep typing -> we abort the HTTP call
 *  - send only ~60 lines before and ~20 lines after the cursor
 * Measurement: every suggestion shown / accepted is reported to the server log.
 */
const DEBOUNCE_MS = 300;
const LINES_BEFORE = 60;
const LINES_AFTER = 20;

export class InlineProvider implements vscode.InlineCompletionItemProvider {
  private counter = 0;
  shown = 0;
  accepted = 0;
  lastLatency: number | undefined;

  constructor(
    private serverUrl: () => string,
    private onStats: () => void,
  ) {}

  enabled(): boolean {
    return vscode.workspace.getConfiguration('localAssistant').get<boolean>('autocomplete', true);
  }

  async provideInlineCompletionItems(
    doc: vscode.TextDocument,
    pos: vscode.Position,
    _ctx: vscode.InlineCompletionContext,
    token: vscode.CancellationToken,
  ): Promise<vscode.InlineCompletionItem[] | undefined> {
    if (!this.enabled() || doc.uri.scheme !== 'file') return;

    // only suggest at the end of a line (or before closing brackets), not in the middle of words
    const after = doc.lineAt(pos.line).text.slice(pos.character);
    if (!/^[\s)\]}'":;,]*$/.test(after)) return;

    await new Promise((r) => setTimeout(r, DEBOUNCE_MS));
    if (token.isCancellationRequested) return;

    const start = new vscode.Position(Math.max(0, pos.line - LINES_BEFORE), 0);
    const endLine = Math.min(doc.lineCount - 1, pos.line + LINES_AFTER);
    const end = doc.lineAt(endLine).range.end;
    const prefix = doc.getText(new vscode.Range(start, pos));
    const suffix = doc.getText(new vscode.Range(pos, end));
    if (!prefix.trim()) return;

    const controller = new AbortController();
    const sub = token.onCancellationRequested(() => controller.abort());
    const t0 = Date.now();
    try {
      const res = await fetch(`${this.serverUrl()}/autocomplete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prefix, suffix, language: doc.languageId }),
        signal: controller.signal,
      });
      if (!res.ok) return;
      const data = (await res.json()) as { completion: string; cached: boolean };
      const latency = Date.now() - t0;
      if (token.isCancellationRequested || !data.completion.trim()) return;

      const id = `${Date.now()}-${++this.counter}`;
      this.shown++;
      this.lastLatency = latency;
      this.onStats();
      this.report({ event: 'shown', id, latency_ms: latency, cached: data.cached,
                    chars: data.completion.length, language: doc.languageId });

      const item = new vscode.InlineCompletionItem(data.completion, new vscode.Range(pos, pos));
      // runs only when the user presses Tab to accept
      item.command = { title: 'accepted', command: 'localAssistant.suggestionAccepted',
                       arguments: [id, latency, data.completion.length, doc.languageId] };
      return [item];
    } catch {
      return; // aborted (user kept typing) or server offline
    } finally {
      sub.dispose();
    }
  }

  markAccepted(id: string, latency: number, chars: number, language: string) {
    this.accepted++;
    this.onStats();
    this.report({ event: 'accepted', id, latency_ms: latency, chars, language });
  }

  private report(body: object) {
    fetch(`${this.serverUrl()}/autocomplete/event`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).catch(() => undefined);
  }
}
