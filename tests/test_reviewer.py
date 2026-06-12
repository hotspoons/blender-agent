# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
The budget reviewer in isolation: verdict parsing, its two
verification tools, and the bounded tool loop.
"""

__all__ = ()

import asyncio
import importlib.util
import json
import os
import sys
import unittest
from typing import Any

_REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _sub in ("agent", "mcp"):
    _path = os.path.join(_REPO_DIR, _sub)
    if _path not in sys.path:
        sys.path.insert(0, _path)

_HAS_AGENT_DEPS = all(
    importlib.util.find_spec(mod) is not None
    for mod in ("starlette", "httpx", "mcp", "blmcp")
)

_RECORDS = [
    {"role": "user", "content": "Rig the spider and animate a walk cycle."},
    {"role": "assistant", "content": "Working on it."},
    {"role": "tool", "name": "rig",
     "content": json.dumps({"status": "ok", "armature": "Rig.Assembly"})},
    {"role": "user", "content": "(synthetic nudge)", "synthetic": True},
    {"role": "user", "content": "Make the legs less mechanical."},
]


@unittest.skipUnless(_HAS_AGENT_DEPS, "agent dependencies not installed (optional feature)")
class TestVerdictParsing(unittest.TestCase):

    def _parse(self, text: str, max_grant: int = 8):
        from blagent.reviewer import _parse_verdict
        return _parse_verdict(text, max_grant)

    def test_clean_json(self) -> None:
        verdict, grant, summary = self._parse(
            '{"verdict": "continue", "grant_rounds": 4, "summary": "Solid evidence."}')
        self.assertEqual((verdict, grant, summary), ("continue", 4, "Solid evidence."))

    def test_wrapped_in_prose_and_fences(self) -> None:
        text = 'Here is my decision:\n```json\n{"verdict": "stop", ' \
               '"grant_rounds": 3, "summary": "No progress."}\n```\nDone.'
        verdict, grant, _summary = self._parse(text)
        self.assertEqual(verdict, "stop")
        self.assertEqual(grant, 0)  # stop always zeroes the grant

    def test_grant_clamped(self) -> None:
        _v, grant, _s = self._parse(
            '{"verdict": "continue", "grant_rounds": 999, "summary": "x"}', max_grant=8)
        self.assertEqual(grant, 8)

    def test_continue_without_grant_gets_half(self) -> None:
        _v, grant, _s = self._parse(
            '{"verdict": "continue", "grant_rounds": 0, "summary": "x"}', max_grant=8)
        self.assertEqual(grant, 4)

    def test_garbage_is_none(self) -> None:
        self.assertIsNone(self._parse("I think we should continue."))
        self.assertIsNone(self._parse("{not json}"))


@unittest.skipUnless(_HAS_AGENT_DEPS, "agent dependencies not installed (optional feature)")
class TestReviewerTools(unittest.TestCase):

    def test_user_requests_skip_synthetic(self) -> None:
        from blagent.reviewer import _get_user_requests
        requests = _get_user_requests(_RECORDS)
        self.assertEqual(len(requests), 2)
        self.assertIn("walk cycle", requests[0])
        self.assertNotIn("(synthetic nudge)", requests)

    def test_search_finds_tool_results(self) -> None:
        from blagent.reviewer import _search_history
        hits = _search_history(_RECORDS, "Rig.Assembly armature")
        self.assertTrue(hits)
        self.assertEqual(hits[0]["role"], "tool")
        self.assertIn("Rig.Assembly", hits[0]["snippet"])

    def test_search_empty_query(self) -> None:
        from blagent.reviewer import _search_history
        self.assertEqual(_search_history(_RECORDS, "!!"), [])


@unittest.skipUnless(_HAS_AGENT_DEPS, "agent dependencies not installed (optional feature)")
class TestReviewLoop(unittest.TestCase):

    def test_verifies_then_decides(self) -> None:
        """
        The reviewer calls search_history first, receives the hit, and
        only then renders its verdict — the checks land in the detail.
        """
        from blagent.llm import LlmChunk, LlmClient
        from blagent.reviewer import review_budget

        class Skeptic(LlmClient):
            async def stream(self, request: dict[str, Any]) -> Any:
                tool_replies = [m for m in request["messages"] if m["role"] == "tool"]
                if not tool_replies:
                    yield LlmChunk(tool_calls=[{
                        "index": 0, "id": "rc1",
                        "function": {"name": "search_history",
                                     "arguments": json.dumps({"query": "Rig.Assembly"})},
                    }])
                    return
                assert "Rig.Assembly" in str(tool_replies[-1]["content"])
                yield LlmChunk(content=json.dumps({
                    "verdict": "continue", "grant_rounds": 3,
                    "summary": "The armature exists as claimed; the walk cycle remains.",
                }))

        result = asyncio.new_event_loop().run_until_complete(review_budget(
            Skeptic(), "m", "Objective: rig + walk. Evidence: Rig.Assembly built.",
            _RECORDS, max_grant=8))
        self.assertEqual(result.verdict, "continue")
        self.assertEqual(result.grant_rounds, 3)
        self.assertEqual(result.detail["checks"][0]["tool"], "search_history")

    def test_never_decides_fails_safe(self) -> None:
        """
        A reviewer that only ever calls tools runs out of rounds, gets
        one tool-less final request, and an unparseable answer = stop.
        """
        from blagent.llm import LlmChunk, LlmClient
        from blagent.reviewer import review_budget

        class Waffler(LlmClient):
            async def stream(self, request: dict[str, Any]) -> Any:
                if request.get("tools"):
                    yield LlmChunk(tool_calls=[{
                        "index": 0, "id": "rcx",
                        "function": {"name": "get_user_requests", "arguments": "{}"},
                    }])
                else:
                    yield LlmChunk(content="hmm, hard to say")

        result = asyncio.new_event_loop().run_until_complete(review_budget(
            Waffler(), "m", "report", _RECORDS, max_grant=8))
        self.assertEqual(result.verdict, "stop")
        self.assertEqual(result.grant_rounds, 0)


if __name__ == "__main__":
    unittest.main()
