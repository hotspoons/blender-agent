// SPDX-License-Identifier: GPL-3.0-or-later
//
// Local-model inference engine on Transformers.js, host-agnostic: the
// same class runs inside a Web Worker (core/local-llm-worker.js) or on
// the main thread (when a browser - notably Safari - exposes WebGPU to
// pages but not to workers; the panel picks the host). The vendored
// bundle is imported by URL because import maps do not apply inside
// workers.
//
// Message protocol (postMessage-shaped both ways):
// in:  {type: "load", modelId, dtype?}
//      {type: "generate", id, messages, temperature?, max_tokens?}
//      {type: "abort"} | {type: "unload"}
// out: {type: "device", device, dtype, note?}
//      {type: "progress", file, progress, loaded, total}
//      {type: "ready", device, dtype} | {type: "load_error", message}
//      {id, type: "delta", text} | {id, type: "done"}
//      {id, type: "error", message} | {type: "unloaded"}

export class LocalLlmEngine {
  /** @param emit callback receiving every outbound protocol message. */
  constructor(emit) {
    this._emit = emit;
    this._tf = null;
    this._tokenizer = null;
    this._model = null;
    this._stopper = null;
    // Loads and generations are serialized; the model is not reentrant.
    this._queue = Promise.resolve();
  }

  handle(msg) {
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
        try { this._stopper?.interrupt(); } catch {}
        break;
      case "unload":
        this._queue = this._queue.then(async () => {
          try { await this._model?.dispose(); } catch {}
          this._model = null;
          this._tokenizer = null;
          this._emit({ type: "unloaded" });
        });
        break;
      default:
        break;
    }
  }

  async _transformers() {
    if (!this._tf) {
      this._tf = await import("/static/vendor/transformers.min.js");
      // Cache the onnxruntime WASM runtime alongside the model weights
      // so everything works offline after the first load.
      this._tf.env.useWasmCache = true;
    }
    return this._tf;
  }

  static async pickDevice() {
    // navigator.gpu existing is not enough - an adapter may still be
    // unavailable (headless browsers, blocklisted GPUs, some Linux
    // setups), and ORT does not fall back on its own.
    try {
      if (navigator.gpu && await navigator.gpu.requestAdapter()) return "webgpu";
    } catch {}
    return "wasm";
  }

  static isMemoryError(err) {
    return /bad_alloc|allocat|out of memory|oom/i.test(err?.message || String(err));
  }

  /**
   * Memory failures deserve a diagnosis, not a one-liner. The trap:
   * onnxruntime-web builds the session inside a 32-bit WASM heap
   * (~4GB, single buffers ~2GB) EVEN ON WEBGPU - GPU memory is not the
   * limit, the loader's address space is. Single-file exports much
   * past ~1GB die in the protobuf parse; repos that ship external
   * weight data (model.onnx_data) bypass the heap and load fine.
   */
  static describeError(err, device, dtype) {
    const text = err?.message || String(err);
    let message = `[${device}/${dtype}] ${text}`;
    if (LocalLlmEngine.isMemoryError(err)) {
      message += device === "webgpu"
        ? " - the loader ran out of address space building the session"
          + " (onnxruntime-web parses the model in a ~4GB WASM heap even on"
          + " WebGPU; this is not your GPU memory). Single-file exports over"
          + " ~1GB cannot load - pick a repo that ships external weight data"
          + " (model.onnx_data), e.g. onnx-community/Qwen3-4B-ONNX or"
          + " Llama-3.2-3B-Instruct-ONNX, or a smaller quantization."
        : " - the model does not fit in browser WASM memory (heap capped at"
          + " ~4GB, single buffers at ~2GB). Use a WebGPU-capable browser"
          + " (recent Chrome/Edge) or a smaller model such as"
          + " onnx-community/Qwen3-0.6B-ONNX.";
    }
    return message;
  }

  async _load(msg) {
    const tf = await this._transformers();
    const device = await LocalLlmEngine.pickDevice();
    const dtype = msg.dtype || (device === "webgpu" ? "q4f16" : "q4");
    this._emit({ type: "device", device, dtype });

    // Aggregate per-file download progress into one overall fraction.
    const files = new Map();
    const progress_callback = (item) => {
      if (!item.file) return;
      if (item.status === "initiate" && !files.has(item.file)) {
        files.set(item.file, { loaded: 0, total: 0 });
      } else if (item.status === "progress") {
        files.set(item.file, { loaded: item.loaded || 0, total: item.total || 0 });
      } else {
        return;
      }
      let loaded = 0;
      let total = 0;
      for (const f of files.values()) { loaded += f.loaded; total += f.total; }
      this._emit({ type: "progress", file: item.file, progress: total ? loaded / total : 0, loaded, total });
    };

    this._tokenizer = await tf.AutoTokenizer.from_pretrained(msg.modelId, { progress_callback });
    let used = { device, dtype };
    try {
      this._model = await tf.AutoModelForCausalLM.from_pretrained(msg.modelId, { device, dtype, progress_callback });
    } catch (gpuErr) {
      if (device !== "webgpu") throw new Error(LocalLlmEngine.describeError(gpuErr, device, dtype));
      // A memory failure cannot be fixed by retrying on WASM - the q4
      // file is bigger and the heap is the same. Report it directly.
      if (LocalLlmEngine.isMemoryError(gpuErr)) {
        throw new Error(LocalLlmEngine.describeError(gpuErr, device, dtype));
      }
      // GPU init can still fail after a successful adapter probe; the
      // weights are cached by now, so a WASM retry is cheap. Keep the
      // GPU error - if the retry also fails, both matter.
      used = { device: "wasm", dtype: msg.dtype || "q4" };
      this._emit({ type: "device", ...used, note: "WebGPU failed, retrying on WASM" });
      console.warn("local-llm: WebGPU load failed, retrying on WASM:", gpuErr);
      try {
        this._model = await tf.AutoModelForCausalLM.from_pretrained(msg.modelId, { ...used, progress_callback });
      } catch (wasmErr) {
        throw new Error(
          `${LocalLlmEngine.describeError(wasmErr, used.device, used.dtype)}`
          + ` (WASM retry after WebGPU failed: ${gpuErr?.message || gpuErr})`);
      }
    }
    this._stopper = new tf.InterruptableStoppingCriteria();
    this._emit({ type: "ready", ...used });
  }

  /**
   * Prefill the prompt through forward() in bounded chunks, carrying
   * the KV cache, and return inputs for generate() holding only the
   * final token.
   *
   * Why: ONNX decoder exports emit logits for EVERY input position
   * (none of the current onnx-community exports take
   * num_logits_to_keep), so a single-pass prefill allocates
   * prompt_tokens x vocab x 2-4 bytes - with ~250k vocabs an
   * agent-sized prompt is a multi-GB GPU buffer that crashes Dawn
   * ("Failed to allocate memory for buffer mapping") and freezes the
   * machine. Chunking caps that at chunk x vocab. WebLLM never had
   * this problem (MLC materializes last-token logits only); this is
   * the price of ORT-web generality.
   */
  async _prefillInChunks(inputs, chunkSize) {
    const ids = inputs.input_ids;
    const mask = inputs.attention_mask;
    const total = ids.dims.at(-1);
    if (!mask || total <= chunkSize * 2) return inputs;

    let past = null;
    let prevTensors = null;
    let consumed = 0;
    const prefillEnd = total - 1;   // generate() consumes the last token
    while (consumed < prefillEnd) {
      const len = Math.min(chunkSize, prefillEnd - consumed);
      const output = await this._model({
        input_ids: ids.slice(null, [consumed, consumed + len]),
        // Slicing the real mask keeps the int64 dtype right.
        attention_mask: mask.slice(null, [0, consumed + len]),
        past_key_values: past,
      });
      // Raw forward() returns the cache as present.* output tensors;
      // fold them into a DynamicCache the same way generate() does.
      const updates = Object.create(null);
      for (const name in output) {
        if (!name.startsWith("present")) continue;
        updates[name
          .replace("present_ssm", "past_ssm")
          .replace("present_conv", "past_conv")
          .replace("present_recurrent", "past_recurrent")
          .replace("present", "past_key_values")] = output[name];
      }
      if (Object.keys(updates).length === 0) {
        // Export does not round-trip a KV cache through forward();
        // chunking is impossible - let the single-pass path try.
        console.warn("local-llm: forward() returned no KV cache; prefill chunking disabled");
        return inputs;
      }
      if (past) past.update(updates);
      else past = new this._tf.DynamicCache(updates);
      // The previous chunk's cache tensors were consumed as inputs and
      // replaced; free their GPU buffers (generate's loop does the
      // equivalent each step - without this, prefill would accumulate
      // one KV copy per chunk, the very blow-up chunking exists to
      // avoid).
      if (prevTensors) {
        for (const tensor of prevTensors) {
          if (tensor.location === "gpu-buffer") { try { tensor.dispose(); } catch {} }
        }
      }
      prevTensors = Object.values(updates);
      consumed += len;
      try { output.logits?.dispose?.(); } catch {}
    }
    this.lastPrefillChunks = Math.ceil(prefillEnd / chunkSize);
    return {
      input_ids: ids.slice(null, [prefillEnd, total]),
      attention_mask: mask,
      past_key_values: past,
    };
  }

  async _generate(msg) {
    if (!this._model || !this._tokenizer) {
      this._emit({ id: msg.id, type: "error", message: "model not loaded" });
      return;
    }
    try {
      let inputs;
      try {
        inputs = this._tokenizer.apply_chat_template(msg.messages, {
          add_generation_prompt: true,
          return_dict: true,
        });
      } catch {
        // Base models without a chat template: plain role-tagged prompt.
        const prompt = msg.messages.map((m) => `${m.role}: ${m.content}`).join("\n\n") + "\n\nassistant:";
        inputs = this._tokenizer(prompt);
      }
      const chunkSize = msg.prefill_chunk ?? 256;
      this.lastPrefillChunks = 0;
      let prepared = inputs;
      try {
        prepared = await this._prefillInChunks(inputs, chunkSize);
      } catch (err) {
        console.warn("local-llm: chunked prefill failed, falling back to single pass:", err);
        prepared = inputs;
      }
      const chunked = prepared !== inputs;
      const streamer = new this._tf.TextStreamer(this._tokenizer, {
        skip_prompt: true,
        skip_special_tokens: true,
        callback_function: (text) => {
          if (text) this._emit({ id: msg.id, type: "delta", text });
        },
      });
      this._stopper.reset();
      const temperature = msg.temperature ?? 0.7;
      const result = await this._model.generate({
        ...prepared,
        max_new_tokens: msg.max_tokens ?? 2048,
        do_sample: temperature > 0,
        ...(temperature > 0 ? { temperature } : {}),
        streamer,
        stopping_criteria: this._stopper,
        // When we own the KV cache, generate() will not dispose it -
        // ask for it back so we can.
        ...(chunked ? { return_dict_in_generate: true } : {}),
      });
      if (chunked) {
        try { await result?.past_key_values?.dispose?.(); } catch {}
      }
      this._emit({ id: msg.id, type: "done" });
    } catch (err) {
      this._emit({ id: msg.id, type: "error", message: err?.message || String(err) });
    }
  }
}

/**
 * Worker-shaped wrapper around an engine running on the MAIN thread.
 * Used when the page has WebGPU but workers do not (Safari): GPU
 * inference is async, so the UI stays responsive - the same trade
 * WebLLM made. Mirrors the Worker API surface the panel uses.
 */
export class MainThreadLlmHost {
  constructor() {
    this.onmessage = null;
    this.onerror = null;
    this._engine = new LocalLlmEngine((msg) => { this.onmessage?.({ data: msg }); });
  }

  postMessage(msg) {
    this._engine.handle(msg);
  }

  terminate() {
    this._engine.handle({ type: "abort" });
    this._engine.handle({ type: "unload" });
  }
}
