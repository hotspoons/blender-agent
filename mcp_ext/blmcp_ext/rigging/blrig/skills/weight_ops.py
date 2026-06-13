# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Weight painting at scale: verb-dispatched bulk operations on vertex-group
weights. The LLM picks the verb and semantic parameters; everything
coordinate-level (which verts, which side of the midline, nearest mirrored
position) is computed here.

Verbs: ``inspect``, ``transfer``, ``mirror``, ``clean``, ``smooth``,
``bind``, ``validate``. Mutating verbs snapshot the scene and restore it
on failure, then log to ``failures.jsonl`` — retrying is always safe.
"""

__all__ = (
    "dispatch",
)

import fnmatch
import os
import re
import traceback

import bpy
import numpy as np

from .. import perception
from ..standard import validate_weights
from . import _bones
from . import _contract
from . import _proxy

_SIDE_RE = re.compile(r"\.(L|R)(?=$|\.)")


def _flip_side(name: str) -> str:
    """
    ``DEF-thigh.L.001`` -> ``DEF-thigh.R.001`` (and vice versa); names
    without a side token come back unchanged.
    """
    return _SIDE_RE.sub(lambda m: "." + ("R" if m.group(1) == "L" else "L"), name)


def _mesh(args: dict, key: str = "object"):
    name = args.get(key)
    if not name:
        return None, _contract.fail("bad_args", detail="missing {!r}".format(key))
    obj = bpy.data.objects.get(name)
    if obj is None:
        return None, _contract.fail("object_not_found", object=name)
    if obj.type != "MESH":
        return None, _contract.fail("wrong_object_type", object=name, type=obj.type)
    return obj, None


def _meshes(args: dict):
    names = args.get("objects") or ([args["object"]] if args.get("object") else [])
    if not names:
        return [], _contract.fail("bad_args", detail="missing 'objects' (or 'object')")
    objects = []
    for name in names:
        obj = bpy.data.objects.get(name)
        if obj is None:
            return [], _contract.fail("object_not_found", object=name)
        if obj.type != "MESH":
            return [], _contract.fail("wrong_object_type", object=name, type=obj.type)
        objects.append(obj)
    return objects, None


def _armature(args: dict, required: bool = True):
    name = args.get("armature")
    if not name:
        if required:
            return None, _contract.fail("bad_args", detail="missing 'armature'")
        return None, None
    obj = bpy.data.objects.get(name)
    if obj is None:
        return None, _contract.fail("object_not_found", object=name)
    if obj.type != "ARMATURE":
        return None, _contract.fail("wrong_object_type", object=name, type=obj.type)
    return obj, None


def _midline_x(obj, args: dict):
    """
    World-space x of the bilateral midline: explicit ``center_x`` wins,
    else the perception symmetry plane (must be X-ish, like the character
    skills require).
    """
    if args.get("center_x") is not None:
        return float(args["center_x"]), None
    symmetry = perception.symmetry_plane(obj)
    normal = symmetry.get("normal")
    if not symmetry.get("found") or normal is None or abs(normal[0]) < 0.9:
        return None, _contract.fail(
            "no_symmetry_plane",
            asymmetry_pct=symmetry.get("asymmetry_pct"),
            suggest="pass args={'center_x': <world x of the midline>}")
    point = np.asarray(symmetry["point"], dtype=np.float64)
    normal = np.asarray(normal, dtype=np.float64)
    return float(point @ normal / normal[0]), None


def _group_stats(obj, rig=None) -> dict:
    """
    Per-group coverage: weighted-vert counts and weight mass, plus which
    groups map to deform bones.
    """
    deform = {b.name for b in rig.data.bones if b.use_deform} if rig else None
    counts = {g.index: 0 for g in obj.vertex_groups}
    mass = {g.index: 0.0 for g in obj.vertex_groups}
    for v in obj.data.vertices:
        for ge in v.groups:
            if ge.weight > 0.0 and ge.group in counts:
                counts[ge.group] += 1
                mass[ge.group] += ge.weight
    groups = {}
    for g in obj.vertex_groups:
        groups[g.name] = {
            "weighted_verts": counts[g.index],
            "weight_mass": round(mass[g.index], 3),
        }
        if deform is not None:
            groups[g.name]["deform"] = g.name in deform
    return groups


def _run_vgroup_op(obj, op, **kwargs) -> None:
    """
    Run a ``bpy.ops.object.vertex_group_*`` operator on *obj*. Some of
    them poll only in a paint mode — fall back to WEIGHT_PAINT (with the
    selection masks off so every vertex is affected), always returning to
    OBJECT mode.
    """
    _bones.select_only([obj], active=obj)
    try:
        op(**kwargs)
        return
    except RuntimeError:
        pass
    bpy.ops.object.mode_set(mode="WEIGHT_PAINT")
    try:
        mesh = obj.data
        prev_masks = (mesh.use_paint_mask, mesh.use_paint_mask_vertex)
        mesh.use_paint_mask = False
        mesh.use_paint_mask_vertex = False
        op(**kwargs)
        mesh.use_paint_mask, mesh.use_paint_mask_vertex = prev_masks
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")


def _mutate(verb: str, body):
    """
    Snapshot -> body() -> restore + structured failure on exception or
    ok=False. *body* must re-resolve objects by name after any restore.
    """
    snapshot = _contract.scene_snapshot()
    try:
        report = body()
        if not report.get("ok"):
            _contract.scene_restore(snapshot)
            _contract.log_failure("weights." + verb, "run", report)
        return report
    except Exception as ex:
        _contract.scene_restore(snapshot)
        report = _contract.fail("exception", error=str(ex),
                                traceback=traceback.format_exc())
        _contract.log_failure("weights." + verb, "run", report)
        return report
    finally:
        if os.path.exists(snapshot):
            os.unlink(snapshot)


# -----------------------------------------------------------------------------
# Verbs


def _inspect(args: dict) -> dict:
    """
    Non-destructive coverage report: per-group weighted-vert counts,
    unweighted/unnormalized verts against the armature, empty and
    non-deform groups, and L/R balance per sided-group pair.
    """
    obj, err = _mesh(args)
    if err is not None:
        return err
    rig, err = _armature(args, required=False)
    if err is not None:
        return err

    groups = _group_stats(obj, rig)
    empty = sorted(n for n, g in groups.items() if g["weighted_verts"] == 0)

    balance = []
    for name, stats in sorted(groups.items()):
        side = _SIDE_RE.search(name)
        if side is None or side.group(1) != "L":
            continue
        twin = groups.get(_flip_side(name))
        if twin is None:
            balance.append({"left": name, "right": None,
                            "left_verts": stats["weighted_verts"]})
            continue
        n_l, n_r = stats["weighted_verts"], twin["weighted_verts"]
        entry = {"left": name, "right": _flip_side(name),
                 "left_verts": n_l, "right_verts": n_r}
        if max(n_l, n_r) > 0:
            entry["imbalance_pct"] = round(100.0 * abs(n_l - n_r) / max(n_l, n_r), 1)
        balance.append(entry)

    report = _contract.ok(
        object=obj.name,
        n_verts=len(obj.data.vertices),
        groups=groups,
        empty_groups=empty,
    )
    if balance:
        report["lr_balance"] = balance
    if rig is not None:
        validation = validate_weights(obj, rig)
        report["validation"] = validation
        deform = {b.name for b in rig.data.bones if b.use_deform}
        report["bones_without_group"] = sorted(
            deform - {g.name for g in obj.vertex_groups})
    return report


def _transfer(args: dict) -> dict:
    """
    Copy ALL vertex-group weights source -> each target by world-space
    nearest-face interpolation (the proven proxy pattern).
    """
    source, err = _mesh(args, key="source")
    if err is not None:
        return err
    target_names = args.get("targets") or ([args["target"]] if args.get("target") else [])
    if not target_names:
        return _contract.fail("bad_args", detail="missing 'targets' (or 'target')")
    if not source.vertex_groups:
        return _contract.fail("source_has_no_groups", object=source.name)
    rig, err = _armature(args, required=False)
    if err is not None:
        return err

    def body() -> dict:
        results = {}
        for name in target_names:
            target = bpy.data.objects.get(name)
            if target is None or target.type != "MESH":
                return _contract.fail("object_not_found", object=name)
            _proxy.transfer_weights(source, target)
            entry = {"n_groups": len(target.vertex_groups)}
            if rig is not None:
                validation = validate_weights(target, rig)
                entry["validation_errors"] = [e["rule"] for e in validation["errors"]]
                if any(e["rule"] == "E_UNWEIGHTED" for e in validation["errors"]):
                    return _contract.fail(
                        "transfer_failed", object=name,
                        detail=next(e["detail"] for e in validation["errors"]
                                    if e["rule"] == "E_UNWEIGHTED"),
                        suggest="source mesh doesn't cover the target; transfer "
                                "from a closer-fitting mesh, then weights('clean')")
            results[name] = entry
        return _contract.ok(source=source.name, targets=results)

    return _mutate("transfer", body)


def _mirror(args: dict) -> dict:
    """
    Directionally mirror weights across the bilateral midline: every vert
    on the destination side gets the flipped-name weights of its mirrored
    counterpart on the source side. Verts inside the midline margin keep
    their blend (the crotch SHOULD weight both thighs).
    """
    obj, err = _mesh(args)
    if err is not None:
        return err
    rig, err = _armature(args, required=False)
    if err is not None:
        return err
    from_side = args.get("from_side", "L")
    if from_side not in ("L", "R"):
        return _contract.fail("bad_args", detail="from_side must be 'L' or 'R'")
    center_x, err = _midline_x(obj, args)
    if err is not None:
        return err

    verts, _tris = perception._mesh.mesh_arrays(obj)
    if len(verts) == 0:
        return _contract.fail("empty_mesh", object=obj.name)
    diag = float(np.linalg.norm(verts.max(axis=0) - verts.min(axis=0)))
    margin = float(args.get("margin", 0.005 * diag))
    tolerance = float(args.get("tolerance", 0.02 * diag))

    # .L lives at +x (Blender convention, enforced by the character skills).
    source_sign = 1.0 if from_side == "L" else -1.0
    offsets = verts[:, 0] - center_x
    source_idx = np.nonzero(offsets * source_sign > margin)[0]
    dest_idx = np.nonzero(offsets * source_sign < -margin)[0]
    if len(source_idx) == 0 or len(dest_idx) == 0:
        return _contract.fail(
            "mirror_no_side_verts", center_x=center_x,
            n_source=int(len(source_idx)), n_dest=int(len(dest_idx)),
            suggest="check center_x — is the midline really at this x?")

    def body() -> dict:
        from mathutils import kdtree

        mesh_obj = bpy.data.objects[obj.name]
        tree = kdtree.KDTree(len(source_idx))
        for i in source_idx:
            tree.insert(verts[i], int(i))
        tree.balance()

        # Source weights by vert index, group names pre-flipped.
        names_by_index = {g.index: g.name for g in mesh_obj.vertex_groups}
        unmatched = 0
        written = 0
        for di in dest_idx:
            mirrored = verts[di].copy()
            mirrored[0] = 2.0 * center_x - mirrored[0]
            _co, si, dist = tree.find(mirrored)
            if si is None or dist > tolerance:
                unmatched += 1
                continue
            new_weights = {
                _flip_side(names_by_index[ge.group]): ge.weight
                for ge in mesh_obj.data.vertices[si].groups if ge.weight > 0.0}
            # REPLACE semantics: clear the dest vert from every group first.
            for ge in list(mesh_obj.data.vertices[di].groups):
                mesh_obj.vertex_groups[ge.group].remove([int(di)])
            for group_name, weight in new_weights.items():
                group = mesh_obj.vertex_groups.get(group_name)
                if group is None:
                    group = mesh_obj.vertex_groups.new(name=group_name)
                group.add([int(di)], weight, "REPLACE")
            written += 1

        if written == 0:
            return _contract.fail(
                "mirror_no_match", tolerance=tolerance, unmatched=unmatched,
                suggest="raise 'tolerance' — the two sides may differ in "
                        "tessellation, or the mesh is genuinely asymmetric")
        report = _contract.ok(
            object=mesh_obj.name, from_side=from_side, center_x=center_x,
            verts_written=written, verts_unmatched=unmatched,
            margin=margin)
        if rig is not None:
            arm = bpy.data.objects[rig.name]
            validation = validate_weights(mesh_obj, arm)
            report["validation_errors"] = [e["rule"] for e in validation["errors"]]
        return report

    return _mutate("mirror", body)


def _clean(args: dict) -> dict:
    """
    Prune tiny weights, cap influences per vert, drop empty groups,
    normalize — the standard cleanup pass after transfer/painting.
    """
    obj, err = _mesh(args)
    if err is not None:
        return err
    rig, err = _armature(args, required=False)
    if err is not None:
        return err
    threshold = float(args.get("threshold", 0.01))
    limit = int(args.get("limit", 4))
    normalize = bool(args.get("normalize", True))
    remove_empty = bool(args.get("remove_empty", True))

    def body() -> dict:
        mesh_obj = bpy.data.objects[obj.name]
        before = _group_stats(mesh_obj)
        # keep_single guards against creating unweighted verts.
        _run_vgroup_op(mesh_obj, bpy.ops.object.vertex_group_clean,
                       group_select_mode="ALL", limit=threshold, keep_single=True)
        if limit > 0:
            _run_vgroup_op(mesh_obj, bpy.ops.object.vertex_group_limit_total,
                           group_select_mode="ALL", limit=limit)
        if normalize:
            _run_vgroup_op(mesh_obj, bpy.ops.object.vertex_group_normalize_all,
                           lock_active=False)
        removed = []
        if remove_empty:
            after = _group_stats(mesh_obj)
            for name, stats in after.items():
                if stats["weighted_verts"] == 0:
                    mesh_obj.vertex_groups.remove(mesh_obj.vertex_groups[name])
                    removed.append(name)
        report = _contract.ok(
            object=mesh_obj.name,
            threshold=threshold, limit=limit, normalized=normalize,
            removed_empty_groups=sorted(removed),
            groups_before=len(before),
            groups_after=len(mesh_obj.vertex_groups),
        )
        if rig is not None:
            arm = bpy.data.objects[rig.name]
            validation = validate_weights(mesh_obj, arm)
            report["validation_errors"] = [e["rule"] for e in validation["errors"]]
        return report

    return _mutate("clean", body)


def _smooth(args: dict) -> dict:
    """
    Blur weights along the topology (fixes hard transfer seams and
    stair-stepping). Optional group globs restrict the pass.
    """
    obj, err = _mesh(args)
    if err is not None:
        return err
    rig, err = _armature(args, required=False)
    if err is not None:
        return err
    factor = float(args.get("factor", 0.5))
    iterations = int(args.get("iterations", 3))
    expand = float(args.get("expand", 0.0))
    patterns = args.get("groups")

    def body() -> dict:
        mesh_obj = bpy.data.objects[obj.name]
        if patterns:
            matched = [g.name for g in mesh_obj.vertex_groups
                       if any(fnmatch.fnmatch(g.name, p) for p in patterns)]
            if not matched:
                return _contract.fail(
                    "no_groups_matched", patterns=patterns,
                    available=[g.name for g in mesh_obj.vertex_groups])
            for name in matched:
                mesh_obj.vertex_groups.active_index = \
                    mesh_obj.vertex_groups[name].index
                _run_vgroup_op(mesh_obj, bpy.ops.object.vertex_group_smooth,
                               group_select_mode="ACTIVE", factor=factor,
                               repeat=iterations, expand=expand)
        else:
            matched = [g.name for g in mesh_obj.vertex_groups]
            _run_vgroup_op(mesh_obj, bpy.ops.object.vertex_group_smooth,
                           group_select_mode="ALL", factor=factor,
                           repeat=iterations, expand=expand)
        if rig is not None and bool(args.get("normalize", True)):
            _run_vgroup_op(mesh_obj, bpy.ops.object.vertex_group_normalize_all,
                           lock_active=False)
        report = _contract.ok(
            object=mesh_obj.name, groups=sorted(matched),
            factor=factor, iterations=iterations)
        if rig is not None:
            arm = bpy.data.objects[rig.name]
            validation = validate_weights(mesh_obj, arm)
            report["validation_errors"] = [e["rule"] for e in validation["errors"]]
        return report

    return _mutate("smooth", body)


def _bind(args: dict) -> dict:
    """
    Armature modifier + parent (transform preserved) for each object.
    Weights must already exist (painted, transferred or mirrored) unless
    ``allow_unweighted`` says this is a pre-weighting bind.
    """
    objects, err = _meshes(args)
    if err is not None:
        return err
    rig, err = _armature(args)
    if err is not None:
        return err
    allow_unweighted = bool(args.get("allow_unweighted"))

    def body() -> dict:
        arm = bpy.data.objects[rig.name]
        results = {}
        for src in objects:
            target = bpy.data.objects[src.name]
            _proxy.bind_to_rig(target, arm)
            validation = validate_weights(target, arm)
            rules = [e["rule"] for e in validation["errors"]]
            if not allow_unweighted and (
                    "E_NO_DEFORM_GROUPS" in rules or "E_UNWEIGHTED" in rules):
                return _contract.fail(
                    "bind_unweighted", object=target.name, errors=rules,
                    suggest="weights('transfer') from a weighted mesh first, "
                            "or pass {'allow_unweighted': True} if weights "
                            "come later")
            results[target.name] = {"validation_errors": rules}
        bpy.context.view_layer.update()
        return _contract.ok(armature=arm.name, objects=results)

    return _mutate("bind", body)


def _validate(args: dict) -> dict:
    """
    validate_weights() for each object against the armature — the QA gate.
    """
    objects, err = _meshes(args)
    if err is not None:
        return err
    rig, err = _armature(args)
    if err is not None:
        return err
    reports = {o.name: validate_weights(o, rig) for o in objects}
    return {"ok": all(r["ok"] for r in reports.values()), "objects": reports}


_VERBS = {
    "inspect": _inspect,
    "transfer": _transfer,
    "mirror": _mirror,
    "clean": _clean,
    "smooth": _smooth,
    "bind": _bind,
    "validate": _validate,
}


def dispatch(verb: str, args: dict | None) -> dict:
    fn = _VERBS.get(verb)
    if fn is None:
        return _contract.fail("unknown_verb", verb=verb, valid=sorted(_VERBS))
    return fn(args or {})
