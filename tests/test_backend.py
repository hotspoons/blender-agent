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
    return importlib.import_module("blagent.backend")


def _run(coro: Any) -> Any:
    return asyncio.new_event_loop().run_until_complete(coro)


@unittest.skipUnless(_HAS_AGENT_DEPS, "agent dependencies not installed (optional feature)")
class TestPythonToolBackend(unittest.TestCase):

    def _tools(self) -> Any:
        from blagent.tools import Tool, ToolError, ToolResult

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
        from blagent.tools import ToolContext, ToolError
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
        from blagent.tools import Tool, ToolResult

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
        from blagent.tools import Tool, ToolContext, ToolResult

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
    from blagent.media import MediaLibrary
    return MediaLibrary(tempfile.mkdtemp(prefix="media_"))


if __name__ == "__main__":
    unittest.main()
