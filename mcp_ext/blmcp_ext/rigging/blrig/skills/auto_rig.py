# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
One-call rigging: inspect -> pick the top suggested skill -> diagnose ->
run -> verify, returning a compact staged transcript. The "just do it"
path for clear-cut scenes, so an agent need not orchestrate four calls
(and read four reports) when the routing is unambiguous. ``skill`` /
``params`` override the routing when the caller knows better; suggested
params still fill in as defaults.
"""

__all__ = (
    "auto",
)

from . import get_skill
from . import inspect_scene

# Lists longer than this are elided in the transcript (counts + a sample);
# the full reports remain available through the step-by-step verbs.
_BRIEF_LIST_CAP = 8


def _brief(value, depth: int = 0):
    """
    Shrink a report for the staged transcript: long lists become
    ``{"n": ..., "first": [...]}``; verify check-lists keep only the
    failures. Lossy by design — for reading, not round-tripping.
    """
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key == "checks" and isinstance(item, list):
                out[key] = {"n": len(item),
                            "failed": [c for c in item if not c.get("ok")]}
            else:
                out[key] = _brief(item, depth + 1)
        return out
    if isinstance(value, list):
        if depth > 0 and len(value) > _BRIEF_LIST_CAP:
            return {"n": len(value), "first": value[:3]}
        return [_brief(item, depth + 1) for item in value]
    return value


def _usable_default(value) -> bool:
    """
    Suggestion params are concrete except for documented placeholders
    ("<assembly rig>", ["ball", "..."]) — never merge those.
    """
    if isinstance(value, str) and value.startswith("<"):
        return False
    if isinstance(value, list) and "..." in value:
        return False
    return True


def auto(object_names: list[str], skill: str | None = None,
         params: dict | None = None,
         contact_tolerance: float | None = None) -> dict:
    """
    Inspect *object_names*, pick a skill (or use *skill*), then
    diagnose/run/verify it. Stops at the first failing stage with that
    stage's failure code (and ``suggest`` when the skill offers one);
    a failed run has already rolled back.
    """
    stages: list[dict] = []
    out: dict = {"ok": False, "stages": stages}

    report = inspect_scene.inspect(
        object_names, contact_tolerance=contact_tolerance)
    if report["missing"]:
        out["fail"] = "object_not_found"
        out["missing"] = report["missing"]
        return out

    merged = dict(params or {})
    suggestion_for = {s["skill"]: s for s in report["suggested"]}
    if skill is None:
        if not report["suggested"]:
            out["fail"] = "no_suggestion"
            out["detail"] = ("inspect produced no skill suggestion; pick one "
                             "yourself via rig('diagnose', ...) — see "
                             "skills_read('rigging-overview')")
            return out
        skill = report["suggested"][0]["skill"]
        reason = report["suggested"][0].get("reason", "")
    else:
        reason = "caller override"
    chosen = suggestion_for.get(skill)
    if chosen:
        for key, value in (chosen.get("params") or {}).items():
            if _usable_default(value):
                merged.setdefault(key, value)
    if contact_tolerance is not None:
        merged.setdefault("contact_tolerance", contact_tolerance)
    stages.append({"stage": "inspect", "picked": skill, "reason": reason,
                   "params": merged})

    out["skill"] = skill
    module = get_skill(skill)
    ctx = {"objects": list(object_names)}

    diag = module.diagnose(ctx, merged or None)
    stages.append({"stage": "diagnose", "report": _brief(diag)})
    if not diag.get("ok"):
        out["fail"] = diag.get("fail", "diagnose_failed")
        if "suggest" in diag:
            out["suggest"] = diag["suggest"]
        return out

    run_report = module.run(ctx, params=merged or None)
    stages.append({"stage": "run", "report": _brief(run_report)})
    if not run_report.get("ok"):
        out["fail"] = run_report.get("fail", "run_failed")
        if "suggest" in run_report:
            out["suggest"] = run_report["suggest"]
        return out

    verify_report = module.verify(ctx)
    stages.append({"stage": "verify", "report": _brief(verify_report)})
    out["ok"] = bool(verify_report.get("ok"))
    if not out["ok"]:
        out["fail"] = "verify_failed"
    out["armature"] = ctx.get("armature")
    return out
