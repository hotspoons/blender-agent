// SPDX-License-Identifier: GPL-3.0-or-later
//
// Message composer: Enter sends, Shift+Enter newlines, abort while
// busy. Image attachments arrive by paste, drag-and-drop, or the
// attach button; they upload immediately and ride along as media ids.
// The textarea auto-grows and is also manually resizable.

import { LitElement, html, css, nothing } from "lit";
import { store } from "/static/core/store.js";
import { icon } from "/static/core/icons.js";

export class BaComposer extends LitElement {
  static properties = {
    _busy: { state: true },
    _connected: { state: true },
    _attachments: { state: true },   // [{id, sessionId, uploading}]
    _dragOver: { state: true },
  };

  constructor() {
    super();
    this._busy = store.state.busy;
    this._connected = store.state.connected;
    this._attachments = [];
    this._dragOver = false;
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
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this._unsub?.();
  }

  async _addFiles(files) {
    for (const file of files) {
      if (!file.type.startsWith("image/")) continue;
      const staged = { id: "", sessionId: "", uploading: true, name: file.name || "pasted image" };
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
    const onMove = (ev) => {
      const next = Math.min(maxHeight, Math.max(24, startHeight + (startY - ev.clientY)));
      ta.style.height = next + "px";
      this._manualHeight = true;
    };
    const onUp = (ev) => {
      try { grip.releasePointerCapture(ev.pointerId); } catch {}
      grip.classList.remove("active");
      grip.removeEventListener("pointermove", onMove);
      grip.removeEventListener("pointerup", onUp);
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
      border-radius: var(--radius-md);
      padding: 8px 8px 8px 12px;
      transition: border-color 0.15s ease;
    }
    .box:focus-within { border-color: var(--accent); }
    .box.drag { border-color: var(--accent); background: var(--accent-soft); }
    .grip {
      height: 10px;
      margin: -8px -8px 0 -12px;   /* span the box's full width */
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
    .row { display: flex; gap: 8px; align-items: flex-end; }
    textarea {
      flex: 1;
      resize: none;              /* the top-edge handle resizes instead */
      border: none;
      outline: none;
      background: transparent;
      color: var(--text);
      font: inherit;
      line-height: 1.5;
      max-height: 50vh;
      min-height: 24px;
      padding: 4px 0;
    }
    textarea::placeholder { color: var(--text-muted); opacity: 0.7; }
    button.act {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font: inherit;
      font-weight: 600;
      border: none;
      border-radius: var(--radius-sm);
      padding: 9px 16px;
      cursor: pointer;
      color: #fff;
      background: linear-gradient(135deg, var(--accent), var(--accent-2));
    }
    button.act:disabled { opacity: 0.45; cursor: default; }
    button.act.abort { background: var(--danger); }
    button.attach {
      display: inline-flex;
      border: none;
      background: none;
      color: var(--text-muted);
      cursor: pointer;
      padding: 9px 6px;
      border-radius: var(--radius-sm);
    }
    button.attach:hover { color: var(--text); background: var(--accent-soft); }
    input[type="file"] { display: none; }
  `;

  _send() {
    const ta = this.renderRoot.querySelector("textarea");
    const text = ta.value.trim();
    const ready = this._attachments.filter((a) => !a.uploading).map((a) => a.id);
    if ((!text && !ready.length) || this._busy || !this._connected) return;
    if (this._attachments.some((a) => a.uploading)) return;
    store.chat(text || "(see attached image)", ready);
    this._attachments = [];
    ta.value = "";
    ta.style.height = "auto";
    this._manualHeight = false;
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
        <div class="row">
          <button class="attach" title="Attach image"
            @click=${() => this.renderRoot.querySelector("input[type=file]").click()}>
            ${icon("plus")}</button>
          <input type="file" accept="image/*" multiple
            @change=${(e) => { this._addFiles([...e.target.files]); e.target.value = ""; }}>
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
          ${this._busy
            ? html`<button class="act abort" @click=${() => store.abort()}>${icon("stop")} Stop</button>`
            : html`<button class="act" ?disabled=${!this._connected} @click=${() => this._send()}>
                ${icon("paper-airplane")} Send</button>`}
        </div>
      </div>
    `;
  }
}

customElements.define("ba-composer", BaComposer);
