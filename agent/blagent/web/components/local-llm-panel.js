// SPDX-License-Identifier: GPL-3.0-or-later
//
// Settings view over the local-model controller
// (core/local-llm-controller.js): engine picker (Transformers.js /
// WebLLM), curated model list, tool-call format override, load
// progress and per-turn throughput stats. The controller owns the
// inference host and the reverse tunnel - this component is a thin
// observer, so loads keep running when the settings modal closes
// (the topbar model chip is another view over the same state).

import { LitElement, html, css, nothing } from "lit";
import { icon } from "/static/core/icons.js";
import { localLlm, TRANSFORMERS_MODELS, WEBLLM_MODELS } from "/static/core/local-llm-controller.js";
import { FAMILIES } from "/static/core/llm-output-parser.js";
import "/static/core/widgets.js";

export class BaLocalLlmPanel extends LitElement {
  static properties = {
    _tick: { state: true },
  };

  constructor() {
    super();
    this._tick = 0;
    this._onChange = () => { this._tick += 1; };
  }

  connectedCallback() {
    super.connectedCallback();
    localLlm.addEventListener("change", this._onChange);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    localLlm.removeEventListener("change", this._onChange);
  }

  static styles = css`
    *, *::before, *::after { box-sizing: border-box; }
    :host { display: block; font-family: var(--font-sans); }
    .head {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 10px;
      font-weight: 600;
      font-size: 13.5px;
      color: var(--text);
    }
    .dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; margin-left: auto; }
    .dot.idle { background: var(--text-muted); }
    .dot.loading { background: var(--warning); animation: pulse 1s infinite; }
    .dot.ready { background: var(--success); }
    .dot.error { background: var(--danger); }
    @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
    .row { display: flex; gap: 8px; align-items: center; }
    .row + .row { margin-top: 8px; }
    .row ba-combo { flex: 1; min-width: 0; }
    .seg {
      display: inline-flex;
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      overflow: hidden;
    }
    .seg button {
      font: inherit;
      font-size: 12.5px;
      font-weight: 600;
      padding: 6px 12px;
      border: none;
      background: transparent;
      color: var(--text-muted);
      cursor: pointer;
    }
    .seg button.on {
      background: var(--accent-soft);
      color: var(--text);
    }
    .seg button:disabled { cursor: default; opacity: 0.6; }
    button.act {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font: inherit;
      font-size: 13px;
      font-weight: 600;
      padding: 8px 14px;
      border-radius: var(--radius-sm);
      border: 1px solid var(--accent);
      background: var(--accent-soft);
      color: var(--text);
      cursor: pointer;
      white-space: nowrap;
    }
    button.act:disabled { opacity: 0.5; cursor: default; }
    button.act.danger { border-color: var(--danger); color: var(--danger); background: transparent; }
    .fmt {
      display: flex;
      gap: 6px;
      align-items: center;
      font-size: 12px;
      color: var(--text-muted);
    }
    .fmt select {
      font: inherit;
      font-size: 12px;
      padding: 3px 6px;
      border-radius: var(--radius-sm);
      border: 1px solid var(--border);
      background: var(--surface);
      color: var(--text);
    }
    .bar {
      width: 100%; height: 4px; border-radius: 2px;
      background: var(--surface-muted); overflow: hidden; margin-top: 10px;
    }
    .fill {
      height: 100%;
      background: linear-gradient(90deg, var(--accent), var(--accent-2));
      transition: width 0.3s ease;
    }
    .hint { font-size: 12px; color: var(--text-muted); margin-top: 6px; }
    .stats {
      font-size: 12px;
      color: var(--text-muted);
      margin-top: 6px;
      font-variant-numeric: tabular-nums;
    }
    .stats b { color: var(--text); font-weight: 600; }
    .err { font-size: 12px; color: var(--danger); margin-top: 6px; }
  `;

  _renderStats() {
    const s = localLlm.stats;
    if (!s) return nothing;
    const chunks = s.prefill_chunks ? ` / ${s.prefill_chunks} chunks` : "";
    return html`<div class="stats">
      Last turn: prefill <b>${s.prompt_tokens}</b> tok in <b>${(s.prefill_ms / 1000).toFixed(1)}s</b>
      (${s.prefill_tps} tok/s${chunks}) ·
      decode <b>${s.decode_tps}</b> tok/s (${s.decode_tokens} tok)
    </div>`;
  }

  render() {
    const c = localLlm;
    const isLoading = c.status === "loading";
    const isReady = c.status === "ready";
    const busy = isLoading || isReady;
    const isWebllm = c.engineKind === "webllm";
    const familyKey = c.familyKey();
    const list = isWebllm ? WEBLLM_MODELS : TRANSFORMERS_MODELS;
    const labels = list.map((m) => m.label);
    const current = list.find((m) => m.id === c.modelId);
    return html`
      <div class="head">${icon("cpu-chip")} Local model (in-browser)
        <span class="dot ${c.status}"></span></div>
      <div class="row">
        <span class="seg">
          <button class=${!isWebllm ? "on" : ""} ?disabled=${busy}
            title=${busy ? "Unload the model to switch engines" : "ONNX Runtime Web - widest model catalog"}
            @click=${() => c.switchEngine("transformers")}>Transformers.js</button>
          <button class=${isWebllm ? "on" : ""} ?disabled=${busy}
            title=${busy ? "Unload the model to switch engines" : "MLC WebGPU kernels - fastest at long context, smaller catalog"}
            @click=${() => c.switchEngine("webllm")}>WebLLM</button>
        </span>
        <span class="fmt" style="margin-left:auto">
          Tool calls
          <select .value=${c.familyOverride} @change=${(e) => c.setFamily(e.target.value)}>
            <option value="auto">Auto (${FAMILIES[familyKey] ? familyKey : "generic"})</option>
            <option value="qwen">Qwen</option>
            <option value="gemma">Gemma 4</option>
            <option value="harmony">Harmony (GPT-OSS)</option>
            <option value="generic">Generic</option>
          </select>
        </span>
      </div>
      <div class="row">
        <ba-combo .options=${labels} .editable=${false}
          .value=${current?.label || ""}
          @input=${(e) => {
            const picked = list[labels.indexOf(e.detail.value)];
            if (picked) c.pickModel(picked.id);
          }}></ba-combo>
        ${isReady
          ? html`<button class="act danger" @click=${() => c.unload()}>${icon("x-mark")} Unload</button>`
          : html`<button class="act" ?disabled=${isLoading} @click=${() => c.load()}>
              ${isLoading ? "Loading..." : html`${icon("check")} Load`}</button>`}
      </div>
      <div class="hint">${isWebllm
        ? "MLC-compiled models (paged attention - fast at long context). Qwen3.5 entries are official mlc-ai builds; Gemma 4 is a community-compiled wasm. Weights download once and are cached."
        : "Runs on your GPU via WebGPU. Weights download once from the Hugging Face Hub, then are cached by the browser."}</div>
      ${isLoading && c.progress ? html`
        <div class="bar"><div class="fill" style="width: ${(c.progress.progress * 100).toFixed(0)}%"></div></div>
        <div class="hint">${c.progress.text}</div>` : nothing}
      ${isReady ? html`<div class="hint">
        Model loaded on ${isWebllm ? "WebGPU (MLC)" : c.device === "webgpu" ? "WebGPU" : "WASM (no WebGPU - slower)"}${
          c.hostKind === "main" ? " (main thread - this browser has no WebGPU in workers)" : ""};
        serving the backend over the reverse tunnel. Tool-call format: ${familyKey}.</div>` : nothing}
      ${this._renderStats()}
      ${c.error ? html`<div class="err">${c.error}</div>` : nothing}
    `;
  }
}

customElements.define("ba-local-llm-panel", BaLocalLlmPanel);
