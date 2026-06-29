# SPDX-FileCopyrightText: 2026 agentcore contributors
#
# SPDX-License-Identifier: MIT OR Apache-2.0

"""
Backend-owned reduction of the orchestrator/swarm event stream into the view
the UI renders. ALL the distributed-state complexity lives here, in Python —
the frontend is a pure projection of ``snapshot()`` and never reduces events
itself. A run feeds events through ``apply()``; the runtime emits ``snapshot()``
as an ``autonomy_view`` message and persists it, so reload is just "render the
snapshot" — no event replay, no JS reducer.

The snapshot shape is what ``chat-stage`` renders (objectives, agents keyed by
id with their timeline/calls/proof/media, agentOrder, rounds, gathered, done,
audit). Worker activity events are tagged with ``parent_session_id`` (their
``session_id`` is the worker id); run-level events carry the run's session id.
"""

__all__ = ("OrchestratorView",)

from typing import Any


class OrchestratorView:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.prompts: list[str] = []
        self.objectives: list[dict[str, Any]] = []
        self.agents: dict[str, dict[str, Any]] = {}
        self.agent_order: list[str] = []
        self.rounds: list[dict[str, Any]] = []
        self.gathered: dict[str, Any] | None = None
        self.done: dict[str, Any] | None = None
        self.audit: dict[str, Any] | None = None
        self.planner: dict[str, Any] | None = None
        self.current_round: int = 0

    def snapshot(self) -> dict[str, Any]:
        return {
            "prompts": self.prompts,
            "objectives": self.objectives,
            "agents": self.agents,
            "agentOrder": self.agent_order,
            "rounds": self.rounds,
            "gathered": self.gathered,
            "done": self.done,
            "audit": self.audit,
            "planner": self.planner,
            "currentRound": self.current_round,
            "draft": None,
        }

    def mark_stopped(self) -> None:
        """Finalize a stopped/aborted run: no agent stays 'running' (stale stop
        controls), and the planner card goes inactive."""
        for ag in self.agents.values():
            if ag.get("state") == "running":
                ag["state"] = "done"
                ag["ok"] = False
                ag["stopping"] = False
        if self.planner and self.planner.get("active"):
            self.planner["active"] = False
        if self.done is None:
            self.done = {"paused": False, "allMet": False, "rounds": self.current_round + 1,
                         "stopped": True}

    def apply(self, ev: dict[str, Any]) -> bool:
        """Fold one event into the view. Returns True if the view changed."""
        t = ev.get("type")
        # Worker sub-agent activity (its own event stream).
        if ev.get("parent_session_id") and ev.get("session_id") in self.agents:
            return self._worker(ev)

        if t == "autonomy_goal":
            self.prompts = list(ev.get("prompts") or [])
            return True
        if t == "autonomy_round_start":
            if ev.get("objectives") is not None:
                self.objectives = ev["objectives"]
            self.current_round = int(ev.get("round", self.current_round) or 0)
            self.planner = None      # fresh planner panel each round
            return True
        if t == "planner_stream":
            phase = ev.get("phase", "plan")
            state = ev.get("state")
            if state == "start" or self.planner is None or self.planner.get("phase") != phase:
                self.planner = {"phase": phase, "round": self.current_round,
                                "reasoning": "", "content": "", "active": True}
            if state != "start":
                self.planner["reasoning"] += str(ev.get("reasoning", "") or "")
                self.planner["content"] += str(ev.get("content", "") or "")
            if state == "done":
                self.planner["active"] = False
            return True
        if t == "objectives_update":
            if ev.get("objectives") is not None:
                self.objectives = ev["objectives"]
                return True
            return False
        if t == "autonomy_round_done":
            self.rounds.append({"round": ev.get("round"),
                                "verdicts": ev.get("verdicts") or [],
                                "allMet": bool(ev.get("all_met"))})
            return True
        if t == "agent_spawned":
            aid = str(ev.get("agent_id", ""))
            self.agents[aid] = {
                "id": aid, "role": ev.get("role", "worker"), "task": ev.get("task", ""),
                "objectiveId": ev.get("objective_id", ""), "state": "running",
                "proof": "", "ok": None, "timeline": [], "calls": {}, "stream": "",
                "media": [], "queued": None, "stopping": False,
                "reviews": ev.get("reviews"),   # qa agent -> worker id it reviews
                "dependsOn": ev.get("depends_on") or [],   # DAG edges (agent ids)
                "round": None if ev.get("role") == "gather" else self.current_round,
            }
            if aid not in self.agent_order:
                self.agent_order.append(aid)
            return True
        if t == "agent_done":
            aid = str(ev.get("agent_id", ""))
            ag = self.agents.get(aid) or {
                "id": aid, "role": ev.get("role", "worker"),
                "timeline": [], "calls": {}, "media": []}
            ag.update({"state": "done", "ok": ev.get("ok") is not False,
                       "proof": ev.get("proof", ""),
                       "artifacts": ev.get("artifacts") or ag.get("artifacts") or [],
                       "ref": ev.get("ref") or ag.get("ref")})
            self.agents[aid] = ag
            if aid not in self.agent_order:
                self.agent_order.append(aid)
            return True
        if t == "worker_review":
            ag = self.agents.get(str(ev.get("agent_id", "")))
            if ag is not None:
                ag["review"] = {"passed": bool(ev.get("passed")),
                                "note": ev.get("note", ""), "qa": ev.get("qa", ""),
                                "attempt": ev.get("attempt", 0),
                                "stopped": bool(ev.get("stopped"))}
                return True
            return False
        if t == "swarm_gathered":
            self.gathered = {"master": ev.get("master"),
                             "components": ev.get("components") or [],
                             "objects": ev.get("objects") or []}
            return True
        if t == "autonomy_audit":
            self.audit = {"passed": bool(ev.get("passed")), "summary": ev.get("summary", ""),
                          "overclaims": ev.get("overclaims") or [],
                          "verdicts": ev.get("verdicts") or []}
            return True
        if t in ("autonomy_done", "autonomy_paused"):
            if ev.get("objectives") is not None:
                self.objectives = ev["objectives"]
            self.done = {"paused": t == "autonomy_paused", "allMet": bool(ev.get("all_met")),
                         "rounds": ev.get("rounds", 0)}
            return True
        return False

    def _worker(self, ev: dict[str, Any]) -> bool:
        ag = self.agents[ev["session_id"]]
        t = ev.get("type")

        def push_call(cid: str) -> None:
            if not any(e.get("kind") == "call" and e.get("call_id") == cid
                       for e in ag["timeline"]):
                ag["timeline"].append({"kind": "call", "call_id": cid})

        if t == "token":
            ag["stream"] = ag.get("stream", "") + str(ev.get("text", ""))
            return True
        if t == "assistant_done":
            if str(ev.get("content", "")).strip():
                ag["timeline"].append({"kind": "text", "content": ev["content"]})
            for tc in ev.get("tool_calls") or []:
                push_call(tc.get("id"))
            ag["stream"] = ""
            return True
        if t == "tool_status":
            cid = ev.get("call_id")
            ex = ag["calls"].get(cid, {})
            ag["calls"][cid] = {
                **ex, "name": ev.get("name"), "arguments": ev.get("arguments"),
                "state": ev.get("state"), "summary": ev.get("summary") or ex.get("summary", ""),
                "media_ids": ev.get("media_ids") or ex.get("media_ids") or []}
            push_call(cid)
            return True
        if t == "worker_question":
            ag["timeline"].append({"kind": "question", "content": ev.get("question", ""),
                                   "options": ev.get("options") or []})
            return True
        if t == "worker_question_answered":
            ag["timeline"].append({"kind": "answer", "content": ev.get("answer", ""),
                                   "source": ev.get("source", "orchestrator")})
            return True
        if t == "worker_media":
            ag.setdefault("media", []).append({"id": ev.get("media_id"), "data_url": ev.get("data_url")})
            return True
        if t == "injected":
            ag["timeline"].append({"kind": "injected", "content": ev.get("content", "")})
            ag["queued"] = None
            return True
        if t == "turn_done":
            ag["stream"] = ""
            return True
        return False
