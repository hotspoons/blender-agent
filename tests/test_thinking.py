# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the chain-of-thought codec (agent/blagent/thinking.py)."""

__all__ = ()

import importlib
import os
import sys
import unittest

_REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _mod():
    for p in (os.path.join(_REPO_DIR, "mcp"), os.path.join(_REPO_DIR, "agent")):
        if p not in sys.path:
            sys.path.insert(0, p)
    return importlib.import_module("agentcore.thinking")


class TestToContext(unittest.TestCase):
    def test_strips_think_block(self):
        m = _mod()
        self.assertEqual(m.to_context("<think>plan</think>answer"), "answer")
        self.assertEqual(m.to_context("<thinking>x</thinking>  hi "), "hi")
        self.assertEqual(m.to_context("no tags here"), "no tags here")
        # unterminated runs to end
        self.assertEqual(m.to_context("before <think>dangling"), "before")


class TestToDisplay(unittest.TestCase):
    def test_folds_reasoning(self):
        m = _mod()
        self.assertEqual(m.to_display("", "answer"), "answer")
        out = m.to_display("plan", "answer")
        self.assertIn("<think>", out)
        self.assertIn("plan", out)
        self.assertTrue(out.strip().endswith("answer"))


class TestDecoderServerChannel(unittest.TestCase):
    def test_reasoning_then_content(self):
        m = _mod()
        d = m.ThinkingDecoder()
        ev = []
        ev += d.feed(reasoning="I think ")
        ev += d.feed(reasoning="hard.")
        ev += d.feed(content="The answer.")
        ev += d.finish()
        self.assertEqual(d.reasoning, "I think hard.")
        self.assertEqual(d.content, "The answer.")
        # display reconstructs a <think> block + clean answer
        self.assertIn("<think>", d.display())
        self.assertIn("The answer.", d.display())
        channels = [c for c, _ in ev]
        self.assertIn("reasoning", channels)
        self.assertIn("content", channels)


class TestDecoderInlineTags(unittest.TestCase):
    def test_inline_think_parsed_out(self):
        m = _mod()
        d = m.ThinkingDecoder()
        d.feed(content="<think>secret plan</think>visible answer")
        d.finish()
        self.assertEqual(d.reasoning, "secret plan")
        self.assertEqual(d.content, "visible answer")

    def test_tag_split_across_deltas(self):
        m = _mod()
        d = m.ThinkingDecoder()
        # "<thi" + "nk>r</thin" + "k>ans" — tags split mid-stream
        for piece in ["<thi", "nk>r</thin", "k>ans"]:
            d.feed(content=piece)
        d.finish()
        self.assertEqual(d.reasoning, "r")
        self.assertEqual(d.content, "ans")

    def test_unterminated_think_stays_reasoning(self):
        m = _mod()
        d = m.ThinkingDecoder()
        d.feed(content="visible <think>dangling thought")
        d.finish()
        self.assertEqual(d.content, "visible ")
        self.assertEqual(d.reasoning, "dangling thought")

    def test_plain_content_no_tags(self):
        m = _mod()
        d = m.ThinkingDecoder()
        d.feed(content="just an answer")
        d.finish()
        self.assertEqual(d.content, "just an answer")
        self.assertEqual(d.reasoning, "")


class TestDecoderMixedSources(unittest.TestCase):
    def test_server_reasoning_plus_inline_in_content(self):
        # A server reasoning channel AND inline tags in content both feed the
        # same reasoning trace; content stays clean.
        m = _mod()
        d = m.ThinkingDecoder()
        d.feed(reasoning="server-side thought ")
        d.feed(content="<think>inline thought</think>final")
        d.finish()
        self.assertIn("server-side thought", d.reasoning)
        self.assertIn("inline thought", d.reasoning)
        self.assertEqual(d.content, "final")


if __name__ == "__main__":
    unittest.main()
