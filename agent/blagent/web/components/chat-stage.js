// SPDX-License-Identifier: GPL-3.0-or-later
//
// Conversation stage: transcript with markdown, collapsible model
// thinking blocks (Qwen-style <think> tags), the live streaming
// buffer, tool-call cards with status, and the destructive-tool
// confirmation gate.

import { LitElement, html, css, nothing } from "lit";
import { store } from "/static/core/store.js";
import { icon } from "/static/core/icons.js";
import { brandMark } from "/static/core/brand.js";
import { adoptHighlightStyles, ensureMarkdownReady, renderMarkdown } from "/static/core/markdown.js";
import "/static/components/json-view.js";
import "/static/core/widgets.js";
import "/static/components/stl-viewer.js";

function unsafeHtml(htmlText) {
  const template = document.createElement("template");
  template.innerHTML = htmlText;
  return template.content;
}

/**
 * Split model output into ordered parts: {type: "think"|"text", body,
 * open} - handles complete <think>...</think> (and <thinking>) blocks
 * and an unterminated tail while streaming (open: true). Empty think
 * blocks are dropped.
 */
export function splitThinking(text) {
  const parts = [];
  const re = /<think(?:ing)?>([\s\S]*?)(<\/think(?:ing)?>|$)/g;
  let cursor = 0;
  let match;
  while ((match = re.exec(text)) !== null) {
    if (match.index > cursor) {
      parts.push({ type: "text", body: text.slice(cursor, match.index) });
    }
    const body = match[1].trim();
    if (body) {
      parts.push({ type: "think", body, open: match[2] === "" });
    }
    cursor = match.index + match[0].length;
  }
  if (cursor < text.length) {
    parts.push({ type: "text", body: text.slice(cursor) });
  }
  return parts.filter((p) => p.type === "think" || p.body.trim());
}

export class BaChatStage extends LitElement {
  static properties = {
    _records: { state: true },
    _streaming: { state: true },
    _toolOrder: { state: true },
    _pending: { state: true },
    _error: { state: true },
    _busy: { state: true },
    _drafting: { state: true },
    _quiet: { state: true },
    _expanded: { state: true },
    _openThinks: { state: true },
    _closedThinks: { state: true },
    _lightbox: { state: true },
    _approvals: { state: true },
    _autonomy: { state: true },
    _openAgents: { state: true },
  };

  constructor() {
    super();
    this._records = store.state.records;
    this._streaming = "";
    this._toolOrder = [];
    this._pending = null;
    // tool-name -> "approved" | "rejected", once the human decides on a
    // pending agent-authored tool.
    this._approvals = {};
    this._error = "";
    this._busy = false;
    this._drafting = null;
    this._quiet = 0;
    this._expanded = new Set();
    this._openThinks = new Set();
    this._closedThinks = new Set();
    this._lightbox = null;
    this._autonomy = store.state.autonomy;
    this._openAgents = new Set();   // agent ids the user expanded
  }

  connectedCallback() {
    super.connectedCallback();
    ensureMarkdownReady().then(() => {
      adoptHighlightStyles(this.renderRoot);
      this.requestUpdate();
    });
    this._unsub = store.subscribe((keys) => {
      if (keys.has("records")) this._records = [...store.state.records];
      if (keys.has("streaming")) this._streaming = store.state.streaming;
      if (keys.has("toolOrder") || keys.has("toolCalls")) this._toolOrder = [...store.state.toolOrder];
      if (keys.has("pendingConfirm")) this._pending = store.state.pendingConfirm;
      if (keys.has("error")) this._error = store.state.error;
      if (keys.has("busy")) this._busy = store.state.busy;
      if (keys.has("drafting")) this._drafting = store.state.drafting;
      if (keys.has("quiet")) this._quiet = store.state.quiet;
      if (keys.has("autonomy")) this._autonomy = store.state.autonomy;
      this._scrollSoon();
    });
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this._unsub?.();
  }

  _scrollSoon() {
    requestAnimationFrame(() => {
      const el = this.renderRoot.querySelector(".scroll");
      if (el && el.scrollHeight - el.scrollTop - el.clientHeight < 240) {
        el.scrollTop = el.scrollHeight;
      }
    });
  }

  static styles = css`
    *, *::before, *::after { box-sizing: border-box; }
    :host { display: block; min-height: 0; font-family: var(--font-sans); }
    .scroll { height: 100%; overflow-y: auto; padding: 20px 16px; }
    .col {
      max-width: 820px;
      margin: 0 auto;
      display: flex;
      flex-direction: column;
      gap: 14px;
    }
    .msg { line-height: 1.6; min-width: 0; }
    .msg.user {
      align-self: flex-end;
      max-width: 76%;
      background: var(--accent-soft);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      padding: 9px 14px;
      word-break: break-word;
    }
    .msg.user .txt { white-space: pre-wrap; }
    .msg.assistant { align-self: stretch; }
    .msg.assistant :first-child { margin-top: 0; }
    .msg.assistant pre {
      background: var(--surface-elevated);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      padding: 10px 12px;
      overflow-x: auto;
      font-size: 12.5px;
    }
    .msg.assistant code { font-family: var(--font-mono); }
    .msg.assistant :not(pre) > code {
      background: var(--surface-muted);
      border-radius: 4px;
      padding: 1px 5px;
      font-size: 0.88em;
    }
    .think {
      border: 1px solid var(--border);
      border-left: 2px solid var(--accent-2);
      border-radius: var(--radius-sm);
      background: var(--surface-elevated);
      font-size: 13px;
    }
    .think-head {
      display: flex;
      align-items: center;
      gap: 7px;
      padding: 6px 10px;
      color: var(--text-muted);
      cursor: pointer;
      user-select: none;
      font-weight: 500;
    }
    .think-head:hover { color: var(--text); }
    .think-head .live { color: var(--accent-2); }
    /* Activity notice while a collapsed block is still streaming. */
    .think-head .activity { color: var(--text-muted); font-weight: 400; font-size: 12px; }
    .think-head .ellipsis::after {
      content: "...";
      display: inline-block;
      overflow: hidden;
      vertical-align: bottom;
      animation: thinkdots 1.2s steps(4, end) infinite;
    }
    @keyframes thinkdots {
      from { width: 0; }
      to { width: 1.1em; }
    }
    .think-body {
      padding: 0 12px 10px;
      color: var(--text-muted);
      white-space: pre-wrap;
      word-break: break-word;
      line-height: 1.55;
    }
    .tool-card {
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      background: var(--surface-elevated);
      font-size: 12.5px;
      overflow: hidden;
    }
    .tool-head {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 7px 10px;
      cursor: pointer;
      user-select: none;
      color: var(--text-muted);
    }
    .tool-head:hover { background: var(--accent-soft); }
    .tool-head .name {
      font-family: var(--font-mono);
      font-weight: 600;
      color: var(--text);
      flex-shrink: 0;
    }
    .tool-head .summary {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      flex: 1;
      /* Flex min-width:auto would force the card as wide as the full
         one-line summary, breaking narrow viewports. */
      min-width: 0;
    }
    .badge { flex-shrink: 0; }
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      font-size: 10.5px;
      border-radius: 999px;
      padding: 2px 9px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    .badge.running { background: var(--accent-soft); color: var(--accent); }
    .badge.done { background: rgba(34, 197, 94, 0.14); color: var(--success); }
    .badge.error, .badge.rejected { background: rgba(239, 68, 68, 0.14); color: var(--danger); }
    .badge.pending_confirm { background: rgba(234, 179, 8, 0.16); color: var(--warning); }
    .tool-body {
      border-top: 1px solid var(--border);
      padding: 8px 10px;
      background: var(--surface);
    }
    .tool-body pre {
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      font-size: 12px;
      font-family: var(--font-mono);
      color: var(--text-muted);
    }
    /* Full, wrapping error text - the header summary is clipped, so the
       expanded card is where the whole message must be readable. */
    .tool-error {
      white-space: pre-wrap;
      word-break: break-word;
      font-family: var(--font-mono);
      font-size: 12px;
      line-height: 1.5;
      color: var(--danger);
      background: rgba(239, 68, 68, 0.08);
      border: 1px solid rgba(239, 68, 68, 0.25);
      border-radius: var(--radius-sm);
      padding: 8px 10px;
      margin-top: 8px;
    }
    .confirm {
      border: 1px solid var(--warning);
      border-radius: var(--radius-md);
      padding: 12px 14px;
      background: var(--surface-elevated);
    }
    .confirm .q { margin-bottom: 8px; }
    .confirm code { font-family: var(--font-mono); }
    .confirm pre {
      white-space: pre-wrap;
      font-size: 12px;
      font-family: var(--font-mono);
      color: var(--text-muted);
    }
    .confirm button {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font: inherit;
      font-weight: 600;
      border: none;
      border-radius: var(--radius-sm);
      padding: 7px 14px;
      margin-right: 8px;
      cursor: pointer;
    }
    .confirm .yes { background: var(--success); color: #fff; }
    .confirm .no { background: var(--surface-muted); color: var(--text); }
    .error-banner {
      border: 1px solid var(--danger);
      color: var(--danger);
      border-radius: var(--radius-md);
      padding: 10px 12px;
      font-size: 13px;
      white-space: pre-wrap;
    }
    .thinking-row {
      display: flex;
      align-items: center;
      gap: 8px;
      color: var(--text-muted);
      font-size: 13px;
    }
    .thinking-row .spin { animation: spin 1.4s linear infinite; display: inline-flex; }
    .thinking-row code {
      font-family: var(--font-mono);
      font-size: 12px;
      color: var(--text);
    }
    .thinking-row .drafting-size {
      font-family: var(--font-mono);
      font-size: 11px;
      color: var(--text-muted);
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    /* Autonomy view: sticky objectives + bounded nested agent cards. */
    .auto { display: flex; flex-direction: column; gap: 10px; margin-bottom: 12px; }
    .objectives {
      position: sticky; top: 0; z-index: 2;
      background: var(--surface-elevated); border: 1px solid var(--border);
      border-radius: var(--radius-md); padding: 10px 12px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.25);
    }
    .obj-head { display: flex; justify-content: space-between; align-items: center;
      font-weight: 700; font-size: 12px; letter-spacing: 0.04em; text-transform: uppercase;
      color: var(--text-muted); margin-bottom: 8px; }
    .badge { font-size: 11px; font-weight: 600; text-transform: none; letter-spacing: 0;
      padding: 2px 8px; border-radius: 999px; }
    .badge.ok { background: rgba(34,197,94,0.18); color: var(--success); }
    .badge.warn { background: rgba(234,179,8,0.18); color: var(--warning); }
    .badge.paused { background: rgba(129,140,248,0.18); color: var(--accent); }
    .obj { display: flex; align-items: baseline; gap: 8px; padding: 3px 0; font-size: 13.5px; }
    .obj .dot { width: 16px; text-align: center; }
    .obj.met .dot { color: var(--success); }
    .obj.met .obj-text { color: var(--text-muted); }
    .obj .obj-text { flex: 1; }
    .obj .ev { color: var(--text-muted); font-size: 12px; max-width: 40%;
      overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .agent {
      border: 1px solid var(--border); border-left: 3px solid var(--text-muted);
      border-radius: var(--radius-md); background: var(--surface-elevated); overflow: hidden;
    }
    .agent.worker { border-left-color: var(--accent); }
    .agent.eval { border-left-color: var(--warning); }
    .agent.gather { border-left-color: var(--accent-2); }
    .agent.done { opacity: 0.92; }
    .agent-head { display: flex; align-items: center; gap: 10px; padding: 8px 12px; cursor: pointer; }
    .agent-head:hover { background: var(--surface-muted); }
    .agent .role { font-size: 11px; font-weight: 700; text-transform: uppercase;
      letter-spacing: 0.05em; color: var(--text-muted); }
    .agent .task { flex: 1; font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .agent .state { display: inline-flex; }
    .agent .state .spin { animation: spin 1.4s linear infinite; }
    .agent .state.ok { color: var(--success); }
    .agent .state.fail { color: var(--danger); }
    .agent .proof { padding: 0 12px 10px 12px; font-size: 12.5px; color: var(--text);
      white-space: pre-wrap; border-top: 1px solid var(--border); padding-top: 8px; }
    .agent .inject { display: flex; gap: 6px; padding: 8px 12px; border-top: 1px solid var(--border); }
    .agent .inject input { flex: 1; background: var(--surface); color: var(--text);
      border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 5px 8px; font: inherit; font-size: 12.5px; }
    .agent .inject button { background: var(--surface-muted); color: var(--text-muted);
      border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 4px 10px;
      font: inherit; font-size: 12px; cursor: pointer; }
    .agent .inject button:hover { color: var(--text); }
    .agent .inject button.now { color: var(--brand); border-color: var(--brand); }
    /* Live worker activity: a compact mini-transcript inside the card. */
    .agent-activity { padding: 8px 12px; border-top: 1px solid var(--border);
      display: flex; flex-direction: column; gap: 6px; }
    .agent-activity.media-strip { flex-direction: row; }
    .wtext { font-size: 12.5px; color: var(--text); white-space: pre-wrap; overflow-wrap: anywhere; }
    .wtext.stream { color: var(--text-muted); }
    .winject { font-size: 12px; color: var(--accent); font-style: italic; }
    .wdraft { font-size: 11.5px; color: var(--text-muted); display: flex; align-items: center; gap: 6px; }
    .wdraft svg { width: 12px; height: 12px; animation: spin 1.4s linear infinite; }
    .wcall { border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--surface); }
    .wcall-head { display: flex; align-items: center; gap: 6px; padding: 4px 8px; cursor: pointer; font-size: 12px; }
    .wcall-head svg { width: 13px; height: 13px; flex: none; }
    .wcall .wname { font-family: var(--font-mono); color: var(--text); }
    .wcall .wsum { flex: 1; color: var(--text-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .wcall .wbadge { display: inline-flex; }
    .wcall .wbadge svg { width: 13px; height: 13px; }
    .wcall.running .wbadge svg { animation: spin 1.4s linear infinite; color: var(--text-muted); }
    .wcall.ok .wbadge, .wcall.done .wbadge { color: var(--success); }
    .wcall.error .wbadge, .wcall.rejected .wbadge { color: var(--danger); }
    .wcall-body { padding: 4px 8px 8px; }
    .worker-controls { display: flex; flex-direction: column; gap: 6px; padding: 8px 12px; border-top: 1px solid var(--border); }
    .worker-controls .queued { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--text-muted); }
    .worker-controls .queued span { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .worker-controls .queued button.now { background: var(--surface-muted); color: var(--brand);
      border: 1px solid var(--brand); border-radius: var(--radius-sm); padding: 3px 10px; font: inherit; font-size: 12px; cursor: pointer; }
    .worker-controls .inject-na { font-size: 11.5px; color: var(--text-muted); font-style: italic; }
    .worker-controls .stop { align-self: flex-start; display: inline-flex; align-items: center; gap: 5px;
      background: transparent; color: var(--danger); border: 1px solid var(--danger); border-radius: var(--radius-sm);
      padding: 3px 10px; font: inherit; font-size: 12px; cursor: pointer; }
    .worker-controls .stop svg { width: 13px; height: 13px; }
    .worker-controls .stop:disabled { opacity: 0.5; cursor: default; }
    .gather-done { font-size: 13px; color: var(--text-muted); padding: 4px 2px; }
    .gather-done code { color: var(--accent-2); }
    /* Independent audit panel (opt-in reward-hacking check). */
    .audit { margin-top: 6px; border: 1px solid var(--border); border-radius: var(--radius-md);
      background: var(--surface-elevated); padding: 8px 12px; }
    .audit.ok { border-left: 3px solid var(--success); }
    .audit.fail { border-left: 3px solid var(--danger); }
    .audit-head { display: flex; align-items: center; gap: 10px; }
    .audit-sum { font-size: 13px; color: var(--text); }
    .audit-over { margin-top: 6px; font-size: 12.5px; color: var(--danger); font-weight: 600; }
    .audit-row { display: flex; align-items: baseline; gap: 8px; padding: 3px 0; font-size: 12.5px; }
    .audit-row .dot { width: 14px; text-align: center; }
    .audit-row.met .dot { color: var(--success); }
    .audit-row.unmet .dot { color: var(--danger); }
    .audit-row .aid { font-family: var(--font-mono); color: var(--text-muted); }
    .audit-row .over-chip { font-size: 10px; font-weight: 700; text-transform: uppercase;
      color: var(--danger); border: 1px solid var(--danger); border-radius: var(--radius-sm); padding: 0 5px; }
    .audit-row .aev { flex: 1; color: var(--text-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .round-div { display: flex; align-items: center; gap: 10px; margin: 4px 2px 2px;
      font-size: 11px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase;
      color: var(--text-muted); }
    .round-div::before, .round-div::after { content: ""; flex: 1; height: 1px; background: var(--border); }
    .agent-events { display: flex; flex-wrap: wrap; gap: 4px; padding: 8px 12px 0; }
    .ev-chip { font-size: 11px; font-family: var(--font-mono); padding: 1px 6px;
      border-radius: var(--radius-sm); background: var(--surface-muted); color: var(--text-muted);
      border: 1px solid var(--border); }
    .ev-chip.error, .ev-chip.rejected { color: var(--danger); border-color: var(--danger); }
    .ev-chip.art { color: var(--accent-2); border-color: var(--accent-2); }
    .empty {
      margin: auto;
      text-align: center;
      color: var(--text-muted);
      padding-top: 16vh;
    }
    .empty h2 { color: var(--text); font-weight: 600; letter-spacing: 0.01em; }
    .empty .word { color: var(--brand); }
    .empty .mark { width: 48px; height: 48px; margin: 0 auto 12px; }
    .compacted {
      display: flex;
      align-items: center;
      gap: 10px;
      color: var(--text-muted);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      user-select: none;
    }
    .compacted::before, .compacted::after {
      content: "";
      flex: 1;
      border-top: 1px solid var(--border);
    }
    .media-strip { display: flex; gap: 6px; flex-wrap: wrap; }
    .media-strip img {
      max-height: 120px;
      border-radius: var(--radius-sm);
      border: 1px solid var(--border);
      cursor: pointer;
    }
    .media-strip ba-stl-viewer {
      width: 160px;
      height: 120px;
      border-radius: var(--radius-sm);
      border: 1px solid var(--border);
      overflow: hidden;
    }
    .file-chip {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 10px;
      font-size: 12px;
      font-family: var(--font-mono);
      color: var(--text);
      text-decoration: none;
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      background: var(--surface);
    }
    .file-chip:hover { border-color: var(--accent); }
    .compacted { cursor: pointer; }
    .compacted-body {
      margin: 4px 0 8px;
      padding: 10px 12px;
      font-size: 12.5px;
      line-height: 1.55;
      color: var(--text-muted);
      border: 1px dashed var(--border);
      border-radius: var(--radius-sm);
      background: var(--surface);
      overflow-wrap: anywhere;
    }
    .compacted-body :first-child { margin-top: 0; }
    .compacted-body :last-child { margin-bottom: 0; }
    .review-card {
      border: 1px solid var(--border);
      border-left: 3px solid var(--accent);
      border-radius: var(--radius-sm);
      background: var(--surface);
      padding: 8px 12px 10px;
    }
    .review-card.stopped { border-left-color: var(--danger); }
    .review-head {
      display: flex;
      align-items: center;
      gap: 8px;
      cursor: pointer;
      user-select: none;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--text-muted);
    }
    .review-verdict {
      margin-left: auto;
      font-weight: 600;
      text-transform: none;
      letter-spacing: 0;
      color: var(--accent);
    }
    .review-card.stopped .review-verdict { color: var(--danger); }
    .review-summary {
      margin-top: 6px;
      font-size: 13px;
      line-height: 1.5;
      color: var(--text);
      overflow-wrap: anywhere;
    }
    .review-summary :first-child { margin-top: 0; }
    .review-summary :last-child { margin-bottom: 0; }
    .review-card ba-json-view { display: block; margin-top: 8px; }
  `;

  _toggleSet(setName, id) {
    const next = new Set(this[setName]);
    next.has(id) ? next.delete(id) : next.add(id);
    this[setName] = next;
  }

  /** Render assistant text with <think> blocks as collapsible cards. */
  _renderAssistantText(text, keyPrefix) {
    return splitThinking(text).map((part, index) => {
      if (part.type === "text") {
        return html`<div class="msg assistant">${unsafeHtml(renderMarkdown(part.body))}</div>`;
      }
      const key = `${keyPrefix}:${index}`;
      // A live (still-streaming) block starts expanded and can be
      // collapsed; collapsed, it keeps signalling activity. A finished
      // block starts collapsed and can be expanded.
      const live = part.open;
      const open = live ? !this._closedThinks.has(key) : this._openThinks.has(key);
      const words = live ? part.body.trim().split(/\s+/).filter(Boolean).length : 0;
      return html`
        <div class="think">
          <div class="think-head"
            @click=${() => this._toggleSet(live ? "_closedThinks" : "_openThinks", key)}>
            ${icon(open ? "chevron-down" : "chevron-right")}
            ${live
              ? html`<span class="live ellipsis">Thinking</span>
                  ${open ? nothing : html`<span class="activity">${words} words so far</span>`}`
              : "Thought for a moment"}
          </div>
          ${open ? html`<div class="think-body">${part.body}</div>` : nothing}
        </div>`;
    });
  }

  /**
   * One media-strip entry, by id: images render inline, STL gets a 3D
   * thumbnail (interactive in the lightbox), anything else is a
   * download chip. Named ids carry their extension; short ids
   * (i<N>) are always images.
   */
  _renderMediaThumb(m) {
    const src = `/media/${store.state.sessionId}/${m}`;
    if (/\.stl$/i.test(m)) {
      return html`<ba-stl-viewer thumb .src=${src} .label=${m}
        @zoom=${(e) => { this._lightbox = e.detail; }}></ba-stl-viewer>`;
    }
    if (/^i\d+$/.test(m) || /\.(png|jpe?g|webp|gif|bmp|svg)$/i.test(m)) {
      return html`<img src=${src} alt=${m} title=${m}
        @click=${() => { this._lightbox = { src, alt: m }; }}>`;
    }
    return html`<a class="file-chip" href=${src} download=${m} title=${m}>
      ${icon("arrow-down-tray")} ${m}</a>`;
  }

  _renderToolCard(id) {
    const call = store.state.toolCalls[id];
    if (!call) return nothing;
    const open = this._expanded.has(id);
    const badgeIcon = {
      running: "arrow-path",
      done: "check",
      error: "exclamation-triangle",
      rejected: "x-mark",
      pending_confirm: "exclamation-triangle",
    }[call.state];
    return html`
      <div class="tool-card">
        <div class="tool-head" @click=${() => this._toggleSet("_expanded", id)}>
          ${icon(open ? "chevron-down" : "chevron-right")}
          <span class="name">${call.name}</span>
          <span class="summary" title=${call.summary || ""}>${call.summary}</span>
          <span class="badge ${call.state}">${badgeIcon ? icon(badgeIcon) : nothing}
            ${call.state.replace("_", " ")}</span>
        </div>
        ${open ? html`
          <div class="tool-body">
            <ba-json label="Arguments" .data=${call.arguments}></ba-json>
            ${(call.state === "error" || call.state === "rejected") && call.summary ? html`
              <div class="tool-error">${call.summary}</div>` : nothing}
            ${call.data !== undefined && call.data !== null ? html`
              <div style="margin-top: 8px;">
                <ba-json label="Result" .data=${call.data}></ba-json>
              </div>` : nothing}
            ${this._renderToolApproval(call.data)}
          </div>` : nothing}
        ${call.media_ids?.length ? html`
          <div class="tool-body media-strip">
            ${call.media_ids.map((m) => this._renderMediaThumb(m))}
          </div>` : nothing}
      </div>
    `;
  }

  _toggleAgent(id) {
    const s = new Set(this._openAgents);
    s.has(id) ? s.delete(id) : s.add(id);
    this._openAgents = s;
  }

  _send(e, agentId) {
    const input = e.target.closest(".inject")?.querySelector("input");
    const v = (input?.value || "").trim();
    if (!v) return;
    store.injectWorker(agentId, v);
    input.value = "";
  }

  _renderWorkerMediaThumb(agentId, m) {
    const src = `/worker-media/${agentId}/${m}`;
    if (/\.stl$/i.test(m)) {
      return html`<ba-stl-viewer thumb .src=${src} .label=${m}
        @zoom=${(ev) => { this._lightbox = ev.detail; }}></ba-stl-viewer>`;
    }
    if (/^i\d+$/.test(m) || /\.(png|jpe?g|webp|gif|bmp|svg)$/i.test(m)) {
      return html`<img src=${src} alt=${m} title=${m}
        @click=${() => { this._lightbox = { src, alt: m }; }}>`;
    }
    return html`<a class="file-chip" href=${src} download=${m} title=${m}>
      ${icon("arrow-down-tray")} ${m}</a>`;
  }

  /** A worker's tool call, compact: name · state · summary + media thumbs. */
  _renderWorkerCall(agentId, callId, call) {
    if (!call) return nothing;
    const key = `${agentId}/${callId}`;
    const open = this._expanded.has(key);
    const badgeIcon = { running: "arrow-path", ok: "check", done: "check",
      error: "exclamation-triangle", rejected: "x-mark" }[call.state];
    return html`
      <div class="wcall ${call.state}">
        <div class="wcall-head" @click=${() => this._toggleSet("_expanded", key)}>
          ${icon(open ? "chevron-down" : "chevron-right")}
          <span class="wname">${call.name}</span>
          <span class="wsum" title=${call.summary || ""}>${call.summary}</span>
          <span class="wbadge ${call.state}">${badgeIcon ? icon(badgeIcon) : nothing}</span>
        </div>
        ${open && call.arguments ? html`
          <div class="wcall-body"><ba-json label="Arguments" .data=${call.arguments}></ba-json></div>` : nothing}
        ${call.media_ids?.length ? html`
          <div class="wcall-body media-strip">
            ${call.media_ids.map((m) => this._renderWorkerMediaThumb(agentId, m))}
          </div>` : nothing}
      </div>`;
  }

  _renderAgentCard(agent) {
    if (!agent) return nothing;
    const open = this._openAgents.has(agent.id) || agent.state === "running";
    const roleClass = agent.role === "gather" ? "gather" : agent.role === "evaluator" ? "eval" : "worker";
    const badge = agent.state === "running"
      ? html`<span class="spin">${icon("arrow-path")}</span>`
      : (agent.ok === false ? "✗" : "✓");
    const canInject = store.state.autonomyLevel !== "swarm"; // in-process only
    return html`
      <div class="agent ${roleClass} ${agent.state}">
        <div class="agent-head" @click=${() => this._toggleAgent(agent.id)}>
          <span class="role">${agent.role}</span>
          <span class="task">${agent.task || agent.id}</span>
          <span class="state ${agent.ok === false ? "fail" : agent.state === "done" ? "ok" : ""}">${badge}</span>
        </div>
        ${open && agent.timeline?.length ? html`
          <div class="agent-activity">
            ${agent.timeline.map((e) => {
              if (e.kind === "text") return html`<div class="wtext">${e.content}</div>`;
              if (e.kind === "injected") return html`<div class="winject">⟶ ${e.content}</div>`;
              return this._renderWorkerCall(agent.id, e.call_id, agent.calls[e.call_id]);
            })}
            ${agent.stream ? html`<div class="wtext stream">${agent.stream}</div>` : nothing}
            ${agent.drafting ? html`<div class="wdraft">${icon("arrow-path")} drafting ${agent.drafting.name || ""}…</div>` : nothing}
          </div>` : nothing}
        ${open && agent.media?.length ? html`
          <div class="agent-activity media-strip">
            ${agent.media.map((mm) => html`<img src=${mm.data_url} alt=${mm.id} title=${mm.id}
              @click=${() => { this._lightbox = { src: mm.data_url, alt: mm.id }; }}>`)}
          </div>` : nothing}
        ${open && agent.proof ? html`<div class="proof">${agent.proof}</div>` : nothing}
        ${open && agent.artifacts?.length ? html`
          <div class="agent-events">
            ${agent.artifacts.map((p) => html`<span class="ev-chip art">${p.split("/").pop()}</span>`)}
          </div>` : nothing}
        ${agent.state === "running" ? html`
          <div class="worker-controls">
            ${canInject ? html`
              <div class="inject">
                <input type="text" placeholder="Inject guidance into this worker…"
                  @keydown=${(e) => { if (e.key === "Enter") { e.preventDefault(); this._send(e, agent.id); } }}>
                <button title="Queue for the worker's next round" @click=${(e) => this._send(e, agent.id)}>Send</button>
              </div>
              ${agent.queued ? html`
                <div class="queued">
                  <span title=${agent.queued}>⏳ queued: ${agent.queued}</span>
                  <button class="now" title="Apply it now (interrupt)"
                    @click=${() => store.interruptWorker(agent.id)}>Send now</button>
                </div>` : nothing}`
              : html`<div class="inject-na">injection isn't available for swarm workers (out of process)</div>`}
            <button class="stop" ?disabled=${agent.stopping}
              title="Cancel this worker" @click=${() => store.stopWorker(agent.id)}>
              ${icon("x-mark")} ${agent.stopping ? "stopping…" : "Stop worker"}</button>
          </div>` : nothing}
      </div>`;
  }

  _renderAutonomy() {
    const a = this._autonomy || {};
    const active = (a.objectives?.length || a.agentOrder?.length || a.done);
    if (!active) return nothing;
    const sym = (s) => (s === "met" ? "✓" : "○");
    const done = a.done;
    return html`
      <div class="auto">
        <div class="objectives">
          <div class="obj-head">
            <span>Objectives</span>
            ${done ? html`<span class="badge ${done.paused ? "paused" : done.allMet ? "ok" : "warn"}">${
              done.paused ? "paused" : done.allMet ? "all met" : "incomplete"} · ${done.rounds} round${done.rounds === 1 ? "" : "s"}</span>` : nothing}
          </div>
          ${(a.objectives || []).map((o) => html`
            <div class="obj ${o.status}">
              <span class="dot">${sym(o.status)}</span>
              <span class="obj-text">${o.text}</span>
              ${o.evidence ? html`<span class="ev" title=${o.evidence}>${o.evidence}</span>` : nothing}
            </div>`)}
        </div>
        ${(() => {
          const rows = [];
          let lastRound;
          for (const id of (a.agentOrder || [])) {
            const ag = a.agents[id];
            if (!ag) continue;
            if (ag.round !== lastRound) {
              lastRound = ag.round;
              rows.push(html`<div class="round-div">${ag.round == null ? "Gather" : `Round ${ag.round + 1}`}</div>`);
            }
            rows.push(this._renderAgentCard(ag));
          }
          return rows;
        })()}
        ${a.gathered?.master ? html`
          <div class="gather-done">⬇ merged ${a.gathered.components?.length || 0} components →
            <code>${a.gathered.master.split("/").pop()}</code>
            ${a.gathered.objects?.length ? html`<span class="ev"> · ${a.gathered.objects.length} objects: ${a.gathered.objects.join(", ")}</span>` : nothing}</div>` : nothing}
        ${this._renderAudit(a.audit)}
      </div>`;
  }

  _renderAudit(audit) {
    if (!audit) return nothing;
    const over = audit.overclaims || [];
    return html`
      <div class="audit ${audit.passed ? "ok" : "fail"}">
        <div class="audit-head">
          <span class="badge ${audit.passed ? "ok" : "warn"}">
            ${audit.passed ? "✓ independent audit passed" : "✗ independent audit FAILED"}</span>
          <span class="audit-sum">${audit.summary}</span>
        </div>
        ${over.length ? html`<div class="audit-over">⚠ orchestrator overclaimed: ${over.join(", ")}</div>` : nothing}
        ${(audit.verdicts || []).map((v) => html`
          <div class="audit-row ${v.met ? "met" : "unmet"}">
            <span class="dot">${v.met ? "✓" : "✗"}</span>
            <span class="aid">${v.objective_id}</span>
            ${v.overclaim ? html`<span class="over-chip">overclaimed</span>` : nothing}
            <span class="aev" title=${v.evidence}>${v.evidence}</span>
          </div>`)}
      </div>`;
  }

  render() {
    const records = this._records.filter((r) => !r.synthetic && r.role !== "tool");
    const autoActive = !!(this._autonomy && (this._autonomy.objectives?.length
      || this._autonomy.agentOrder?.length || this._autonomy.done));
    // (compaction "summary" records render as a divider, see _renderRecord)
    const showEmpty = records.length === 0 && !this._streaming && !this._busy && !autoActive;
    return html`
      <div class="scroll">
        ${showEmpty ? html`
          <div class="empty">
            <div class="mark">${brandMark}</div>
            <h2><span class="word">Blender</span> Agent</h2>
            <p>Connected to your Blender session through the MCP tool surface.<br>
            Try: "what's in my scene?" or "make the selected mesh manifold".</p>
          </div>` : html`
          <div class="col">
            ${this._renderAutonomy()}
            ${records.map((r, i) => this._renderRecord(r, i))}
            ${this._unclaimedLiveToolIds(records).map((id) => this._renderToolCard(id))}
            ${this._pending ? this._renderConfirm() : nothing}
            ${this._streaming ? this._renderAssistantText(this._streaming, "stream") : nothing}
            ${this._drafting && !this._quiet ? html`
              <div class="thinking-row"><span class="spin">${icon("arrow-path")}</span>
                writing ${this._drafting.name ? html`<code>${this._drafting.name}</code>` : "tool call"}&hellip;
                <span class="drafting-size">${(this._drafting.chars / 1024).toFixed(1)} kB</span>
              </div>` : nothing}
            ${this._quiet ? html`
              <div class="thinking-row"><span class="spin">${icon("arrow-path")}</span>
                ${this._drafting?.name
                  ? html`writing <code>${this._drafting.name}</code>&hellip;`
                  : html`generating&hellip;`}
                <span class="drafting-size">${Math.round(this._quiet)}s without output (backend busy)</span>
              </div>` : nothing}
            ${this._busy && !this._streaming && !this._drafting && !this._quiet ? html`
              <div class="thinking-row"><span class="spin">${icon("arrow-path")}</span> working...</div>` : nothing}
            ${this._error ? html`<div class="error-banner">${this._error}</div>` : nothing}
          </div>`}
      </div>
      ${this._lightbox ? html`
        <ba-lightbox .src=${this._lightbox.src} .alt=${this._lightbox.alt}
          .kind=${this._lightbox.kind || ""}
          @close=${() => { this._lightbox = null; }}></ba-lightbox>` : nothing}
    `;
  }

  /**
   * Live tool calls not yet claimed by an assistant record. Normally
   * empty (the engine appends the assistant record BEFORE dispatching
   * its tools, and the record renders its own calls inline) — this is
   * the defensive tail so a card is never silently dropped.
   */
  _unclaimedLiveToolIds(records) {
    const claimed = new Set();
    for (const record of records) {
      for (const call of record.tool_calls || []) claimed.add(call.id);
    }
    return this._toolOrder.filter((id) => !claimed.has(id));
  }

  /** Tool results from the transcript, keyed by tool_call_id. */
  _toolResultsByCallId() {
    const map = {};
    for (const record of this._records) {
      if (record.role === "tool" && record.tool_call_id) {
        map[record.tool_call_id] = record.content;
      }
    }
    return map;
  }

  _renderRecord(r, recordIndex) {
    if (r.role === "summary") {
      // Compaction marker: older history above this point was folded
      // into a summary for the model; the transcript itself is intact.
      // Click to expand the summary itself, like a tool card.
      const open = this._expanded.has(`compacted-${recordIndex}`);
      return html`
        <div class="compacted" @click=${() => this._toggleSet("_expanded", `compacted-${recordIndex}`)}>
          ${icon(open ? "chevron-down" : "chevron-right")} context compacted
        </div>
        ${open ? html`
          <div class="compacted-body">${unsafeHtml(renderMarkdown(r.content || ""))}</div>` : nothing}`;
    }
    if (r.role === "review") {
      // Budget checkpoint: the orchestrator's verdict on the worker's
      // self-report. Summary up front; the full review (self-report,
      // assessment, evidence checks) expands below — ba-json-view's
      // fullscreen control doubles as the modal view.
      const open = this._expanded.has(`review-${recordIndex}`);
      const granted = r.granted_rounds > 0;
      return html`
        <div class="review-card ${granted ? "granted" : "stopped"}">
          <div class="review-head" @click=${() => this._toggleSet("_expanded", `review-${recordIndex}`)}>
            ${icon(open ? "chevron-down" : "chevron-right")}
            <span class="review-title">budget review</span>
            <span class="review-verdict">${granted
              ? `granted ${r.granted_rounds} more rounds`
              : "stopped — needs your input"}</span>
          </div>
          <div class="review-summary">${unsafeHtml(renderMarkdown(r.content || ""))}</div>
          ${open ? html`
            <ba-json-view .data=${{
              verdict: r.verdict,
              granted_rounds: r.granted_rounds,
              ...(r.detail || {}),
            }} label="review"></ba-json-view>` : nothing}
        </div>`;
    }
    if (r.role === "user") {
      return html`<div class="msg user"><span class="txt">${r.content}</span>${r.media_ids?.length ? html`
            <div class="media-strip" style="margin-top: 6px;">
              ${r.media_ids.map((m) => this._renderMediaThumb(m))}
            </div>` : nothing}</div>`;
    }
    // Tool cards render INLINE at their owning record, in conversation
    // order: live calls (current turn, status chip from the event stream)
    // use the live card; everything else re-derives from the transcript.
    const live = store.state.toolCalls;
    const calls = r.tool_calls || [];
    if (!r.content && calls.length === 0) return nothing;
    const historic = calls.filter((c) => !live[c.id]);
    const results = historic.length ? this._toolResultsByCallId() : {};
    return html`
      ${r.content ? this._renderAssistantText(r.content, `r${recordIndex}`) : nothing}
      ${calls.map((c) => {
        if (live[c.id]) return this._renderToolCard(c.id);
        const open = this._expanded.has(c.id);
        // Media ids live inside the persisted tool-result JSON - the
        // live-turn state is gone once the next turn starts, so cards
        // must re-derive their thumbnails from the transcript.
        let mediaIds = [];
        let errorMessage = "";
        if (results[c.id]) {
          try {
            const parsed = JSON.parse(results[c.id]);
            mediaIds = parsed.media_ids || [];
            // Error/declined records carry the full message; surface it
            // in full rather than letting the tree preview clip it.
            if ((parsed.status === "error" || parsed.status === "rejected") && parsed.message) {
              errorMessage = String(parsed.message);
            }
          } catch {}
        }
        return html`
          <div class="tool-card">
            <div class="tool-head" @click=${() => this._toggleSet("_expanded", c.id)}>
              ${icon(open ? "chevron-down" : "chevron-right")}
              <span class="name">${c.name}</span>
              <span class="summary" title=${errorMessage || (c.arguments || "")}>${errorMessage || (c.arguments || "").slice(0, 120)}</span>
            </div>
            ${open ? html`
              <div class="tool-body">
                <ba-json label="Arguments" .data=${c.arguments}></ba-json>
                ${errorMessage ? html`<div class="tool-error">${errorMessage}</div>` : nothing}
                ${results[c.id] ? html`
                  <div style="margin-top: 8px;">
                    <ba-json label="Result" .data=${results[c.id]}></ba-json>
                  </div>` : nothing}
              </div>` : nothing}
            ${mediaIds.length ? html`
              <div class="tool-body media-strip">
                ${mediaIds.map((m) => this._renderMediaThumb(m))}
              </div>` : nothing}
          </div>`;
      })}
    `;
  }

  _approveTool(name, approve) {
    store.approveAgentTool(name, approve);
    this._approvals = { ...this._approvals, [name]: approve ? "approved" : "rejected" };
  }

  /**
   * When an author_tool result is INERT pending import approval, show the
   * human an Allow/Deny gate (the in-process counterpart to the MCP
   * elicitation external clients get). The model cannot reach this path.
   */
  _renderToolApproval(data) {
    if (!data || typeof data !== "object" || !data.needs_approval) return nothing;
    const name = data.name;
    const imports = data.needs_approval.imports || [];
    const flags = data.needs_approval.flags || [];
    const decided = this._approvals[name];
    if (decided) {
      return html`<div class="confirm"><div class="q">
        Tool <code>${name}</code> ${decided === "approved" ? "approved — it can run now." : "rejected and discarded."}
      </div></div>`;
    }
    const wants = [
      imports.length ? `imports: ${imports.join(", ")}` : "",
      flags.length ? `dynamic exec: ${flags.join(", ")}` : "",
    ].filter(Boolean).join("; ");
    return html`
      <div class="confirm">
        <div class="q">Agent tool <code>${name}</code> is saved but INERT — it requests ${wants}, outside the 3D-modeling allowlist. Approve so it can run?</div>
        <button class="yes" @click=${() => this._approveTool(name, true)}>${icon("check")} Approve</button>
        <button class="no" @click=${() => this._approveTool(name, false)}>${icon("x-mark")} Reject</button>
      </div>
    `;
  }

  _renderConfirm() {
    const p = this._pending;
    let prettyArgs = p.arguments || "";
    try { prettyArgs = JSON.stringify(JSON.parse(prettyArgs), null, 2); } catch {}
    return html`
      <div class="confirm">
        <div class="q">The agent wants to run <code>${p.name}</code>:</div>
        <pre>${prettyArgs.slice(0, 2000)}</pre>
        <button class="yes" @click=${() => store.confirm(p.call_id, true)}>${icon("check")} Allow</button>
        <button class="no" @click=${() => store.confirm(p.call_id, false)}>${icon("x-mark")} Deny</button>
      </div>
    `;
  }
}

customElements.define("ba-chat-stage", BaChatStage);
