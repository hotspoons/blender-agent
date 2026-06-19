# SPDX-FileCopyrightText: 2026 agentcore contributors
#
# SPDX-License-Identifier: MIT OR Apache-2.0

"""
The orchestrator as a PERSISTENT, tool-using conductor (not a stateless round
loop). It runs in its own ``AgentEngine`` whose transcript IS the session, so
user messages are ordinary turns — steering, never a restart — and the
conductor keeps full context across the whole session.

The conductor OWNS the objective list and evolves it as it works; it delegates
scoped tasks to worker sub-agents, reviews each worker's proof, steers/reads
workers, and can search the transcript. These are its tools (this module);
the runtime supplies the callbacks that reach the live run + worker machinery.

Tools:
  - post_objectives      — post/replace the plan the UI shows (the list is the
                           conductor's, not the user's composer).
  - complete_objective   — mark one met (with evidence) as work lands.
  - delegate             — spawn ONE reviewed worker for a task, get its proof.
  - read_worker          — re-read a worker's proof/transcript to review it.
  - search_transcript    — search the session conversation + worker proofs.
"""

__all__ = ("CONDUCTOR_SYSTEM", "build_conductor_tools")

# NB: when you add/remove a tool here, update build_conductor_tools + the
# runtime callbacks in AgentRuntime._ensure_conductor.

from typing import Any, Awaitable, Callable

from agentcore.tools import Tool, ToolContext, ToolError, ToolResult


CONDUCTOR_SYSTEM = """
You are the ORCHESTRATOR (conductor) of an autonomous Blender session. You do
not edit the scene directly — you PLAN, DELEGATE to worker sub-agents, REVIEW
their proof, and keep the objective list current until the user's goal is met.

How you work:
1. Understand the goal. Inspect the scene with the read-only tools first if you
   need to (scene, get_*; you have no user to ask — make reasonable calls).
2. POST a concrete objective list with `post_objectives` (each with a checkable
   'acceptance'). This list is what the user sees; keep it the source of truth.
3. For each objective, `delegate` a specific, self-contained task to a worker.
   The worker has the full Blender tool surface and returns a PROOF OF WORK.
4. REVIEW each worker's proof against the acceptance criteria. If it's good,
   `complete_objective`. If not, delegate a follow-up (be specific about the
   fix). Use `read_worker` to re-read details and `search_transcript` to recall
   earlier context.
5. The user may send a message AT ANY TIME — treat it as steering, NEVER start
   over (you keep all prior context). If a `delegate` (or `await_workers`)
   returns "interrupted", the user messaged WHILE a worker is running: read what
   they said and decide — `steer_worker` to inject guidance straight into that
   running worker, `post_objectives` to adjust the plan, or `await_workers` to
   let it finish. Steer the worker only if the feedback is worth interrupting it.
6. When every objective is met, give a short final summary. Don't loop idly.

`delegate` blocks until the worker finishes and returns its proof — UNLESS the
user interrupts, in which case it returns immediately with the worker still
running (use steer_worker / await_workers as above).

Be decisive and concrete. Prefer one clear delegated task at a time so you can
review it before the next. Keep the objective list honest — only complete an
objective when the worker's proof actually shows it.
"""


class PostObjectivesTool(Tool):
    name = "post_objectives"
    group = "orchestrator"
    read_only = True
    description = (
        "Post or replace the objective list shown to the user (you own this "
        "list). Pass every objective you intend to pursue, each with a clear, "
        "checkable 'acceptance'. Call again to add/remove/reword as the plan "
        "evolves or the user steers. Include already-met ones with status 'met' "
        "so they aren't dropped."
    )

    def __init__(self, on_post: "Callable[[list[dict[str, Any]]], Awaitable[list[dict[str, Any]]]]") -> None:
        self._on_post = on_post

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "objectives": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "acceptance": {"type": "string"},
                            "status": {"type": "string", "enum": ["unmet", "met"]},
                        },
                        "required": ["text"],
                    },
                },
            },
            "required": ["objectives"],
        }

    async def call(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        raw = args.get("objectives") or []
        if not isinstance(raw, list) or not raw:
            raise ToolError("post_objectives needs a non-empty 'objectives' list")
        objs = await self._on_post(raw)
        return ToolResult(summary="objectives: {:d} posted".format(len(objs)), data={"objectives": objs})


class CompleteObjectiveTool(Tool):
    name = "complete_objective"
    group = "orchestrator"
    read_only = True
    description = ("Mark one objective met, with one line of concrete evidence (object names, "
                   "counts, diagnostics) — only when a worker's proof actually shows it.")

    def __init__(self, on_complete: "Callable[[str, str], Awaitable[bool]]") -> None:
        self._on_complete = on_complete

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"id": {"type": "string"}, "evidence": {"type": "string"}},
            "required": ["id", "evidence"],
        }

    async def call(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        oid = str(args.get("id", "")).strip()
        ok = await self._on_complete(oid, str(args.get("evidence", "")).strip())
        if not ok:
            raise ToolError("no objective with id {!r}; call post_objectives first / check ids".format(oid))
        return ToolResult(summary="objective {:s}: met".format(oid), data={"id": oid, "status": "met"})


class DelegateTool(Tool):
    name = "delegate"
    group = "orchestrator"
    description = (
        "Delegate ONE concrete, self-contained task to a worker sub-agent (it has "
        "the full Blender tool surface, its own headless context). It acts, then "
        "returns a PROOF OF WORK. Reference the objective it serves so progress is "
        "tracked. Returns the worker's id, ok flag, and proof — REVIEW the proof "
        "before completing the objective or delegating the next task."
    )

    def __init__(self, on_delegate: "Callable[[str, str, str], Awaitable[dict[str, Any]]]") -> None:
        self._on_delegate = on_delegate

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "imperative, self-contained instruction"},
                "objective_id": {"type": "string", "description": "the objective this serves"},
                "acceptance": {"type": "string", "description": "how the worker knows it's done"},
            },
            "required": ["task"],
        }

    async def call(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        task = str(args.get("task", "")).strip()
        if not task:
            raise ToolError("delegate needs a 'task'")
        res = await self._on_delegate(task, str(args.get("objective_id", "")).strip(),
                                      str(args.get("acceptance", "")).strip())
        ok = bool(res.get("ok"))
        return ToolResult(
            summary="worker {:s}: {:s}".format(str(res.get("agent_id", "?")), "ok" if ok else "needs work"),
            data=res)


class ReadWorkerTool(Tool):
    name = "read_worker"
    group = "orchestrator"
    read_only = True
    description = ("Re-read a worker's proof and recent activity (by its agent id) to review its "
                   "work in detail before judging an objective.")

    def __init__(self, on_read: "Callable[[str], Awaitable[dict[str, Any] | None]]") -> None:
        self._on_read = on_read

    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {"agent_id": {"type": "string"}}, "required": ["agent_id"]}

    async def call(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        data = await self._on_read(str(args.get("agent_id", "")).strip())
        if data is None:
            raise ToolError("no worker with that id")
        return ToolResult(summary="worker {:s}: {:s}".format(
            str(data.get("agent_id", "?")), "ok" if data.get("ok") else "incomplete"), data=data)


class SearchTranscriptTool(Tool):
    name = "search_transcript"
    group = "orchestrator"
    read_only = True
    description = ("Search this session's transcript — your earlier messages, the user's, and "
                   "worker proofs — for a keyword/phrase, to recall what was said or done.")

    def __init__(self, on_search: "Callable[[str, int], Awaitable[list[dict[str, Any]]]]") -> None:
        self._on_search = on_search

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"query": {"type": "string"},
                           "max_results": {"type": "integer", "minimum": 1, "maximum": 20}},
            "required": ["query"],
        }

    async def call(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        query = str(args.get("query", "")).strip()
        if not query:
            raise ToolError("search_transcript needs a 'query'")
        hits = await self._on_search(query, int(args.get("max_results", 6)))
        return ToolResult(summary="{:d} match(es) for {!r}".format(len(hits), query), data={"hits": hits})


class SteerWorkerTool(Tool):
    name = "steer_worker"
    group = "orchestrator"
    description = ("Inject a guidance message straight into a RUNNING worker's context (it lands "
                   "at the worker's next step). Use to course-correct a worker mid-task — e.g. when "
                   "the user gives feedback while it works. Returns whether the worker was live.")

    def __init__(self, on_steer: "Callable[[str, str], Awaitable[bool]]") -> None:
        self._on_steer = on_steer

    def input_schema(self) -> dict[str, Any]:
        return {"type": "object",
                "properties": {"agent_id": {"type": "string"}, "message": {"type": "string"}},
                "required": ["agent_id", "message"]}

    async def call(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        aid = str(args.get("agent_id", "")).strip()
        msg = str(args.get("message", "")).strip()
        if not aid or not msg:
            raise ToolError("steer_worker needs 'agent_id' and 'message'")
        ok = await self._on_steer(aid, msg)
        return ToolResult(summary="steer {:s}: {:s}".format(aid, "delivered" if ok else "not live"),
                          data={"agent_id": aid, "delivered": ok})


class AwaitWorkersTool(Tool):
    name = "await_workers"
    group = "orchestrator"
    read_only = True
    description = ("Wait for currently-running delegated worker(s) to finish and return their "
                   "proofs. Returns early as 'interrupted' if the user sends a message while you "
                   "wait — read it and decide. Use after a delegate was interrupted, or when you "
                   "spawned work and want to collect it.")

    def __init__(self, on_await: "Callable[[], Awaitable[dict[str, Any]]]") -> None:
        self._on_await = on_await

    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def call(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        data = await self._on_await()
        if data.get("interrupted"):
            return ToolResult(summary="interrupted: the user sent a message", data=data)
        fin = data.get("finished") or {}
        return ToolResult(summary="{:d} worker(s) finished, {:d} still running".format(
            len(fin), len(data.get("still_running") or [])), data=data)


def build_conductor_tools(
        *,
        on_post: "Callable[[list[dict[str, Any]]], Awaitable[list[dict[str, Any]]]]",
        on_complete: "Callable[[str, str], Awaitable[bool]]",
        on_delegate: "Callable[[str, str, str], Awaitable[dict[str, Any]]]",
        on_read: "Callable[[str], Awaitable[dict[str, Any] | None]]",
        on_search: "Callable[[str, int], Awaitable[list[dict[str, Any]]]]",
        on_steer: "Callable[[str, str], Awaitable[bool]]",
        on_await: "Callable[[], Awaitable[dict[str, Any]]]",
) -> "list[Tool]":
    """The conductor's meta-tool set, wired to the runtime's live-run callbacks."""
    return [
        PostObjectivesTool(on_post),
        CompleteObjectiveTool(on_complete),
        DelegateTool(on_delegate),
        SteerWorkerTool(on_steer),
        AwaitWorkersTool(on_await),
        ReadWorkerTool(on_read),
        SearchTranscriptTool(on_search),
    ]
