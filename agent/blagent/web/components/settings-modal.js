// SPDX-License-Identifier: GPL-3.0-or-later
//
// Settings dialog. Model source is a mutually exclusive choice:
// a remote OpenAI-compatible endpoint (with the model combo box
// auto-populated from {endpoint}/models once reachable - directly,
// or after an API key is provided) or the local in-browser model
// model. All controls are Lit-rendered (core/widgets.js).

import { LitElement, html, css, nothing } from "lit";
import { store } from "/static/core/store.js";
import { icon } from "/static/core/icons.js";
import "/static/core/widgets.js";
import "/static/components/local-llm-panel.js";

export class BaSettingsModal extends LitElement {
  static properties = {
    _mode: { state: true },        // "remote" | "local"
    _endpoint: { state: true },
    _model: { state: true },
    _apiKey: { state: true },      // staged key; empty = keep saved
    _autonomy: { state: true },
    _models: { state: true },
  };

  constructor() {
    super();
    const config = store.state.config || {};
    this._mode = config.use_local_llm ? "local" : "remote";
    this._endpoint = config.endpoint || "";
    this._model = config.model || "";
    this._apiKey = "";
    this._autonomy = config.autonomy || "ask";
    this._models = store.state.models;
    this._fetchTimer = null;
  }

  connectedCallback() {
    super.connectedCallback();
    this._unsub = store.subscribe((keys) => {
      if (keys.has("models")) this._models = { ...store.state.models };
    });
    // Populate the combo for the saved endpoint right away.
    if (this._endpoint) store.requestModels(this._endpoint, "");
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this._unsub?.();
    clearTimeout(this._fetchTimer);
  }

  /** Debounced model-list fetch as the endpoint or key changes. */
  _scheduleModelFetch() {
    clearTimeout(this._fetchTimer);
    const endpoint = this._endpoint.trim();
    if (!endpoint) return;
    this._fetchTimer = setTimeout(() => {
      store.requestModels(endpoint, this._apiKey);
    }, 450);
  }

  static styles = css`
    *, *::before, *::after { box-sizing: border-box; }
    label {
      display: block;
      font-size: 12px;
      font-weight: 500;
      color: var(--text-muted);
      margin: 14px 0 5px;
      letter-spacing: 0.02em;
    }
    .section {
      display: flex;
      align-items: center;
      gap: 7px;
      font-size: 11px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--text-muted);
      margin: 18px 0 4px;
      padding-bottom: 6px;
      border-bottom: 1px solid var(--border);
    }
    .section:first-child { margin-top: 2px; }
    input.text {
      width: 100%;
      font: inherit;
      font-family: var(--font-sans);
      color: var(--text);
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      padding: 8px 10px;
      outline: none;
      transition: border-color 0.15s ease;
    }
    input.text:focus { border-color: var(--accent); }
    input.text::placeholder { color: var(--text-muted); opacity: 0.7; }
    .hint { font-size: 12px; color: var(--text-muted); margin-top: 5px; }
    .hint.err { color: var(--danger); }
    .hint.ok { color: var(--success); }
    .switchrow {
      display: flex;
      align-items: center;
      gap: 10px;
      font-size: 13.5px;
      color: var(--text);
      margin-top: 14px;
    }
    .switchrow .sub { color: var(--text-muted); font-size: 12px; }
    .localbox {
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      background: var(--surface);
      padding: 12px;
      margin-top: 12px;
    }
    button.btn {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font: inherit;
      font-weight: 600;
      border: none;
      border-radius: var(--radius-sm);
      padding: 8px 18px;
      cursor: pointer;
    }
    .btn.save { color: #fff; background: linear-gradient(135deg, var(--accent), var(--accent-2)); }
    .btn.cancel { background: var(--surface-muted); color: var(--text); }
  `;

  _save() {
    const updates = {
      use_local_llm: this._mode === "local",
      endpoint: this._endpoint.trim(),
      model: this._model.trim(),
      autonomy: this._autonomy,
    };
    if (this._apiKey) updates.api_key = this._apiKey;
    store.setConfig(updates);
    this.dispatchEvent(new CustomEvent("close"));
  }

  _renderRemote() {
    const config = store.state.config || {};
    const models = this._models;
    const forThisEndpoint = models.endpoint === this._endpoint.trim().replace(/\/+$/, "");
    return html`
      <label>Endpoint (OpenAI-compatible base URL ending in /v1)</label>
      <input class="text" type="text"
        placeholder="e.g. https://api.openai.com/v1 or http://127.0.0.1:8080/v1"
        .value=${this._endpoint}
        @input=${(e) => { this._endpoint = e.target.value; this._scheduleModelFetch(); }}>

      <label>API key ${config.has_api_key ? "(saved - enter to replace)" : "(optional)"}</label>
      <input class="text" type="password" autocomplete="off"
        placeholder=${config.has_api_key ? "************" : "none required for local servers"}
        .value=${this._apiKey}
        @input=${(e) => { this._apiKey = e.target.value; this._scheduleModelFetch(); }}>

      <label>Model</label>
      <ba-combo
        .value=${this._model}
        .options=${forThisEndpoint ? models.list : []}
        .loading=${models.loading}
        placeholder=${forThisEndpoint && models.list.length
          ? "pick from the list or type"
          : "type a model id, or enter an endpoint to list models"}
        @input=${(e) => { this._model = e.detail.value; }}></ba-combo>
      ${forThisEndpoint && models.error
        ? html`<div class="hint err">${icon("exclamation-triangle")} Could not list models: ${models.error}</div>`
        : nothing}
      ${forThisEndpoint && !models.error && models.list.length
        ? html`<div class="hint ok">${models.list.length} model(s) available from this endpoint.</div>`
        : nothing}
    `;
  }

  render() {
    return html`
      <ba-modal @close=${() => this.dispatchEvent(new CustomEvent("close"))}>
        <h2 slot="title">Agent settings</h2>

        <div class="section">${icon("cpu-chip")} Model source</div>
        <div style="margin-top: 10px;">
          <ba-segmented
            .options=${[
              { value: "remote", label: "Remote endpoint", icon: "arrow-top-right-on-square" },
              { value: "local", label: "Local (in-browser)", icon: "computer-desktop" },
            ]}
            .value=${this._mode}
            @input=${(e) => { this._mode = e.detail.value; }}></ba-segmented>
        </div>

        ${this._mode === "remote"
          ? this._renderRemote()
          : html`<div class="localbox"><ba-local-llm-panel></ba-local-llm-panel></div>`}

        <div class="section">${icon("cog-6-tooth")} Behavior</div>
        <div class="switchrow">
          <ba-switch .on=${this._autonomy === "auto"}
            @input=${(e) => { this._autonomy = e.detail.value ? "auto" : "ask"; }}></ba-switch>
          <span>Full autonomy
            <div class="sub">Off: destructive tool calls pause for an Allow/Deny confirmation.</div>
          </span>
        </div>

        <div slot="footer" style="display: flex; gap: 8px;">
          <button class="btn cancel" @click=${() => this.dispatchEvent(new CustomEvent("close"))}>Cancel</button>
          <button class="btn save" @click=${() => this._save()}>${icon("check")} Save</button>
        </div>
      </ba-modal>
    `;
  }
}

customElements.define("ba-settings-modal", BaSettingsModal);
