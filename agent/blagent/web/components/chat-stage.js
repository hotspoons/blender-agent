// SPDX-License-Identifier: GPL-3.0-or-later
//
// Conversation stage: transcript rendering with markdown, the live
// streaming buffer, collapsible tool-call cards with status badges,
// and the destructive-tool confirmation gate. Modeled on Foyer
// Studio's `agent-panel.js`.

import { LitElement, html, css, nothing } from "lit";
import { store } from "/static/core/store.js";
import { ensureMarkdownReady, renderMarkdown } from "/static/core/markdown.js";

function unsafeHtml(htmlText) {
  const template = document.createElement("template");
  template.innerHTML = htmlText;
  return template.content;
}

export class BaChatStage extends LitElement {
  static properties = {
    _records: { state: true },
    _streaming: { state: true },
    _toolOrder: { state: true },
    _pending: { state: true },
    _error: { state: true },
    _busy: { state: true },
    _expanded: { state: true },
  };

  constructor() {
    super();
    this._records = store.state.records;
    this._streaming = "";
    this._toolOrder = [];
    this._pending = null;
    this._error = "";
    this._busy = false;
    this._expanded = new Set();
  }

  connectedCallback() {
    super.connectedCallback();
    ensureMarkdownReady().then(() => this.requestUpdate());
    this._unsub = store.subscribe((keys) => {
      if (keys.has("records")) this._records = [...store.state.records];
      if (keys.has("streaming")) this._streaming = store.state.streaming;
      if (keys.has("toolOrder") || keys.has("toolCalls")) this._toolOrder = [...store.state.toolOrder];
      if (keys.has("pendingConfirm")) this._pending = store.state.pendingConfirm;
      if (keys.has("error")) this._error = store.state.error;
      if (keys.has("busy")) this._busy = store.state.busy;
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
    :host { display: block; min-height: 0; }
    .scroll {
      height: 100%;
      overflow-y: auto;
      padding: 18px 14px;
    }
    .col {
      max-width: 860px;
      margin: 0 auto;
      display: flex;
      flex-direction: column;
      gap: 14px;
    }
    .msg { line-height: 1.55; min-width: 0; }
    .msg.user {
      align-self: flex-end;
      max-width: 78%;
      background: var(--user-bubble);
      border-radius: 14px 14px 4px 14px;
      padding: 9px 14px;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .msg.assistant { align-self: stretch; }
    .msg.assistant :first-child { margin-top: 0; }
    .msg.assistant pre {
      background: var(--bg-input);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 10px;
      overflow-x: auto;
      font-size: 12.5px;
    }
    .msg.assistant code { font-family: ui-monospace, "Cascadia Code", Menlo, monospace; }
    .msg.assistant :not(pre) > code {
      background: var(--bg-raised);
      border-radius: 4px;
      padding: 1px 5px;
      font-size: 0.9em;
    }
    .synthetic { display: none; }
    .tool-card {
      border: 1px solid var(--border);
      border-radius: 10px;
      background: var(--bg-panel);
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
    }
    .tool-head:hover { background: var(--bg-raised); }
    .tool-head .name { font-family: ui-monospace, monospace; font-weight: 600; }
    .tool-head .summary {
      color: var(--text-dim);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      flex: 1;
    }
    .badge {
      font-size: 10.5px;
      border-radius: 999px;
      padding: 1px 8px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }
    .badge.running { background: var(--accent-soft); color: var(--accent); }
    .badge.done { background: rgba(76, 175, 114, 0.15); color: var(--ok); }
    .badge.error, .badge.rejected { background: rgba(224, 92, 92, 0.15); color: var(--err); }
    .badge.pending_confirm { background: rgba(224, 164, 55, 0.18); color: var(--warn); }
    .tool-body {
      border-top: 1px solid var(--border);
      padding: 8px 10px;
      background: var(--bg-input);
    }
    .tool-body pre {
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      font-size: 12px;
      font-family: ui-monospace, monospace;
      color: var(--text-dim);
    }
    .confirm {
      border: 1px solid var(--warn);
      border-radius: 10px;
      padding: 12px;
      background: var(--bg-panel);
    }
    .confirm .q { margin-bottom: 8px; }
    .confirm code { font-family: ui-monospace, monospace; }
    .confirm button {
      border: none;
      border-radius: 7px;
      padding: 6px 14px;
      margin-right: 8px;
      cursor: pointer;
      font-weight: 600;
    }
    .confirm .yes { background: var(--ok); color: #fff; }
    .confirm .no { background: var(--bg-raised); color: var(--text); }
    .error-banner {
      border: 1px solid var(--err);
      color: var(--err);
      border-radius: 10px;
      padding: 10px 12px;
      font-size: 13px;
      white-space: pre-wrap;
    }
    .thinking { color: var(--text-dim); font-size: 13px; }
    .thinking .dots::after {
      content: "...";
      animation: dots 1.2s steps(4, end) infinite;
    }
    @keyframes dots { 0% { content: ""; } 25% { content: "."; } 50% { content: ".."; } 75% { content: "..."; } }
    .empty {
      margin: auto;
      text-align: center;
      color: var(--text-dim);
      padding-top: 16vh;
    }
    .empty h2 { color: var(--text); font-weight: 650; }
    .media-strip { display: flex; gap: 6px; margin-top: 6px; flex-wrap: wrap; }
    .media-strip img {
      max-height: 120px;
      border-radius: 8px;
      border: 1px solid var(--border);
      cursor: pointer;
    }
  `;

  _toggle(id) {
    const next = new Set(this._expanded);
    next.has(id) ? next.delete(id) : next.add(id);
    this._expanded = next;
  }

  _renderToolCard(id) {
    const call = store.state.toolCalls[id];
    if (!call) return nothing;
    const open = this._expanded.has(id);
    let prettyArgs = call.arguments || "";
    try { prettyArgs = JSON.stringify(JSON.parse(prettyArgs), null, 2); } catch {}
    return html`
      <div class="tool-card">
        <div class="tool-head" @click=${() => this._toggle(id)}>
          <span>${open ? "▾" : "▸"}</span>
          <span class="name">${call.name}</span>
          <span class="summary">${call.summary}</span>
          <span class="badge ${call.state}">${call.state.replace("_", " ")}</span>
        </div>
        ${open ? html`<div class="tool-body"><pre>${prettyArgs}</pre></div>` : nothing}
        ${call.media_ids?.length ? html`
          <div class="tool-body media-strip">
            ${call.media_ids.map((m) => html`
              <img src="/media/${store.state.sessionId}/${m}" alt=${m} title=${m}
                @click=${(e) => window.open(e.target.src, "_blank")}>`)}
          </div>` : nothing}
      </div>
    `;
  }

  render() {
    const records = this._records.filter((r) => !r.synthetic && r.role !== "tool");
    const showEmpty = records.length === 0 && !this._streaming && !this._busy;
    return html`
      <div class="scroll">
        ${showEmpty ? html`
          <div class="empty">
            <h2><span style="color: var(--accent)">Blender</span> Agent</h2>
            <p>Connected to your Blender session through the MCP tool surface.<br>
            Try: "what's in my scene?" or "make the selected mesh manifold".</p>
          </div>` : html`
          <div class="col">
            ${records.map((r) => this._renderRecord(r))}
            ${this._toolOrder.map((id) => this._renderToolCard(id))}
            ${this._pending ? this._renderConfirm() : nothing}
            ${this._streaming ? html`
              <div class="msg assistant">${unsafeHtml(renderMarkdown(this._streaming))}</div>` : nothing}
            ${this._busy && !this._streaming ? html`
              <div class="thinking">thinking<span class="dots"></span></div>` : nothing}
            ${this._error ? html`<div class="error-banner">${this._error}</div>` : nothing}
          </div>`}
      </div>
    `;
  }

  _renderRecord(r) {
    if (r.role === "user") {
      return html`<div class="msg user">${r.content}</div>`;
    }
    const liveIds = new Set(this._toolOrder);
    // Historic tool calls (reloaded sessions / earlier turns) render as
    // static cards; the live turn's calls render with status below.
    const historic = (r.tool_calls || []).filter((c) => !liveIds.has(c.id));
    if (!r.content && historic.length === 0) return nothing;
    return html`
      ${r.content ? html`<div class="msg assistant">${unsafeHtml(renderMarkdown(r.content))}</div>` : nothing}
      ${historic.map((c) => html`
        <div class="tool-card">
          <div class="tool-head" style="cursor: default;">
            <span class="name">${c.name}</span>
            <span class="summary">${(c.arguments || "").slice(0, 120)}</span>
          </div>
        </div>`)}
    `;
  }

  _renderConfirm() {
    const p = this._pending;
    let prettyArgs = p.arguments || "";
    try { prettyArgs = JSON.stringify(JSON.parse(prettyArgs), null, 2); } catch {}
    return html`
      <div class="confirm">
        <div class="q">The agent wants to run <code>${p.name}</code>:</div>
        <pre style="white-space:pre-wrap; font-size:12px;">${prettyArgs.slice(0, 2000)}</pre>
        <button class="yes" @click=${() => store.confirm(p.call_id, true)}>Allow</button>
        <button class="no" @click=${() => store.confirm(p.call_id, false)}>Deny</button>
      </div>
    `;
  }
}

customElements.define("ba-chat-stage", BaChatStage);
