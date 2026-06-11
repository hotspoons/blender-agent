# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Shared skill-contract machinery: structured reports, clean rollback,
failure logging, and common verify checks.
"""

__all__ = (
    "Rollback",
    "check",
    "fail",
    "log_failure",
    "ok",
    "resolve_objects",
    "run_with_rollback",
    "scene_snapshot",
    "scene_restore",
    "verify_common",
)

import json
import os
import tempfile
import time
import traceback

import bpy

from .. import standard

# BLRIG_LOG_DIR redirects failure logs (the test runner points it at a temp
# dir so deliberate test failures don't pollute the production log).
_LOGS_DIR = os.environ.get("BLRIG_LOG_DIR") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "logs")


# -----------------------------------------------------------------------------
# Reports


def ok(**extra) -> dict:
    report = {"ok": True}
    report.update(extra)
    return report


def fail(code: str, suggest: str | None = None, **extra) -> dict:
    """
    Structured failure the agent can act on, e.g.
    ``fail("asymmetric", suggest="rig_rigid_assembly", asymmetry_pct=12.0)``.
    """
    report = {"ok": False, "fail": code}
    if suggest is not None:
        report["suggest"] = suggest
    report.update(extra)
    return report


def check(name: str, passed: bool, detail="") -> dict:
    return {"name": name, "ok": bool(passed), "detail": detail}


def log_failure(skill: str, stage: str, report: dict) -> None:
    """
    Append a structured failure record to ``logs/failures.jsonl``
    (append-only; every production failure should become a corpus asset).
    """
    os.makedirs(_LOGS_DIR, exist_ok=True)
    record = {
        "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "skill": skill,
        "stage": stage,
        "blend": bpy.data.filepath or "<unsaved>",
        "report": report,
    }
    with open(os.path.join(_LOGS_DIR, "failures.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


# -----------------------------------------------------------------------------
# Context resolution


def resolve_objects(ctx: dict, expected: int | None = None,
                    types: tuple[str, ...] = ("MESH",)) -> tuple[list, dict | None]:
    """
    Resolve ``ctx["objects"]`` names to objects. Returns ``(objects, None)``
    on success or ``([], fail_report)`` describing what's missing.
    """
    names = ctx.get("objects", [])
    if expected is not None and len(names) != expected:
        return [], fail(
            "wrong_object_count",
            detail="expected {:d} object names in ctx['objects'], got {:d}".format(
                expected, len(names)),
        )
    objects = []
    for name in names:
        obj = bpy.data.objects.get(name)
        if obj is None:
            return [], fail("object_not_found", object=name)
        if obj.type not in types:
            return [], fail("wrong_object_type", object=name, type=obj.type)
        objects.append(obj)
    return objects, None


# -----------------------------------------------------------------------------
# Rollback

class Rollback:
    """
    Tracked-creation rollback: skills register every datablock they create;
    ``undo()`` removes them in reverse order. Cheap, reference-safe, and
    works headless (background-mode undo via ``bpy.ops.ed.undo`` does not).

    Use :func:`scene_snapshot`/:func:`scene_restore` instead around
    operators with diffuse side effects (Rigify generation).
    """

    def __init__(self) -> None:
        self._actions: list[tuple] = []

    def track_object(self, obj: bpy.types.Object) -> bpy.types.Object:
        self._actions.append(("object", obj.name))
        return obj

    def track_modifier(self, obj: bpy.types.Object, mod) -> object:
        self._actions.append(("modifier", obj.name, mod.name))
        return mod

    def track_vgroup(self, obj: bpy.types.Object, group) -> object:
        self._actions.append(("vgroup", obj.name, group.name))
        return group

    def track_bones(self, obj: bpy.types.Object, names: list[str]) -> None:
        """
        Bones added to a PRE-EXISTING armature (a chain composing into a
        larger rig) — removed by name on undo.
        """
        self._actions.append(("bones", obj.name, tuple(names)))

    def track_constraint(self, pose_bone, con) -> object:
        self._actions.append(("constraint", pose_bone.id_data.name, pose_bone.name, con.name))
        return con

    def track_parent(self, obj: bpy.types.Object) -> None:
        self._actions.append(("parent", obj.name, obj.parent.name if obj.parent else None,
                              tuple(map(tuple, obj.matrix_world))))

    def undo(self) -> None:
        for action in reversed(self._actions):
            try:
                self._undo_one(action)
            except Exception:
                # Rollback is best-effort per item; never raise from here.
                traceback.print_exc()
        self._actions.clear()

    @staticmethod
    def _undo_one(action: tuple) -> None:
        kind = action[0]
        if kind == "object":
            obj = bpy.data.objects.get(action[1])
            if obj is not None:
                data = obj.data
                bpy.data.objects.remove(obj)
                if data is not None and data.users == 0:
                    collection = (
                        bpy.data.armatures if isinstance(data, bpy.types.Armature)
                        else bpy.data.meshes if isinstance(data, bpy.types.Mesh)
                        else None)
                    if collection is not None:
                        collection.remove(data)
        elif kind == "modifier":
            obj = bpy.data.objects.get(action[1])
            if obj is not None:
                mod = obj.modifiers.get(action[2])
                if mod is not None:
                    obj.modifiers.remove(mod)
        elif kind == "vgroup":
            obj = bpy.data.objects.get(action[1])
            if obj is not None:
                group = obj.vertex_groups.get(action[2])
                if group is not None:
                    obj.vertex_groups.remove(group)
        elif kind == "constraint":
            obj = bpy.data.objects.get(action[1])
            if obj is not None and obj.pose is not None:
                pb = obj.pose.bones.get(action[2])
                if pb is not None:
                    con = pb.constraints.get(action[3])
                    if con is not None:
                        pb.constraints.remove(con)
        elif kind == "bones":
            obj = bpy.data.objects.get(action[1])
            if obj is not None and obj.type == "ARMATURE":
                from .. import _armature
                _armature.remove_bones(obj, list(action[2]))
        elif kind == "parent":
            obj = bpy.data.objects.get(action[1])
            if obj is not None:
                obj.parent = bpy.data.objects.get(action[2]) if action[2] else None
                import mathutils
                obj.matrix_world = mathutils.Matrix(action[3])


def run_with_rollback(skill_name: str, body) -> dict:
    """
    Execute *body(rollback)* and return its report; on exception or
    ``ok=False``, undo everything tracked and log the failure.
    """
    rollback = Rollback()
    try:
        report = body(rollback)
    except Exception as ex:
        rollback.undo()
        report = fail("exception", error=str(ex), traceback=traceback.format_exc())
        log_failure(skill_name, "run", report)
        return report
    if not report.get("ok"):
        rollback.undo()
        log_failure(skill_name, "run", report)
    return report


# -----------------------------------------------------------------------------
# Snapshot (heavyweight rollback for operator-driven skills)


def scene_snapshot() -> str:
    """
    Save the current main file to a temp .blend and return its path.
    """
    fd, path = tempfile.mkstemp(suffix=".blend", prefix="blrig_snapshot_")
    os.close(fd)
    bpy.ops.wm.save_as_mainfile(filepath=path, copy=True, compress=False)
    return path


def scene_restore(path: str) -> None:
    """
    Reload the snapshot saved by :func:`scene_snapshot`. Invalidates every
    Python reference into bpy.data — callers must re-resolve by name.
    """
    bpy.ops.wm.open_mainfile(filepath=path)


# -----------------------------------------------------------------------------
# Shared verify checks


def verify_common(armature_name: str) -> list[dict]:
    """
    Postconditions every skill shares: the armature exists, passes
    ``validate_rig()``, and has no NaN/inf in bone matrices.
    """
    checks = []
    obj = bpy.data.objects.get(armature_name)
    checks.append(check("armature_exists", obj is not None,
                        "object {!r}".format(armature_name)))
    if obj is None:
        return checks

    rig_report = standard.validate_rig(obj)
    checks.append(check(
        "validate_rig", rig_report["ok"],
        "; ".join("{}: {}".format(e["rule"], e["detail"]) for e in rig_report["errors"])))

    finite = all(
        all(all(abs(v) < 1e12 and v == v for v in row) for row in b.matrix_local)
        for b in obj.data.bones)
    checks.append(check("finite_bone_matrices", finite))
    return checks
