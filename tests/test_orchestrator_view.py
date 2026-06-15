# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the backend orchestrator-view reducer (orchestrator_view.py)."""

__all__ = ()

import importlib
import os
import sys
import unittest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _mod():
    for p in (os.path.join(_REPO, "mcp"), os.path.join(_REPO, "agent")):
        if p not in sys.path:
            sys.path.insert(0, p)
    return importlib.import_module("blagent.orchestrator_view")


class TestOrchestratorView(unittest.TestCase):

    def test_full_run_reduces_to_expected_snapshot(self):
        V = _mod().OrchestratorView
        v = V()
        # round start with objectives
        v.apply({"type": "autonomy_round_start", "session_id": "run", "round": 0,
                 "objectives": [{"id": "o0", "text": "Goal A", "acceptance": "done A", "status": "unmet"}]})
        # worker spawns
        self.assertTrue(v.apply({"type": "agent_spawned", "session_id": "run",
                                 "agent_id": "run:w:t0", "role": "worker", "task": "do A", "objective_id": "o0"}))
        snap = v.snapshot()
        self.assertEqual(snap["agentOrder"], ["run:w:t0"])
        self.assertEqual(snap["agents"]["run:w:t0"]["state"], "running")
        self.assertEqual(snap["currentRound"], 0)

        # worker activity (parent_session_id tags it as the worker's stream)
        v.apply({"type": "token", "session_id": "run:w:t0", "parent_session_id": "run", "text": "thinking "})
        self.assertEqual(v.snapshot()["agents"]["run:w:t0"]["stream"], "thinking ")
        v.apply({"type": "tool_status", "session_id": "run:w:t0", "parent_session_id": "run",
                 "call_id": "c1", "name": "get_objects_summary", "arguments": "{}", "state": "running"})
        v.apply({"type": "assistant_done", "session_id": "run:w:t0", "parent_session_id": "run",
                 "content": "did it", "tool_calls": []})
        ag = v.snapshot()["agents"]["run:w:t0"]
        self.assertEqual(ag["stream"], "")                       # cleared on assistant_done
        self.assertEqual(ag["calls"]["c1"]["name"], "get_objects_summary")
        kinds = [e["kind"] for e in ag["timeline"]]
        self.assertIn("call", kinds)
        self.assertIn("text", kinds)

        # done with proof
        v.apply({"type": "agent_done", "session_id": "run", "agent_id": "run:w:t0",
                 "role": "worker", "ok": True, "proof": "PROOF"})
        ag = v.snapshot()["agents"]["run:w:t0"]
        self.assertEqual(ag["state"], "done")
        self.assertEqual(ag["proof"], "PROOF")

        # round done + run done
        v.apply({"type": "autonomy_round_done", "session_id": "run", "round": 0,
                 "all_met": True, "verdicts": [{"objective_id": "o0", "met": True}]})
        v.apply({"type": "autonomy_done", "session_id": "run", "all_met": True, "rounds": 1})
        snap = v.snapshot()
        self.assertEqual(len(snap["rounds"]), 1)
        self.assertEqual(snap["done"], {"paused": False, "allMet": True, "rounds": 1})

    def test_qa_review_spawns_agent_and_annotates_worker(self):
        V = _mod().OrchestratorView
        v = V()
        v.apply({"type": "agent_spawned", "session_id": "run", "agent_id": "run:w:t0",
                 "role": "worker", "task": "do A", "objective_id": "o0"})
        v.apply({"type": "agent_done", "session_id": "run", "agent_id": "run:w:t0",
                 "role": "worker", "ok": True, "proof": "PROOF"})
        # The dedicated QA agent is a first-class spawned/done agent...
        v.apply({"type": "agent_spawned", "session_id": "run", "agent_id": "run:qa:t0",
                 "role": "qa", "task": "QA review — do A", "objective_id": "o0",
                 "reviews": "run:w:t0"})
        v.apply({"type": "agent_done", "session_id": "run", "agent_id": "run:qa:t0",
                 "role": "qa", "ok": False, "proof": "missing X"})
        # ...and its verdict is annotated onto the worker it reviewed.
        self.assertTrue(v.apply({"type": "worker_review", "session_id": "run",
                                 "agent_id": "run:w:t0", "passed": False,
                                 "note": "missing X", "by": "run:qa:t0"}))
        snap = v.snapshot()
        self.assertIn("run:qa:t0", snap["agentOrder"])
        self.assertEqual(snap["agents"]["run:qa:t0"]["role"], "qa")
        self.assertEqual(snap["agents"]["run:qa:t0"]["reviews"], "run:w:t0")
        review = snap["agents"]["run:w:t0"]["review"]
        self.assertEqual(review, {"passed": False, "note": "missing X", "by": "run:qa:t0"})

    def test_worker_review_for_unknown_worker_is_ignored(self):
        V = _mod().OrchestratorView
        v = V()
        self.assertFalse(v.apply({"type": "worker_review", "session_id": "run",
                                  "agent_id": "nope", "passed": True, "note": "x"}))

    def test_worker_event_for_unknown_agent_is_ignored(self):
        V = _mod().OrchestratorView
        v = V()
        # no agent_spawned yet -> worker token must not crash or create state
        self.assertFalse(v.apply({"type": "token", "session_id": "run:w:zz",
                                  "parent_session_id": "run", "text": "x"}))
        self.assertEqual(v.snapshot()["agents"], {})

    def test_swarm_gather_and_audit(self):
        V = _mod().OrchestratorView
        v = V()
        v.apply({"type": "swarm_gathered", "session_id": "run", "master": "m.blend",
                 "components": ["a", "b"], "objects": ["Cube"]})
        v.apply({"type": "autonomy_audit", "session_id": "run", "passed": False,
                 "summary": "overclaim", "overclaims": ["o0"], "verdicts": []})
        snap = v.snapshot()
        self.assertEqual(snap["gathered"]["master"], "m.blend")
        self.assertFalse(snap["audit"]["passed"])
        self.assertEqual(snap["audit"]["overclaims"], ["o0"])

    def test_reset(self):
        V = _mod().OrchestratorView
        v = V()
        v.apply({"type": "agent_spawned", "session_id": "run", "agent_id": "a", "role": "worker"})
        v.reset()
        self.assertEqual(v.snapshot()["agentOrder"], [])
        self.assertEqual(v.snapshot()["agents"], {})


if __name__ == "__main__":
    unittest.main()
