# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
The HTTP transport for the ToolBackend boundary, dogfooded in-process: the
reference handler (serve_backend) re-exposes a PythonToolBackend over the REST
contract, and HttpToolBackend drives it through an in-memory ASGI client (no
real network). Proves the harness is transport-blind.

    python -m unittest tests.test_http_backend -v
"""

__all__ = ()

import asyncio
import importlib.util
import os
import sys
import unittest
from typing import Any

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_HAS_DEPS = all(importlib.util.find_spec(m) is not None
                for m in ("starlette", "httpx", "mcp", "blmcp"))


def _imp() -> Any:
    for p in (os.path.join(_REPO, "mcp"), os.path.join(_REPO, "agent")):
        if p not in sys.path:
            sys.path.insert(0, p)
    import blagent.http_backend as h
    return h


def _run(coro: Any) -> Any:
    return asyncio.new_event_loop().run_until_complete(coro)


def _client(app: Any) -> Any:
    import httpx
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@unittest.skipUnless(_HAS_DEPS, "agent dependencies not installed (optional feature)")
class TestHttpToolBackend(unittest.TestCase):

    def _echo_backend(self) -> Any:
        from blagent.backend import PythonToolBackend
        from blagent.tools import Tool, ToolError, ToolResult

        seen: list[dict] = []

        class Echo(Tool):
            name = "echo"
            description = "echo a message"
            read_only = True

            def input_schema(self) -> dict:
                return {"type": "object", "properties": {"msg": {"type": "string"}}}

            async def call(self, ctx: Any, args: dict) -> Any:
                seen.append(args)
                if args.get("msg") == "boom":
                    raise ToolError("kaboom")
                return ToolResult(summary="said " + str(args.get("msg", "")),
                                  data={"echo": args.get("msg")})

        async def probe(session_id: str) -> str:
            return "scene: 3 cubes (session %s)" % session_id

        return PythonToolBackend([Echo()], probe=probe), seen

    def test_round_trips_the_full_contract(self) -> None:
        h = _imp()
        py, seen = self._echo_backend()
        app = h.serve_backend(py)

        async def scenario():
            client = _client(app)
            be = h.HttpToolBackend("http://test", client=client)
            specs = await be.list_tools()
            ok = await be.call_tool("echo", {"msg": "hi"}, session_id="s1")
            err = await be.call_tool("echo", {"msg": "boom"}, session_id="s1")
            unknown = await be.call_tool("nope", {}, session_id="s1")
            await be.open()                      # fetches + caches capabilities
            caps = be.capabilities()
            state = await be.state_probe(session_id="s1")
            await client.aclose()
            return specs, ok, err, unknown, caps, state

        specs, ok, err, unknown, caps, state = _run(scenario())
        self.assertEqual([s.name for s in specs], ["echo"])
        self.assertTrue(specs[0].read_only)
        self.assertEqual(specs[0].input_schema["properties"]["msg"]["type"], "string")
        self.assertEqual(ok.status, "ok")
        self.assertIn("said hi", ok.summary)
        self.assertEqual(ok.data["echo"], "hi")
        self.assertEqual(err.status, "error")
        self.assertIn("kaboom", err.error)
        self.assertEqual(unknown.status, "error")           # unknown tool -> error, not crash
        self.assertIn("probe", caps)
        self.assertIn("media", caps)
        self.assertIn("3 cubes", state)
        self.assertIn({"msg": "hi"}, seen)                  # the call really reached the tool

    def test_registry_from_backend_over_http(self) -> None:
        h = _imp()
        from blagent.backend import registry_from_backend
        py, _ = self._echo_backend()
        app = h.serve_backend(py)

        async def scenario():
            client = _client(app)
            be = h.HttpToolBackend("http://test", client=client)
            reg = await registry_from_backend(be)
            tool = reg.get("echo")
            # The adapted tool calls straight through the transport.
            from blagent.tools import ToolContext
            result = await tool.call(ToolContext(media=None, session_id="s1"), {"msg": "yo"})
            await client.aclose()
            return [t.name for t in reg], result

        names, result = _run(scenario())
        self.assertIn("echo", names)
        self.assertIn("said yo", result.summary)

    def test_media_bytes_round_trip(self) -> None:
        h = _imp()
        from blagent.backend import _DefaultBackendMixin, ToolSpec

        class MediaBackend(_DefaultBackendMixin):
            async def list_tools(self):
                return [ToolSpec(name="noop", description="", input_schema={})]

            async def call_tool(self, name, args, *, session_id, media=None):
                from blagent.backend import ToolCallResult
                return ToolCallResult(summary="ok")

            def capabilities(self):
                return {"media"}

            async def read_media(self, media_id):
                return b"PNGDATA-" + media_id.encode(), "image/png"

        app = h.serve_backend(MediaBackend())

        async def scenario():
            client = _client(app)
            be = h.HttpToolBackend("http://test", client=client)
            got = await be.read_media("img7")
            missing = await be.read_media("")  # empty path -> route miss / 404-ish
            await client.aclose()
            return got, missing

        got, _missing = _run(scenario())
        self.assertIsNotNone(got)
        data, mime = got
        self.assertEqual(data, b"PNGDATA-img7")
        self.assertEqual(mime, "image/png")

    def test_auth_required_when_key_set(self) -> None:
        h = _imp()
        py, _ = self._echo_backend()
        app = h.serve_backend(py, api_key="secret")

        async def scenario():
            # No key -> unauthorized; correct key -> works.
            no_key = h.HttpToolBackend("http://test", client=_client(app))
            with_key = h.HttpToolBackend("http://test", api_key="secret", client=_client(app))
            bad = await no_key.call_tool("echo", {"msg": "x"}, session_id="s1")
            good = await with_key.call_tool("echo", {"msg": "x"}, session_id="s1")
            return bad, good

        bad, good = _run(scenario())
        self.assertEqual(bad.status, "error")
        self.assertEqual(good.status, "ok")

    def test_healthz_and_openapi_served(self) -> None:
        h = _imp()
        py, _ = self._echo_backend()
        app = h.serve_backend(py)

        async def scenario():
            client = _client(app)
            health = await client.get("http://test/healthz")
            schema = await client.get("http://test/openapi.json")
            await client.aclose()
            return health.json(), schema.json()

        health, schema = _run(scenario())
        self.assertEqual(health["status"], "ok")
        self.assertEqual(schema["openapi"], "3.1.0")
        self.assertIn("/tools/{name}", schema["paths"])


if __name__ == "__main__":
    unittest.main()
