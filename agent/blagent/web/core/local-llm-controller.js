// SPDX-License-Identifier: GPL-3.0-or-later
//
// Singleton controller for the in-browser local model: owns the
// inference host (Transformers.js worker / main-thread engine / WebLLM
// host), the reverse-tunnel WebSocket, model/engine selection, and the
// per-request output parsing. UI components (the settings panel, the
// topbar model chip) are thin views subscribing to "change" events -
// the model must keep loading and serving regardless of which panels
// happen to be open.

import { MainThreadLlmHost } from "/static/core/local-llm-engine.js";
import { WebLlmHost } from "/static/core/webllm-host.js";
import { FAMILIES, createParser, inferFamily } from "/static/core/llm-output-parser.js";

// Curated lists - strong tool-calling models only.
//
// Transformers.js: modern multi-component exports with external weight
// data (model.onnx_data), which bypasses onnxruntime's 4GB WASM
// session-build heap. NOT every Hub export qualifies: older
// single-file exports >~1GB cannot load at all (Qwen3-1.7B q4f16).
// Sizes are the q4f16 component totals actually downloaded.
export const TRANSFORMERS_MODELS = [
  { id: "onnx-community/Qwen3.5-0.8B-ONNX", label: "Qwen3.5 0.8B (~0.7GB)" },
  { id: "onnx-community/Qwen3.5-2B-ONNX", label: "Qwen3.5 2B (~1.6GB)" },
  { id: "onnx-community/Qwen3.5-4B-ONNX", label: "Qwen3.5 4B (~2.8GB)" },
  { id: "onnx-community/gemma-4-E2B-it-ONNX", label: "Gemma 4 E2B (~3.3GB)" },
  { id: "onnx-community/gemma-4-E4B-it-ONNX", label: "Gemma 4 E4B (~5.2GB)" },
  // The GPT-OSS-WebGPU demo's model: 20B MoE (3.6B active), so it
  // decodes fast for its size. Harmony output format.
  { id: "onnx-community/gpt-oss-20b-ONNX", label: "GPT-OSS 20B MoE (~12.6GB)" },
];

// WebLLM: Qwen3.5 entries are official mlc-ai conversions shipped in
// web-llm 0.2.84's prebuilt catalog (model libs hosted by mlc-ai).
// Gemma 4 has no official MLC port yet; these community builds bundle
// their own compiled WebGPU wasm in the weights repo (a third-party
// binary - see the repo's build-provenance.json) and were compiled
// with a 4k context window.
export const WEBLLM_MODELS = [
  { id: "Qwen3.5-0.8B-q4f16_1-MLC", label: "Qwen3.5 0.8B (~0.7GB)" },
  { id: "Qwen3.5-2B-q4f16_1-MLC", label: "Qwen3.5 2B (~1.5GB)" },
  { id: "Qwen3.5-4B-q4f16_1-MLC", label: "Qwen3.5 4B (~2.7GB)" },
  { id: "Qwen3.5-9B-q4f16_1-MLC", label: "Qwen3.5 9B (~5.5GB)" },
  // The builds bake sliding_window_size: 512 (gemma-4's local-attention
  // window) into mlc-chat-config.json, and MLC refuses a config where
  // both that and context_window_size are positive. The official gemma
  // catalog entries resolve the same conflict at the ModelRecord level,
  // so these overrides force plain 4k-window KV (sliding window off).
  {
    id: "gemma-4-E2B-it-q4f16_1-MLC",
    label: "Gemma 4 E2B (community build, 4k ctx)",
    custom: {
      model: "https://huggingface.co/welcoma/gemma-4-E2B-it-q4f16_1-MLC",
      model_lib: "https://huggingface.co/welcoma/gemma-4-E2B-it-q4f16_1-MLC/resolve/main/libs/gemma-4-E2B-it-q4f16_1-MLC-webgpu.wasm",
      overrides: { context_window_size: 4096, sliding_window_size: -1 },
    },
  },
  {
    id: "gemma-4-E4B-it-q4f16_1-MLC",
    label: "Gemma 4 E4B (community build, 4k ctx)",
    custom: {
      model: "https://huggingface.co/welcoma/gemma-4-E4B-it-q4f16_1-MLC",
      model_lib: "https://huggingface.co/welcoma/gemma-4-E4B-it-q4f16_1-MLC/resolve/main/libs/gemma-4-E4B-it-q4f16_1-MLC-webgpu.wasm",
      overrides: { context_window_size: 4096, sliding_window_size: -1 },
    },
  },
];

const ENGINE_KEY = "blender-agent.local-engine";
const TJS_MODEL_KEY = "blender-agent.local-model";
const WEBLLM_MODEL_KEY = "blender-agent.webllm-model";
const FAMILY_KEY = "blender-agent.local-tool-format";

class LocalLlmController extends EventTarget {
  constructor() {
    super();
    const knownTjs = (id) => TRANSFORMERS_MODELS.some((m) => m.id === id);
    const knownWebllm = (id) => WEBLLM_MODELS.some((m) => m.id === id);
    const storedTjs = localStorage.getItem(TJS_MODEL_KEY);
    const storedWebllm = localStorage.getItem(WEBLLM_MODEL_KEY);
    this.engineKind = localStorage.getItem(ENGINE_KEY) || "transformers";
    this.tjsModelId = (storedTjs && knownTjs(storedTjs) && storedTjs) || TRANSFORMERS_MODELS[0].id;
    this.webllmModelId = (storedWebllm && knownWebllm(storedWebllm) && storedWebllm) || "Qwen3.5-4B-q4f16_1-MLC";
    this.familyOverride = localStorage.getItem(FAMILY_KEY) || "auto";
    this.status = "idle";       // idle | loading | ready | error
    this.progress = null;       // {progress, text}
    this.error = "";
    this.stats = null;
    this.device = "";
    this.hostKind = "";         // "worker" | "main" | "webllm"
    this._worker = null;
    this._ws = null;
    this._requests = new Map(); // request id -> {ws, content, parser}
  }

  get modelId() {
    return this.engineKind === "webllm" ? this.webllmModelId : this.tjsModelId;
  }

  get models() {
    return this.engineKind === "webllm" ? WEBLLM_MODELS : TRANSFORMERS_MODELS;
  }

  get modelLabel() {
    return this.models.find((m) => m.id === this.modelId)?.label || this.modelId;
  }

  /** Family for the loaded model: explicit override, else inferred
   *  from the model id (the output grammar is the model's training,
   *  whichever engine runs it). */
  familyKey() {
    if (this.familyOverride && this.familyOverride !== "auto") return this.familyOverride;
    return inferFamily(this.modelId);
  }

  _changed() {
    this.dispatchEvent(new Event("change"));
  }

  pickModel(id) {
    if (this.status === "loading" || this.status === "ready") return;
    if (this.engineKind === "webllm") this.webllmModelId = id;
    else this.tjsModelId = id;
    this._changed();
  }

  setFamily(key) {
    this.familyOverride = key;
    localStorage.setItem(FAMILY_KEY, key);
    this._changed();
  }

  switchEngine(kind) {
    if (kind === this.engineKind || this.status === "loading" || this.status === "ready") return;
    this.engineKind = kind;
    localStorage.setItem(ENGINE_KEY, kind);
    this.error = "";
    this._changed();
  }

  _attachWorker(worker) {
    worker.onmessage = (e) => this._onWorkerMessage(e.data);
    worker.onerror = (e) => {
      this.status = "error";
      this.error = e.message || "inference worker crashed";
      this._changed();
    };
  }

  /**
   * The Transformers.js worker reported it would run on WASM. If the
   * PAGE has WebGPU, this browser (Safari) just does not expose it to
   * workers - rehost the engine on the main thread, the trade WebLLM
   * always made. GPU inference is async, so the UI stays responsive;
   * the WASM path stays in the worker, where its blocking generate()
   * belongs.
   */
  async _rehostOnMainThread() {
    try {
      if (!navigator.gpu || !await navigator.gpu.requestAdapter()) return false;
    } catch {
      return false;
    }
    try { this._worker.terminate(); } catch {}
    this._worker = new MainThreadLlmHost();
    this.hostKind = "main";
    this._attachWorker(this._worker);
    this.progress = { text: "WebGPU unavailable in workers here - reloading on the main thread...", progress: 0 };
    this._changed();
    this._worker.postMessage({ type: "load", modelId: this.modelId.trim() });
    return true;
  }

  _onWorkerMessage(msg) {
    switch (msg.type) {
      case "device": {
        this.device = msg.device;
        if (msg.device === "wasm" && this.hostKind === "worker" && this.status === "loading") {
          this._rehostOnMainThread();
        }
        this._changed();
        break;
      }
      case "progress": {
        const mb = (n) => (n / (1024 * 1024)).toFixed(0);
        this.progress = {
          progress: msg.progress,
          text: msg.text
            || (msg.total
              ? `Downloading model... ${mb(msg.loaded)} / ${mb(msg.total)} MB`
              : "Preparing model..."),
        };
        this._changed();
        break;
      }
      case "ready":
        this.status = "ready";
        this.progress = null;
        this.device = msg.device;
        localStorage.setItem(
          this.engineKind === "webllm" ? WEBLLM_MODEL_KEY : TJS_MODEL_KEY, this.modelId);
        this._connectBridge();
        this._changed();
        break;
      case "load_error":
        this.status = "error";
        this.error = msg.message;
        this.progress = null;
        this._changed();
        break;
      case "delta": {
        const req = this._requests.get(msg.id);
        if (!req) break;
        const out = req.parser.push(msg.text);
        if (out) {
          req.content += out;
          this._sendChunk(req.ws, msg.id, { content: out });
        }
        break;
      }
      case "stats":
        this.stats = msg.stats;
        this._changed();
        break;
      case "done": {
        const req = this._requests.get(msg.id);
        if (!req) break;
        this._requests.delete(msg.id);
        this._finishRequest(req, msg.id);
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

  load() {
    if (this.status === "loading" || this.status === "ready") return;
    this.status = "loading";
    this.error = "";
    this.stats = null;
    this.progress = { text: "Starting inference engine...", progress: 0 };
    if (!this._worker) {
      if (this.engineKind === "webllm") {
        this._worker = new WebLlmHost();
        this.hostKind = "webllm";
      } else {
        this._worker = new Worker("/static/core/local-llm-worker.js", { type: "module" });
        this.hostKind = "worker";
      }
      this._attachWorker(this._worker);
    }
    const entry = this.engineKind === "webllm"
      ? WEBLLM_MODELS.find((m) => m.id === this.modelId)
      : null;
    this._worker.postMessage({
      type: "load",
      modelId: this.modelId.trim(),
      ...(entry?.custom ? { custom: entry.custom } : {}),
    });
    this._changed();
  }

  unload() {
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
    this.error = "";
    this.stats = null;
    this.hostKind = "";
    this._changed();
  }

  // ------------------------------------------------------------------
  // Reverse tunnel.

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

  /**
   * Prepare messages per family. Native-tools families (Qwen3.5,
   * Gemma 4, GPT-OSS on Transformers.js) keep structured
   * tool_calls/tool roles and hand the specs to the chat template -
   * the exact rendering the model was trained on. Everything else gets
   * the prompt-injected format with compact signatures (schemas are
   * ~6k chars of permanent prompt overhead, and context length is the
   * throughput knob for in-browser inference).
   */
  _prepareMessages(req, family) {
    let messages = [...(req.messages || [])];
    const toolDefs = req.tools || [];
    const native = family.nativeTools && this.engineKind !== "webllm" && toolDefs.length > 0;

    if (!native && toolDefs.length > 0) {
      const signature = (params) => {
        const props = params?.properties || {};
        const required = new Set(params?.required || []);
        return Object.entries(props)
          .map(([key, spec]) => `${key}${required.has(key) ? "" : "?"}: ${spec.type || "any"}`)
          .join(", ");
      };
      const toolBlock = toolDefs.map((t) => {
        const f = t.function || t;
        return `- ${f.name}(${signature(f.parameters)}): ${f.description || ""}`;
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

    messages = messages.map((m) => {
      // Vision content arrays are flattened for these text-only paths.
      if (Array.isArray(m.content)) {
        const text = m.content.filter((p) => p.type === "text").map((p) => p.text).join("\n");
        m = { ...m, content: text || "[attached media omitted - text-only local model]" };
      }
      if (m.role === "assistant" && m.tool_calls) {
        if (native) {
          // Templates iterate arguments as a mapping; the wire format
          // carries JSON strings.
          return {
            ...m,
            tool_calls: m.tool_calls.map((tc) => {
              const fn = tc.function || {};
              let args = fn.arguments;
              if (typeof args === "string") {
                try { args = JSON.parse(args); } catch { args = {}; }
              }
              return { ...tc, function: { ...fn, arguments: args || {} } };
            }),
          };
        }
        const callText = m.tool_calls.map((tc) => {
          const fn = tc.function || {};
          return `<tool_call>\n{"name": "${fn.name}", "arguments": ${fn.arguments || "{}"}}\n</tool_call>`;
        }).join("\n");
        const { tool_calls, ...rest } = m;
        return { ...rest, content: `${rest.content || ""}${callText}`.trim() };
      }
      if (m.role === "tool" && !native) {
        const label = m.name || m.tool_call_id || "unknown";
        return { role: "user", content: `[Tool result: ${label}]\n${m.content}` };
      }
      return m;
    });

    return { messages, tools: native ? toolDefs : undefined };
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
    const familyKey = this.familyKey();
    const family = FAMILIES[familyKey] || FAMILIES.generic;
    const prepared = this._prepareMessages(req, family);
    this._requests.set(requestId, {
      ws,
      content: "",
      // MLC conversation templates do not pre-open <think> the way
      // Qwen's HF template does - the model emits its own tags there.
      parser: createParser(familyKey, req.tools,
        this.engineKind === "webllm" ? { implicitThink: false } : undefined),
    });
    this._worker.postMessage({
      type: "generate",
      id: requestId,
      messages: prepared.messages,
      tools: prepared.tools,
      keep_special: family.keepSpecial,
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

  /** Post-stream: flush the parser and surface captured tool calls. */
  _finishRequest(req, requestId) {
    const fin = req.parser.finish();
    if (fin.delta) {
      this._sendChunk(req.ws, requestId, { content: fin.delta });
    }
    for (let i = 0; i < fin.toolCalls.length; i++) {
      const tc = fin.toolCalls[i];
      this._sendChunk(req.ws, requestId, {
        tool_calls: [{
          index: i,
          id: `call_${requestId.slice(0, 8)}_${i}`,
          type: "function",
          function: { name: tc.name, arguments: JSON.stringify(tc.arguments) },
        }],
      });
    }
    if (fin.toolCalls.length > 0) {
      this._sendChunk(req.ws, requestId, {}, "tool_calls");
    }
    req.ws.send(JSON.stringify({ id: requestId, type: "done" }));
  }
}

export const localLlm = new LocalLlmController();
