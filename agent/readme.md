# Blender Agent (Optional)

A web-based agent for Blender, built directly on the
[blender-mcp](../mcp) tool surface. One Python process hosts:

- the **agent harness** (LLM loop, tool dispatch, sessions, skills,
  media) - the harness design is ported from Foyer Studio's
  `foyer-agent`,
- the **web UI** (zero-build Lit ES modules, served as static files -
  no Node or bundler at runtime),
- the **WebLLM reverse tunnel** (the browser can host the LLM via
  WebGPU and serve it to the backend over a WebSocket - protocol
  ported from zip-ties),
- optionally, an **MCP streamable-HTTP listener** exposing the same
  tools to external MCP clients.

The agent invokes the ``blmcp`` tools as plain Python in-process - no
MCP protocol on the agent path. Tool calls reach Blender through the
add-on's TCP bridge exactly like the stdio MCP server does, so the
tool surface (Blender's Python API + bundled documentation) is
identical everywhere and the agent thread never touches ``bpy``.

```
                                    Browser (UI + optional WebLLM)
                                       ⇕ ws://.../ws  ⇕ ws://.../ws/webllm
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
- **WebLLM**: leave the endpoint empty and load a model in the
  browser panel; inference runs on your GPU via WebGPU and streams to
  the backend over the reverse tunnel.
- **Autonomy**: ``ask`` (destructive tool calls pause for an
  Allow/Deny confirmation in the UI) or ``auto``.

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
  llm.py           OpenAI-compatible streaming client + WebLLM client
  webllm.py        reverse-tunnel bridge (zip-ties protocol)
  blender_tools.py blmcp tools invoked in-process (shared FastMCP registry)
  agent_tools.py   skills / media recall / continue_working tools
  store.py         config, JSONL session transcripts, skills, memory
  media.py         short-id media library (i1, i2, ...)
  app.py           starlette app: /ws, /ws/webllm, /media, static UI
  web/             zero-build Lit frontend (vendored lit/marked/highlight/web-llm)
  data/            system prompt + seeded skills
```

Frontend validation tooling (Node 22) is available in the
devcontainer for syntax checks only - it is never needed to run or
ship the agent.
