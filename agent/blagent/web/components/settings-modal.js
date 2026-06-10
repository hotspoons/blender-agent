// SPDX-License-Identifier: GPL-3.0-or-later
//
// Settings: LLM endpoint/model/key, autonomy mode, WebLLM fallback.
// Modeled on Foyer Studio's agent settings modal.

import { LitElement, html, css } from "lit";
import { store } from "/static/core/store.js";

export class BaSettingsModal extends LitElement {
  static properties = {
    _config: { state: true },
  };

  constructor() {
    super();
    this._config = { ...store.state.config };
  }

  static styles = css`
    :host {
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.5);
      display: flex;
      align-items: center;
      justify-content: center;
      z-index: 100;
    }
    .modal {
      width: min(480px, 92vw);
      background: var(--bg-panel);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 18px;
    }
    h2 { margin: 0 0 14px; font-size: 16px; }
    label { display: block; font-size: 12px; color: var(--text-dim); margin: 10px 0 4px; }
    input, select {
      width: 100%;
      padding: 7px 9px;
      border-radius: 7px;
      border: 1px solid var(--border);
      background: var(--bg-input);
      color: var(--text);
      font: inherit;
    }
    input:focus, select:focus { outline: none; border-color: var(--accent); }
    .check { display: flex; align-items: center; gap: 8px; margin-top: 12px; font-size: 13px; }
    .check input { width: auto; }
    .hint { font-size: 11.5px; color: var(--text-dim); margin-top: 3px; }
    .row { display: flex; justify-content: flex-end; gap: 8px; margin-top: 18px; }
    button {
      border: none;
      border-radius: 8px;
      padding: 8px 16px;
      cursor: pointer;
      font-weight: 600;
    }
    .save { background: var(--accent); color: #fff; }
    .cancel { background: var(--bg-raised); color: var(--text); }
  `;

  _save() {
    const updates = {
      endpoint: this._config.endpoint || "",
      model: this._config.model || "",
      autonomy: this._config.autonomy || "ask",
      use_webllm: !!this._config.use_webllm,
    };
    const key = this.renderRoot.querySelector("#api-key").value;
    if (key) updates.api_key = key;
    store.setConfig(updates);
    this.dispatchEvent(new CustomEvent("close"));
  }

  render() {
    const c = this._config;
    return html`
      <div class="modal" @click=${(e) => e.stopPropagation()}>
        <h2>Agent settings</h2>

        <label>OpenAI-compatible endpoint (base URL ending in /v1)</label>
        <input type="text" placeholder="e.g. https://api.openai.com/v1 or http://127.0.0.1:8080/v1"
          .value=${c.endpoint || ""}
          @input=${(e) => { this._config = { ...c, endpoint: e.target.value }; }}>
        <div class="hint">Leave empty to use the in-browser WebLLM model.</div>

        <label>Model</label>
        <input type="text" placeholder="e.g. gpt-4o, claude-fable-5, qwen3:8b"
          .value=${c.model || ""}
          @input=${(e) => { this._config = { ...c, model: e.target.value }; }}>

        <label>API key (optional)</label>
        <input id="api-key" type="password"
          placeholder=${c.has_api_key ? "(saved - enter to replace)" : "(none)"}>

        <label>Autonomy</label>
        <select .value=${c.autonomy || "ask"}
          @change=${(e) => { this._config = { ...c, autonomy: e.target.value }; }}>
          <option value="ask">Ask - confirm destructive tool calls</option>
          <option value="auto">Auto - run everything without confirmation</option>
        </select>

        <div class="check">
          <input id="webllm" type="checkbox" .checked=${c.use_webllm !== false}
            @change=${(e) => { this._config = { ...c, use_webllm: e.target.checked }; }}>
          <label for="webllm" style="margin: 0;">Use in-browser WebLLM when no endpoint is set</label>
        </div>

        <div class="row">
          <button class="cancel" @click=${() => this.dispatchEvent(new CustomEvent("close"))}>Cancel</button>
          <button class="save" @click=${() => this._save()}>Save</button>
        </div>
      </div>
    `;
  }

  connectedCallback() {
    super.connectedCallback();
    this.addEventListener("click", (e) => {
      if (e.target === this) this.dispatchEvent(new CustomEvent("close"));
    });
  }
}

customElements.define("ba-settings-modal", BaSettingsModal);
