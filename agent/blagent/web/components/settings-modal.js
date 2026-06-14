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
    _contextTokens: { state: true },
    _models: { state: true },
    _policy: { state: true },
    _maxAutoRounds: { state: true },
    _shareContext: { state: true },
    _audit: { state: true },
    _workers: { state: true },
  };

  constructor() {
    super();
    const config = store.state.config || {};
    this._mode = config.use_local_llm ? "local" : "remote";
    this._endpoint = config.endpoint || "";
    this._model = config.model || "";
    this._apiKey = "";
    this._autonomy = config.autonomy || "ask";
    this._contextTokens = config.context_tokens || 16384;
    this._models = store.state.models;
    this._policy = config.autonomy_policy || "auto_until_done";
    this._maxAutoRounds = config.max_autonomy_rounds || 6;
    this._shareContext = !!config.autonomy_share_context;
    this._audit = !!config.autonomy_audit;
    this._workers = config.autonomy_workers || "in_process";
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
      context_tokens: Math.max(2048, parseInt(this._contextTokens, 10) || 16384),
      autonomy_policy: this._policy,
      max_autonomy_rounds: Math.max(1, parseInt(this._maxAutoRounds, 10) || 6),
      autonomy_share_context: this._shareContext,
      autonomy_audit: this._audit,
      autonomy_workers: this._workers,
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
            <div class="sub">Off: destructive tool calls pause for an Allow/Deny confirmation.
              Same switch as the composer's <strong>Ask</strong> ↔ <strong>YOLO</strong> levels.</div>
          </span>
        </div>

        <label>Context window (tokens)</label>
        <input class="text" type="number" min="2048" step="1024"
          .value=${String(this._contextTokens)}
          @input=${(e) => { this._contextTokens = e.target.value; }}>
        <div class="hint">Older exchanges are trimmed to fit this budget. Lower values keep
          long sessions fast - in-browser models especially slow down as the context grows.</div>

        <div class="section">${icon("rectangle-group")} Autonomy (orchestrator / swarm)</div>
        <label>Worker execution</label>
        <ba-segmented
          .options=${[
            { value: "in_process", label: "In-process" },
            { value: "swarm", label: "Swarm (subprocess)" },
          ]}
          .value=${this._workers}
          @input=${(e) => { this._workers = e.detail.value; }}></ba-segmented>
        <div class="hint">In-process: workers are child sessions in this process (the composer's
          <strong>Orchestrator</strong> level). Swarm: each worker is a subprocess with its own headless
          Blender, merged at the end (the composer's <strong>Swarm</strong> level). Picking a composer
          level sets this for you; change it here to mix (e.g. swarm workers without switching the slider).</div>

        <label>Policy</label>
        <ba-segmented
          .options=${[
            { value: "auto_until_done", label: "Auto until done" },
            { value: "pause_when_blocked", label: "Pause when blocked" },
          ]}
          .value=${this._policy}
          @input=${(e) => { this._policy = e.detail.value; }}></ba-segmented>
        <div class="hint">Auto until done runs round after round until objectives are met or the
          round cap; pause when blocked hands control back when the evaluator sees no path forward.</div>

        <label>Max autonomy rounds</label>
        <input class="text" type="number" min="1" step="1"
          .value=${String(this._maxAutoRounds)}
          @input=${(e) => { this._maxAutoRounds = e.target.value; }}>

        <div class="switchrow">
          <ba-switch .on=${this._shareContext}
            @input=${(e) => { this._shareContext = e.detail.value; }}></ba-switch>
          <span>Share orchestrator context with workers
            <div class="sub">Off (default): workers run blind on just their task. On: each worker is
              seeded with the objective list - so blind vs informed can be compared.</div>
          </span>
        </div>

        <div class="switchrow">
          <ba-switch .on=${this._audit}
            @input=${(e) => { this._audit = e.detail.value; }}></ba-switch>
          <span>Independent audit (catch reward-hacking)
            <div class="sub">Off (default): trust the orchestrator's verdict. On: after a run, a
              separate auditor with NO shared context re-checks every objective against the real
              scene and calls out overclaims. Costs one extra LLM pass per run.</div>
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
