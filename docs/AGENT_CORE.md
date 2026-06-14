# Core agent harness + portable tool backend (design)

Goal: split this project into a **reusable, domain-agnostic agent harness +
UI** (`agentcore`) and a thin **Blender build** (`blagent`) on top of it. The
core knows nothing about Blender; the domain is reached through ONE portable
interface — implemented either **in-process Python** or over a **documented
HTTP/OpenAPI** contract — and the whole agent is configured by a **YAML file**.

Status: ~85% of the current code is already domain-agnostic; coupling is
concentrated in a few seams (see the module table at the bottom). This design
unifies those seams under a single `ToolBackend` interface + an `AgentProfile`
+ a YAML loader.

---

## 1. The boundary: `ToolBackend`

The single seam between core and domain. Core drives the domain entirely
through this; it never imports `bpy`/`blmcp`/Blender anything.

```python
# agentcore/backend.py  (the portable contract)

@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict          # JSON Schema for the tool's args
    destructive: bool = False   # gated by "ask" autonomy (confirm)
    read_only: bool = False     # discounted in the turn budget

@dataclass
class MediaRef:
    id: str
    mime: str
    data_url: str | None = None # inline (HTTP); or fetched via the backend (Python)

@dataclass
class ToolCallResult:
    summary: str
    data: Any = None
    media: list[MediaRef] = field(default_factory=list)
    status: str = "ok"          # ok | error
    error: str | None = None

class ToolBackend(Protocol):
    async def list_tools(self) -> list[ToolSpec]: ...
    async def call_tool(self, name: str, args: dict, *, session_id: str) -> ToolCallResult: ...

    # Optional capabilities — return None / no-op when unsupported.
    async def state_probe(self, *, session_id: str) -> str | None: ...   # ground truth for autonomy/audit
    async def read_media(self, media_id: str) -> tuple[bytes, str] | None: ...  # (bytes, mime)
    async def open(self) -> None: ...    # bring the compute surface up (e.g. spawn Blender)
    async def close(self) -> None: ...   # tear it down
    def capabilities(self) -> set[str]: ...  # {"probe","media","surface","swarm"}
```

Core adapts each `ToolSpec` into its existing `Tool`/`ToolRegistry` via a thin
`BackendTool` that calls `backend.call_tool`. Autonomy's evaluator/auditor probe
calls `backend.state_probe`. The compute-surface lifecycle is `open`/`close`.

### Two transports

- **`PythonToolBackend`** — wraps an in-process object/registry. The Blender
  build provides one (today's `blender_tools` + the MCP bridge + scene probe +
  `BlenderSurface` for `open/close`). Zero serialization overhead.
- **`HttpToolBackend(base_url)`** — speaks the REST contract below to a service
  in *any language*. Lets the Blender tooling (or any domain) run as a separate
  process/container, even on another host.

Both satisfy the identical `ToolBackend` protocol, so core is transport-blind.

---

## 2. HTTP contract (OpenAPI 3.1)

A documented, language-agnostic REST API. `agentcore` ships the OpenAPI schema
as a static artifact (`agentcore/openapi/tool-backend.json`) so anyone can
implement a backend in Go/Rust/TS/etc. Endpoints:

```
GET  /tools                         -> { "tools": [ToolSpec, ...] }
POST /tools/{name}                  body { "args": {...}, "session_id": "..." }
                                    -> ToolCallResult
GET  /state?session_id=...          -> { "state": "<text>" }            # probe (optional)
GET  /media/{id}                    -> bytes (Content-Type: mime)        # optional
POST /surface/open                  -> { "ok": true }                    # optional
POST /surface/close                 -> { "ok": true }                    # optional
GET  /capabilities                  -> { "capabilities": ["probe","media","surface"] }
GET  /healthz                       -> { "status": "ok" }
GET  /openapi.json                  -> the schema itself
```

- Media: small images returned inline as `data_url` in the ToolCallResult;
  large blobs referenced by `id` and fetched via `GET /media/{id}`.
- Auth: optional `Authorization: Bearer <key>` (configured in YAML).
- Streaming: v1 is request/response per tool call (the agent loop already
  streams *its own* tokens to the UI; per-tool streaming is a later add).
### Swarm over HTTP

Swarm spawns parallel domain workers (each its own compute instance) and merges
their artifacts. A backend opts in by advertising `swarm` in `/capabilities`
and implementing:

```
POST /swarm/workers          body { "task": {...}, "session_id": "..." }
                             -> { "worker_id": "...", "endpoint": "<openai base_url>" }
                                spawn a worker instance; the agent drives it over
                                the returned OpenAI-compatible endpoint (today's
                                RemoteWorkerStrategy._chat, transport-identical).
GET  /swarm/workers/{id}     -> { "status": "starting|ready|done|error", "log": "..." }
POST /swarm/workers/{id}/stop -> { "ok": true }                  # cancel a runaway worker
GET  /swarm/workers/{id}/artifact -> bytes (the component the worker produced)
POST /swarm/gather           body { "components": ["id", ...] }
                             -> { "master": "<artifact id>", "objects": [...] }
                                merge components into one master; returns a summary
                                + a probe-able object list for the auditor.
```

The core swarm framework (PortAllocator-equivalent, ParallelScheduler,
streaming each worker's activity into its card, per-worker stop, the gather
step) stays in `agentcore`; it calls these endpoints instead of hardcoding
`.blend` collection. The Python backend implements the same Python-level hooks
(`spawn_worker`, `collect_artifact`, `gather`) so both transports share the
orchestration. Backends without `swarm` simply run in-process (orchestrator).

---

## 3. YAML configuration

One file fully describes an agent. `agentcore.load_agent("agent.yaml")` builds
the LLM client, the `AgentProfile`, the `ToolBackend` (python import or http
client), and returns a wired `AgentRuntime`.

```yaml
profile:
  name: "Blender Agent"
  ui:
    brand: "Blender Agent"
    welcome: "Connected to your Blender session through the MCP tool surface."
    media_viewers: ["stl"]          # registerable domain viewers
  prompts:                          # all optional; omitted -> neutral core default
    compaction: "..."
    planner: "..."
    evaluator: "..."
    auditor: "..."
    draft: "..."
    worker_proof: "..."

llm:
  endpoint: "http://172.16.10.252:8000/v1"
  model: "moonshot/kimi-k2.7-Code"
  api_key_env: "BLENDER_AGENT_API_KEY"   # read from env, never inline secrets

autonomy:
  policy: "auto_until_done"         # | pause_when_blocked
  max_rounds: 6
  audit: false
  workers: "in_process"             # | swarm

backend:
  type: "python"                    # | http
  # --- type: python ---
  factory: "blagent.backend:make_backend"   # callable -> ToolBackend
  options: { spawn_blender: true, offscreen_gl: false }
  # --- type: http ---
  # base_url: "http://localhost:8800"
  # api_key_env: "BLENDER_TOOLS_KEY"
```

The Blender build then reduces to: a `make_backend()` factory + an `agent.yaml`
+ UI branding. Anyone can build a different agent by writing a backend (Python
or an HTTP service) + a YAML file — no fork of core.

---

## 4. `AgentProfile` (prompt + UI flavor)

Absorbs all the "string" coupling (prompts that say "Blender", the chat-api
extension field names, brand/copy). Core ships neutral defaults; the profile
(from YAML) overrides. Carries: domain noun, the 6 prompt overrides, chat-api
field prefix (`tool_calls`/`media` neutral; Blender can keep `blender_*` for
back-compat), and the UI block (brand, welcome, registered media viewers).

---

## 5. Build sequence (each step tested, main stays green)

1. **Python transport + profile + YAML** — introduce `ToolBackend`,
   `BackendTool` adapter, `AgentProfile`, and `load_agent(yaml)`; refactor the
   current Blender wiring onto a `PythonToolBackend`. Behavior identical.
2. **HTTP transport** — `HttpToolBackend` + the OpenAPI schema + a reference
   handler (a tiny Starlette app that re-exposes a Python backend over the REST
   contract, so the contract is dogfooded and testable in-process).
3. **Physical split** — move the domain-agnostic modules + generic UI into a
   top-level `agentcore/` package (its own `pyproject`, no shared root with
   `blagent`, so it can spin out to its own repo). `blagent` becomes the thin
   Blender build depending on `agentcore`.
4. **Rewire** build/deploy (post-create, devcontainer, Dockerfile, Helm,
   README, `.mcp.json`) + test import paths; verify clean installs + Playwright.

---

## 6. Current coupling map (why this is tractable)

Only `blender_surface.py` and `blender_tools.py` import `bpy`/`blmcp` at
top level. Everything else couples via **lazy imports**, **strings/prompts**,
or **subprocess argv** — all of which the seams above replace:

| Lives in `agentcore` (generic) | Becomes `blagent` (Blender build) |
|---|---|
| engine, tools, reviewer, llm, media, store, app, chat_api | blender_tools.py (`PythonToolBackend`) |
| autonomy (neutral prompts), swarm framework | blender_surface.py (`open/close` + Xvfb) |
| agent_tools (skills/media/continue/ask_user/set_autonomy) | scene + `.blend` probes; swarm `.blend` collect/gather |
| runtime (BackendTool adapter, sessions, orchestration) | `make_backend()` + `agent.yaml` + UI branding |
| web UI (generic, themeable) | skills/tools content (in `mcp/`) |
