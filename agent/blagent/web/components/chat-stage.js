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
    _expanded: { state: true },
    _openThinks: { state: true },
    _closedThinks: { state: true },
    _lightbox: { state: true },
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
    this._openThinks = new Set();
    this._closedThinks = new Set();
    this._lightbox = null;
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
    @keyframes spin { to { transform: rotate(360deg); } }
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
          <span class="summary">${call.summary}</span>
          <span class="badge ${call.state}">${badgeIcon ? icon(badgeIcon) : nothing}
            ${call.state.replace("_", " ")}</span>
        </div>
        ${open ? html`
          <div class="tool-body">
            <ba-json label="Arguments" .data=${call.arguments}></ba-json>
            ${call.data !== undefined && call.data !== null ? html`
              <div style="margin-top: 8px;">
                <ba-json label="Result" .data=${call.data}></ba-json>
              </div>` : nothing}
          </div>` : nothing}
        ${call.media_ids?.length ? html`
          <div class="tool-body media-strip">
            ${call.media_ids.map((m) => this._renderMediaThumb(m))}
          </div>` : nothing}
      </div>
    `;
  }

  render() {
    const records = this._records.filter((r) => !r.synthetic && r.role !== "tool");
    // (compaction "summary" records render as a divider, see _renderRecord)
    const showEmpty = records.length === 0 && !this._streaming && !this._busy;
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
            ${records.map((r, i) => this._renderRecord(r, i))}
            ${this._unclaimedLiveToolIds(records).map((id) => this._renderToolCard(id))}
            ${this._pending ? this._renderConfirm() : nothing}
            ${this._streaming ? this._renderAssistantText(this._streaming, "stream") : nothing}
            ${this._busy && !this._streaming ? html`
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
        if (results[c.id]) {
          try { mediaIds = JSON.parse(results[c.id]).media_ids || []; } catch {}
        }
        return html`
          <div class="tool-card">
            <div class="tool-head" @click=${() => this._toggleSet("_expanded", c.id)}>
              ${icon(open ? "chevron-down" : "chevron-right")}
              <span class="name">${c.name}</span>
              <span class="summary">${(c.arguments || "").slice(0, 120)}</span>
            </div>
            ${open ? html`
              <div class="tool-body">
                <ba-json label="Arguments" .data=${c.arguments}></ba-json>
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
