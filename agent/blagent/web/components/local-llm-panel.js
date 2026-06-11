// SPDX-License-Identifier: GPL-3.0-or-later
//
// In-browser LLM via WebGPU/WebLLM, served to the backend over the
// /ws/webllm reverse tunnel. Ported from zip-ties' `zt-webllm.js`
// (same wire protocol; see blagent/webllm.py for the server side).

import { LitElement, html, css, nothing } from "lit";

export class BaWebLlmPanel extends LitElement {
  static properties = {
    modelId: { type: String },
    status: { type: String },     // idle | loading | ready | error
    progress: { type: Object },
    thinking: { type: Boolean },
    _error: { state: true },
  };

  static MODELS = [
    { id: "Qwen3-8B-q4f16_1-MLC", label: "Qwen3 8B", size: "~4.5GB" },
    { id: "Qwen3-4B-q4f16_1-MLC", label: "Qwen3 4B", size: "~2.3GB" },
    { id: "Qwen3-1.7B-q4f16_1-MLC", label: "Qwen3 1.7B", size: "~1.0GB" },
    { id: "Qwen3-30B-A3B-q4f16_1-MLC", label: "Qwen3 30B MoE", size: "~17GB" },
    { id: "Hermes-3-Llama-3.1-8B-q4f16_1-MLC", label: "Hermes 3 Llama 3.1 8B", size: "~4.3GB" },
    { id: "Hermes-2-Pro-Mistral-7B-q4f16_1-MLC", label: "Hermes 2 Pro Mistral 7B", size: "~4.0GB" },
  ];

  static STORAGE_KEY = "blender-agent.webllm-model";
  static THINKING_KEY = "blender-agent.webllm-thinking";

  // Engine + WS survive component teardown (panel toggles, session
  // switches) in shared static state.
  static _shared = { engine: null, ws: null, modelId: "", status: "idle" };

  constructor() {
    super();
    const s = BaWebLlmPanel._shared;
    this.modelId = s.modelId || localStorage.getItem(BaWebLlmPanel.STORAGE_KEY) || BaWebLlmPanel.MODELS[2].id;
    this.status = s.status;
    this.progress = null;
    this.thinking = localStorage.getItem(BaWebLlmPanel.THINKING_KEY) === "true";
    this._error = "";
    this._engine = s.engine;
    this._ws = s.ws;
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    BaWebLlmPanel._shared = {
      engine: this._engine, ws: this._ws, modelId: this.modelId, status: this.status,
    };
  }

  async _loadModel() {
    this.status = "loading";
    this._error = "";
    this.progress = { text: "Initializing WebLLM engine...", progress: 0 };
    try {
      if (!navigator.gpu) {
        throw new Error("WebGPU is not available in this browser.");
      }
      const { CreateMLCEngine } = await import("@mlc-ai/web-llm");
      this._engine = await CreateMLCEngine(
        this.modelId,
        {
          initProgressCallback: (report) => {
            this.progress = { text: report.text || "", progress: report.progress || 0 };
          },
        },
        { context_window_size: 20480 },
      );
      this.status = "ready";
      this.progress = null;
      localStorage.setItem(BaWebLlmPanel.STORAGE_KEY, this.modelId);
      BaWebLlmPanel._shared = { engine: this._engine, ws: null, modelId: this.modelId, status: "ready" };
      await this._connectBridge();
    } catch (e) {
      this.status = "error";
      this._error = e.message || String(e);
      console.error("WebLLM load failed:", e);
    }
  }

  _unloadModel() {
    this._closeWs();
    if (this._engine) {
      try { this._engine.unload(); } catch {}
      this._engine = null;
    }
    this.status = "idle";
    this.progress = null;
    this._error = "";
    localStorage.removeItem(BaWebLlmPanel.STORAGE_KEY);
    BaWebLlmPanel._shared = { engine: null, ws: null, modelId: "", status: "idle" };
  }

  _connectBridge() {
    this._closeWs();
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws/webllm`);

    const ready = new Promise((resolve, reject) => {
      ws.onopen = () => {
        ws.send(JSON.stringify({ type: "model_info", model_id: this.modelId, status: "ready" }));
        resolve();
      };
      ws.onerror = (e) => reject(e);
    });

    ws.onmessage = async (e) => {
      try {
        const req = JSON.parse(e.data);
        await this._handleRequest(req, ws);
      } catch (err) {
        console.error("WebLLM request handling error:", err);
      }
    };
    ws.onclose = () => {
      this._ws = null;
      if (this.status === "ready") setTimeout(() => this._connectBridge(), 2000);
    };
    this._ws = ws;
    return ready;
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

    if (!this.thinking) {
      const directive = "/no_think";
      if (messages.length > 0 && messages[0].role === "system") {
        messages[0] = { ...messages[0], content: `${directive}\n${messages[0].content}` };
      } else {
        messages.unshift({ role: "system", content: directive });
      }
    }

    // Tools are injected into the system prompt rather than passed to
    // the engine - WebLLM's native function-calling parsers are
    // model-specific and fragile; <tool_call> tags are parsed here.
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

    // WebLLM only supports system/user/assistant roles.
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
      // Vision content arrays are not supported by WebLLM text models;
      // flatten to the text parts.
      if (Array.isArray(m.content)) {
        const text = m.content.filter((p) => p.type === "text").map((p) => p.text).join("\n");
        return { ...m, content: text || "[attached media omitted - text-only local model]" };
      }
      return m;
    });

    return messages;
  }

  async _handleRequest(req, ws) {
    const requestId = req.id;
    if (!requestId || !this._engine) return;
    try {
      const messages = this._prepareMessages(req);
      const model = req.model || this.modelId;
      const chunks = await this._engine.chat.completions.create({
        messages,
        model,
        temperature: req.temperature ?? 0.7,
        max_tokens: req.max_tokens ?? 2048,
        stream: true,
      });

      let fullContent = "";
      for await (const chunk of chunks) {
        const choice = chunk.choices?.[0];
        if (!choice) continue;
        const delta = choice.delta || {};
        if (delta.content) fullContent += delta.content;
        ws.send(JSON.stringify({
          id: requestId,
          type: "chunk",
          choices: [{ index: 0, delta, finish_reason: choice.finish_reason || null }],
          model,
        }));
      }

      // Post-stream: surface <tool_call> blocks as proper tool calls.
      if (fullContent) {
        const parsed = this._parseToolCalls(fullContent);
        for (let i = 0; i < parsed.toolCalls.length; i++) {
          const tc = parsed.toolCalls[i];
          ws.send(JSON.stringify({
            id: requestId,
            type: "chunk",
            choices: [{
              index: 0,
              delta: {
                tool_calls: [{
                  index: i,
                  id: `call_${requestId.slice(0, 8)}_${i}`,
                  type: "function",
                  function: { name: tc.name, arguments: JSON.stringify(tc.arguments) },
                }],
              },
              finish_reason: null,
            }],
            model,
          }));
        }
        if (parsed.toolCalls.length > 0) {
          ws.send(JSON.stringify({
            id: requestId,
            type: "chunk",
            choices: [{ index: 0, delta: {}, finish_reason: "tool_calls" }],
            model,
          }));
        }
      }
      ws.send(JSON.stringify({ id: requestId, type: "done" }));
    } catch (err) {
      ws.send(JSON.stringify({ id: requestId, error: err.message || String(err) }));
    }
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
    :host { display: block; }
    .card {
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 10px;
      background: var(--bg-raised);
      font-size: 12.5px;
    }
    .head { display: flex; align-items: center; gap: 7px; margin-bottom: 8px; font-weight: 600; }
    .dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
    .dot.idle { background: var(--text-dim); }
    .dot.loading { background: var(--warn); animation: pulse 1s infinite; }
    .dot.ready { background: var(--ok); }
    .dot.error { background: var(--err); }
    @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
    .row { display: flex; gap: 6px; align-items: center; }
    select, button {
      font-size: 12px;
      padding: 5px 8px;
      border-radius: 6px;
      border: 1px solid var(--border);
      background: var(--bg-input);
      color: var(--text);
    }
    select { flex: 1; min-width: 0; }
    button { cursor: pointer; white-space: nowrap; }
    button.primary { background: var(--accent-soft); border-color: var(--accent); }
    button.danger { border-color: var(--err); color: var(--err); }
    .bar {
      width: 100%; height: 4px; border-radius: 2px;
      background: var(--bg-input); overflow: hidden; margin-top: 8px;
    }
    .fill { height: 100%; background: var(--accent); transition: width 0.3s ease; }
    .hint { font-size: 11px; color: var(--text-dim); margin-top: 5px; }
    .err { font-size: 11.5px; color: var(--err); margin-top: 5px; }
    label.think {
      display: flex; align-items: center; gap: 5px;
      font-size: 11.5px; color: var(--text-dim); margin-top: 7px; cursor: pointer;
    }
  `;

  render() {
    const isLoading = this.status === "loading";
    const isReady = this.status === "ready";
    return html`
      <div class="card">
        <div class="head"><span class="dot ${this.status}"></span> WebLLM (in-browser)</div>
        <div class="row">
          <select ?disabled=${isLoading || isReady}
            @change=${(e) => { this.modelId = e.target.value; }}>
            ${BaWebLlmPanel.MODELS.map((m) => html`
              <option value=${m.id} ?selected=${m.id === this.modelId}>${m.label} (${m.size})</option>`)}
          </select>
          ${isReady
            ? html`<button class="danger" @click=${this._unloadModel}>Unload</button>`
            : html`<button class="primary" ?disabled=${isLoading} @click=${this._loadModel}>
                ${isLoading ? "Loading..." : "Load"}</button>`}
        </div>
        ${isLoading && this.progress ? html`
          <div class="bar"><div class="fill" style="width: ${(this.progress.progress * 100).toFixed(0)}%"></div></div>
          <div class="hint">${this.progress.text}</div>` : nothing}
        <label class="think">
          <input type="checkbox" .checked=${this.thinking} @change=${(e) => {
            this.thinking = e.target.checked;
            localStorage.setItem(BaWebLlmPanel.THINKING_KEY, String(this.thinking));
          }}>
          Allow thinking
        </label>
        ${isReady ? html`<div class="hint">Model loaded; serving the backend over the reverse tunnel.</div>` : nothing}
        ${this._error ? html`<div class="err">${this._error}</div>` : nothing}
      </div>
    `;
  }
}

customElements.define("ba-webllm-panel", BaWebLlmPanel);
