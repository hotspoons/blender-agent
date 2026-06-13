# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Posing at scale: verb-dispatched batch operations on pose bones. The LLM
names bones (globs allowed) and semantic values; rotation-mode handling,
depsgraph ordering, mirroring math and IK/FK snapping live here.

Hard-won rules baked in (see PROGRESS "multipart round"):
- an armature left in EDIT mode silently freezes pose evaluation — every
  verb guards with ``ensure_object_mode``;
- ``rotation_euler`` on a QUATERNION-mode bone animates nothing — values
  are converted to the bone's actual rotation mode;
- Rigify ``IK_FK`` switches must be captured/restored or later IK posing
  becomes a silent no-op — the ``ik_fk`` verb owns that property.

Verbs: ``get``, ``set``, ``mirror``, ``reset``, ``ik_fk``,
``save_named``, ``apply_named``, ``list_named``. Mutating verbs capture
the prior pose state and restore it on failure (cheap — no scene
snapshot needed for pose-channel changes).
"""

__all__ = (
    "apply_channels",
    "dispatch",
    "match_bones",
)

import fnmatch
import json
import math
import re
import traceback

import bpy

from mathutils import Euler, Quaternion

from . import _bones
from . import _contract

_SIDE_RE = re.compile(r"\.(L|R)(?=$|\.)")

_POSES_PROP = "blrig_poses"


def _flip_side(name: str) -> str:
    return _SIDE_RE.sub(lambda m: "." + ("R" if m.group(1) == "L" else "L"), name)


def _rig(args: dict):
    name = args.get("armature")
    if not name:
        return None, _contract.fail("bad_args", detail="missing 'armature'")
    obj = bpy.data.objects.get(name)
    if obj is None:
        return None, _contract.fail("object_not_found", object=name)
    if obj.type != "ARMATURE":
        return None, _contract.fail("wrong_object_type", object=name, type=obj.type)
    _bones.ensure_object_mode(obj)
    return obj, None


def match_bones(rig, patterns) -> list:
    """
    Pose bones whose names match any glob in *patterns* (order-stable,
    deduplicated).
    """
    matched = []
    seen = set()
    for pb in rig.pose.bones:
        if pb.name in seen:
            continue
        if any(fnmatch.fnmatchcase(pb.name, p) for p in patterns):
            matched.append(pb)
            seen.add(pb.name)
    return matched


def _is_identity(pb) -> bool:
    return (tuple(pb.location) == (0.0, 0.0, 0.0)
            and tuple(pb.rotation_euler) == (0.0, 0.0, 0.0)
            and tuple(pb.rotation_quaternion) == (1.0, 0.0, 0.0, 0.0)
            and tuple(pb.scale) == (1.0, 1.0, 1.0))


def _channels(pb) -> dict:
    entry = {
        "rotation_mode": pb.rotation_mode,
        "location": [round(v, 6) for v in pb.location],
        "scale": [round(v, 6) for v in pb.scale],
    }
    if pb.rotation_mode == "QUATERNION":
        entry["rotation_quaternion"] = [round(v, 6) for v in pb.rotation_quaternion]
    else:
        entry["rotation_deg"] = [round(math.degrees(v), 4) for v in pb.rotation_euler]
    return entry


def _capture(rig, bones=None) -> dict:
    state = {}
    for pb in (bones if bones is not None else rig.pose.bones):
        state[pb.name] = (
            pb.rotation_mode,
            tuple(pb.location),
            tuple(pb.rotation_euler),
            tuple(pb.rotation_quaternion),
            tuple(pb.scale),
        )
    return state


def _restore(rig, state: dict) -> None:
    for name, (mode, loc, eul, quat, scale) in state.items():
        pb = rig.pose.bones.get(name)
        if pb is None:
            continue
        pb.rotation_mode = mode
        pb.location = loc
        pb.rotation_euler = eul
        pb.rotation_quaternion = quat
        pb.scale = scale
    bpy.context.view_layer.update()


def apply_channels(pb, values: dict, additive: bool = False) -> None:
    """
    Set pose channels respecting the bone's rotation mode: ``rotation_deg``
    on a QUATERNION bone is converted, never silently dropped.
    """
    if "rotation_deg" in values:
        rad = [math.radians(float(v)) for v in values["rotation_deg"]]
        if pb.rotation_mode == "QUATERNION":
            quat = Euler(rad, "XYZ").to_quaternion()
            pb.rotation_quaternion = (
                pb.rotation_quaternion @ quat if additive else quat)
        else:
            current = pb.rotation_euler
            order = pb.rotation_mode
            new = Euler((rad[0] + current.x, rad[1] + current.y,
                         rad[2] + current.z) if additive else rad, order)
            pb.rotation_euler = new
    if "rotation_quaternion" in values:
        quat = Quaternion(values["rotation_quaternion"])
        pb.rotation_mode = "QUATERNION"
        pb.rotation_quaternion = (
            pb.rotation_quaternion @ quat if additive else quat)
    if "location" in values:
        loc = [float(v) for v in values["location"]]
        if additive:
            loc = [a + b for a, b in zip(pb.location, loc)]
        pb.location = loc
    if "scale" in values:
        pb.scale = [float(v) for v in values["scale"]]


def _mutate(verb: str, rig, body):
    """
    Capture the full pose state, run *body*, restore the pose + log on
    exception or ok=False.
    """
    state = _capture(rig)
    try:
        report = body()
        if not report.get("ok"):
            _restore(rig, state)
            _contract.log_failure("pose." + verb, "run", report)
        return report
    except Exception as ex:
        _restore(rig, state)
        report = _contract.fail("exception", error=str(ex),
                                traceback=traceback.format_exc())
        _contract.log_failure("pose." + verb, "run", report)
        return report


# -----------------------------------------------------------------------------
# Rigify IK/FK plumbing (name conventions are Rigify's, not ours)


def _ik_fk_holders(rig, patterns=None) -> list:
    holders = [pb for pb in rig.pose.bones if "IK_FK" in pb.keys()]
    if patterns:
        holders = [pb for pb in holders
                   if any(fnmatch.fnmatchcase(pb.name, p) for p in patterns)]
    return holders


def _limb_orgs(rig, holder) -> list:
    """
    The ORG- bone chain of a holder's limb, parent-first. Holder names
    follow Rigify's ``{stem}_parent.{side}`` (e.g. upper_arm_parent.L);
    the chain is ORG-{stem}.{side} plus its same-side ORG descendants.
    """
    side = _SIDE_RE.search(holder.name)
    if side is None:
        return []
    suffix = holder.name[side.start():]
    stem = holder.name[:side.start()].removesuffix("_parent")
    root = rig.pose.bones.get("ORG-" + stem + suffix)
    if root is None:
        return []
    chain = [root]
    frontier = [root]
    while frontier:
        pb = frontier.pop(0)
        for child in pb.children:
            if child.name.startswith("ORG-") and child.name.endswith(suffix):
                chain.append(child)
                frontier.append(child)
    return chain


def _org_stem(org_name: str) -> str:
    return org_name.removeprefix("ORG-")


# -----------------------------------------------------------------------------
# Verbs


def _get(args: dict) -> dict:
    """
    Read pose channels. Default: only bones posed away from rest (compact
    on 700-bone Rigify rigs); pass bones globs (e.g. ["*"]) for more.
    """
    rig, err = _rig(args)
    if err is not None:
        return err
    bpy.context.view_layer.update()
    patterns = args.get("bones")
    if patterns:
        bones = match_bones(rig, patterns)
        if not bones:
            return _contract.fail(
                "no_bones_matched", patterns=patterns,
                sample=[pb.name for pb in rig.pose.bones[:20]])
    else:
        bones = [pb for pb in rig.pose.bones if not _is_identity(pb)]
    report = _contract.ok(
        armature=rig.name,
        n_bones_total=len(rig.pose.bones),
        bones={pb.name: _channels(pb) for pb in bones},
    )
    holders = _ik_fk_holders(rig)
    if holders:
        report["ik_fk"] = {pb.name: round(float(pb["IK_FK"]), 3) for pb in holders}
    if not patterns:
        report["note"] = "showing posed bones only; pass {'bones': ['*']} for all"
    return report


def _set(args: dict) -> dict:
    """
    Batch-set transforms: ``bones`` maps name-or-glob -> channel values
    ({rotation_deg | rotation_quaternion, location, scale}).
    """
    rig, err = _rig(args)
    if err is not None:
        return err
    mapping = args.get("bones")
    if not isinstance(mapping, dict) or not mapping:
        return _contract.fail(
            "bad_args",
            detail="'bones' must map name/glob -> {rotation_deg|location|scale|"
                   "rotation_quaternion}")
    additive = bool(args.get("additive"))

    def body() -> dict:
        applied = {}
        for pattern in sorted(mapping):
            values = mapping[pattern] or {}
            bones = match_bones(rig, [pattern])
            if not bones:
                return _contract.fail(
                    "no_bones_matched", patterns=[pattern],
                    sample=[pb.name for pb in rig.pose.bones[:20]])
            for pb in bones:
                apply_channels(pb, values, additive=additive)
                applied[pb.name] = _channels(pb)
        bpy.context.view_layer.update()
        return _contract.ok(armature=rig.name, n_bones=len(applied), bones=applied)

    return _mutate("set", rig, body)


def _mirror(args: dict) -> dict:
    """
    Copy the pose of every ``from_side`` bone onto its twin, flipped
    (Blender paste-flipped channel math: -loc.x, euler -y/-z, quat -y/-z).
    Assumes Blender's mirrored-roll convention, which Rigify and
    symmetrize both produce.
    """
    rig, err = _rig(args)
    if err is not None:
        return err
    from_side = args.get("from_side", "L")
    if from_side not in ("L", "R"):
        return _contract.fail("bad_args", detail="from_side must be 'L' or 'R'")
    patterns = args.get("bones") or ["*"]

    def body() -> dict:
        mirrored = []
        skipped = []
        for pb in match_bones(rig, patterns):
            side = _SIDE_RE.search(pb.name)
            if side is None or side.group(1) != from_side:
                continue
            twin = rig.pose.bones.get(_flip_side(pb.name))
            if twin is None:
                skipped.append(pb.name)
                continue
            twin.rotation_mode = pb.rotation_mode
            twin.location = (-pb.location.x, pb.location.y, pb.location.z)
            twin.scale = tuple(pb.scale)
            if pb.rotation_mode == "QUATERNION":
                q = pb.rotation_quaternion
                twin.rotation_quaternion = (q.w, q.x, -q.y, -q.z)
            else:
                e = pb.rotation_euler
                twin.rotation_euler = Euler((e.x, -e.y, -e.z), pb.rotation_mode)
            mirrored.append(twin.name)
        if not mirrored:
            return _contract.fail(
                "no_bones_matched",
                detail="no {!r}-side bones matched {!r}".format(from_side, patterns),
                skipped_no_twin=skipped)
        bpy.context.view_layer.update()
        return _contract.ok(armature=rig.name, from_side=from_side,
                            mirrored=mirrored, skipped_no_twin=skipped)

    return _mutate("mirror", rig, body)


def _reset(args: dict) -> dict:
    """
    Zero pose transforms (all bones, or a glob subset).
    """
    rig, err = _rig(args)
    if err is not None:
        return err
    patterns = args.get("bones")

    def body() -> dict:
        if patterns:
            bones = match_bones(rig, patterns)
            if not bones:
                return _contract.fail(
                    "no_bones_matched", patterns=patterns,
                    sample=[pb.name for pb in rig.pose.bones[:20]])
            _bones.reset_pose(rig, bones=[pb.name for pb in bones])
            n = len(bones)
        else:
            _bones.reset_pose(rig)
            n = len(rig.pose.bones)
        return _contract.ok(armature=rig.name, n_bones=n)

    return _mutate("reset", rig, body)


def _ik_fk(args: dict) -> dict:
    """
    Switch Rigify limbs between IK and FK, snapping the destination
    controls to the current visual pose so nothing jumps. ``limbs`` globs
    match the IK_FK holder bones (e.g. ["upper_arm_parent.L"] or
    ["thigh_*"]); default all. Pole targets are placed geometrically —
    a small ``snap_drift`` is normal for IK targets the solver can't
    reach exactly.
    """
    rig, err = _rig(args)
    if err is not None:
        return err
    to = args.get("to")
    if to not in ("fk", "ik"):
        return _contract.fail("bad_args", detail="'to' must be 'fk' or 'ik'")
    snap = bool(args.get("snap", True))
    holders = _ik_fk_holders(rig, args.get("limbs"))
    if not holders:
        return _contract.fail(
            "no_ik_fk_properties",
            detail="no pose bones carry an IK_FK custom property"
                   + (" matching {!r}".format(args["limbs"]) if args.get("limbs") else ""),
            suggest="only Rigify-generated rigs have IK/FK switching; "
                    "available holders: {!r}".format(
                        [pb.name for pb in _ik_fk_holders(rig)]))

    def body() -> dict:
        bpy.context.view_layer.update()
        size = max(max(rig.dimensions), 1e-6)
        results = {}
        for holder in holders:
            orgs = _limb_orgs(rig, holder)
            side_match = _SIDE_RE.search(holder.name)
            if not orgs or side_match is None:
                results[holder.name] = {"switched": False, "detail": "no ORG chain"}
                continue
            side = holder.name[side_match.start():]
            end_before = orgs[-1].matrix.copy()

            # Capture the visual chain BEFORE flipping the switch.
            snap_targets = []
            if snap and to == "fk":
                for org in orgs:
                    stem = _org_stem(org.name)[:-len(side)]
                    fk = rig.pose.bones.get(stem + "_fk" + side)
                    if fk is not None:
                        snap_targets.append((fk.name, org.matrix.copy()))
            elif snap and to == "ik":
                for org in orgs:
                    ik = rig.pose.bones.get(
                        _org_stem(org.name)[:-len(side)] + "_ik" + side)
                    if ik is not None:
                        snap_targets.append((ik.name, org.matrix.copy()))
                pole = rig.pose.bones.get(
                    _org_stem(orgs[0].name)[:-len(side)] + "_ik_target" + side)
                if pole is not None and len(orgs) >= 3:
                    root = orgs[0].matrix.translation
                    mid = orgs[1].matrix.translation
                    end = orgs[2].matrix.translation
                    bend = mid - (root + end) * 0.5
                    if bend.length > 1e-9:
                        reach = (root - mid).length + (end - mid).length
                        pos = mid + bend.normalized() * 0.5 * reach
                        mat = pole.matrix.copy()
                        mat.translation = pos
                        snap_targets.append((pole.name, mat))

            holder["IK_FK"] = 1.0 if to == "fk" else 0.0
            rig.update_tag()
            bpy.context.view_layer.update()

            for bone_name, matrix in snap_targets:
                rig.pose.bones[bone_name].matrix = matrix
                bpy.context.view_layer.update()

            end_after = rig.pose.bones[orgs[-1].name].matrix
            drift = (end_after.translation - end_before.translation).length
            results[holder.name] = {
                "switched": True,
                "snapped": [n for n, _m in snap_targets],
                "snap_drift": round(drift, 5),
                "snap_drift_ok": drift < 0.05 * size,
            }
        return _contract.ok(armature=rig.name, to=to, limbs=results)

    return _mutate("ik_fk", rig, body)


def _save_named(args: dict) -> dict:
    """
    Store the current pose (posed bones only, or a glob subset) under a
    name on the armature object — a minimal pose library.
    """
    rig, err = _rig(args)
    if err is not None:
        return err
    name = args.get("name")
    if not name:
        return _contract.fail("bad_args", detail="missing 'name'")
    patterns = args.get("bones")
    if patterns:
        bones = match_bones(rig, patterns)
    else:
        bones = [pb for pb in rig.pose.bones if not _is_identity(pb)]
    if not bones:
        return _contract.fail(
            "nothing_to_save",
            detail="no posed bones (or none matched); pose first or pass 'bones'")
    poses = json.loads(rig.get(_POSES_PROP, "{}"))
    poses[name] = {pb.name: _channels(pb) for pb in bones}
    rig[_POSES_PROP] = json.dumps(poses)
    return _contract.ok(armature=rig.name, name=name, n_bones=len(bones),
                        saved_poses=sorted(poses))


def _apply_named(args: dict) -> dict:
    """
    Apply a pose saved by ``save_named``.
    """
    rig, err = _rig(args)
    if err is not None:
        return err
    name = args.get("name")
    poses = json.loads(rig.get(_POSES_PROP, "{}"))
    if name not in poses:
        return _contract.fail("pose_not_found", name=name, available=sorted(poses))

    def body() -> dict:
        missing = []
        applied = 0
        if bool(args.get("reset_first", True)):
            _bones.reset_pose(rig)
        for bone_name, values in poses[name].items():
            pb = rig.pose.bones.get(bone_name)
            if pb is None:
                missing.append(bone_name)
                continue
            if "rotation_mode" in values and "rotation_quaternion" not in values:
                pb.rotation_mode = values["rotation_mode"]
            apply_channels(pb, values)
            applied += 1
        bpy.context.view_layer.update()
        if applied == 0:
            return _contract.fail("pose_bones_missing", missing=missing)
        return _contract.ok(armature=rig.name, name=name,
                            n_applied=applied, missing=missing)

    return _mutate("apply_named", rig, body)


def _list_named(args: dict) -> dict:
    rig, err = _rig(args)
    if err is not None:
        return err
    poses = json.loads(rig.get(_POSES_PROP, "{}"))
    return _contract.ok(armature=rig.name,
                        poses={n: len(b) for n, b in sorted(poses.items())})


_VERBS = {
    "get": _get,
    "set": _set,
    "mirror": _mirror,
    "reset": _reset,
    "ik_fk": _ik_fk,
    "save_named": _save_named,
    "apply_named": _apply_named,
    "list_named": _list_named,
}


def dispatch(verb: str, args: dict | None) -> dict:
    fn = _VERBS.get(verb)
    if fn is None:
        return _contract.fail("unknown_verb", verb=verb, valid=sorted(_VERBS))
    return fn(args or {})
