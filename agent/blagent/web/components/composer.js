// SPDX-License-Identifier: GPL-3.0-or-later
//
// Message composer: Enter sends, Shift+Enter newlines; abort while busy.

import { LitElement, html, css } from "lit";
import { store } from "/static/core/store.js";

export class BaComposer extends LitElement {
  static properties = {
    _busy: { state: true },
    _connected: { state: true },
  };

  constructor() {
    super();
    this._busy = store.state.busy;
    this._connected = store.state.connected;
  }

  connectedCallback() {
    super.connectedCallback();
    this._unsub = store.subscribe((keys) => {
      if (keys.has("busy")) this._busy = store.state.busy;
      if (keys.has("connected")) this._connected = store.state.connected;
    });
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this._unsub?.();
  }

  static styles = css`
    :host {
      display: block;
      padding: 10px 14px 14px;
      background: var(--bg);
    }
    .box {
      max-width: 860px;
      margin: 0 auto;
      display: flex;
      gap: 8px;
      align-items: flex-end;
      background: var(--bg-input);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 8px;
    }
    .box:focus-within { border-color: var(--accent); }
    textarea {
      flex: 1;
      resize: none;
      border: none;
      outline: none;
      background: transparent;
      color: var(--text);
      font: inherit;
      max-height: 180px;
      min-height: 22px;
    }
    button {
      border: none;
      border-radius: 8px;
      padding: 8px 16px;
      font-weight: 600;
      cursor: pointer;
      background: var(--accent);
      color: #fff;
    }
    button:disabled { opacity: 0.45; cursor: default; }
    button.abort { background: var(--err); }
  `;

  _send() {
    const ta = this.renderRoot.querySelector("textarea");
    const text = ta.value.trim();
    if (!text || this._busy || !this._connected) return;
    store.chat(text);
    ta.value = "";
    ta.style.height = "auto";
  }

  render() {
    return html`
      <div class="box">
        <textarea rows="1" placeholder="Ask the Blender agent..."
          @input=${(e) => {
            e.target.style.height = "auto";
            e.target.style.height = e.target.scrollHeight + "px";
          }}
          @keydown=${(e) => {
            if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); this._send(); }
          }}></textarea>
        ${this._busy
          ? html`<button class="abort" @click=${() => store.abort()}>Stop</button>`
          : html`<button ?disabled=${!this._connected} @click=${() => this._send()}>Send</button>`}
      </div>
    `;
  }
}

customElements.define("ba-composer", BaComposer);
