// SPDX-License-Identifier: GPL-3.0-or-later
//
// ba-json: structured JSON viewer for tool-call payloads.
// Tree tab: expandable nodes laid out as key | value rows.
// Raw tab: pretty-printed JSON with syntax highlighting (hljs when
// loaded via core/markdown.js, plain otherwise).

import { LitElement, html, css, nothing } from "lit";
import { icon } from "/static/core/icons.js";
import { adoptHighlightStyles, ensureMarkdownReady, escapeHtml, renderMarkdown } from "/static/core/markdown.js";

function unsafeHtml(htmlText) {
  const template = document.createElement("template");
  template.innerHTML = htmlText;
  return template.content;
}

const PREVIEW_LIMIT = 64;

// Keys whose string values get rich rendering instead of an inline
// JSON literal: code -> syntax-highlighted block; markdown bodies ->
// rendered markdown. Multiline strings under any other key render as
// whitespace-preserving <pre> blocks.
const CODE_KEYS = { code: "python" };
const MARKDOWN_KEYS = new Set(["body", "memory"]);

function previewOf(value) {
  if (value === null) return "null";
  if (Array.isArray(value)) return `[ ${value.length} item${value.length === 1 ? "" : "s"} ]`;
  if (typeof value === "object") {
    const keys = Object.keys(value);
    return `{ ${keys.length} field${keys.length === 1 ? "" : "s"} }`;
  }
  const text = JSON.stringify(value);
  return text.length > PREVIEW_LIMIT ? text.slice(0, PREVIEW_LIMIT) + "..." : text;
}

export class BaJson extends LitElement {
  static properties = {
    data: { attribute: false },     // object | string (JSON text)
    label: { type: String },
    _tab: { state: true },          // "tree" | "raw"
    _open: { state: true },         // Set of expanded paths
    _zoom: { state: true },         // {title, text, lang, md} fullscreen view
  };

  constructor() {
    super();
    this.data = null;
    this.label = "";
    this._tab = "tree";
    // Root and the conventional result-envelope keys start expanded so
    // rich payloads (skill markdown, code) are visible without a click.
    this._open = new Set(["", ".result"]);
    this._zoom = null;
    this._onKeydown = (e) => {
      if (e.key === "Escape" && this._zoom) this._zoom = null;
    };
  }

  connectedCallback() {
    super.connectedCallback();
    window.addEventListener("keydown", this._onKeydown);
    ensureMarkdownReady().then(() => {
      adoptHighlightStyles(this.renderRoot);
      this.requestUpdate();
    });
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    window.removeEventListener("keydown", this._onKeydown);
  }

  get _value() {
    if (typeof this.data !== "string") return this.data;
    try { return JSON.parse(this.data); } catch { return this.data; }
  }

  static styles = css`
    *, *::before, *::after { box-sizing: border-box; }
    :host { display: block; font-family: var(--font-sans); }
    .frame {
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      background: var(--surface);
      overflow: hidden;
    }
    .bar {
      display: flex;
      align-items: center;
      gap: 4px;
      padding: 4px 6px;
      border-bottom: 1px solid var(--border);
      background: var(--surface-elevated);
    }
    .bar .label {
      font-size: 11px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.07em;
      color: var(--text-muted);
      margin-right: auto;
      padding-left: 4px;
    }
    .bar button {
      font: inherit;
      font-size: 11.5px;
      font-weight: 500;
      color: var(--text-muted);
      background: none;
      border: none;
      border-radius: var(--radius-sm);
      padding: 3px 9px;
      cursor: pointer;
    }
    .bar button:hover { color: var(--text); }
    .bar button.active { color: var(--text); background: var(--accent-soft); }
    .bar button.copy { display: inline-flex; align-items: center; gap: 4px; }
    .scroll { max-height: 320px; overflow: auto; }
    /* Grid, not <table>: a table's min-content width grows with wide
       code blocks, pushing nested scrollbars out of view. Grid lets
       the value column shrink (minmax 0) so .rich blocks scroll
       themselves, and gives the key column a real min/max range. */
    .tree {
      display: grid;
      /* Key column sizes to content within a 150-320px range (a fixed
         max would greedily take the whole 320px before the fr track
         gets anything); the cap lives on .k below. */
      grid-template-columns: minmax(150px, max-content) minmax(0, 1fr);
      font-size: 12.5px;
    }
    .tree > div {
      padding: 3px 8px;
      min-width: 0;
    }
    .tree > div.top {
      border-top: 1px solid color-mix(in srgb, var(--border) 45%, transparent);
    }
    .k {
      font-family: var(--font-mono);
      color: var(--accent-2);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      max-width: 320px;
    }
    .k .twist {
      display: inline-flex;
      vertical-align: -3px;
      color: var(--text-muted);
      cursor: pointer;
      margin-right: 2px;
    }
    .k .pad { display: inline-block; }
    .v {
      font-family: var(--font-mono);
      color: var(--text);
      word-break: break-word;
      white-space: pre-wrap;
    }
    .v.string { color: var(--success); }
    .v.number { color: var(--warning); }
    .v.boolean, .v.null { color: var(--accent); }
    .v.preview { color: var(--text-muted); cursor: pointer; }
    pre.raw {
      margin: 0;
      padding: 10px 12px;
      font-family: var(--font-mono);
      font-size: 12px;
      line-height: 1.5;
    }
    pre.raw code { background: transparent; }
    .richwrap { position: relative; min-width: 0; }
    .richwrap .zoom {
      position: absolute;
      top: 8px;
      right: 8px;
      z-index: 2;
      display: inline-flex;
      padding: 4px;
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      background: var(--surface);
      color: var(--text-muted);
      cursor: pointer;
      opacity: 0;
      transition: opacity 0.12s ease;
    }
    .richwrap:hover .zoom { opacity: 1; }
    .richwrap .zoom:hover { color: var(--text); border-color: var(--accent); }
    .rich {
      max-height: 260px;
      max-width: 100%;
      overflow: auto;
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      background: var(--surface-elevated);
      margin: 2px 0;
    }
    .rich pre {
      margin: 0;
      padding: 8px 10px;
      font-family: var(--font-mono);
      font-size: 12px;
      line-height: 1.5;
      white-space: pre;       /* preserve newlines, tabs, spaces */
      tab-size: 4;
    }
    .rich pre code { background: transparent; }
    .rich.md {
      padding: 8px 12px;
      font-size: 13px;
      line-height: 1.55;
    }
    .rich.md :first-child { margin-top: 0; }
    .rich.md :last-child { margin-bottom: 0; }
    .rich.md pre {
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      white-space: pre;
      overflow-x: auto;
    }
    /* Fullscreen view for code / long payloads. */
    .zoombox {
      position: fixed;
      inset: 0;
      z-index: 120;
      display: flex;
      align-items: center;
      justify-content: center;
      background: var(--overlay-tint);
      backdrop-filter: blur(var(--overlay-blur)) saturate(var(--overlay-saturate));
    }
    .zoombox .panel {
      display: flex;
      flex-direction: column;
      width: min(1100px, 94vw);
      height: min(860px, 88vh);
      background: var(--surface-elevated);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      box-shadow: var(--shadow-panel);
      overflow: hidden;
    }
    .zoombox header {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 8px 8px 8px 14px;
      border-bottom: 1px solid var(--border);
      font-size: 12px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.07em;
      color: var(--text-muted);
    }
    .zoombox header .title { margin-right: auto; }
    .zoombox header button {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      font: inherit;
      color: var(--text-muted);
      background: none;
      border: none;
      border-radius: var(--radius-sm);
      padding: 5px 8px;
      cursor: pointer;
    }
    .zoombox header button:hover { color: var(--text); background: var(--accent-soft); }
    .zoombox .body {
      flex: 1;
      min-height: 0;
      overflow: auto;
    }
    .zoombox .body pre {
      margin: 0;
      padding: 14px 16px;
      font-family: var(--font-mono);
      font-size: 13px;
      line-height: 1.55;
      white-space: pre;
      tab-size: 4;
    }
    .zoombox .body pre code { background: transparent; }
    .zoombox .body .mdpad { padding: 14px 18px; font-size: 13.5px; line-height: 1.55; }
  `;

  _highlight(text, lang) {
    if (lang && window.hljs?.getLanguage?.(lang)) {
      try {
        return html`<pre><code class="hljs">${unsafeHtml(window.hljs.highlight(text, { language: lang }).value)}</code></pre>`;
      } catch {}
    }
    return html`<pre>${text}</pre>`;
  }

  /** Rich rendering for code / markdown / multiline string values. */
  _renderRichString(key, text) {
    const md = MARKDOWN_KEYS.has(key);
    const lang = CODE_KEYS[key] || "";
    const zoomButton = html`
      <span class="zoom" title="Expand"
        @click=${() => { this._zoom = { title: `${this.label || "payload"} / ${key}`, text, lang, md }; }}>
        ${icon("arrows-pointing-out")}</span>`;
    const block = md
      ? html`<div class="rich md">${unsafeHtml(renderMarkdown(text))}</div>`
      : html`<div class="rich">${this._highlight(text, lang)}</div>`;
    return html`<div class="richwrap">${zoomButton}${block}</div>`;
  }

  _renderZoom() {
    const z = this._zoom;
    if (!z) return nothing;
    return html`
      <div class="zoombox" @click=${(e) => { if (e.target === e.currentTarget) this._zoom = null; }}>
        <div class="panel">
          <header>
            <span class="title">${z.title}</span>
            <button title="Copy" @click=${() => navigator.clipboard?.writeText(z.text)}>
              ${icon("clipboard")}</button>
            <button title="Close (Esc)" @click=${() => { this._zoom = null; }}>${icon("x-mark")}</button>
          </header>
          <div class="body">
            ${z.md
              ? html`<div class="mdpad">${unsafeHtml(renderMarkdown(z.text))}</div>`
              : this._highlight(z.text, z.lang)}
          </div>
        </div>
      </div>`;
  }

  _toggle(path) {
    const next = new Set(this._open);
    next.has(path) ? next.delete(path) : next.add(path);
    this._open = next;
  }

  _rows(value, path, depth, out) {
    const entries = Array.isArray(value)
      ? value.map((v, i) => [String(i), v])
      : Object.entries(value);
    for (const [key, child] of entries) {
      const childPath = `${path}.${key}`;
      const expandable = child !== null && typeof child === "object" && Object.keys(child).length > 0;
      const open = this._open.has(childPath);
      out.push({ key, child, childPath, depth, expandable, open });
      if (expandable && open) this._rows(child, childPath, depth + 1, out);
    }
  }

  _renderTree() {
    const value = this._value;
    if (value === null || typeof value !== "object") {
      return html`<pre class="raw">${typeof value === "string" ? value : JSON.stringify(value)}</pre>`;
    }
    const rows = [];
    this._rows(value, "", 0, rows);
    if (!rows.length) {
      return html`<pre class="raw">${Array.isArray(value) ? "[]" : "{}"}</pre>`;
    }
    return html`
      <div class="tree">
        ${rows.map((row, index) => {
          const kind = row.child === null ? "null" : typeof row.child;
          const isRich = kind === "string"
            && (MARKDOWN_KEYS.has(row.key) || row.key in CODE_KEYS || row.child.includes("\n"))
            && row.child.length > 0;
          const top = index > 0 ? "top" : "";
          const key = html`
            <div class="k ${top}" title=${row.key}>
              <span class="pad" style="width: ${row.depth * 14}px;"></span>
              ${row.expandable
                ? html`<span class="twist" @click=${() => this._toggle(row.childPath)}>
                    ${icon(row.open ? "chevron-down" : "chevron-right")}</span>`
                : html`<span class="twist" style="visibility: hidden;">${icon("chevron-right")}</span>`}
              ${row.key}
            </div>`;
          const value = row.expandable && !row.open
            ? html`<div class="v preview ${top}" @click=${() => this._toggle(row.childPath)}>${previewOf(row.child)}</div>`
            : row.expandable
              ? html`<div class="v preview ${top}" @click=${() => this._toggle(row.childPath)}>${Array.isArray(row.child) ? "[" : "{"}</div>`
              : isRich
                ? html`<div class="v ${top}">${this._renderRichString(row.key, row.child)}</div>`
                : html`<div class="v ${kind} ${top}">${previewOf(row.child)}</div>`;
          return html`${key}${value}`;
        })}
      </div>
    `;
  }

  _renderRaw() {
    const value = this._value;
    const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
    if (window.hljs?.getLanguage?.("json") && typeof value !== "string") {
      try {
        const highlighted = window.hljs.highlight(text, { language: "json" }).value;
        return html`<pre class="raw"><code class="hljs">${unsafeHtml(highlighted)}</code></pre>`;
      } catch {}
    }
    return html`<pre class="raw">${unsafeHtml(escapeHtml(text))}</pre>`;
  }

  _copy() {
    const value = this._value;
    const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
    navigator.clipboard?.writeText(text);
  }

  render() {
    if (this.data === null || this.data === undefined || this.data === "") return nothing;
    return html`
      <div class="frame">
        <div class="bar">
          <span class="label">${this.label}</span>
          <button class=${this._tab === "tree" ? "active" : ""}
            @click=${() => { this._tab = "tree"; }}>Tree</button>
          <button class=${this._tab === "raw" ? "active" : ""}
            @click=${() => { this._tab = "raw"; }}>Raw</button>
          <button class="copy" title="Expand" @click=${() => {
            const value = this._value;
            this._zoom = {
              title: this.label || "payload",
              text: typeof value === "string" ? value : JSON.stringify(value, null, 2),
              lang: typeof value === "string" ? "" : "json",
              md: false,
            };
          }}>${icon("arrows-pointing-out")}</button>
          <button class="copy" title="Copy JSON" @click=${() => this._copy()}>${icon("clipboard")}</button>
        </div>
        <div class="scroll">
          ${this._tab === "tree" ? this._renderTree() : this._renderRaw()}
        </div>
      </div>
      ${this._renderZoom()}
    `;
  }
}

customElements.define("ba-json", BaJson);
