# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Animation at scale: verb-dispatched bulk keyframing, PARAMETRIC cycles,
looping, baking and layered-Action management for Blender 5.x.

The cycle builder is a generic phase-offset oscillator: the agent says
which bones swing, how far, and with what phase relationship (gait
knowledge — alternating support groups — lives in the skills docs); this
module computes every key. There is deliberately NO named-gait library:
a cycle is always derived from the parameters and the rig's actual
bones, never from a stored configuration.

Blender 5.x note (see the core ``animating-basics`` skill):
``action.fcurves`` no longer exists — reading goes through
layers -> strips -> channelbag(slot). :func:`action_fcurves` is that
recipe; writing still goes through plain ``keyframe_insert``.

Verbs: ``inspect``, ``keyframe``, ``cycle``, ``loop``, ``bake``,
``actions``, ``clear``. Heavyweight mutators (keyframe/cycle/loop/bake/
clear) snapshot the scene and restore it on failure.
"""

__all__ = (
    "action_fcurves",
    "dispatch",
)

import math
import os
import re
import traceback

import bpy

from . import _bones
from . import _contract
from . import pose_ops

_BONE_PATH_RE = re.compile(r'^pose\.bones\["(.+?)"\]\.(\w+)$')

_AXIS_INDEX = {"x": 0, "y": 1, "z": 2}


def _axis_index(axis) -> int | None:
    """
    Lenient axis parsing — live agents pass "x", "X" and bare indices.
    """
    if isinstance(axis, (int, float)) and int(axis) in (0, 1, 2):
        return int(axis)
    if isinstance(axis, str):
        return _AXIS_INDEX.get(axis.lower())
    return None

_CHANNEL_PATHS = {"rotation": "rotation_euler", "location": "location"}


def action_fcurves(action) -> list:
    """
    Every f-curve of a layered/slotted Action (Blender 5.x:
    layers -> strips -> channelbag(slot) -> fcurves).
    """
    if action is None:
        return []
    fcurves = []
    for layer in action.layers:
        for strip in layer.strips:
            for slot in action.slots:
                bag = strip.channelbag(slot)
                if bag:
                    fcurves.extend(bag.fcurves)
    return fcurves


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


def _mutate(verb: str, body):
    snapshot = _contract.scene_snapshot()
    try:
        report = body()
        if not report.get("ok"):
            _contract.scene_restore(snapshot)
            _contract.log_failure("anim." + verb, "run", report)
        return report
    except Exception as ex:
        _contract.scene_restore(snapshot)
        report = _contract.fail("exception", error=str(ex),
                                traceback=traceback.format_exc())
        _contract.log_failure("anim." + verb, "run", report)
        return report
    finally:
        if os.path.exists(snapshot):
            os.unlink(snapshot)


def _probe_animates(rig, frame_a: int, frame_b: int) -> bool:
    """
    Headless motion check: does ANY pose-bone matrix differ between the
    two frames? Full matrices — translation alone misses rotation-only
    motion on a bone spinning about its own head.
    """
    scene = bpy.context.scene
    current = scene.frame_current
    scene.frame_set(frame_a)
    bpy.context.view_layer.update()
    before = {pb.name: pb.matrix.copy() for pb in rig.pose.bones}
    scene.frame_set(frame_b)
    bpy.context.view_layer.update()
    moved = any(
        max(max(abs(v) for v in row) for row in (pb.matrix - before[pb.name])) > 1e-9
        for pb in rig.pose.bones)
    scene.frame_set(current)
    bpy.context.view_layer.update()
    return moved


def _add_cycles_modifiers(action) -> int:
    added = 0
    for fc in action_fcurves(action):
        if not any(m.type == "CYCLES" for m in fc.modifiers):
            fc.modifiers.new("CYCLES")
            added += 1
    return added


# -----------------------------------------------------------------------------
# Verbs


def _inspect(args: dict) -> dict:
    """
    Read-only animation state: action, keyed bones/channels, key range,
    loop modifiers, NLA tracks, scene frame range.
    """
    rig, err = _rig(args)
    if err is not None:
        return err
    scene = bpy.context.scene
    report = _contract.ok(
        armature=rig.name,
        scene_frame_range=[scene.frame_start, scene.frame_end],
    )
    ad = rig.animation_data
    if ad is None or (ad.action is None and not ad.nla_tracks):
        report["action"] = None
        report["detail"] = "no animation data"
        return report

    if ad.action is not None:
        fcurves = action_fcurves(ad.action)
        bones: dict[str, set] = {}
        key_min, key_max = None, None
        n_cyclic = 0
        for fc in fcurves:
            match = _BONE_PATH_RE.match(fc.data_path)
            if match:
                bones.setdefault(match.group(1), set()).add(match.group(2))
            if fc.keyframe_points:
                lo = fc.keyframe_points[0].co[0]
                hi = fc.keyframe_points[-1].co[0]
                key_min = lo if key_min is None else min(key_min, lo)
                key_max = hi if key_max is None else max(key_max, hi)
            if any(m.type == "CYCLES" for m in fc.modifiers):
                n_cyclic += 1
        report["action"] = ad.action.name
        report["n_fcurves"] = len(fcurves)
        report["n_cyclic_fcurves"] = n_cyclic
        report["keyed_frame_range"] = (
            [key_min, key_max] if key_min is not None else None)
        report["keyed_bones"] = {b: sorted(c) for b, c in sorted(bones.items())}
    else:
        report["action"] = None
    report["nla_tracks"] = [
        {"name": t.name, "strips": [
            {"name": s.name, "action": s.action.name if s.action else None,
             "frames": [s.frame_start, s.frame_end]} for s in t.strips]}
        for t in ad.nla_tracks]
    return report


def _keyframe(args: dict) -> dict:
    """
    Bulk keyframe insert: ``keys`` is a list of
    ``{"frame": F, "bones": {name-or-glob: channel values}}`` — every
    matched bone gets its channels set then keyed at F.
    """
    rig, err = _rig(args)
    if err is not None:
        return err
    keys = args.get("keys")
    if not isinstance(keys, list) or not keys:
        return _contract.fail(
            "bad_args",
            detail="'keys' must be [{'frame': F, 'bones': {glob: "
                   "{rotation_deg|location|scale|rotation_quaternion}}}]")

    def body() -> dict:
        n_keys = 0
        keyed_bones = set()
        for entry in keys:
            frame = entry.get("frame")
            mapping = entry.get("bones")
            if frame is None or not isinstance(mapping, dict):
                return _contract.fail(
                    "bad_args", detail="each key needs 'frame' and 'bones'")
            for pattern in sorted(mapping):
                values = mapping[pattern] or {}
                bones = pose_ops.match_bones(rig, [pattern])
                if not bones:
                    return _contract.fail(
                        "no_bones_matched", patterns=[pattern],
                        sample=[pb.name for pb in rig.pose.bones[:20]])
                for pb in bones:
                    pose_ops.apply_channels(pb, values)
                    if "rotation_deg" in values or "rotation_quaternion" in values:
                        path = ("rotation_quaternion"
                                if pb.rotation_mode == "QUATERNION"
                                else "rotation_euler")
                        pb.keyframe_insert(path, frame=frame)
                        n_keys += 1
                    if "location" in values:
                        pb.keyframe_insert("location", frame=frame)
                        n_keys += 1
                    if "scale" in values:
                        pb.keyframe_insert("scale", frame=frame)
                        n_keys += 1
                    keyed_bones.add(pb.name)
        bpy.context.view_layer.update()
        action = rig.animation_data.action if rig.animation_data else None
        return _contract.ok(
            armature=rig.name,
            action=action.name if action else None,
            n_keys=n_keys,
            bones=sorted(keyed_bones),
            n_fcurves=len(action_fcurves(action)),
        )

    return _mutate("keyframe", body)


def _cycle(args: dict) -> dict:
    """
    Build a parametric, seamlessly-looping cycle. Each channel spec is an
    oscillator over the cycle:

        value(t) = offset + amplitude * sin(2*pi*frequency*(t + phase))

    spec fields: ``bones`` (globs), ``channel`` ("rotation"|"location"),
    ``axis`` ("x"|"y"|"z"), ``amplitude`` (degrees for rotation, units for
    location), ``phase`` (0..1, e.g. opposite legs 0 and 0.5), optional
    ``phase_step`` (per-matched-bone increment — tripod/wave gaits),
    ``frequency`` (integer multiplier; a root bob uses 2 — once per
    footfall), ``offset`` (center value).

    The keyed value at t=1 equals t=0 by construction, so the loop is
    seamless; CYCLES modifiers extrapolate beyond one period.
    """
    rig, err = _rig(args)
    if err is not None:
        return err
    specs = args.get("channels")
    if not isinstance(specs, list) or not specs:
        return _contract.fail(
            "bad_args",
            detail="'channels' must be a list of {bones, channel, axis, "
                   "amplitude, phase?, phase_step?, frequency?, offset?}")
    frames = int(args.get("frames", 24))
    start = int(args.get("start", 1))
    samples = max(2, int(args.get("samples", 4)))
    if frames < 2:
        return _contract.fail("bad_args", detail="'frames' must be >= 2")

    plans = []
    for i, spec in enumerate(specs):
        channel = spec.get("channel", "rotation")
        if channel not in _CHANNEL_PATHS:
            return _contract.fail(
                "bad_args", spec=i,
                detail="channel must be 'rotation' or 'location'")
        axis = _axis_index(spec.get("axis", "x"))
        if axis is None:
            return _contract.fail("bad_args", spec=i,
                                  detail="axis must be x|y|z (or 0|1|2)")
        patterns = spec.get("bones")
        if not patterns:
            return _contract.fail("bad_args", spec=i, detail="missing 'bones'")
        bones = pose_ops.match_bones(rig, patterns)
        if not bones:
            return _contract.fail(
                "no_bones_matched", spec=i, patterns=patterns,
                sample=[pb.name for pb in rig.pose.bones[:20]])
        plans.append({
            "bones": bones,
            "path": _CHANNEL_PATHS[channel],
            "index": axis,
            "amplitude": float(spec.get("amplitude", 0.0)),
            "phase": float(spec.get("phase", 0.0)),
            "phase_step": float(spec.get("phase_step", 0.0)),
            # Non-integer frequencies can't wrap seamlessly — round them.
            "frequency": max(1, round(float(spec.get("frequency", 1)))),
            "offset": float(spec.get("offset", 0.0)),
            "is_rotation": channel == "rotation",
        })
    if all(p["amplitude"] == 0.0 for p in plans):
        return _contract.fail(
            "bad_args", detail="every channel has amplitude 0 — nothing animates")

    def body() -> dict:
        for plan in plans:
            for k, pb in enumerate(plan["bones"]):
                phase = plan["phase"] + k * plan["phase_step"]
                if plan["is_rotation"] and pb.rotation_mode == "QUATERNION":
                    # Oscillators key one euler axis; quaternion bones are
                    # switched explicitly (animating-basics rule: never key
                    # euler on a quaternion-mode bone).
                    pb.rotation_mode = "XYZ"
                for s in range(samples + 1):
                    t = s / samples
                    value = plan["offset"] + plan["amplitude"] * math.sin(
                        2.0 * math.pi * plan["frequency"] * (t + phase))
                    if plan["is_rotation"]:
                        value = math.radians(value)
                    getattr(pb, plan["path"])[plan["index"]] = value
                    pb.keyframe_insert(plan["path"], index=plan["index"],
                                       frame=start + t * frames)
        scene = bpy.context.scene
        scene.frame_start = start
        scene.frame_end = start + frames - 1

        action = rig.animation_data.action
        n_cyclic = _add_cycles_modifiers(action) if args.get("loop", True) else 0
        # Probe at a quarter period of the fastest oscillator — every
        # sin channel is zero at the half period, so probing there reads
        # a healthy cycle as static.
        fmax = max(p["frequency"] for p in plans)
        quarter = start + max(1, round(frames / (4.0 * fmax)))
        eighth = start + max(1, round(frames / (8.0 * fmax)))
        animates = (_probe_animates(rig, start, quarter)
                    or _probe_animates(rig, start, eighth))
        if not animates:
            return _contract.fail(
                "cycle_static",
                detail="keys inserted but no pose-bone matrix changes between "
                       "frames — wrong bones (DEF- instead of controls?) or "
                       "constraints overriding the channel",
                suggest="animate the rig's CTL-/control bones; check "
                        "pose('get') for what actually moves the rig")
        bpy.context.view_layer.update()
        return _contract.ok(
            armature=rig.name,
            action=action.name,
            frames=frames, start=start, samples=samples,
            n_fcurves=len(action_fcurves(action)),
            n_cyclic_fcurves=n_cyclic,
            channels=[{
                "bones": [pb.name for pb in p["bones"]],
                "path": p["path"], "axis_index": p["index"],
                "amplitude": p["amplitude"], "phase": p["phase"],
                "phase_step": p["phase_step"], "frequency": p["frequency"],
            } for p in plans],
        )

    return _mutate("cycle", body)


def _loop(args: dict) -> dict:
    """
    Make the current action loop cleanly: pin every f-curve's last key to
    its first value (at the global last keyed frame) and add CYCLES
    extrapolation; optionally sync the scene frame range.
    """
    rig, err = _rig(args)
    if err is not None:
        return err
    ad = rig.animation_data
    if ad is None or ad.action is None:
        return _contract.fail("no_action", suggest="anim('keyframe') or "
                                                   "anim('cycle') first")

    def body() -> dict:
        action = rig.animation_data.action
        fcurves = [fc for fc in action_fcurves(action) if fc.keyframe_points]
        if not fcurves:
            return _contract.fail("no_keyframes", action=action.name)
        global_start = min(fc.keyframe_points[0].co[0] for fc in fcurves)
        global_end = max(fc.keyframe_points[-1].co[0] for fc in fcurves)
        if global_end <= global_start:
            return _contract.fail(
                "no_keyframes", detail="action has a single keyed frame")
        n_fixed = 0
        if bool(args.get("fix", True)):
            for fc in fcurves:
                first_value = fc.keyframe_points[0].co[1]
                last = fc.keyframe_points[-1]
                if (abs(last.co[0] - global_end) > 1e-6
                        or abs(last.co[1] - first_value) > 1e-9):
                    fc.keyframe_points.insert(
                        global_end, first_value, options={"REPLACE"})
                    fc.update()
                    n_fixed += 1
        n_cyclic = _add_cycles_modifiers(action)
        if bool(args.get("set_frame_range", True)):
            scene = bpy.context.scene
            scene.frame_start = int(global_start)
            # The wrap frame duplicates the first pose; stop one short.
            scene.frame_end = max(int(global_end) - 1, int(global_start))
        bpy.context.view_layer.update()
        return _contract.ok(
            armature=rig.name, action=action.name,
            keyed_frame_range=[global_start, global_end],
            n_fcurves=len(fcurves), n_end_keys_fixed=n_fixed,
            n_cycles_modifiers_added=n_cyclic)

    return _mutate("loop", body)


def _bake(args: dict) -> dict:
    """
    Bake the evaluated result (constraints, IK, drivers) into plain
    keyframes — visual keying. ``bones`` globs restrict the bake.
    """
    rig, err = _rig(args)
    if err is not None:
        return err
    scene = bpy.context.scene
    frame_start = int(args.get("frame_start", scene.frame_start))
    frame_end = int(args.get("frame_end", scene.frame_end))
    step = max(1, int(args.get("step", 1)))
    if frame_end < frame_start:
        return _contract.fail("bad_args", detail="frame_end < frame_start")
    patterns = args.get("bones")

    def body() -> dict:
        from bpy_extras import anim_utils

        only_selected = False
        if patterns:
            bones = pose_ops.match_bones(rig, patterns)
            if not bones:
                return _contract.fail(
                    "no_bones_matched", patterns=patterns,
                    sample=[pb.name for pb in rig.pose.bones[:20]])
            for pb in rig.pose.bones:
                pb.select = False
            for pb in bones:
                pb.select = True
            only_selected = True

        _bones.select_only([rig], active=rig)
        options = anim_utils.BakeOptions(
            only_selected=only_selected,
            do_pose=True, do_object=False,
            do_visual_keying=bool(args.get("visual", True)),
            do_constraint_clear=bool(args.get("clear_constraints", False)),
            do_parents_clear=False,
            do_clean=bool(args.get("clean", True)),
            do_location=True, do_rotation=True, do_scale=True,
            do_bbone=False, do_custom_props=False)
        action = anim_utils.bake_action(
            rig, action=None,
            frames=range(frame_start, frame_end + 1, step),
            bake_options=options)
        if action is None:
            return _contract.fail("bake_produced_nothing",
                                  detail="no channels were baked")
        bpy.context.view_layer.update()
        return _contract.ok(
            armature=rig.name, action=action.name,
            frames=[frame_start, frame_end], step=step,
            n_fcurves=len(action_fcurves(action)))

    return _mutate("bake", body)


def _actions(args: dict) -> dict:
    """
    Layered-Action management: ``op`` is one of list / new / assign /
    rename / push_nla / remove. ``push_nla`` pushes the active action to
    a fresh NLA track and frees the action slot for the next layer (the
    animating-basics layering model).
    """
    rig, err = _rig(args)
    if err is not None:
        return err
    op = args.get("op", "list")
    name = args.get("name")

    try:
        if op == "list":
            ad = rig.animation_data
            active = ad.action.name if ad and ad.action else None
            return _contract.ok(
                armature=rig.name, active=active,
                actions=[{
                    "name": a.name, "users": a.users,
                    "n_fcurves": len(action_fcurves(a)),
                    "frame_range": list(a.frame_range),
                } for a in bpy.data.actions])

        if op == "new":
            if not name:
                return _contract.fail("bad_args", detail="'new' needs 'name'")
            action = bpy.data.actions.new(name)
            ad = rig.animation_data_create()
            ad.action = action
            return _contract.ok(armature=rig.name, action=action.name,
                                assigned=True)

        if op == "assign":
            action = bpy.data.actions.get(name or "")
            if action is None:
                return _contract.fail("action_not_found", name=name,
                                      available=[a.name for a in bpy.data.actions])
            ad = rig.animation_data_create()
            ad.action = action
            if action.slots:
                ad.action_slot = action.slots[0]
            return _contract.ok(armature=rig.name, action=action.name)

        if op == "rename":
            action = bpy.data.actions.get(name or "")
            new_name = args.get("new_name")
            if action is None or not new_name:
                return _contract.fail(
                    "bad_args", detail="'rename' needs 'name' and 'new_name'")
            action.name = new_name
            return _contract.ok(action=action.name)

        if op == "push_nla":
            ad = rig.animation_data
            if ad is None or ad.action is None:
                return _contract.fail("no_action",
                                      detail="nothing assigned to push")
            action = ad.action
            track = ad.nla_tracks.new()
            track.name = name or action.name
            start = int(action.frame_range[0])
            track.strips.new(action.name, start, action)
            ad.action = None
            return _contract.ok(
                armature=rig.name, pushed=action.name, track=track.name,
                detail="action slot is free — keyframe the next layer, or "
                       "assign another action")

        if op == "remove":
            action = bpy.data.actions.get(name or "")
            if action is None:
                return _contract.fail("action_not_found", name=name)
            bpy.data.actions.remove(action)
            return _contract.ok(removed=name)

        return _contract.fail(
            "bad_args",
            detail="op must be list|new|assign|rename|push_nla|remove")
    except Exception as ex:
        report = _contract.fail("exception", error=str(ex),
                                traceback=traceback.format_exc())
        _contract.log_failure("anim.actions", "run", report)
        return report


def _clear(args: dict) -> dict:
    """
    Unlink the active action (keeping it in the file unless
    ``remove_action``); optionally wipe NLA tracks too.
    """
    rig, err = _rig(args)
    if err is not None:
        return err

    def body() -> dict:
        ad = rig.animation_data
        if ad is None:
            return _contract.ok(armature=rig.name, detail="no animation data")
        cleared = ad.action.name if ad.action else None
        action = ad.action
        ad.action = None
        removed = False
        if action is not None and bool(args.get("remove_action")):
            bpy.data.actions.remove(action)
            removed = True
        n_tracks = 0
        if bool(args.get("nla")):
            n_tracks = len(ad.nla_tracks)
            for track in list(ad.nla_tracks):
                ad.nla_tracks.remove(track)
        bpy.context.view_layer.update()
        return _contract.ok(armature=rig.name, cleared_action=cleared,
                            action_removed=removed, nla_tracks_removed=n_tracks)

    return _mutate("clear", body)


_VERBS = {
    "inspect": _inspect,
    "keyframe": _keyframe,
    "cycle": _cycle,
    "loop": _loop,
    "bake": _bake,
    "actions": _actions,
    "clear": _clear,
}


def dispatch(verb: str, args: dict | None) -> dict:
    fn = _VERBS.get(verb)
    if fn is None:
        return _contract.fail("unknown_verb", verb=verb, valid=sorted(_VERBS))
    return fn(args or {})
