# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
The tool-drafting heartbeat: while a model streams a long tool-call
argument (no content tokens), the engine must emit throttled
``tool_drafting`` progress events so the UI can show activity.
"""

__all__ = ()

import asyncio
import importlib.util
import json
import os
import sys
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


@unittest.skipUnless(_HAS_AGENT_DEPS, "agent dependencies not installed (optional feature)")
class TestToolDrafting(unittest.TestCase):

    def test_drafting_events_during_argument_stream(self) -> None:
        from blagent.engine import AgentEngine
        from blagent.llm import LlmChunk, LlmClient
        from blagent.tools import ToolRegistry

        events = []

        async def emit(event):
            events.append(event)

        engine = AgentEngine(
            registry=ToolRegistry([]),
            media=None,
            system_prompt="",
            emit=emit,
            append_record=lambda record: None,
        )

        class SlowToolWriter(LlmClient):
            async def stream(self, request):
                yield LlmChunk(content="Writing code. ")
                yield LlmChunk(tool_calls=[{
                    "index": 0, "id": "call_1",
                    "function": {"name": "execute_blender_code", "arguments": ""},
                }])
                for i in range(4):
                    await asyncio.sleep(0.3)  # past the 0.25s throttle
                    yield LlmChunk(tool_calls=[{
                        "index": 0,
                        "function": {"arguments": json.dumps({"chunk": i}) + "\n" * 50},
                    }])

        content, calls = asyncio.new_event_loop().run_until_complete(
            engine._stream_round("s1", {"messages": []}, SlowToolWriter()))

        self.assertEqual(content, "Writing code. ")
        self.assertEqual(len(calls), 1)

        drafting = [e for e in events if e["type"] == "tool_drafting"]
        self.assertGreaterEqual(len(drafting), 2, events)
        self.assertEqual(drafting[-1]["name"], "execute_blender_code")
        self.assertEqual(drafting[-1]["n_calls"], 1)
        # Progress grows monotonically.
        chars = [e["chars"] for e in drafting]
        self.assertEqual(chars, sorted(chars))
        self.assertGreater(chars[-1], 0)

    def test_quiet_watchdog_reports_silent_stream(self) -> None:
        """
        Production gap (2026-06-12): vLLM's tool-call parsers buffer the
        whole call server-side, so NO deltas arrive while the model
        writes — drafting can't fire. The watchdog must report the
        silence itself.
        """
        from blagent.engine import AgentEngine
        from blagent.llm import LlmChunk, LlmClient
        from blagent.tools import ToolRegistry

        events = []

        async def emit(event):
            events.append(event)

        engine = AgentEngine(
            registry=ToolRegistry([]),
            media=None,
            system_prompt="",
            emit=emit,
            append_record=lambda record: None,
        )

        class BufferingBackend(LlmClient):
            async def stream(self, request):
                yield LlmChunk(content="Thinking. ")
                await asyncio.sleep(3.5)  # server-side buffering: dead air
                yield LlmChunk(tool_calls=[{
                    "index": 0, "id": "call_1",
                    "function": {"name": "execute_blender_code",
                                 "arguments": json.dumps({"code": "pass"})},
                }])

        content, calls = asyncio.new_event_loop().run_until_complete(
            engine._stream_round("s1", {"messages": []}, BufferingBackend()))

        self.assertEqual(content, "Thinking. ")
        self.assertEqual(len(calls), 1)
        quiet = [e for e in events if e["type"] == "llm_quiet"]
        self.assertGreaterEqual(len(quiet), 1, events)
        self.assertGreaterEqual(quiet[-1]["seconds"], 2.0)


if __name__ == "__main__":
    unittest.main()
