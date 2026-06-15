# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the portable ToolBackend boundary (agent/blagent/backend.py)."""

__all__ = ()

import asyncio
import importlib.util
import os
import sys
import tempfile
import unittest
from typing import Any

_REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_HAS_AGENT_DEPS = all(
    importlib.util.find_spec(m) is not None for m in ("starlette", "httpx", "mcp", "blmcp"))


def _imp() -> Any:
    for p in (os.path.join(_REPO_DIR, "mcp"), os.path.join(_REPO_DIR, "agent")):
        if p not in sys.path:
            sys.path.insert(0, p)
    import importlib
    return importlib.import_module("agentcore.backend")


def _run(coro: Any) -> Any:
    return asyncio.new_event_loop().run_until_complete(coro)


@unittest.skipUnless(_HAS_AGENT_DEPS, "agent dependencies not installed (optional feature)")
class TestPythonToolBackend(unittest.TestCase):

    def _tools(self) -> Any:
        from agentcore.tools import Tool, ToolError, ToolResult

        class Build(Tool):
            name = "build_thing"
            description = "make a thing"
            destructive = True

            def input_schema(self) -> dict:
                return {"type": "object", "properties": {"n": {"type": "integer"}}}

            async def call(self, ctx: Any, args: dict) -> Any:
                if args.get("boom"):
                    raise ToolError("kaboom")
                return ToolResult(summary="made {}".format(args.get("n", 0)), data={"ok": True})

        class Look(Tool):
            name = "look"
            description = "look"
            read_only = True

            def input_schema(self) -> dict:
                return {"type": "object", "properties": {}}

            async def call(self, ctx: Any, args: dict) -> Any:
                return ToolResult(summary="looked", data="scene: empty")

        return [Build(), Look()]

    def test_list_tools_preserves_flags(self) -> None:
        b = _imp()
        backend = b.PythonToolBackend(self._tools())
        specs = {s.name: s for s in _run(backend.list_tools())}
        self.assertEqual(set(specs), {"build_thing", "look"})
        self.assertTrue(specs["build_thing"].destructive)
        self.assertTrue(specs["look"].read_only)
        self.assertIn("n", specs["build_thing"].input_schema["properties"])

    def test_call_tool_ok_and_error_and_unknown(self) -> None:
        b = _imp()
        backend = b.PythonToolBackend(self._tools())
        ok = _run(backend.call_tool("build_thing", {"n": 3}, session_id="s"))
        self.assertEqual(ok.status, "ok")
        self.assertIn("made 3", ok.summary)
        err = _run(backend.call_tool("build_thing", {"boom": True}, session_id="s"))
        self.assertEqual(err.status, "error")
        self.assertIn("kaboom", err.error)
        unk = _run(backend.call_tool("nope", {}, session_id="s"))
        self.assertEqual(unk.status, "error")
        self.assertIn("unknown tool", unk.error)

    def test_capabilities_reflect_hooks(self) -> None:
        b = _imp()
        plain = b.PythonToolBackend(self._tools())
        self.assertEqual(plain.capabilities(), {"media"})

        async def probe(_sid: str) -> str:
            return "PROBED"
        opened = {"n": 0}

        async def _open() -> None:
            opened["n"] += 1
        rich = b.PythonToolBackend(self._tools(), probe=probe, surface_open=_open)
        self.assertEqual(rich.capabilities(), {"media", "probe", "surface"})
        self.assertEqual(_run(rich.state_probe(session_id="s")), "PROBED")
        _run(rich.open())
        self.assertEqual(opened["n"], 1)

    def test_backend_tool_adapter_round_trips(self) -> None:
        b = _imp()
        from agentcore.tools import ToolContext, ToolError
        backend = b.PythonToolBackend(self._tools())
        reg = _run(b.registry_from_backend(backend))
        tool = reg.get("build_thing")
        self.assertIsNotNone(tool)
        assert tool is not None
        self.assertTrue(tool.destructive)
        media = _media()
        res = _run(tool.call(ToolContext(media=media, session_id="s"), {"n": 7}))
        self.assertIn("made 7", res.summary)
        # error surfaces as ToolError to the engine
        with self.assertRaises(ToolError):
            _run(tool.call(ToolContext(media=media, session_id="s"), {"boom": True}))

    def test_registry_includes_extra_core_tools(self) -> None:
        b = _imp()
        from agentcore.tools import Tool, ToolResult

        class Core(Tool):
            name = "skills"
            description = "core tool"

            def input_schema(self) -> dict:
                return {"type": "object", "properties": {}}

            async def call(self, ctx: Any, args: dict) -> Any:
                return ToolResult(summary="ok")

        backend = b.PythonToolBackend(self._tools())
        reg = _run(b.registry_from_backend(backend, extra=[Core()]))
        names = {t.name for t in reg}
        self.assertEqual(names, {"build_thing", "look", "skills"})

    def test_media_data_url_ingested_by_adapter(self) -> None:
        # An HTTP-style backend that returns inline data-URL media -> the
        # adapter ingests it into the session library and yields a media id.
        b = _imp()
        from agentcore.tools import Tool, ToolContext, ToolResult

        png = ("data:image/png;base64,"
               "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")

        class _InlineBackend(b._DefaultBackendMixin):
            async def list_tools(self):
                return [b.ToolSpec(name="render", description="r", input_schema={"type": "object", "properties": {}})]

            async def call_tool(self, name, args, *, session_id, media=None):
                return b.ToolCallResult(summary="rendered", media=[b.MediaRef(id="x", mime="image/png", data_url=png)])

        reg = _run(b.registry_from_backend(_InlineBackend()))
        tool = reg.get("render")
        assert tool is not None
        media = _media()
        res = _run(tool.call(ToolContext(media=media, session_id="s"), {}))
        self.assertEqual(len(res.media_ids), 1)
        self.assertIsNotNone(media.get(res.media_ids[0]))


def _media() -> Any:
    from agentcore.media import MediaLibrary
    return MediaLibrary(tempfile.mkdtemp(prefix="media_"))


@unittest.skipUnless(_HAS_AGENT_DEPS, "agent dependencies not installed (optional feature)")
class TestRuntimeBackendWiring(unittest.TestCase):
    """The runtime holds a ToolBackend and reaches ground truth through it."""

    def _runtime(self, tools: Any) -> Any:
        from agentcore.runtime import AgentRuntime
        from agentcore.store import AgentStore
        store = AgentStore(data_dir=tempfile.mkdtemp(prefix="agentdata_"))
        return AgentRuntime(store, tools)

    def _probe_tool(self) -> Any:
        from agentcore.tools import Tool, ToolResult

        class Probe(Tool):
            name = "scene"
            description = "scene probe"
            read_only = True

            def input_schema(self) -> dict:
                return {"type": "object", "properties": {}}

            async def call(self, ctx: Any, args: dict) -> Any:
                return ToolResult(summary="ok", data="scene: 3 cubes")

        return Probe()

    def test_list_is_wrapped_in_python_backend_with_probe(self) -> None:
        b = _imp()
        rt = self._runtime([self._probe_tool()])
        self.assertIsInstance(rt.backend, b.PythonToolBackend)
        # Backend advertises the probe hook the runtime wired in.
        self.assertIn("probe", rt.backend.capabilities())
        # Registry carries the domain tool AND the core harness tools.
        names = {t.name for t in rt.registry}
        self.assertIn("scene", names)
        self.assertTrue({"skills", "media", "ask_user"} <= names)

    def test_probe_routes_through_backend(self) -> None:
        rt = self._runtime([self._probe_tool()])
        sid = rt.new_session()
        text = _run(rt._make_probe(sid)())
        self.assertEqual(text, "scene: 3 cubes")

    def test_probe_handles_missing_tool(self) -> None:
        rt = self._runtime([])           # no scene probe
        sid = rt.new_session()
        text = _run(rt._make_probe(sid)())
        self.assertIn("unavailable", text)

    def test_create_builds_registry_from_generic_backend(self) -> None:
        b = _imp()
        from agentcore.runtime import AgentRuntime
        from agentcore.store import AgentStore

        class _Inline(b._DefaultBackendMixin):
            async def list_tools(self):
                return [b.ToolSpec(name="render", description="r",
                                   input_schema={"type": "object", "properties": {}})]

            async def call_tool(self, name, args, *, session_id, media=None):
                return b.ToolCallResult(summary="rendered")

        store = AgentStore(data_dir=tempfile.mkdtemp(prefix="agentdata_"))
        rt = _run(AgentRuntime.create(store, _Inline()))
        names = {t.name for t in rt.registry}
        self.assertIn("render", names)                 # via BackendTool adapter
        self.assertTrue({"skills", "ask_user"} <= names)  # core tools too

    def test_bad_backend_type_raises(self) -> None:
        with self.assertRaises(TypeError):
            self._runtime("not a backend")  # type: ignore[arg-type]

    def test_public_ui_profile_defaults_to_generic_agentcore(self) -> None:
        # Post-split: agentcore is domain-agnostic, so the default profile is
        # neutral; the Blender branding comes from blagent's blender_profile().
        rt = self._runtime([])
        ui = rt.public_ui_profile()
        self.assertEqual(ui["brand"]["word"], "Agent")
        self.assertIn("hint", ui["welcome"])

    def test_blender_profile_supplies_branding_and_prompt(self) -> None:
        from blagent.blender_tools import blender_profile
        prof = blender_profile()
        self.assertEqual(prof.title, "Blender Agent")
        self.assertEqual(prof.brand_word, "Blender")
        self.assertTrue(prof.system_prompt)        # the Blender system prompt is carried

    def test_explicit_profile_overrides(self) -> None:
        from agentcore.profile import AgentProfile
        from agentcore.runtime import AgentRuntime
        from agentcore.store import AgentStore
        store = AgentStore(data_dir=tempfile.mkdtemp(prefix="agentdata_"))
        rt = AgentRuntime(store, [], profile=AgentProfile(title="Foo", brand_word="Foo"))
        self.assertEqual(rt.public_ui_profile()["title"], "Foo")

    def test_session_media_aggregates_worker_media(self) -> None:
        from agentcore.media import MediaLibrary
        rt = self._runtime([])
        sid = rt.new_session()
        rt._get_or_load_session(sid).media.register_bytes(b"OWN", mime="image/png", label="own")
        # A worker writes a render into its own media jail.
        agent_id = "{:s}:w:task-0".format(sid)
        wdir = os.path.join(rt.store.session_dir(sid), "workers", agent_id.replace(":", "_"))
        wid = MediaLibrary(wdir).register_bytes(b"RENDER", mime="image/png", label="render")

        items = rt.session_media(sid)
        urls = {it["url"] for it in items}
        self.assertIn("/media/{:s}/i1".format(sid), urls)                 # session's own
        worker_items = [it for it in items if it.get("worker") == agent_id]
        self.assertEqual(len(worker_items), 1)                            # aggregated
        self.assertEqual(worker_items[0]["url"], "/worker-media/{:s}/{:s}".format(agent_id, wid))
        # The /worker-media route resolver maps the agent id back to that dir.
        self.assertIsNotNone(rt.worker_media_library(agent_id).get(wid))

    def test_orchestrator_run_persists_objectives(self) -> None:
        # Orchestrator sessions must not reload empty: the objectives are
        # persisted to the transcript (synchronously, before the run task) and
        # drive a meaningful session title (not the synthetic autonomy notice).
        from agentcore.llm import LlmChunk, LlmClient
        rt = self._runtime([])

        class FakeLlm(LlmClient):
            async def stream(self, request):  # noqa: ANN001
                yield LlmChunk(content='{"tasks": []}')

        rt._make_llm = lambda: FakeLlm()      # type: ignore[method-assign]
        rt._model_name = lambda: "m"          # type: ignore[method-assign]
        # A synthetic autonomy notice already in the session (as set_autonomy adds).
        sid = rt.new_session()
        rt._get_or_load_session(sid).engine.push_record(
            {"role": "user", "content": "[Autonomy changed] orchestrator", "synthetic": True})
        _run(rt.run_autonomy_turn(sid, [{"text": "Assemble the robot arm", "acceptance": "peg mates"}]))

        recs = rt.session_records(sid)
        # The objectives persist (so the session reloads non-empty), but as a
        # SYNTHETIC record — shown via the Objectives card, not a raw bubble.
        objrec = [r for r in recs if r.get("autonomy_objectives")]
        self.assertTrue(objrec)
        self.assertTrue(objrec[0].get("synthetic"))
        # Title comes from the explicit objective title, not the synthetic notice
        # or the verbose "**Objectives**" header.
        title = next(s["title"] for s in rt.list_sessions() if s["id"] == sid)
        self.assertNotIn("Autonomy changed", str(title))
        self.assertIn("Assemble the robot arm", str(title))


    def test_set_config_persists_autonomy_qa(self) -> None:
        # The per-worker QA toggle must survive a restart (read back from disk),
        # since run_autonomy_turn decides the reviewer from config at run start.
        import yaml
        rt = self._runtime([])
        rt.set_config({"autonomy_qa": True})
        self.assertTrue(rt.store.config.autonomy_qa)
        self.assertTrue(rt.store._config_path.endswith(".yaml"))
        with open(rt.store._config_path, encoding="utf-8") as fh:
            self.assertTrue(yaml.safe_load(fh).get("autonomy_qa"))

    def _review_stub(self):
        from agentcore.autonomy import WorkerResult, WorkerTask

        class StubRunner:
            def __init__(self) -> None:
                self.continues = 0
                self.released = False

            async def __call__(self, task):  # noqa: ANN001
                return WorkerResult(task.id, task.objective_id, "first attempt", ok=True)

            async def continue_(self, task, guidance):  # noqa: ANN001
                self.continues += 1
                return WorkerResult(task.id, task.objective_id, "continued: " + guidance, ok=True)

            def release(self, task):  # noqa: ANN001
                self.released = True

        return StubRunner(), WorkerTask(id="t0", objective_id="o1", instruction="build it",
                                        acceptance="exists")

    def test_autonomy_switch_defers_during_a_turn_then_applies(self) -> None:
        rt = self._runtime([])
        sid = rt.new_session()
        session = rt._get_or_load_session(sid)
        out: dict = {}

        async def scenario():
            async def busywork():
                await asyncio.sleep(0.3)
            session.task = asyncio.ensure_future(busywork())
            out["deferred"] = rt.set_autonomy_level(sid, "orchestrator")   # busy -> defer
            out["mid"] = rt.store.config.autonomy_level
            await session.task                                            # turn ends
            await rt._apply_pending_autonomy(sid)
            out["after"] = rt.store.config.autonomy_level

        _run(scenario())
        self.assertEqual(out["deferred"].get("pending_autonomy"), "orchestrator")
        self.assertEqual(out["mid"], "yolo")            # not switched mid-turn
        self.assertEqual(out["after"], "orchestrator")  # applied at turn end
        self.assertNotIn(sid, rt._pending_autonomy)

    def test_autonomy_switch_immediate_when_idle_with_role_note(self) -> None:
        rt = self._runtime([])
        sid = rt.new_session()
        public = rt.set_autonomy_level(sid, "orchestrator")   # idle -> immediate
        self.assertEqual(public["autonomy_level"], "orchestrator")
        self.assertIsNone(public.get("pending_autonomy"))
        note = [r for r in rt.session_records(sid)
                if r.get("autonomy_notice") == "orchestrator"][-1]
        self.assertIn("ROLE CHANGED", note["content"])
        self.assertIn("ORCHESTRATOR", note["content"])

    def test_review_loop_replenishes_and_reruns_until_accepted(self) -> None:
        from agentcore.llm import LlmChunk, LlmClient
        rt = self._runtime([self._probe_tool()])

        class ReviewLlm(LlmClient):
            def __init__(self) -> None:
                self.n = 0

            async def stream(self, request):  # noqa: ANN001
                self.n += 1
                if self.n == 1:
                    yield LlmChunk(content='{"accept": false, "guidance": "fix the seam", "request_qa": false}')
                else:
                    yield LlmChunk(content='{"accept": true, "guidance": "", "request_qa": false}')

        llm = ReviewLlm()
        rt._make_llm = lambda: llm                # type: ignore[method-assign]
        rt._model_name = lambda: "m"              # type: ignore[method-assign]
        stub, task = self._review_stub()
        events: list[dict] = []

        async def emit(ev):  # noqa: ANN001
            events.append(ev)

        reviewing = rt._make_reviewing_runner(
            "s1", stub, emit, rt._make_probe("s1"), "m",
            qa_enabled=False, media_factory=lambda a: None)
        result = _run(reviewing(task))

        self.assertEqual(stub.continues, 1)       # one guided re-run, then accepted
        self.assertTrue(stub.released)
        self.assertIn("fix the seam", result.proof)
        reviews = [e for e in events if e["type"] == "worker_review"]
        self.assertEqual([r["passed"] for r in reviews], [False, True])

    def test_review_loop_does_not_rerun_a_stopped_worker(self) -> None:
        from agentcore.llm import LlmChunk, LlmClient
        rt = self._runtime([self._probe_tool()])

        class RejectLlm(LlmClient):
            async def stream(self, request):  # noqa: ANN001
                yield LlmChunk(content='{"accept": false, "guidance": "more", "request_qa": false}')

        rt._make_llm = lambda: RejectLlm()        # type: ignore[method-assign]
        rt._model_name = lambda: "m"              # type: ignore[method-assign]
        stub, task = self._review_stub()
        rt._stopped_workers.add("s1:w:t0")        # user hit Stop
        events: list[dict] = []

        async def emit(ev):  # noqa: ANN001
            events.append(ev)

        reviewing = rt._make_reviewing_runner(
            "s1", stub, emit, rt._make_probe("s1"), "m",
            qa_enabled=False, media_factory=lambda a: None)
        _run(reviewing(task))

        self.assertEqual(stub.continues, 0)       # stopped -> orchestrator notified, no re-run
        review = [e for e in events if e["type"] == "worker_review"][0]
        self.assertTrue(review["stopped"])
        self.assertTrue(review["passed"])         # accepted as-is

    def test_worker_ask_orchestrator_answers_directly(self) -> None:
        from agentcore.llm import LlmChunk, LlmClient
        rt = self._runtime([self._probe_tool()])

        class FakeLlm(LlmClient):
            async def stream(self, request):  # noqa: ANN001
                yield LlmChunk(content='{"answer": "use the Z axis"}')

        rt._make_llm = lambda: FakeLlm()      # type: ignore[method-assign]
        rt._model_name = lambda: "m"          # type: ignore[method-assign]
        sid = rt.new_session()
        rt._autonomy_objs[sid] = []
        seen: list[dict] = []

        async def emit(ev):  # noqa: ANN001
            seen.append(ev)

        ask = rt._make_orchestrator_ask(sid, emit)
        resp = _run(ask(sid + ":w:t0", "Which axis?", ["X", "Z"]))
        self.assertEqual(resp["source"], "orchestrator")
        self.assertIn("Z axis", resp["answer"])
        self.assertIn("worker_question", [e["type"] for e in seen])
        ans = [e for e in seen if e["type"] == "worker_question_answered"][0]
        self.assertEqual(ans["source"], "orchestrator")

    def test_worker_ask_orchestrator_escalates_to_user(self) -> None:
        from agentcore.llm import LlmChunk, LlmClient
        rt = self._runtime([self._probe_tool()])

        class FakeLlm(LlmClient):
            async def stream(self, request):  # noqa: ANN001
                yield LlmChunk(content='{"escalate": true, "question": "Glossy or matte?"}')

        rt._make_llm = lambda: FakeLlm()      # type: ignore[method-assign]
        rt._model_name = lambda: "m"          # type: ignore[method-assign]
        sid = rt.new_session()
        rt._autonomy_objs[sid] = []
        rt._get_or_load_session(sid)

        async def drive():
            q = rt.subscribe()
            ask = rt._make_orchestrator_ask(sid, rt.emit)
            task = asyncio.ensure_future(ask(sid + ":w:t0", "done?", []))
            elicit_id = None
            while elicit_id is None:
                ev = await asyncio.wait_for(q.get(), timeout=5)
                if ev.get("type") == "elicitation":
                    elicit_id = ev["elicit_id"]
            rt.resolve_elicit(sid, elicit_id, {"choices": ["matte"], "text": ""})
            result = await asyncio.wait_for(task, timeout=5)
            rt.unsubscribe(q)
            return result

        resp = _run(drive())
        self.assertEqual(resp["source"], "user")
        self.assertIn("matte", resp["answer"])


if __name__ == "__main__":
    unittest.main()
