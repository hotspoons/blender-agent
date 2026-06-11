# Blender Agent (Optional)

A web-based agent for Blender, built directly on the
[blender-mcp](../mcp) tool surface. One Python process hosts:

- the **agent harness** (LLM loop, tool dispatch, sessions, skills,
  media) - the harness design is ported from Foyer Studio's
  `foyer-agent`,
- the **web UI** (zero-build Lit ES modules, served as static files -
  no Node or bundler at runtime),
- the **local-model reverse tunnel** (the browser can host the LLM
  itself - Transformers.js/ONNX or WebLLM/MLC, both on WebGPU - and
  serve it to the backend over a WebSocket; protocol ported from
  zip-ties),
- optionally, an **MCP streamable-HTTP listener** exposing the same
  tools to external MCP clients.

The agent invokes the ``blmcp`` tools as plain Python in-process - no
MCP protocol on the agent path. Tool calls reach Blender through the
add-on's TCP bridge exactly like the stdio MCP server does, so the
tool surface (Blender's Python API + bundled documentation) is
identical everywhere and the agent thread never touches ``bpy``.

```
                                Browser (UI + optional Transformers.js)
                                       ⇕ ws://.../ws  ⇕ ws://.../ws/local-llm
MCP Client  ⇐ MCP/http ⇒  blender-agent (tools in-process)  ⇐ TCP socket ⇒  Blender Add-on
                                       ⇓ https
                            any OpenAI-compatible endpoint
```

## Install and run (development)

```
pip install ./mcp ./agent
blender-agent --mcp-port 10101
```

Defaults: web UI at ``http://127.0.0.1:10102/``; MCP over HTTP only
with ``--mcp-port``. Blender must be running with the MCP add-on's
bridge server started. When the preferred ports are taken (another
Blender instance's agent), the next free ports are auto-assigned;
``--no-port-auto`` disables the scan.

## Launching from Blender

The add-on's preferences expose a **Web Agent** section: enable the
agent, pick ports, optionally serve MCP over HTTP (the matching
``.mcp.json`` is displayed with a copy button), and start it - a
launcher entry also appears in the **Window** menu. The add-on runs
the agent in-process when ``blagent`` is importable inside Blender's
Python, or falls back to a ``blender-agent`` executable on PATH.
Each Blender instance auto-assigns free ports, so several can run
side by side.

## LLM configuration

Settings (gear icon in the UI, persisted server-side):

- **OpenAI-compatible endpoint** + model + optional API key - any
  ``/v1`` base URL: OpenAI, Anthropic, OpenRouter, llama.cpp, Ollama,
  vLLM, ...
- **Local (in-browser)**: leave the endpoint empty and load a model
  in the browser panel, picking one of two engines. **Transformers.js**
  (ONNX Runtime Web; WebGPU with WASM fallback) covers the widest
  catalog via a curated list of onnx-community exports; **WebLLM**
  (MLC) runs models compiled to WebGPU kernels with paged attention -
  noticeably faster decode at agent-sized contexts, from a curated list
  of MLC builds (official mlc-ai Qwen3.5 conversions plus
  community-compiled Gemma 4). Either way inference streams to the backend
  over the reverse tunnel and weights are downloaded once, then cached.
  Raw model output is parsed per model family (Qwen XML tool calls,
  Gemma 4's native grammar, or prompt-instructed JSON for everything
  else - override in the panel when auto-detection guesses wrong), and
  `<think>` reasoning renders as collapsible cards in the chat.
- **Autonomy**: ``ask`` (destructive tool calls pause for an
  Allow/Deny confirmation in the UI) or ``auto``.

## Chat completions API (headless clients)

Set ``BLENDER_AGENT_CHAT_API=1`` to expose an OpenAI-compatible
``POST /v1/chat/completions`` (+ ``GET /v1/models``) on the agent's
HTTP port, so any OpenAI client can chat with the agent — no browser
UI involved. This mode REQUIRES a remote LLM: ``BLENDER_AGENT_ENDPOINT``
and ``BLENDER_AGENT_MODEL`` must be set (``BLENDER_AGENT_API_KEY``
optional); the in-browser local model is disabled for the process.

- **Sessions are per client and persistent**: the request's ``user``
  field (or an ``X-Client-Id`` header) maps to one agent session, so
  transcripts, media and compaction accumulate server-side. Each request
  contributes its latest user message; prior ``messages`` are ignored.
- **Tool calls** stream as non-standard ``blender_tool_calls`` entries
  on deltas and the final message (``call_id``/``name``/``args_json``/
  ``status``/``summary``); strict clients ignore them. Set
  ``BLENDER_AGENT_CHAT_API_INLINE_TOOLS=1`` to also render them as
  markdown blockquotes inside the assistant text.
- **Media both ways**: send images as standard ``image_url`` data-URL
  content parts; tool-produced renders come back as ``blender_media``
  entries (data URLs) plus an inline markdown image.
- **Auth**: set ``BLENDER_AGENT_CHAT_API_KEY`` to require
  ``Authorization: Bearer <key>``; unset means open (gate it at the
  network level).
- Turns run with autonomy forced to ``auto`` — nobody can answer a
  confirmation prompt over a fire-and-forget API.

```sh
BLENDER_AGENT_CHAT_API=1 \
BLENDER_AGENT_ENDPOINT=https://openrouter.ai/api/v1 \
BLENDER_AGENT_MODEL=anthropic/claude-sonnet-4.6 \
BLENDER_AGENT_API_KEY=sk-... \
blender-mcp-agent

curl -N http://127.0.0.1:10102/v1/chat/completions -d '{
  "user": "my-pipeline",
  "stream": true,
  "messages": [{"role": "user", "content": "add a cube and render it"}]
}'
```

## Skills

A filesystem-backed playbook library at
``$XDG_DATA_HOME/blender-agent/skills/*.md`` with full-text search,
exposed to the model as the ``skills`` tool (list / get / search /
save / memory). Seeded with recipes for manifold repair, fillets and
bevels, boolean modeling, texturing, and lighting. The agent is
prompted to consult skills before tedious geometry work and to offer
to save new proven recipes.

## Layout

```
blagent/
  engine.py        per-turn agent loop (rounds, autonomy gate, vision feedback)
  runtime.py       sessions, turn tasks, event broadcast
  llm.py           OpenAI-compatible streaming client + local-bridge client
  local_llm.py     reverse-tunnel bridge (zip-ties protocol)
  blender_tools.py blmcp tools invoked in-process (shared FastMCP registry)
  agent_tools.py   skills / media recall / continue_working tools
  store.py         config, JSONL transcripts (flock-guarded for multi-window), skills, memory
  media.py         short-id media library (i1, i2, ...)
  app.py           starlette app: /ws, /ws/local-llm, /media, static UI
  web/             zero-build Lit frontend (vendored lit/marked/highlight/
                   transformers.js/web-llm; family-aware output parser in
                   core/llm-output-parser.js)
  data/            system prompt + seeded skills
```

Frontend validation tooling (Node 22) is available in the
devcontainer for syntax checks only - it is never needed to run or
ship the agent.
