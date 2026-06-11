// SPDX-License-Identifier: GPL-3.0-or-later
//
// In-browser LLM via Transformers.js (WebGPU with WASM fallback),
// served to the backend over the /ws/local-llm reverse tunnel. The
// tunnel protocol originates in zip-ties' `zt-webllm.js` and is
// engine-agnostic (see blagent/local_llm.py for the server side);
// inference itself runs in core/local-llm-worker.js so generation
// never blocks the UI thread.

import { LitElement, html, css, nothing } from "lit";
import { icon } from "/static/core/icons.js";
import { MainThreadLlmHost } from "/static/core/local-llm-engine.js";
import "/static/core/widgets.js";

export class BaLocalLlmPanel extends LitElement {
  static properties = {
    modelId: { type: String },
    status: { type: String },     // idle | loading | ready | error
    progress: { type: Object },
    _error: { state: true },
  };

  // Curated, fixed list - modern multi-component exports with external
  // weight data (model.onnx_data), which bypasses onnxruntime's 4GB
  // WASM session-build heap. NOT every Hub export qualifies: older
  // single-file exports >~1GB cannot load at all (Qwen3-1.7B q4f16),
  // and old exports also lack a KV-friendly layout. Sizes are the
  // q4f16 component totals actually downloaded.
  static MODELS = [
    { id: "onnx-community/Qwen3.5-0.8B-ONNX", label: "Qwen3.5 0.8B (~0.7GB)" },
    { id: "onnx-community/Qwen3.5-2B-ONNX", label: "Qwen3.5 2B (~1.6GB)" },
    { id: "onnx-community/Qwen3.5-4B-ONNX", label: "Qwen3.5 4B (~2.8GB)" },
    { id: "onnx-community/gemma-4-E2B-it-ONNX", label: "Gemma 4 E2B (~3.3GB)" },
    { id: "onnx-community/gemma-4-E4B-it-ONNX", label: "Gemma 4 E4B (~5.2GB)" },
  ];

  static STORAGE_KEY = "blender-agent.local-model";

  // Host (worker or main-thread engine) + WS survive component
  // teardown (panel toggles, session switches) in shared static state.
  static _shared = { worker: null, ws: null, modelId: "", status: "idle", device: "", hostKind: "" };

  constructor() {
    super();
    const s = BaLocalLlmPanel._shared;
    const stored = localStorage.getItem(BaLocalLlmPanel.STORAGE_KEY);
    const known = (id) => BaLocalLlmPanel.MODELS.some((m) => m.id === id);
    this.modelId = (s.modelId && known(s.modelId) && s.modelId)
      || (stored && known(stored) && stored)
      || BaLocalLlmPanel.MODELS[0].id;
    this.status = s.status;
    this.progress = null;
    this._error = "";
    this._worker = s.worker;
    this._ws = s.ws;
    this._device = s.device;
    this._hostKind = s.hostKind;  // "worker" | "main" (WebGPU-less workers)
    this._requests = new Map();   // request id -> {ws, content}
    if (this._worker) this._attachWorker(this._worker);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    BaLocalLlmPanel._shared = {
      worker: this._worker, ws: this._ws, modelId: this.modelId,
      status: this.status, device: this._device, hostKind: this._hostKind,
    };
  }

  _attachWorker(worker) {
    worker.onmessage = (e) => this._onWorkerMessage(e.data);
    worker.onerror = (e) => {
      this.status = "error";
      this._error = e.message || "inference worker crashed";
    };
  }

  /**
   * The worker reported it would run on WASM. If the PAGE has WebGPU,
   * this browser (Safari) just does not expose it to workers - rehost
   * the engine on the main thread, the trade WebLLM always made. GPU
   * inference is async, so the UI stays responsive; the WASM path
   * stays in the worker, where its blocking generate() belongs.
   */
  async _rehostOnMainThread() {
    try {
      if (!navigator.gpu || !await navigator.gpu.requestAdapter()) return false;
    } catch {
      return false;
    }
    try { this._worker.terminate(); } catch {}
    this._worker = new MainThreadLlmHost();
    this._hostKind = "main";
    this._attachWorker(this._worker);
    this.progress = { text: "WebGPU unavailable in workers here - reloading on the main thread...", progress: 0 };
    this._worker.postMessage({ type: "load", modelId: this.modelId.trim() });
    return true;
  }

  _onWorkerMessage(msg) {
    switch (msg.type) {
      case "device": {
        this._device = msg.device;
        if (msg.device === "wasm" && this._hostKind === "worker" && this.status === "loading") {
          this._rehostOnMainThread();
        }
        break;
      }
      case "progress": {
        const mb = (n) => (n / (1024 * 1024)).toFixed(0);
        this.progress = {
          progress: msg.progress,
          text: msg.total
            ? `Downloading model... ${mb(msg.loaded)} / ${mb(msg.total)} MB`
            : "Preparing model...",
        };
        break;
      }
      case "ready":
        this.status = "ready";
        this.progress = null;
        this._device = msg.device;
        localStorage.setItem(BaLocalLlmPanel.STORAGE_KEY, this.modelId);
        BaLocalLlmPanel._shared = {
          worker: this._worker, ws: null, modelId: this.modelId,
          status: "ready", device: msg.device, hostKind: this._hostKind,
        };
        this._connectBridge();
        break;
      case "load_error":
        this.status = "error";
        this._error = msg.message;
        this.progress = null;
        break;
      case "delta": {
        const req = this._requests.get(msg.id);
        if (!req) break;
        req.content += msg.text;
        this._sendChunk(req.ws, msg.id, { content: msg.text });
        break;
      }
      case "done": {
        const req = this._requests.get(msg.id);
        if (!req) break;
        this._requests.delete(msg.id);
        this._finishRequest(req.ws, msg.id, req.content);
        break;
      }
      case "error": {
        const req = this._requests.get(msg.id);
        if (req) {
          this._requests.delete(msg.id);
          req.ws.send(JSON.stringify({ id: msg.id, error: msg.message }));
        }
        break;
      }
      default:
        break;
    }
  }

  async _loadModel() {
    this.status = "loading";
    this._error = "";
    this.progress = { text: "Starting inference worker...", progress: 0 };
    if (!this._worker) {
      this._worker = new Worker("/static/core/local-llm-worker.js", { type: "module" });
      this._hostKind = "worker";
      this._attachWorker(this._worker);
    }
    this._worker.postMessage({ type: "load", modelId: this.modelId.trim() });
  }

  _unloadModel() {
    this._closeWs();
    if (this._worker) {
      // Terminate rather than dispose: frees GPU/WASM memory at once
      // and guarantees no half-finished generation lingers.
      try { this._worker.terminate(); } catch {}
      this._worker = null;
    }
    this._requests.clear();
    this.status = "idle";
    this.progress = null;
    this._error = "";
    this._hostKind = "";
    localStorage.removeItem(BaLocalLlmPanel.STORAGE_KEY);
    BaLocalLlmPanel._shared = { worker: null, ws: null, modelId: "", status: "idle", device: "", hostKind: "" };
  }

  _connectBridge() {
    this._closeWs();
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws/local-llm`);

    ws.onopen = () => {
      ws.send(JSON.stringify({ type: "model_info", model_id: this.modelId, status: "ready" }));
    };
    ws.onmessage = (e) => {
      try {
        const req = JSON.parse(e.data);
        this._handleRequest(req, ws);
      } catch (err) {
        console.error("local-model request handling error:", err);
      }
    };
    ws.onclose = () => {
      this._ws = null;
      if (this.status === "ready") setTimeout(() => this._connectBridge(), 2000);
    };
    this._ws = ws;
  }

  _closeWs() {
    if (this._ws) {
      try { this._ws.close(); } catch {}
      this._ws = null;
    }
  }

  /** Prepare messages: thinking directive, tool injection, role rewrites. */
  _prepareMessages(req) {
    let messages = [...(req.messages || [])];

    // Qwen-family models default to reasoning mode; suppress it - on
    // small local models thinking burns the token budget before the
    // tool call ever appears.
    if (/qwen/i.test(this.modelId)) {
      const directive = "/no_think";
      if (messages.length > 0 && messages[0].role === "system") {
        messages[0] = { ...messages[0], content: `${directive}\n${messages[0].content}` };
      } else {
        messages.unshift({ role: "system", content: directive });
      }
    }

    // Tools are injected into the system prompt rather than handed to
    // the model natively - small local models are unreliable with
    // structured function-calling, so <tool_call> tags are parsed here.
    const toolDefs = req.tools || [];
    if (toolDefs.length > 0) {
      const toolBlock = toolDefs.map((t) => {
        const f = t.function || t;
        return `- ${f.name}: ${f.description || ""}${f.parameters ? `\n  Parameters: ${JSON.stringify(f.parameters)}` : ""}`;
      }).join("\n");
      const toolPrompt = [
        "You have access to tools. To call one, output a <tool_call> block:",
        "<tool_call>",
        '{"name": "exact_tool_id", "arguments": {...}}',
        "</tool_call>",
        "",
        'IMPORTANT: "name" MUST be the exact tool identifier shown before the colon below, NOT a display name.',
        "",
        "Available tools:",
        toolBlock,
        "",
        "Call zero or more tools. If none are needed, respond normally without <tool_call> tags.",
      ].join("\n");
      if (messages.length > 0 && messages[0].role === "system") {
        messages[0] = { ...messages[0], content: `${messages[0].content}\n\n${toolPrompt}` };
      } else {
        messages.unshift({ role: "system", content: toolPrompt });
      }
    }

    // Chat templates expect system/user/assistant roles with string
    // content; tool records and vision arrays are flattened.
    messages = messages.map((m) => {
      if (m.role === "assistant" && m.tool_calls) {
        const callText = m.tool_calls.map((tc) => {
          const fn = tc.function || {};
          return `<tool_call>\n{"name": "${fn.name}", "arguments": ${fn.arguments || "{}"}}\n</tool_call>`;
        }).join("\n");
        const { tool_calls, ...rest } = m;
        return { ...rest, content: `${rest.content || ""}${callText}`.trim() };
      }
      if (m.role === "tool") {
        const label = m.name || m.tool_call_id || "unknown";
        return { role: "user", content: `[Tool result: ${label}]\n${m.content}` };
      }
      if (Array.isArray(m.content)) {
        const text = m.content.filter((p) => p.type === "text").map((p) => p.text).join("\n");
        return { ...m, content: text || "[attached media omitted - text-only local model]" };
      }
      return m;
    });

    return messages;
  }

  _handleRequest(req, ws) {
    const requestId = req.id;
    if (!requestId || !this._worker) return;
    if (req.type === "abort") {
      // The server dropped the stream (aborted turn): stop generating.
      // Requests are serialized, so interrupting the worker only ever
      // hits the request being aborted.
      if (this._requests.delete(requestId)) {
        this._worker.postMessage({ type: "abort" });
      }
      return;
    }
    this._requests.set(requestId, { ws, content: "" });
    this._worker.postMessage({
      type: "generate",
      id: requestId,
      messages: this._prepareMessages(req),
      temperature: req.temperature,
      max_tokens: req.max_tokens,
    });
  }

  _sendChunk(ws, requestId, delta, finishReason = null) {
    ws.send(JSON.stringify({
      id: requestId,
      type: "chunk",
      choices: [{ index: 0, delta, finish_reason: finishReason }],
      model: this.modelId,
    }));
  }

  /** Post-stream: surface <tool_call> blocks as proper tool calls. */
  _finishRequest(ws, requestId, fullContent) {
    const parsed = this._parseToolCalls(fullContent || "");
    for (let i = 0; i < parsed.toolCalls.length; i++) {
      const tc = parsed.toolCalls[i];
      this._sendChunk(ws, requestId, {
        tool_calls: [{
          index: i,
          id: `call_${requestId.slice(0, 8)}_${i}`,
          type: "function",
          function: { name: tc.name, arguments: JSON.stringify(tc.arguments) },
        }],
      });
    }
    if (parsed.toolCalls.length > 0) {
      this._sendChunk(ws, requestId, {}, "tool_calls");
    }
    ws.send(JSON.stringify({ id: requestId, type: "done" }));
  }

  _parseToolCalls(text) {
    const toolCalls = [];
    const re = /<tool_call>\s*([\s\S]*?)\s*<\/tool_call>/g;
    let match;
    while ((match = re.exec(text)) !== null) {
      try {
        const obj = JSON.parse(match[1]);
        toolCalls.push({
          name: obj.name || obj.function?.name || "",
          arguments: obj.arguments || obj.parameters || {},
        });
      } catch {}
    }
    const cleanContent = text.replace(/<tool_call>[\s\S]*?<\/tool_call>/g, "").trim();
    return { toolCalls, cleanContent };
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
    .row ba-combo { flex: 1; min-width: 0; }
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
    .err { font-size: 12px; color: var(--danger); margin-top: 6px; }
  `;

  render() {
    const isLoading = this.status === "loading";
    const isReady = this.status === "ready";
    const labels = BaLocalLlmPanel.MODELS.map((m) => m.label);
    const current = BaLocalLlmPanel.MODELS.find((m) => m.id === this.modelId);
    return html`
      <div class="head">${icon("cpu-chip")} Transformers.js (in-browser)
        <span class="dot ${this.status}"></span></div>
      <div class="row">
        <ba-combo .options=${labels} .editable=${false}
          .value=${current?.label || ""}
          @input=${(e) => {
            const picked = BaLocalLlmPanel.MODELS[labels.indexOf(e.detail.value)];
            if (picked && !isLoading && !isReady) this.modelId = picked.id;
          }}></ba-combo>
        ${isReady
          ? html`<button class="act danger" @click=${this._unloadModel}>${icon("x-mark")} Unload</button>`
          : html`<button class="act" ?disabled=${isLoading} @click=${this._loadModel}>
              ${isLoading ? "Loading..." : html`${icon("check")} Load`}</button>`}
      </div>
      <div class="hint">Runs on your GPU via WebGPU. Weights download once from the
        Hugging Face Hub, then are cached by the browser.</div>
      ${isLoading && this.progress ? html`
        <div class="bar"><div class="fill" style="width: ${(this.progress.progress * 100).toFixed(0)}%"></div></div>
        <div class="hint">${this.progress.text}</div>` : nothing}
      ${isReady ? html`<div class="hint">
        Model loaded on ${this._device === "webgpu" ? "WebGPU" : "WASM (no WebGPU - slower)"}${
          this._hostKind === "main" ? " (main thread - this browser has no WebGPU in workers)" : ""};
        serving the backend over the reverse tunnel.</div>` : nothing}
      ${this._error ? html`<div class="err">${this._error}</div>` : nothing}
    `;
  }
}

customElements.define("ba-local-llm-panel", BaLocalLlmPanel);
