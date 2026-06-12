// SPDX-License-Identifier: GPL-3.0-or-later
//
// Message composer: Enter sends, Shift+Enter newlines, abort while
// busy. Image attachments arrive by paste, drag-and-drop, or the
// attach button; they upload immediately and ride along as media ids.
// The textarea auto-grows and is also manually resizable.

import { LitElement, html, css, nothing } from "lit";
import { store } from "/static/core/store.js";
import { icon } from "/static/core/icons.js";
import { localLlm } from "/static/core/local-llm-controller.js";

const HEIGHT_KEY = "blender-agent.composer-height";

// One comfortable text line (line-height 24 + breathing room): the
// floor for both the drag-resize and the restored height, so the box
// can never be crushed into showing a scrollbar around one line.
const MIN_TA_HEIGHT = 40;

export class BaComposer extends LitElement {
  static properties = {
    _busy: { state: true },
    _connected: { state: true },
    _attachments: { state: true },   // [{id, sessionId, uploading}]
    _dragOver: { state: true },
    _autoload: { state: true },      // loading a local model before send
  };

  constructor() {
    super();
    this._busy = store.state.busy;
    this._connected = store.state.connected;
    this._attachments = [];
    this._dragOver = false;
    this._autoload = false;
    this._onLlmChange = () => this._onLocalLlmState();
  }

  connectedCallback() {
    super.connectedCallback();
    this._unsub = store.subscribe((keys) => {
      if (keys.has("busy")) this._busy = store.state.busy;
      if (keys.has("connected")) this._connected = store.state.connected;
      // Switching sessions drops staged attachments (they belong to
      // the session they were uploaded into).
      if (keys.has("sessionId")) {
        this._attachments = this._attachments.filter(
          (a) => a.sessionId === store.state.sessionId);
      }
    });
    localLlm.addEventListener("change", this._onLlmChange);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this._unsub?.();
    localLlm.removeEventListener("change", this._onLlmChange);
  }

  firstUpdated() {
    // Restore the last manually-chosen composer height (floored so a
    // single line never overflows into a scrollbar).
    const saved = parseInt(localStorage.getItem(HEIGHT_KEY) || "", 10);
    if (saved > MIN_TA_HEIGHT) {
      const ta = this.renderRoot.querySelector("textarea");
      ta.style.height = Math.min(window.innerHeight * 0.5, saved) + "px";
      this._manualHeight = true;
    }
  }

  /** True when the configured model is in-browser and not yet ready. */
  _localNotReady() {
    return !!store.state.config?.use_local_llm && localLlm.status !== "ready";
  }

  /** Drive the deferred send once an auto-load finishes (or fails). */
  _onLocalLlmState() {
    if (!this._autoload) return;
    if (localLlm.status === "ready") {
      this._autoload = false;
      // The bridge needs a beat to register over the tunnel; the turn
      // itself tolerates a not-quite-ready bridge by erroring, so a
      // short settle keeps the common path clean.
      setTimeout(() => this._send(), 150);
    } else if (localLlm.status === "error" || localLlm.status === "idle") {
      this._autoload = false;
    }
    this.requestUpdate();
  }

  async _addFiles(files) {
    for (const file of files) {
      if (file.size > 64 * 1024 * 1024) continue; // server cap
      const staged = { id: "", sessionId: "", uploading: true, name: file.name || "pasted file" };
      this._attachments = [...this._attachments, staged];
      try {
        const uploaded = await store.uploadAttachment(file);
        staged.id = uploaded.id;
        staged.sessionId = uploaded.session_id;
        staged.uploading = false;
      } catch (err) {
        console.error("attachment upload failed:", err);
        this._attachments = this._attachments.filter((a) => a !== staged);
        continue;
      }
      this._attachments = [...this._attachments];
    }
  }

  _onPaste(e) {
    const files = [...(e.clipboardData?.items || [])]
      .filter((item) => item.kind === "file")
      .map((item) => item.getAsFile())
      .filter(Boolean);
    if (files.length) {
      e.preventDefault();
      this._addFiles(files);
    }
  }

  _onDrop(e) {
    e.preventDefault();
    this._dragOver = false;
    this._addFiles([...(e.dataTransfer?.files || [])]);
  }

  /** Top-edge drag: pulling up grows the box (it expands upward). */
  _onGripDown(e) {
    const ta = this.renderRoot.querySelector("textarea");
    const grip = e.currentTarget;
    const startY = e.clientY;
    const startHeight = ta.getBoundingClientRect().height;
    try { grip.setPointerCapture(e.pointerId); } catch {}
    grip.classList.add("active");
    const maxHeight = window.innerHeight * 0.5;
    let height = startHeight;
    const onMove = (ev) => {
      height = Math.min(maxHeight, Math.max(MIN_TA_HEIGHT, startHeight + (startY - ev.clientY)));
      ta.style.height = height + "px";
      this._manualHeight = true;
    };
    const onUp = (ev) => {
      try { grip.releasePointerCapture(ev.pointerId); } catch {}
      grip.classList.remove("active");
      grip.removeEventListener("pointermove", onMove);
      grip.removeEventListener("pointerup", onUp);
      // Remember the chosen size across reloads.
      localStorage.setItem(HEIGHT_KEY, String(Math.round(height)));
    };
    grip.addEventListener("pointermove", onMove);
    grip.addEventListener("pointerup", onUp);
  }

  static styles = css`
    *, *::before, *::after { box-sizing: border-box; }
    :host {
      display: block;
      padding: 10px 16px 16px;
      font-family: var(--font-sans);
    }
    .box {
      max-width: 820px;
      margin: 0 auto;
      display: flex;
      flex-direction: column;
      background: var(--surface-elevated);
      border: 1px solid var(--border);
      border-radius: 22px;
      padding: 8px 12px 10px;
      transition: border-color 0.15s ease, box-shadow 0.15s ease;
    }
    .box:focus-within {
      border-color: var(--accent);
      box-shadow: 0 0 0 3px var(--accent-soft);
    }
    .box.drag { border-color: var(--accent); background: var(--accent-soft); }
    .grip {
      height: 10px;
      margin: -8px -12px 0;   /* span the box's full width */
      cursor: ns-resize;
      display: flex;
      align-items: center;
      justify-content: center;
      touch-action: none;
    }
    .grip::after {
      content: "";
      width: 44px;
      height: 3px;
      border-radius: 2px;
      background: var(--border);
      opacity: 0;
      transition: opacity 0.15s ease;
    }
    .grip:hover::after, .grip.active::after { opacity: 1; background: var(--accent); }
    .chips { display: flex; gap: 6px; flex-wrap: wrap; padding-bottom: 6px; }
    .chip {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      padding: 3px;
      background: var(--surface);
    }
    .chip img { height: 38px; border-radius: 4px; display: block; }
    .chip .up { font-size: 11px; color: var(--text-muted); padding: 0 6px; }
    .chip button {
      display: inline-flex;
      border: none;
      background: none;
      color: var(--text-muted);
      cursor: pointer;
      padding: 2px;
    }
    .chip button:hover { color: var(--danger); }
    textarea {
      width: 100%;
      resize: none;              /* the top-edge handle resizes instead */
      border: none;
      outline: none;
      background: transparent;
      color: var(--text);
      font: inherit;
      line-height: 24px;
      max-height: 50vh;
      min-height: 24px;
      /* Spacing via margin, NOT vertical padding: padding makes even an
         EMPTY one-line box overflow its own height (border-box) and
         grow a scrollbar. */
      padding: 0 4px;
      margin-top: 6px;
      overflow-y: auto;
      scrollbar-width: thin;
      scrollbar-color: var(--border) transparent;
    }
    textarea::placeholder { color: var(--text-muted); opacity: 0.7; }
    /* Controls live UNDER the text like the current crop of chat
       composers: attach on the left, send/stop circle on the right. */
    .controls { display: flex; align-items: center; gap: 6px; padding-top: 6px; }
    .controls .spacer { flex: 1; }
    .circle {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 36px;
      height: 36px;
      border-radius: 50%;
      border: none;
      cursor: pointer;
      font: inherit;
      transition: background 0.15s ease, color 0.15s ease, transform 0.1s ease;
    }
    .circle:active { transform: scale(0.94); }
    .circle svg { width: 20px; height: 20px; }
    button.attach {
      background: none;
      color: var(--text-muted);
      border: 1px solid var(--border);
    }
    button.attach:hover { color: var(--text); background: var(--accent-soft); border-color: transparent; }
    button.act {
      color: #fff;
      background: linear-gradient(135deg, var(--accent), var(--accent-2));
    }
    button.act:hover { filter: brightness(1.1); }
    button.act:disabled { opacity: 0.45; cursor: default; filter: none; }
    button.act.abort { background: var(--danger); }
    button.act .spin { display: inline-flex; animation: spin 1.4s linear infinite; }
    @keyframes spin { to { transform: rotate(360deg); } }
    input[type="file"] { display: none; }
  `;

  _send() {
    const ta = this.renderRoot.querySelector("textarea");
    const text = ta.value.trim();
    const ready = this._attachments.filter((a) => !a.uploading).map((a) => a.id);
    if ((!text && !ready.length) || this._busy || !this._connected) return;
    if (this._attachments.some((a) => a.uploading)) return;
    // Local model not loaded yet: kick off the load and defer the send
    // until it is ready (the Send button shows a spinner meanwhile).
    // The message text stays in the box until then.
    if (this._localNotReady()) {
      if (localLlm.status !== "loading") localLlm.load();
      this._autoload = true;
      this.requestUpdate();
      return;
    }
    this._autoload = false;
    store.chat(text || "(see attached image)", ready);
    this._attachments = [];
    ta.value = "";
    // A manually-chosen height is the user's preference - keep it after
    // sending instead of snapping back to one row; otherwise auto-fit.
    const saved = parseInt(localStorage.getItem(HEIGHT_KEY) || "", 10);
    if (this._manualHeight && saved > 24) {
      ta.style.height = Math.min(window.innerHeight * 0.5, saved) + "px";
    } else {
      ta.style.height = "auto";
      this._manualHeight = false;
    }
  }

  render() {
    return html`
      <div class="box ${this._dragOver ? "drag" : ""}"
        @dragover=${(e) => { e.preventDefault(); this._dragOver = true; }}
        @dragleave=${() => { this._dragOver = false; }}
        @drop=${this._onDrop}>
        <div class="grip" title="Drag to resize" @pointerdown=${this._onGripDown}></div>
        ${this._attachments.length ? html`
          <div class="chips">
            ${this._attachments.map((a) => html`
              <span class="chip">
                ${a.uploading
                  ? html`<span class="up">uploading...</span>`
                  : html`<img src="/media/${a.sessionId}/${a.id}" alt=${a.name} title=${a.name}>`}
                <button title="Remove" @click=${() => {
                  this._attachments = this._attachments.filter((x) => x !== a);
                }}>${icon("x-mark")}</button>
              </span>`)}
          </div>` : nothing}
        <textarea rows="1" placeholder="Ask the Blender agent..."
          @paste=${this._onPaste}
          @input=${(e) => {
            if (!this._manualHeight) {
              e.target.style.height = "auto";
              e.target.style.height = e.target.scrollHeight + "px";
            }
          }}
          @keydown=${(e) => {
            if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); this._send(); }
          }}></textarea>
        <div class="controls">
          <button class="circle attach" title="Attach files (or paste / drop)"
            @click=${() => this.renderRoot.querySelector("input[type=file]").click()}>
            ${icon("plus")}</button>
          <input type="file" multiple
            @change=${(e) => { this._addFiles([...e.target.files]); e.target.value = ""; }}>
          <span class="spacer"></span>
          ${this._busy
            ? html`<button class="circle act abort" title="Stop"
                @click=${() => store.abort()}>${icon("stop")}</button>`
            : this._autoload
              ? html`<button class="circle act" disabled title=${localLlm.progress?.text || "Loading model..."}>
                  <span class="spin">${icon("arrow-path")}</span></button>`
              : html`<button class="circle act" title="Send (Enter)"
                  ?disabled=${!this._connected} @click=${() => this._send()}>
                  ${icon("arrow-up")}</button>`}
        </div>
      </div>
    `;
  }
}

customElements.define("ba-composer", BaComposer);
