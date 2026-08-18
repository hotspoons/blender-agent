# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Tests for the ACP bridge onto a live runtime
(``agent/agentcore/acp/bridge.py``, ``updates.py``).

These drive a real ``AgentRuntime`` with a fake LLM, so a turn genuinely runs:
the events are the engine's own, not hand-written fixtures. What is asserted is
the translation -- that a prompt blocks until the turn ends, that updates come
out in ACP shapes, and that a client which cannot keep up is told so rather
than handed a transcript with a hole in it.

    python -m unittest tests.test_acp_bridge -v
"""

__all__ = ()

import asyncio
import importlib.util
import os
import sys
import tempfile
import unittest
from typing import Any

_REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_AGENT_DIR = os.path.join(_REPO_DIR, "agent")
_MCP_DIR = os.path.join(_REPO_DIR, "mcp")

for _path in (_MCP_DIR, _AGENT_DIR):
    if _path not in sys.path:
        sys.path.insert(0, _path)

_HAS_DEPS = all(
    importlib.util.find_spec(mod) is not None
    for mod in ("acp", "pydantic", "starlette", "httpx", "mcp", "blmcp"))


def _text_llm(reply: str = "Made you a cube."):
    from agentcore.llm import LlmChunk, LlmClient

    class FakeLlm(LlmClient):  # type: ignore[misc]
        async def stream(self, request):  # type: ignore[no-untyped-def]
            for word in reply.split(" "):
                yield LlmChunk(content=word + " ")

    return lambda: FakeLlm()


class RecordingClient:
    """Stands in for the ACP client; records the updates pushed at it."""

    def __init__(self) -> None:
        self.updates: "list[dict[str, Any]]" = []
        self.version = 2

    async def session_update(self, session_id: str, update: "dict[str, Any]") -> None:
        self.updates.append(update)

    async def request_permission(self, *args: Any, **kwargs: Any) -> "dict[str, Any]":
        return {"outcome": {"outcome": "selected", "optionId": "allow"}}

    async def create_elicitation(self, *args: Any, **kwargs: Any) -> "dict[str, Any]":
        return {"outcome": {"outcome": "cancelled"}}

    def kinds(self) -> "list[str]":
        return [str(u.get("sessionUpdate")) for u in self.updates]


@unittest.skipUnless(_HAS_DEPS, "agent dependencies not installed")
class TestBridge(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _bridge(self, reply: str = "Made you a cube.") -> Any:
        from agentcore.acp.bridge import RuntimeBridge
        from agentcore.runtime import AgentRuntime
        from agentcore.store import AgentStore

        store = AgentStore(data_dir=self._tmp.name)
        store.config.endpoint = "http://fake-endpoint/v1"
        store.config.model = "fake-model"
        store.config.autonomy_level = "yolo"
        runtime = AgentRuntime(store, [])
        runtime._make_llm = _text_llm(reply)  # type: ignore[method-assign]
        runtime._model_name = lambda: "fake-model"  # type: ignore[method-assign]
        return RuntimeBridge(runtime), runtime

    def test_prompt_blocks_until_the_turn_ends(self) -> None:
        """
        ACP answers session/prompt with the turn's stop reason, but the runtime
        starts turns fire-and-forget -- so the bridge has to wait for one.
        """
        async def run() -> "tuple[str, RecordingClient]":
            bridge, _runtime = self._bridge()
            client = RecordingClient()
            session_id = await bridge.new_session(None, None, client)
            stop = await bridge.prompt(
                session_id, [{"type": "text", "text": "make a cube"}], client)
            return stop, client

        stop, client = asyncio.run(run())
        self.assertEqual(stop, "end_turn")
        kinds = client.kinds()
        self.assertIn("user_message", kinds)
        self.assertIn("agent_message_chunk", kinds)
        # The turn's end is reported as an idle state update, v2-style.
        self.assertEqual(kinds[-1], "state_update")

    def test_streamed_chunks_share_one_message_id(self) -> None:
        """
        v2 patches messages by id. Every chunk of one reply must carry the same
        one, or a client reconstructs several fragmentary messages instead of
        one; and the final full message must reuse it, so it REPLACES the
        accumulated chunks rather than appending a duplicate.
        """
        async def run() -> RecordingClient:
            bridge, _runtime = self._bridge("one two three")
            client = RecordingClient()
            session_id = await bridge.new_session(None, None, client)
            await bridge.prompt(session_id, [{"type": "text", "text": "go"}], client)
            return client

        client = asyncio.run(run())
        chunk_ids = {
            u["messageId"] for u in client.updates
            if u.get("sessionUpdate") == "agent_message_chunk"}
        self.assertEqual(len(chunk_ids), 1, "chunks split across message ids")

        finals = [u for u in client.updates if u.get("sessionUpdate") == "agent_message"]
        self.assertTrue(finals)
        self.assertEqual(finals[-1]["messageId"], chunk_ids.pop())

    def test_user_and_assistant_messages_get_distinct_ids(self) -> None:
        async def run() -> RecordingClient:
            bridge, _runtime = self._bridge()
            client = RecordingClient()
            session_id = await bridge.new_session(None, None, client)
            await bridge.prompt(session_id, [{"type": "text", "text": "hi"}], client)
            return client

        client = asyncio.run(run())
        user = [u for u in client.updates if u.get("sessionUpdate") == "user_message"]
        agent = [u for u in client.updates if u.get("sessionUpdate") == "agent_message"]
        self.assertTrue(user and agent)
        self.assertNotEqual(user[0]["messageId"], agent[0]["messageId"])

    def test_empty_prompt_is_rejected(self) -> None:
        from acp.exceptions import RequestError

        async def run() -> None:
            bridge, _runtime = self._bridge()
            client = RecordingClient()
            session_id = await bridge.new_session(None, None, client)
            await bridge.prompt(session_id, [{"type": "image", "data": "x"}], client)

        with self.assertRaises(RequestError):
            asyncio.run(run())

    def test_resume_replays_the_transcript(self) -> None:
        async def run() -> "tuple[RecordingClient, str]":
            bridge, _runtime = self._bridge()
            live = RecordingClient()
            session_id = await bridge.new_session(None, None, live)
            await bridge.prompt(session_id, [{"type": "text", "text": "make a cube"}], live)

            replay = RecordingClient()
            await bridge.resume_session(session_id, {"type": "start"}, replay)
            return replay, session_id

        replay, _session_id = asyncio.run(run())
        kinds = replay.kinds()
        self.assertIn("user_message", kinds)
        self.assertIn("agent_message", kinds)

    def test_resume_rejects_unsupported_cursors(self) -> None:
        from acp.exceptions import RequestError

        async def run() -> None:
            bridge, _runtime = self._bridge()
            await bridge.resume_session("s", {"type": "message", "messageId": "x"},
                                        RecordingClient())

        with self.assertRaises(RequestError):
            asyncio.run(run())

    def test_fork_carries_context_without_copying_history(self) -> None:
        """
        A fork inherits the parent's CONTEXT, not its transcript.

        That is what ``session/fork`` is for -- "a new session based on the
        context of an existing one ... without affecting the original's
        history" -- and it is what the harness's seeding already does: the
        parent conversation becomes an LLM-context prefix, so the fork starts
        oriented but owns an empty transcript of its own.
        """
        async def run() -> "tuple[str, str, Any]":
            bridge, runtime = self._bridge()
            client = RecordingClient()
            session_id = await bridge.new_session(None, None, client)
            await bridge.prompt(session_id, [{"type": "text", "text": "make a cube"}], client)
            forked = await bridge.fork_session(session_id, None)
            return session_id, forked, runtime

        session_id, forked, runtime = asyncio.run(run())
        self.assertNotEqual(session_id, forked)
        # The parent is untouched.
        self.assertTrue(runtime.session_records(session_id))
        # The fork has no history of its own ...
        self.assertEqual(runtime.session_records(forked), [])
        # ... but does carry the parent's conversation as context.
        engine = runtime._get_or_load_session(forked).engine  # pylint: disable=protected-access
        seeded = " ".join(str(m.get("content", "")) for m in engine._seed_messages)  # pylint: disable=protected-access
        self.assertIn("make a cube", seeded)

    def test_fork_of_an_unknown_session_is_rejected(self) -> None:
        from acp.exceptions import RequestError

        async def run() -> None:
            bridge, _runtime = self._bridge()
            await bridge.fork_session("no-such-session", None)

        with self.assertRaises(RequestError):
            asyncio.run(run())


def _confirm_tool() -> Any:
    """A destructive tool, so `ask` autonomy gates it behind a confirm."""
    from agentcore.tools import Tool, ToolResult

    class Mutate(Tool):  # type: ignore[misc]
        name = "mutate"
        description = "Change the scene."
        destructive = True

        def input_schema(self) -> "dict[str, Any]":
            return {"type": "object", "properties": {}}

        async def call(self, ctx: Any, args: "dict[str, Any]") -> Any:
            del ctx, args
            return ToolResult(data={"changed": True}, summary="changed the scene")

    return Mutate()


def _tool_calling_llm(reply: str) -> Any:
    from agentcore.llm import LlmChunk, LlmClient

    class FakeLlm(LlmClient):  # type: ignore[misc]
        def __init__(self) -> None:
            self.turns = 0

        async def stream(self, request):  # type: ignore[no-untyped-def]
            self.turns += 1
            if self.turns == 1:
                yield LlmChunk(tool_calls=[{
                    "index": 0, "id": "call-1",
                    "function": {"name": "mutate", "arguments": "{}"}}])
                return
            yield LlmChunk(content=reply)

    instance = FakeLlm()
    return lambda: instance


@unittest.skipUnless(_HAS_DEPS, "agent dependencies not installed")
class TestPermissionGate(unittest.TestCase):
    """
    A destructive tool under `ask` autonomy parks on a future until answered.

    Found by a live run: nothing was wired to answer, so the gate waited out
    its ten-minute timeout and auto-declined -- the worker got as far as
    execute_blender_code and was refused by nobody. The client is the one with
    a user behind it, so the request has to reach it.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _bridge(self) -> Any:
        from agentcore.acp.bridge import RuntimeBridge
        from agentcore.runtime import AgentRuntime
        from agentcore.store import AgentStore

        store = AgentStore(data_dir=self._tmp.name)
        store.config.endpoint = "http://fake-endpoint/v1"
        store.config.model = "fake-model"
        # The shipped default, and the one that caused the live failure.
        store.config.autonomy = "ask"
        store.config.autonomy_level = "ask"
        runtime = AgentRuntime(store, [_confirm_tool()])
        runtime._make_llm = _tool_calling_llm("Done. PROOF: changed.")
        runtime._model_name = lambda: "fake-model"
        return RuntimeBridge(runtime), runtime

    def _run(self, decision: str) -> "tuple[str, RecordingClient]":
        class Decider(RecordingClient):
            def __init__(self) -> None:
                super().__init__()
                self.asked: "list[Any]" = []

            async def request_permission(self, session_id, title, options,
                                         subject=None, description=None):
                self.asked.append((title, subject))
                if decision == "allow":
                    return {"outcome": {"outcome": "selected", "optionId": "allow_once"}}
                return {"outcome": {"outcome": "selected", "optionId": "reject_once"}}

        async def run() -> "tuple[str, Any]":
            bridge, _runtime = self._bridge()
            client = Decider()
            session_id = await bridge.new_session(None, None, client)
            stop = await bridge.prompt(
                session_id, [{"type": "text", "text": "change it"}], client)
            return stop, client

        return asyncio.run(run())

    def test_allowing_lets_the_tool_run(self) -> None:
        stop, client = self._run("allow")
        self.assertEqual(stop, "end_turn")
        self.assertTrue(client.asked, "the client was never asked for permission")
        self.assertIn("mutate", client.asked[0][0])
        # v2 carries the tool call as an extensible subject.
        self.assertEqual(client.asked[0][1]["toolCall"]["toolCallId"], "call-1")
        states = [
            u.get("_meta", {}).get("ai.patapsco.blender-agent", {}).get("state")
            for u in client.updates if u.get("sessionUpdate") == "tool_call_update"]
        self.assertIn("done", states)
        self.assertNotIn("rejected", states)

    def test_rejecting_declines_the_call(self) -> None:
        stop, client = self._run("reject")
        self.assertTrue(client.asked)
        states = [
            u.get("_meta", {}).get("ai.patapsco.blender-agent", {}).get("state")
            for u in client.updates if u.get("sessionUpdate") == "tool_call_update"]
        self.assertIn("rejected", states)
        self.assertEqual(stop, "end_turn")


@unittest.skipUnless(_HAS_DEPS, "agent dependencies not installed")
class TestPerSessionAutonomy(unittest.TestCase):
    """
    Autonomy is per conversation, not per process.

    One agent now serves several clients at once -- web UI windows and ACP
    connections. When ``set_autonomy_level`` wrote the shared config, one
    client switching to swarm silently switched everyone.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _runtime(self) -> Any:
        from agentcore.runtime import AgentRuntime
        from agentcore.store import AgentStore

        store = AgentStore(data_dir=self._tmp.name)
        store.config.endpoint = "http://fake-endpoint/v1"
        store.config.model = "fake-model"
        return AgentRuntime(store, [])

    def test_one_session_does_not_change_another(self) -> None:
        runtime = self._runtime()
        first, second = runtime.new_session(), runtime.new_session()

        runtime.set_autonomy_level(first, "ask")
        self.assertEqual(runtime.autonomy_for(first)[0], "ask")
        self.assertEqual(runtime.autonomy_for(second)[0], "yolo")

        runtime.set_autonomy_level(second, "orchestrator")
        self.assertEqual(runtime.autonomy_for(first)[0], "ask")
        self.assertEqual(runtime.autonomy_for(second)[0], "orchestrator")

    def test_no_session_sets_the_stored_default(self) -> None:
        runtime = self._runtime()
        runtime.set_autonomy_level("", "ask")
        self.assertEqual(runtime.store.config.autonomy_level, "ask")
        # A session created afterwards inherits it ...
        fresh = runtime.new_session()
        self.assertEqual(runtime.autonomy_for(fresh)[0], "ask")
        # ... but one with its own level keeps it.
        chosen = runtime.new_session()
        runtime.set_autonomy_level(chosen, "yolo")
        runtime.set_autonomy_level("", "orchestrator")
        self.assertEqual(runtime.autonomy_for(chosen)[0], "yolo")

    def test_config_echo_names_its_session(self) -> None:
        """
        The config event is broadcast to every subscriber, so the echo has to
        say which session it is about or another window applies it to itself.
        """
        runtime = self._runtime()
        session_id = runtime.new_session()
        public = runtime.set_autonomy_level(session_id, "ask")
        self.assertEqual(public["session_id"], session_id)
        self.assertEqual(public["autonomy_level"], "ask")
        self.assertEqual(public["autonomy"], "ask")

    def test_acp_set_config_option_is_session_scoped(self) -> None:
        async def run() -> "tuple[Any, str, str]":
            from agentcore.acp.bridge import RuntimeBridge

            runtime = self._runtime()
            bridge = RuntimeBridge(runtime)
            client = RecordingClient()
            first = await bridge.new_session(None, None, client)
            second = await bridge.new_session(None, None, client)
            await bridge.set_config_option(first, "autonomy", "ask")
            return runtime, first, second

        runtime, first, second = asyncio.run(run())
        self.assertEqual(runtime.autonomy_for(first)[0], "ask")
        self.assertEqual(runtime.autonomy_for(second)[0], "yolo")

    def test_acp_rejects_unknown_options(self) -> None:
        from acp.exceptions import RequestError

        async def run() -> None:
            from agentcore.acp.bridge import RuntimeBridge

            bridge = RuntimeBridge(self._runtime())
            await bridge.set_config_option("s", "endpoint", "http://evil/v1")

        with self.assertRaises(RequestError):
            asyncio.run(run())


@unittest.skipUnless(_HAS_DEPS, "agent dependencies not installed")
class TestOverflow(unittest.TestCase):
    """
    A slow client must be told it fell behind.

    The broadcast bus drops a lagging subscriber on purpose -- fine for the web
    UI, which re-reads the transcript. For a protocol client that silently
    turns a partial conversation into an apparently complete one, so the
    per-session subscription records the overflow instead.
    """

    def test_subscription_marks_overflow_instead_of_dropping(self) -> None:
        from agentcore.runtime import SessionSubscription

        subscription = SessionSubscription("s1", maxsize=2)
        for index in range(5):
            subscription.offer({"type": "token", "session_id": "s1", "text": str(index)})

        self.assertTrue(subscription.overflowed)
        self.assertEqual(subscription.queue.qsize(), 2)

    def test_subscription_filters_by_session(self) -> None:
        from agentcore.runtime import SessionSubscription

        subscription = SessionSubscription("s1")
        subscription.offer({"type": "token", "session_id": "other"})
        self.assertEqual(subscription.queue.qsize(), 0)

        subscription.offer({"type": "token", "session_id": "s1"})
        self.assertEqual(subscription.queue.qsize(), 1)

    def test_worker_events_reach_the_owning_session(self) -> None:
        """Delegated work is tagged with the worker's id and the parent's."""
        from agentcore.runtime import SessionSubscription

        subscription = SessionSubscription("s1")
        subscription.offer({"type": "token", "session_id": "w1", "parent_session_id": "s1"})
        self.assertEqual(subscription.queue.qsize(), 1)


if __name__ == "__main__":
    unittest.main()
