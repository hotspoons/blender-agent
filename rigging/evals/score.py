# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Scoring for agent skill-selection evals.

The agent harness runs each scenario (asset built into a fresh scene, the
natural-language request given to the agent with the rigging skills
available) and records the chain of skill calls + params it attempted.
Feed those records here:

    python score.py answers.json   # answers: {"scenario_id": {"chain": [...], "params": {...}}}

Two failure modes, tracked separately (fix descriptions for selection
failures; fix code for execution failures):

- selection: wrong skill chain for the request
- params: right chain, unreasonable parameters
"""

__all__ = (
    "score",
)

import json
import os
import sys

_SCENARIOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scenarios.json")


def _params_match(expected: dict, actual: dict) -> bool:
    for key, want in expected.items():
        got = actual.get(key)
        if isinstance(want, (int, float)) and isinstance(got, (int, float)):
            if abs(float(want) - float(got)) > 1e-6:
                return False
        elif want != got:
            return False
    return True


def score(answers: dict) -> dict:
    with open(_SCENARIOS, encoding="utf-8") as fh:
        scenarios = json.load(fh)["scenarios"]

    results = []
    for scenario in scenarios:
        answer = answers.get(scenario["id"])
        entry = {"id": scenario["id"], "selection_ok": False, "params_ok": None}
        if answer is not None:
            entry["selection_ok"] = answer.get("chain") == scenario["expected_chain"]
            checks = scenario.get("param_checks")
            if checks and entry["selection_ok"]:
                entry["params_ok"] = _params_match(checks, answer.get("params") or {})
        results.append(entry)

    n = len(results)
    selection = sum(1 for r in results if r["selection_ok"])
    with_params = [r for r in results if r["params_ok"] is not None]
    return {
        "n_scenarios": n,
        "selection_accuracy": selection / n if n else 0.0,
        "param_accuracy": (
            sum(1 for r in with_params if r["params_ok"]) / len(with_params)
            if with_params else None),
        "results": results,
    }


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8") as fh:
        print(json.dumps(score(json.load(fh)), indent=2))
