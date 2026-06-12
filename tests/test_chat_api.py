# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Tests for the agent's OpenAI-compatible chat-completions front end
(``blagent.chat_api``): env gating, per-client sessions, tool-call
surfacing (structured + inline), media in both directions, auth.
"""

__all__ = ()

import asyncio
import base64
import importlib.util
import json
import os
import sys
import tempfile
import unittest

_REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _sub in ("agent", "mcp"):
    _path = os.path.join(_REPO_DIR, _sub)
    if _path not in sys.path:
        sys.path.insert(0, _path)

_HAS_AGENT_DEPS = all(
    importlib.util.find_spec(mod) is not None
    for mod in ("starlette", "httpx", "mcp", "blmcp")
)

# A valid 1x1 transparent PNG.
_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGBg"
    "AAAABQABh6FO1AAAAABJRU5ErkJggg=="
)

_ENV_VARS = (
    "BLENDER_AGENT_CHAT_API",
    "BLENDER_AGENT_CHAT_API_KEY",
    "BLENDER_AGENT_CHAT_API_INLINE_TOOLS",
    "BLENDER_AGENT_DATA_DIR",
)


@unittest.skipUnless(_HAS_AGENT_DEPS, "agent dependencies not installed (optional feature)")
class _ChatApiTestCase(unittest.TestCase):

    def setUp(self) -> None:
        self._env = {key: os.environ.get(key) for key in _ENV_VARS}
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["BLENDER_AGENT_DATA_DIR"] = self._tmp.name
        os.environ["BLENDER_AGENT_CHAT_API"] = "1"
        os.environ.pop("BLENDER_AGENT_CHAT_API_KEY", None)
        os.environ.pop("BLENDER_AGENT_CHAT_API_INLINE_TOOLS", None)

    def tearDown(self) -> None:
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._tmp.cleanup()

    def _runtime(self, fake_llm_factory):
        from blagent.runtime import AgentRuntime
        from blagent.store import AgentStore

        async def build():
            store = AgentStore(data_dir=self._tmp.name)
            store.config.endpoint = "http://fake-endpoint/v1"
            store.config.model = "fake-model"
            runtime = AgentRuntime(store, [])
            runtime._make_llm = fake_llm_factory  # type: ignore[method-assign]
            runtime._model_name = lambda: "fake-model"  # type: ignore[method-assign]
            return runtime

        return asyncio.new_event_loop().run_until_complete(build())

    def _client(self, fake_llm_factory):
        from blagent.app import create_app
        from starlette.testclient import TestClient

        runtime = self._runtime(fake_llm_factory)
        return runtime, TestClient(create_app(runtime))


def _text_llm(reply: str = "Hello from the agent."):
    from blagent.llm import LlmChunk, LlmClient

    class FakeLlm(LlmClient):
        async def stream(self, request):
            yield LlmChunk(content=reply)

    return FakeLlm


def _tool_llm():
    """
    Round 1: text + a `skills` tool call (local tool, no Blender
    bridge needed). Round 2: final text.
    """
    from blagent.llm import LlmChunk, LlmClient

    class FakeLlm(LlmClient):
        def __init__(self) -> None:
            self.round = 0

        async def stream(self, request):
            self.round += 1
            if self.round == 1:
                yield LlmChunk(content="Checking skills. ")
                yield LlmChunk(tool_calls=[{
                    "index": 0, "id": "call_1",
                    "function": {
                        "name": "skills",
                        "arguments": json.dumps({"subcommand": "list"}),
                    },
                }])
            else:
                yield LlmChunk(content="All done.")

    return FakeLlm


class TestConfigure(_ChatApiTestCase):

    def test_missing_remote_llm_refused(self) -> None:
        from blagent import chat_api
        from blagent.store import AgentStore
        from blagent.runtime import AgentRuntime

        store = AgentStore(data_dir=self._tmp.name)
        store.config.endpoint = ""
        store.config.model = ""
        runtime = AgentRuntime(store, [])
        with self.assertRaises(RuntimeError) as ctx:
            chat_api.configure(runtime)
        self.assertIn("BLENDER_AGENT_ENDPOINT", str(ctx.exception))
        self.assertIn("BLENDER_AGENT_MODEL", str(ctx.exception))

    def test_configure_pins_remote(self) -> None:
        from blagent import chat_api

        runtime = self._runtime(_text_llm())
        runtime.store.config.use_local_llm = True
        chat_api.configure(runtime)
        self.assertFalse(runtime.store.config.use_local_llm)

    def test_disabled_without_env(self) -> None:
        from blagent import chat_api

        os.environ.pop("BLENDER_AGENT_CHAT_API", None)
        self.assertFalse(chat_api.enabled())
        os.environ["BLENDER_AGENT_CHAT_API"] = "1"
        self.assertTrue(chat_api.enabled())


class TestParsing(_ChatApiTestCase):

    def test_client_session_id_deterministic(self) -> None:
        from blagent import chat_api

        class FakeRequest:
            headers: dict = {}

        a1 = chat_api.client_session_id({"user": "alice"}, FakeRequest())
        a2 = chat_api.client_session_id({"user": "alice"}, FakeRequest())
        b = chat_api.client_session_id({"user": "bob"}, FakeRequest())
        self.assertEqual(a1, a2)
        self.assertNotEqual(a1, b)
        self.assertTrue(a1.startswith("api-alice-"))

        header_request = type("R", (), {"headers": {"x-client-id": "kiosk-7"}})()
        h = chat_api.client_session_id({}, header_request)
        self.assertTrue(h.startswith("api-kiosk-7-"))

    def test_extract_last_user_message_with_image(self) -> None:
        from blagent import chat_api

        data_url = "data:image/png;base64," + base64.b64encode(_TINY_PNG).decode()
        text, attachments = chat_api.extract_user_input([
            {"role": "user", "content": "old message"},
            {"role": "assistant", "content": "reply"},
            {"role": "user", "content": [
                {"type": "text", "text": "what is this?"},
                {"type": "image_url", "image_url": {"url": data_url}},
                {"type": "image_url", "image_url": {"url": "https://x/y.png"}},
            ]},
        ])
        self.assertIn("what is this?", text)
        self.assertIn("skipped", text)  # remote URLs are not fetched
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0], (_TINY_PNG, "image/png", None))

    def test_extract_file_part(self) -> None:
        from blagent import chat_api

        _text, attachments = chat_api.extract_user_input([
            {"role": "user", "content": [
                {"type": "text", "text": "rig this"},
                {"type": "file", "file": {
                    "name": "dragon.stl",
                    "b64": base64.b64encode(b"solid x\nendsolid x\n").decode(),
                }},
            ]},
        ])
        self.assertEqual(len(attachments), 1)
        data, _mime, name = attachments[0]
        self.assertEqual(name, "dragon.stl")
        self.assertTrue(data.startswith(b"solid"))


class TestEventTranslator(_ChatApiTestCase):

    def _media_library(self):
        from blagent.media import MediaLibrary

        library = MediaLibrary(os.path.join(self._tmp.name, "media"))
        media_id = library.register_bytes(_TINY_PNG, mime="image/png", label="t")
        return library, media_id

    def test_token_and_error_passthrough(self) -> None:
        from blagent.chat_api import EventTranslator

        translator = EventTranslator(None, inline_tools=False)
        self.assertEqual(translator.feed({"type": "token", "text": "hi"}), {"content": "hi"})
        delta = translator.feed({"type": "error", "message": "boom"})
        self.assertIn("boom", delta["content"])
        self.assertFalse(translator.done)
        translator.feed({"type": "turn_done"})
        self.assertTrue(translator.done)

    def test_tool_status_structured_and_inline(self) -> None:
        from blagent.chat_api import EventTranslator

        for inline in (False, True):
            translator = EventTranslator(None, inline_tools=inline)
            start = translator.feed({
                "type": "tool_status", "state": "running",
                "call_id": "c1", "name": "skills", "arguments": "{}",
            })
            end = translator.feed({
                "type": "tool_status", "state": "done",
                "call_id": "c1", "name": "skills", "arguments": "{}",
                "summary": "5 skill(s)",
            })
            self.assertEqual(start["blender_tool_calls"][0]["status"], "running")
            self.assertEqual(end["blender_tool_calls"][0]["status"], "done")
            self.assertEqual(("content" in start), inline)
            if inline:
                self.assertIn("🔧", start["content"])
                self.assertIn("✅", end["content"])

            merged = translator.merged_tool_calls()
            self.assertEqual(len(merged), 1)
            self.assertEqual(merged[0]["status"], "done")
            self.assertEqual(merged[0]["summary"], "5 skill(s)")

    def test_tool_media_becomes_data_url(self) -> None:
        from blagent.chat_api import EventTranslator

        library, media_id = self._media_library()
        translator = EventTranslator(library, inline_tools=False)
        delta = translator.feed({
            "type": "tool_status", "state": "done",
            "call_id": "c1", "name": "render", "arguments": "{}",
            "summary": "rendered", "media_ids": [media_id],
        })
        self.assertEqual(len(delta["blender_media"]), 1)
        self.assertTrue(delta["blender_media"][0]["data_url"].startswith("data:image/png;base64,"))
        self.assertIn("![{:s}]".format(media_id), delta["content"])
        self.assertEqual(len(translator.media), 1)


class TestEndToEnd(_ChatApiTestCase):

    def test_non_streaming_with_tool_calls(self) -> None:
        _runtime, client = self._client(_tool_llm())
        response = client.post("/v1/chat/completions", json={
            "model": "anything",
            "user": "alice",
            "messages": [{"role": "user", "content": "list your skills"}],
        })
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["object"], "chat.completion")
        message = payload["choices"][0]["message"]
        self.assertIn("All done.", message["content"])
        calls = message["blender_tool_calls"]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "skills")
        self.assertEqual(calls[0]["status"], "done")

    def test_streaming_sse(self) -> None:
        _runtime, client = self._client(_text_llm("streamed reply"))
        with client.stream("POST", "/v1/chat/completions", json={
            "stream": True,
            "user": "bob",
            "messages": [{"role": "user", "content": "hello"}],
        }) as response:
            self.assertEqual(response.status_code, 200)
            lines = [l for l in response.iter_lines() if l.startswith("data: ")]
        self.assertEqual(lines[-1], "data: [DONE]")
        chunks = [json.loads(l[len("data: "):]) for l in lines[:-1]]
        self.assertEqual(chunks[0]["choices"][0]["delta"].get("role"), "assistant")
        content = "".join(
            c["choices"][0]["delta"].get("content") or "" for c in chunks)
        self.assertIn("streamed reply", content)
        self.assertEqual(chunks[-1]["choices"][0]["finish_reason"], "stop")

    def test_session_per_client_persists(self) -> None:
        runtime, client = self._client(_text_llm())
        for i in range(2):
            response = client.post("/v1/chat/completions", json={
                "user": "carol",
                "messages": [{"role": "user", "content": "message {:d}".format(i)}],
            })
            self.assertEqual(response.status_code, 200)

        sessions = [s for s in runtime.list_sessions() if str(s["id"]).startswith("api-carol-")]
        self.assertEqual(len(sessions), 1)
        records = runtime.session_records(str(sessions[0]["id"]))
        user_turns = [r for r in records if r.get("role") == "user"]
        self.assertEqual(len(user_turns), 2)

        # A different client gets a different session.
        client.post("/v1/chat/completions", json={
            "user": "dave",
            "messages": [{"role": "user", "content": "hi"}],
        })
        self.assertTrue(any(
            str(s["id"]).startswith("api-dave-") for s in runtime.list_sessions()))

    def test_media_in_registered(self) -> None:
        runtime, client = self._client(_text_llm())
        data_url = "data:image/png;base64," + base64.b64encode(_TINY_PNG).decode()
        response = client.post("/v1/chat/completions", json={
            "user": "eve",
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": "look at this"},
                {"type": "image_url", "image_url": {"url": data_url}},
            ]}],
        })
        self.assertEqual(response.status_code, 200)
        session_id = next(
            str(s["id"]) for s in runtime.list_sessions()
            if str(s["id"]).startswith("api-eve-"))
        self.assertEqual(len(runtime.session_media(session_id)), 1)

    def test_auth_required_when_key_set(self) -> None:
        os.environ["BLENDER_AGENT_CHAT_API_KEY"] = "sekrit"
        _runtime, client = self._client(_text_llm())
        body = {"user": "f", "messages": [{"role": "user", "content": "hi"}]}

        denied = client.post("/v1/chat/completions", json=body)
        self.assertEqual(denied.status_code, 401)
        self.assertEqual(client.get("/v1/models").status_code, 401)

        allowed = client.post(
            "/v1/chat/completions", json=body,
            headers={"Authorization": "Bearer sekrit"})
        self.assertEqual(allowed.status_code, 200)

    def test_models_endpoint(self) -> None:
        _runtime, client = self._client(_text_llm())
        payload = client.get("/v1/models").json()
        self.assertEqual(payload["data"][0]["id"], "blender-agent")

    def test_no_user_message_rejected(self) -> None:
        _runtime, client = self._client(_text_llm())
        response = client.post("/v1/chat/completions", json={"messages": []})
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
