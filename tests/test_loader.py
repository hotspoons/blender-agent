# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the YAML agent loader (agent/blagent/loader.py)."""

__all__ = ()

import asyncio
import importlib.util
import os
import sys
import tempfile
import unittest

_REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_HAS_AGENT_DEPS = all(
    importlib.util.find_spec(m) is not None for m in ("starlette", "httpx", "mcp", "blmcp"))


def _prep_path() -> None:
    # tests dir too, so the YAML's "test_loader:fake_backend_factory" resolves.
    for p in (os.path.join(_REPO_DIR, "mcp"), os.path.join(_REPO_DIR, "agent"),
              os.path.dirname(os.path.abspath(__file__))):
        if p not in sys.path:
            sys.path.insert(0, p)


def _run(coro):  # noqa: ANN001
    return asyncio.new_event_loop().run_until_complete(coro)


# A module-level factory referenced by the test YAML (module:callable).
def fake_backend_factory(**options):  # noqa: ANN001, ANN003
    from agentcore.backend import PythonToolBackend
    from agentcore.tools import Tool, ToolResult

    class Ping(Tool):
        name = "ping"
        description = "ping"

        def input_schema(self):
            return {"type": "object", "properties": {}}

        async def call(self, ctx, args):  # noqa: ANN001
            return ToolResult(summary="pong")

    return PythonToolBackend([Ping()])


_YAML = """
profile:
  name: "Test Agent"
  noun: "project"
  chat_field_prefix: "test"
  ui:
    title: "Test Agent"
    brand: {{ word: "Test", rest: " Bot" }}
    welcome: {{ word: "Test", rest: " Bot", body: "hi", hint: "try x" }}
    composer_placeholder: "ask test…"
llm:
  endpoint: "http://example.invalid/v1"
  model: "test-model"
autonomy:
  level: "orchestrator"
  max_rounds: 3
backend:
  type: "python"
  factory: "test_loader:fake_backend_factory"
  options: {{}}
"""


@unittest.skipUnless(_HAS_AGENT_DEPS, "agent dependencies not installed (optional feature)")
class TestLoader(unittest.TestCase):

    def _write_yaml(self, body: str) -> str:
        d = tempfile.mkdtemp(prefix="agentcfg_")
        path = os.path.join(d, "agent.yaml")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)
        return path

    def test_load_agent_python_backend(self) -> None:
        _prep_path()
        from blagent.loader import load_agent
        from agentcore.backend import PythonToolBackend
        path = self._write_yaml(_YAML.format())
        rt = _run(load_agent(path, data_dir=tempfile.mkdtemp(prefix="agentdata_")))

        # Profile applied from YAML.
        ui = rt.public_ui_profile()
        self.assertEqual(ui["title"], "Test Agent")
        self.assertEqual(ui["brand"]["word"], "Test")
        self.assertEqual(rt.profile.chat_field_prefix, "test")
        self.assertEqual(rt.profile.noun, "project")
        # LLM + autonomy config seeded into the store.
        self.assertEqual(rt.store.config.endpoint, "http://example.invalid/v1")
        self.assertEqual(rt.store.config.model, "test-model")
        self.assertFalse(rt.store.config.use_local_llm)
        self.assertEqual(rt.store.config.autonomy_level, "orchestrator")
        # Backend wired; its tool + core tools present.
        self.assertIsInstance(rt.backend, PythonToolBackend)
        names = {t.name for t in rt.registry}
        self.assertIn("ping", names)
        self.assertTrue({"skills", "ask_user"} <= names)

    def test_unknown_backend_type_raises(self) -> None:
        _prep_path()
        from blagent.loader import load_agent
        bad = _YAML.format().replace('type: "python"', 'type: "carrier-pigeon"')
        path = self._write_yaml(bad)
        with self.assertRaises(ValueError):
            _run(load_agent(path, data_dir=tempfile.mkdtemp(prefix="agentdata_")))

    def test_blender_make_backend_factory(self) -> None:
        # The real Blender factory lists the blmcp tool surface (no running
        # Blender needed just to enumerate) and wires the scene probe.
        _prep_path()
        from blagent.blender_tools import make_backend
        from agentcore.backend import PythonToolBackend
        backend = _run(make_backend())
        self.assertIsInstance(backend, PythonToolBackend)
        self.assertIn("probe", backend.capabilities())
        names = {s.name for s in _run(backend.list_tools())}
        self.assertIn("scene", names)


if __name__ == "__main__":
    unittest.main()
