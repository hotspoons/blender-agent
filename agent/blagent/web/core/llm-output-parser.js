// SPDX-License-Identifier: GPL-3.0-or-later
//
// Streaming parser for raw local-model output: routes text into
// content vs thinking channels and extracts tool calls, per model
// family. Local models do not share one tool-call grammar - each
// family is trained on the exact rendering of its chat template:
//
//   qwen    Qwen3/3.5. The template pre-opens `<think>` in the
//           generation prompt (output starts mid-thinking, no opening
//           tag!) and tool calls are XML inside <tool_call> tags:
//           <function=name><parameter=key>value</parameter></function>
//           Older Qwen3 checkpoints emit hermes JSON instead - both
//           are accepted.
//   gemma   Gemma 4 native grammar: thinking as
//           `<|channel>thought ... <channel|>` blocks and tool calls
//           as `<|tool_call>call:name{key:value}<tool_call|>` where
//           strings are quoted with `<|"|>`.
//   harmony GPT-OSS. OpenAI's channel format: `<|channel|>analysis`
//           messages are reasoning, `<|channel|>final` is the answer,
//           and tool calls are commentary messages addressed
//           `to=functions.NAME` with a JSON body ended by <|call|>.
//           (Ported from webml-community/GPT-OSS-WebGPU's harmony.ts.)
//   generic Prompt-instructed hermes format: `<tool_call>{json}</tool_call>`
//           plus literal <think>/<thinking> passthrough. Right for
//           unknown models and most WebLLM/MLC conversions.
//
// Thinking is normalized to literal <think>...</think> in the output
// stream - one representation for the transcript, the chat UI's
// collapsible blocks, and the server-side history stripping.
//
// Plain ESM with no dependencies so it runs in the browser and under
// `node --test` (tests/test_llm_output_parser.mjs).

export const FAMILIES = {
  qwen: {
    label: "Qwen (XML tool calls)",
    implicitThink: true,
    keepSpecial: true,
    nativeTools: true,
    toolOpen: "<tool_call>",
    toolClose: "</tool_call>",
    thinkOpen: ["<think>"],
    thinkClose: ["</think>"],
    drops: ["<|im_end|>", "<|endoftext|>"],
    parseToolBody: parseQwenToolBody,
  },
  gemma: {
    label: "Gemma 4 (native tool calls)",
    implicitThink: false,
    keepSpecial: true,
    nativeTools: true,
    toolOpen: "<|tool_call>",
    toolClose: "<tool_call|>",
    thinkOpen: ["<|channel>thought"],
    thinkClose: ["<channel|>"],
    drops: ["<turn|>", "<end_of_turn>", "<eos>", "<bos>", "<|tool_response>"],
    parseToolBody: parseGemmaToolBody,
  },
  harmony: {
    label: "Harmony (GPT-OSS)",
    implicitThink: false,
    keepSpecial: true,
    nativeTools: true,
  },
  generic: {
    label: "Generic (JSON tool calls)",
    implicitThink: false,
    keepSpecial: false,
    nativeTools: false,
    toolOpen: "<tool_call>",
    toolClose: "</tool_call>",
    thinkOpen: ["<think>", "<thinking>"],
    thinkClose: ["</think>", "</thinking>"],
    drops: [],
    parseToolBody: parseJsonToolBody,
  },
};

/** Parser instance for a family key. `opts.implicitThink` overrides
 *  the family default - e.g. Qwen on WebLLM, where MLC's plain qwen2
 *  conversation template does NOT pre-open `<think>` the way the HF
 *  template does. */
export function createParser(familyKey, tools, opts) {
  if (familyKey === "harmony") return new HarmonyStreamParser(tools);
  return new LlmStreamParser(familyKey, tools, opts);
}

/** Family heuristic from a model id; "auto" callers use this. Gemma 3
 *  has no native tool grammar (its template ignores `tools`), so only
 *  Gemma 4 maps to the gemma family - everything unknown gets the
 *  prompt-instructed generic format. */
export function inferFamily(modelId) {
  const id = String(modelId || "").toLowerCase();
  if (/qwen/.test(id)) return "qwen";
  if (/gemma[-_]?4/.test(id)) return "gemma";
  if (/gpt[-_]?oss/.test(id)) return "harmony";
  return "generic";
}

/** {toolName: {param: jsonType}} from OpenAI-style tool specs, used to
 *  keep string parameters verbatim while parsing typed ones. */
export function toolParamTypes(tools) {
  const map = Object.create(null);
  for (const t of tools || []) {
    const f = t.function || t;
    if (!f?.name) continue;
    const props = f.parameters?.properties || {};
    map[f.name] = Object.create(null);
    for (const [key, spec] of Object.entries(props)) {
      map[f.name][key] = spec?.type || "";
    }
  }
  return map;
}

function coerceValue(raw, type) {
  if (type === "string") return raw;
  const text = raw.trim();
  if (type && type !== "string") {
    try { return JSON.parse(text); } catch { return raw; }
  }
  // No schema info: parse only what unambiguously looks structured.
  if (/^(\{|\[|-?\d+(\.\d+)?$|true$|false$|null$)/.test(text)) {
    try { return JSON.parse(text); } catch { return raw; }
  }
  return raw;
}

/** Qwen3.5 XML body; falls back to Qwen3-era hermes JSON. */
function parseQwenToolBody(body, typeOf) {
  const calls = [];
  const fnRe = /<function=([^>\s]+)>([\s\S]*?)<\/function>/g;
  let fn;
  while ((fn = fnRe.exec(body)) !== null) {
    const args = {};
    const pRe = /<parameter=([^>\s]+)>\n?([\s\S]*?)\n?<\/parameter>/g;
    let p;
    while ((p = pRe.exec(fn[2])) !== null) {
      args[p[1]] = coerceValue(p[2], typeOf(fn[1], p[1]));
    }
    calls.push({ name: fn[1], arguments: args });
  }
  return calls.length ? calls : parseJsonToolBody(body, typeOf);
}

function parseJsonToolBody(body, _typeOf) {
  try {
    const obj = JSON.parse(body.trim());
    const name = obj.name || obj.function?.name || "";
    if (!name) return null;
    let args = obj.arguments ?? obj.parameters ?? obj.function?.arguments ?? {};
    if (typeof args === "string") {
      try { args = JSON.parse(args); } catch { /* keep string */ }
    }
    return [{ name, arguments: args }];
  } catch {
    return null;
  }
}

/** Gemma 4 `call:name{key:value,...}` with <|"|>-quoted strings. */
function parseGemmaToolBody(body, _typeOf) {
  const head = /^\s*call:([\w.\-]+)\s*\{/.exec(body);
  if (!head) return null;
  try {
    const parser = new GemmaArgScanner(body.slice(body.indexOf("{")));
    return [{ name: head[1], arguments: parser.parseObject() }];
  } catch {
    return null;
  }
}

const GEMMA_QUOTE = '<|"|>';

class GemmaArgScanner {
  constructor(text) {
    this.text = text;
    this.pos = 0;
  }

  _ws() { while (this.pos < this.text.length && /\s/.test(this.text[this.pos])) this.pos++; }

  _expect(ch) {
    if (this.text[this.pos] !== ch) throw new Error(`expected ${ch} at ${this.pos}`);
    this.pos++;
  }

  parseObject() {
    this._expect("{");
    const out = {};
    this._ws();
    if (this.text[this.pos] === "}") { this.pos++; return out; }
    for (;;) {
      this._ws();
      let key;
      if (this.text.startsWith(GEMMA_QUOTE, this.pos)) {
        key = this._parseQuoted();
      } else {
        const end = this.text.indexOf(":", this.pos);
        if (end < 0) throw new Error("unterminated key");
        key = this.text.slice(this.pos, end).trim();
        this.pos = end;
      }
      this._ws();
      this._expect(":");
      out[key] = this.parseValue();
      this._ws();
      if (this.text[this.pos] === ",") { this.pos++; continue; }
      this._expect("}");
      return out;
    }
  }

  parseArray() {
    this._expect("[");
    const out = [];
    this._ws();
    if (this.text[this.pos] === "]") { this.pos++; return out; }
    for (;;) {
      out.push(this.parseValue());
      this._ws();
      if (this.text[this.pos] === ",") { this.pos++; continue; }
      this._expect("]");
      return out;
    }
  }

  parseValue() {
    this._ws();
    if (this.text.startsWith(GEMMA_QUOTE, this.pos)) return this._parseQuoted();
    const ch = this.text[this.pos];
    if (ch === "{") return this.parseObject();
    if (ch === "[") return this.parseArray();
    // Bare literal up to the next structural character.
    let end = this.pos;
    while (end < this.text.length && !",}]".includes(this.text[end])) end++;
    const raw = this.text.slice(this.pos, end).trim();
    this.pos = end;
    if (raw === "true") return true;
    if (raw === "false") return false;
    if (raw === "null") return null;
    if (/^-?\d+(\.\d+)?([eE][+-]?\d+)?$/.test(raw)) return Number(raw);
    return raw;
  }

  _parseQuoted() {
    this.pos += GEMMA_QUOTE.length;
    const end = this.text.indexOf(GEMMA_QUOTE, this.pos);
    if (end < 0) throw new Error("unterminated string");
    const value = this.text.slice(this.pos, end);
    this.pos = end + GEMMA_QUOTE.length;
    return value;
  }
}

/**
 * Incremental scanner (same shape as the harmony parser in the
 * GPT-OSS-WebGPU demo): feed raw deltas with push(), get back the
 * cleaned content-stream delta - thinking re-wrapped in literal
 * <think> tags, tool calls captured out of band, end-of-turn markers
 * dropped. Text that could be the start of a marker is held back
 * until disambiguated, so markers split across deltas still parse.
 */
export class LlmStreamParser {
  constructor(familyKey, tools, opts) {
    this.family = FAMILIES[familyKey] || FAMILIES.generic;
    this._types = toolParamTypes(tools);
    this._buf = "";
    const implicitThink = opts?.implicitThink ?? this.family.implicitThink;
    this._state = implicitThink ? "think" : "content";
    this._priorState = "content";
    this._thinkOpenEmitted = false;
    this._toolBuf = "";
    this.toolCalls = [];
    this._markers = [
      ...this.family.thinkOpen.map((t) => ({ token: t, kind: "think_open" })),
      ...this.family.thinkClose.map((t) => ({ token: t, kind: "think_close" })),
      { token: this.family.toolOpen, kind: "tool_open" },
      { token: this.family.toolClose, kind: "tool_close" },
      ...this.family.drops.map((t) => ({ token: t, kind: "drop" })),
    ];
  }

  _typeOf = (tool, param) => this._types[tool]?.[param] || "";

  push(text) {
    this._buf += text;
    return this._drain(false);
  }

  /** Flush the tail; returns {delta, toolCalls}. An unclosed tool
   *  block is still parsed (models hit eos/token limits right after
   *  the payload) and falls back to visible text. */
  finish() {
    let delta = this._drain(true);
    if (this._state === "tool") {
      const calls = this.family.parseToolBody(this._toolBuf, this._typeOf);
      if (calls) {
        this.toolCalls.push(...calls);
      } else {
        delta += this._route(this.family.toolOpen + this._toolBuf);
      }
      this._toolBuf = "";
      this._state = this._priorState;
    }
    if (this._state === "think" && this._thinkOpenEmitted) {
      delta += "</think>";
      this._state = "content";
    }
    return { delta, toolCalls: this.toolCalls };
  }

  _earliestMarker() {
    let best = null;
    for (const marker of this._markers) {
      const at = this._buf.indexOf(marker.token);
      if (at >= 0 && (best === null || at < best.at)) best = { at, marker };
    }
    return best;
  }

  /** Longest buffer suffix that is a proper prefix of any marker. */
  _heldBack() {
    const max = Math.min(this._buf.length, 24);
    for (let len = max; len > 0; len--) {
      const tail = this._buf.slice(this._buf.length - len);
      if (this._markers.some((m) => m.token.length > len && m.token.startsWith(tail))) return len;
    }
    return 0;
  }

  /** Send a text segment to whatever channel is current. */
  _route(text) {
    if (!text) return "";
    if (this._state === "tool") {
      this._toolBuf += text;
      return "";
    }
    if (this._state === "think") {
      if (!this._thinkOpenEmitted) {
        // Lazy open: an empty think block (e.g. instant `</think>`)
        // emits nothing at all.
        if (!text.trim()) return "";
        this._thinkOpenEmitted = true;
        return "<think>" + text;
      }
      return text;
    }
    return text;
  }

  _drain(final) {
    let out = "";
    for (;;) {
      const hit = this._earliestMarker();
      if (!hit) break;
      const { at, marker } = hit;
      out += this._route(this._buf.slice(0, at));
      this._buf = this._buf.slice(at + marker.token.length);
      switch (marker.kind) {
        case "think_open":
          if (this._state === "content") {
            this._state = "think";
            this._thinkOpenEmitted = false;
          }
          break;
        case "think_close":
          if (this._state === "think") {
            if (this._thinkOpenEmitted) out += "</think>";
            this._state = "content";
            this._thinkOpenEmitted = false;
          }
          break;
        case "tool_open":
          if (this._state !== "tool") {
            this._priorState = this._state;
            this._state = "tool";
            this._toolBuf = "";
          }
          break;
        case "tool_close": {
          if (this._state !== "tool") break;
          const calls = this.family.parseToolBody(this._toolBuf, this._typeOf);
          this._state = this._priorState;
          if (calls) {
            this.toolCalls.push(...calls);
          } else {
            // Unparseable: keep it visible rather than vanishing it.
            out += this._route(this.family.toolOpen + this._toolBuf + this.family.toolClose);
          }
          this._toolBuf = "";
          break;
        }
        case "drop":
        default:
          break;
      }
    }
    const hold = final ? 0 : this._heldBack();
    const safe = this._buf.length - hold;
    if (safe > 0) {
      out += this._route(this._buf.slice(0, safe));
      this._buf = this._buf.slice(safe);
    }
    if (final && this._buf) {
      out += this._route(this._buf);
      this._buf = "";
    }
    return out;
  }
}

// ---------------------------------------------------------------------------
// Harmony (GPT-OSS).

const HARMONY_MARKERS = [
  "<|start|>", "<|channel|>", "<|constrain|>", "<|message|>",
  "<|end|>", "<|return|>", "<|call|>",
];

/**
 * Streaming parser for the OpenAI Harmony format emitted by GPT-OSS.
 * Each message is `[header] <|message|> body <|end|/|return|/|call|>`;
 * the header names a channel (analysis / commentary / final) and an
 * optional recipient (`to=functions.NAME` marks a tool call, ended by
 * <|call|> with a JSON body). Same push()/finish() surface as
 * LlmStreamParser: analysis (and non-tool commentary preambles)
 * normalize to <think> blocks, final becomes content, tool calls are
 * captured out of band.
 */
export class HarmonyStreamParser {
  constructor(_tools) {
    this.family = FAMILIES.harmony;
    this._buf = "";
    this._mode = "body";        // "body" | "header"
    this._header = "";
    this._channel = "";         // channel of the message being read
    this._recipient = "";
    this._thinkOpen = false;
    this._toolBuf = "";
    this.toolCalls = [];
  }

  push(text) {
    this._buf += text;
    return this._drain(false);
  }

  finish() {
    let delta = this._drain(true);
    if (this._isToolBody() && this._toolBuf.trim()) {
      // <|call|> is an eos token and may be swallowed by the stopping
      // logic before reaching the streamer - close the call anyway.
      delta += this._endMessage("call");
    }
    if (this._thinkOpen) {
      delta += "</think>";
      this._thinkOpen = false;
    }
    return { delta, toolCalls: this.toolCalls };
  }

  _isToolBody() {
    return this._mode === "body" && this._recipient.startsWith("functions.");
  }

  /** Route body text by the current message's channel. */
  _route(text) {
    if (!text || this._mode === "header") {
      this._header += text || "";
      return "";
    }
    if (this._isToolBody()) {
      this._toolBuf += text;
      return "";
    }
    // analysis = chain of thought; commentary without a functions
    // recipient is plan/preamble text - both read as thinking.
    if (this._channel === "analysis" || this._channel === "commentary") {
      if (!this._thinkOpen) {
        if (!text.trim()) return "";
        this._thinkOpen = true;
        return "<think>" + text;
      }
      return text;
    }
    return text;
  }

  _endMessage(reason) {
    let out = "";
    if (this._isToolBody() && reason !== "drop") {
      const name = this._recipient.slice("functions.".length).trim();
      let args = {};
      try { args = JSON.parse(this._toolBuf.trim()); } catch { args = { _raw: this._toolBuf.trim() }; }
      if (name) this.toolCalls.push({ name, arguments: args });
    } else if (this._thinkOpen && this._channel !== "final") {
      out += "</think>";
      this._thinkOpen = false;
    }
    this._toolBuf = "";
    this._channel = "";
    this._recipient = "";
    this._mode = "body";
    return out;
  }

  _applyHeader() {
    const header = this._header.trim();
    const to = /\bto=(\S+)/.exec(header);
    this._recipient = to ? to[1] : "";
    const channel = /\b(analysis|commentary|final)\b/.exec(header);
    if (channel) this._channel = channel[1];
    this._header = "";
    this._mode = "body";
  }

  _heldBack() {
    const max = Math.min(this._buf.length, 12);
    for (let len = max; len > 0; len--) {
      const tail = this._buf.slice(this._buf.length - len);
      if (HARMONY_MARKERS.some((m) => m.length > len && m.startsWith(tail))) return len;
    }
    return 0;
  }

  _drain(final) {
    let out = "";
    for (;;) {
      let at = -1;
      let marker = "";
      for (const m of HARMONY_MARKERS) {
        const found = this._buf.indexOf(m);
        if (found >= 0 && (at < 0 || found < at)) { at = found; marker = m; }
      }
      if (at < 0) break;
      out += this._route(this._buf.slice(0, at));
      this._buf = this._buf.slice(at + marker.length);
      switch (marker) {
        case "<|start|>":
        case "<|channel|>":
          // A new header opens; close out any tool body in flight
          // (start of the next message implies the previous ended).
          if (this._isToolBody() && this._toolBuf.trim()) out += this._endMessage("call");
          if (marker === "<|start|>") { this._channel = ""; this._recipient = ""; }
          this._mode = "header";
          this._header += " ";   // keep header words separated across markers
          break;
        case "<|constrain|>":
          this._mode = "header";  // constraint type joins the header text
          this._header += " ";
          break;
        case "<|message|>":
          this._applyHeader();
          break;
        case "<|end|>":
          out += this._endMessage("end");
          break;
        case "<|return|>":
          out += this._endMessage("return");
          break;
        case "<|call|>":
          out += this._endMessage("call");
          break;
        default:
          break;
      }
    }
    const hold = final ? 0 : this._heldBack();
    const safe = this._buf.length - hold;
    if (safe > 0) {
      out += this._route(this._buf.slice(0, safe));
      this._buf = this._buf.slice(safe);
    }
    if (final && this._buf) {
      out += this._route(this._buf);
      this._buf = "";
    }
    return out;
  }
}
