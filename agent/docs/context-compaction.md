# Context budget & compaction - working plan

Status: phases 1-3 implemented; phase 4 remains future work.

## Why

Two forces, one knob:

1. **Correctness/cost** - remote endpoints reject or silently truncate
   over-long conversations; agent sessions accumulate tool results
   fast (each round may add up to 24k chars of result text on top of a
   ~4.8k-token base prompt: ~950 system + ~3,900 tool specs).
2. **Local throughput** - in-browser inference degrades with sequence
   length much harder than hosted endpoints:
   - ORT-web decode cost grows with context (no paged attention; a
     WebLLM/MLC setup at the same context is several times faster).
   - Current onnx-community decoder exports emit logits for **every**
     input position (none take `num_logits_to_keep`), so single-pass
     prefill allocates `prompt_tokens x vocab x 2-4B`. With ~250k
     vocabs, a 10k-token prompt is a multi-GB GPU buffer. The engine
     now chunk-prefills (256-token chunks, KV carried via
     `DynamicCache`) to bound this, but prefill time still scales with
     prompt length.
   - Per generated token the full-vocab logits row (~0.5-1MB) is
     downloaded for sampling - fixed per-token tax.

So context discipline is simultaneously the compaction story and the
local-performance story.

## Phase 1 - shipped

- `context_tokens` config field (default 16,384, min 2,048), settings
  UI under Behavior, applies to remote and local alike.
- Engine guard rail in `_fit_context()` (`engine.py`), applied when
  projecting the transcript for each round:
  1. truncate old tool results to a 600-char head (newest two stay
     verbatim);
  2. drop whole exchanges oldest-first - an assistant message takes
     its tool replies with it (OpenAI-style APIs reject orphaned
     `tool` messages) - inserting a single
     `[Note: earlier conversation was trimmed ...]` record;
  3. system prompt and the latest exchange always survive.
- Token estimation is chars/4 + ~800/image - an order-of-magnitude
  guard, deliberately tokenizer-free.

Limitations: trims are lossy and abrupt; the model loses old decisions
entirely (it only learns this from the notice). Good enough as a crash
guard; not a memory strategy.

## Phase 2 - summarization compaction (shipped)

After a turn ends, when the projection crosses
`_COMPACT_TRIGGER_RATIO` (70%) of `context_tokens`, the runtime calls
`engine.maybe_compact()`:

- A verbatim tail of ~35% of the budget is kept; everything older
  (whole exchanges - tool replies never split from their calling
  assistant message) is rendered to text, including any previous
  summary, and the *configured model itself* summarizes it (structured
  prompt: scene state / decisions & preferences / completed work /
  open items; one bounded request, between turns only).
- The result persists as a `role: "summary"` record with a
  `covers_count` (`transcript.jsonl` is append-only; nothing is
  rewritten). The LLM projection emits the latest summary in place of
  the records it covers; the UI shows a "context compacted" divider
  and keeps the full transcript visible.
- A failed/empty summarization is logged and skipped - the phase-1
  guard rail still bounds the next turn.
- Local-model caveat (open): summarization through a 0.8-4B model is
  weak; a tighter extractive prompt may be needed.

## Phase 3 - smarter retention (shipped)

- **Tool-result aging**: tools carry a `volatile` flag (for blmcp
  tools it derives from the MCP `readOnlyHint` annotation - read-only
  scene queries go stale the moment the scene changes and are cheap to
  re-run). In `_fit_context`, all but the newest volatile result
  shrink to a 300-char stub *before* ordinary results are touched.
- **Media policy**: only the newest 3 images stay inline in the
  projection; older ones become "[an older image was omitted here -
  use the media tool to view it again]" placeholders.
- **Tool-spec slimming for local models**: the local panel renders
  tool parameters as compact `name(arg: type, arg2?: type)` signatures
  instead of raw JSON Schemas (~6k chars of permanent prompt overhead
  removed - context length is the throughput knob for ORT-web).

## Phase 4 - local-specific ideas

- **KV cache reuse across rounds**: generate() can return its
  `past_key_values`; within one turn, consecutive rounds share a long
  prefix (system + history). Holding the cache between rounds would
  turn each round's prefill into "new tokens only". Needs care with
  the trim guard (any prefix edit invalidates the cache) and GPU
  memory lifetime - prototype behind a flag.
- **`num_logits_to_keep` exports** (partially landed): Gemma 4
  decoders declare the input, and the engine now detects it from the
  session's input names and skips chunked prefill entirely there
  (single-pass prefill only materializes the requested logit rows).
  Qwen3.5 and gpt-oss exports still emit full-sequence logits and use
  the chunked path (512-token chunks). Per-turn prefill/decode timing
  now surfaces in the local panel ("Last turn: prefill ... decode ...")
  to keep this measurable.

## Open questions

- Should `context_tokens` auto-default lower when `use_local_llm` is
  on (e.g. 8,192)? Leaning yes once phase 2 exists.
- Real tokenizer counts for remote endpoints (the `/v1/models` proxy
  could fetch per-model context lengths and suggest the field value).
- Whether the trim notice should enumerate what was dropped ("3 tool
  results, 2 exchanges") so the model knows to re-query scene state.
