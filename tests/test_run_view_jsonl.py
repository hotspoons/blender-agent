# SPDX-License-Identifier: GPL-3.0-or-later
"""
Per-run orchestrator views persist as greppable JSONL (one line per run-meta /
objective / agent / timeline entry / tool call) instead of a single JSON blob.
This pins the WRITER/READER round-trip as lossless — completed runs are
projected to the UI straight from these files, so any loss would corrupt
history.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mcp"))

from agentcore.runtime import AgentRuntime  # noqa: E402


def _sample_snapshot():
    return {
        "prompts": ["Build a rear wing"],
        "objectives": [
            {"id": "obj-0", "text": "Model main plane", "acceptance": "MESH exists", "status": "met"},
            {"id": "obj-1", "text": "Add endplates — unicode é", "status": "unmet"},
        ],
        "agents": {
            "s:w:task-1": {
                "id": "s:w:task-1", "role": "worker", "task": "make it", "state": "done", "ok": True,
                "proof": "done", "stream": "partial", "media": [], "round": 0,
                "timeline": [
                    {"kind": "text", "content": "Let me start by calling welcome."},
                    {"kind": "call", "call_id": "c1"},
                ],
                "calls": {"c1": {"name": "welcome", "args": {}, "result": {"ok": True}}},
            },
            "s:qa:task-1:0": {  # an agent with EMPTY timeline + no calls key (edge cases)
                "id": "s:qa:task-1:0", "role": "qa", "state": "done", "ok": True,
                "timeline": [], "calls": {},
            },
        },
        "agentOrder": ["s:w:task-1", "s:qa:task-1:0"],
        "rounds": [], "gathered": None, "done": {"allMet": True, "rounds": 1},
        "audit": None, "planner": None, "currentRound": 0, "draft": None,
    }


def test_jsonl_round_trip_is_lossless():
    snap = _sample_snapshot()
    text = AgentRuntime._run_view_to_jsonl(snap)
    back = AgentRuntime._run_view_from_jsonl(text)
    assert back == json.loads(json.dumps(snap, default=str))


def test_jsonl_is_one_record_per_line_and_greppable():
    snap = _sample_snapshot()
    text = AgentRuntime._run_view_to_jsonl(snap)
    lines = [ln for ln in text.splitlines() if ln.strip()]
    # every line is independently valid JSON with a "k" tag
    kinds = [json.loads(ln)["k"] for ln in lines]
    assert kinds[0] == "meta"  # run meta first
    assert kinds.count("objective") == 2
    assert kinds.count("agent") == 2
    # the welcome tool call is isolated on its own line, not buried in a blob
    welcome_lines = [ln for ln in lines if '"welcome"' in ln]
    assert len(welcome_lines) == 1
    assert json.loads(welcome_lines[0])["k"] == "call"


def test_empty_collections_preserved():
    # An agent with empty timeline/calls must come back with those exact empties.
    snap = _sample_snapshot()
    back = AgentRuntime._run_view_from_jsonl(AgentRuntime._run_view_to_jsonl(snap))
    assert back["agents"]["s:qa:task-1:0"]["timeline"] == []
    assert back["agents"]["s:qa:task-1:0"]["calls"] == {}


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
