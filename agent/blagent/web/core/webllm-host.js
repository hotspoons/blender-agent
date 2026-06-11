// SPDX-License-Identifier: GPL-3.0-or-later
//
// WebLLM (MLC) engine behind the same postMessage-shaped protocol as
// core/local-llm-engine.js, so the local-model panel can swap engines
// without caring which one is loaded. Restored from the pre-
// Transformers.js setup (zip-ties' zt-webllm.js lineage): MLC compiles
// models to WebGPU kernels with paged attention, which holds decode
// speed at long context far better than ONNX Runtime Web - the trade
// is a much smaller catalog (prebuilt MLC conversions only).
//
// Runs on the main thread like the old setup: GPU inference is async,
// so the UI stays responsive, and MLC's own service-worker mode adds
// nothing here.

export class WebLlmHost {
  constructor() {
    this.onmessage = null;
    this.onerror = null;
    this._engine = null;
    this._generating = false;
    this._aborted = false;
    this._queue = Promise.resolve();
  }

  _emit(msg) {
    this.onmessage?.({ data: msg });
  }

  postMessage(msg) {
    switch (msg.type) {
      case "load":
        this._queue = this._queue
          .then(() => this._load(msg))
          .catch((err) => this._emit({ type: "load_error", message: err?.message || String(err) }));
        break;
      case "generate":
        this._queue = this._queue.then(() => this._generate(msg));
        break;
      case "abort":
        this._aborted = true;
        try { this._engine?.interruptGenerate(); } catch {}
        break;
      case "unload":
        this._queue = this._queue.then(async () => {
          try { await this._engine?.unload(); } catch {}
          this._engine = null;
          this._emit({ type: "unloaded" });
        });
        break;
      default:
        break;
    }
  }

  terminate() {
    this.postMessage({ type: "abort" });
    this.postMessage({ type: "unload" });
  }

  async _load(msg) {
    if (!navigator.gpu || !(await navigator.gpu.requestAdapter().catch(() => null))) {
      throw new Error("WebLLM requires WebGPU, which this browser does not expose.");
    }
    this._emit({ type: "device", device: "webgpu", dtype: "mlc" });
    const { CreateMLCEngine, prebuiltAppConfig } = await import("@mlc-ai/web-llm");
    const options = {
      initProgressCallback: (report) => {
        this._emit({
          type: "progress",
          progress: report.progress || 0,
          text: report.text || "",
        });
      },
    };
    // Models outside the prebuilt catalog (e.g. community Gemma 4
    // builds) carry their weights repo + compiled wasm model lib, and
    // optionally ModelRecord.overrides (the supported place to settle
    // context_window_size vs sliding_window_size conflicts).
    if (msg.custom) {
      options.appConfig = {
        ...prebuiltAppConfig,
        model_list: [
          ...prebuiltAppConfig.model_list,
          {
            model: msg.custom.model,
            model_id: msg.modelId,
            model_lib: msg.custom.model_lib,
            ...(msg.custom.overrides ? { overrides: msg.custom.overrides } : {}),
          },
        ],
      };
    }
    this._engine = await CreateMLCEngine(
      msg.modelId,
      options,
      // Custom entries pin their window via ModelRecord.overrides;
      // forcing another engine-level value would just reintroduce the
      // conflict their overrides exist to settle.
      msg.custom?.overrides ? {} : { context_window_size: 20480 },
    );
    this._emit({ type: "ready", device: "webgpu", dtype: "mlc" });
  }

  async _generate(msg) {
    if (!this._engine) {
      this._emit({ id: msg.id, type: "error", message: "model not loaded" });
      return;
    }
    this._aborted = false;
    try {
      const temperature = msg.temperature ?? 0.7;
      const chunks = await this._engine.chat.completions.create({
        messages: msg.messages,
        temperature,
        max_tokens: msg.max_tokens ?? 2048,
        stream: true,
        stream_options: { include_usage: true },
      });
      let usage = null;
      for await (const chunk of chunks) {
        if (chunk.usage) usage = chunk.usage;
        const text = chunk.choices?.[0]?.delta?.content;
        if (text) this._emit({ id: msg.id, type: "delta", text });
      }
      if (usage) {
        // MLC reports throughput natively; map it onto the shared
        // stats shape so the panel renders one diagnostics line.
        const extra = usage.extra || {};
        const stats = {
          engine: "webllm",
          prompt_tokens: usage.prompt_tokens ?? 0,
          prefill_ms: extra.prefill_tokens_per_s
            ? Math.round(((usage.prompt_tokens ?? 0) / extra.prefill_tokens_per_s) * 1000)
            : 0,
          prefill_tps: +(extra.prefill_tokens_per_s ?? 0).toFixed(1),
          prefill_chunks: 0,
          decode_tokens: usage.completion_tokens ?? 0,
          decode_ms: extra.decode_tokens_per_s
            ? Math.round(((usage.completion_tokens ?? 0) / extra.decode_tokens_per_s) * 1000)
            : 0,
          decode_tps: +(extra.decode_tokens_per_s ?? 0).toFixed(1),
        };
        console.log("webllm stats:", stats);
        this._emit({ id: msg.id, type: "stats", stats });
      }
      this._emit({ id: msg.id, type: "done" });
    } catch (err) {
      if (this._aborted) {
        this._emit({ id: msg.id, type: "done" });
      } else {
        this._emit({ id: msg.id, type: "error", message: err?.message || String(err) });
      }
    }
  }
}
