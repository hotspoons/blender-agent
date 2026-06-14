# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Bundled Tier-B tool: snap a part so one of its ports mates a target frame.

Given a source port (center + axis) and a target frame (center + axis),
rigid-transform the whole object so the source center lands on the target
center and the source axis aligns with the target axis. The free spin about the
shared axis is left at the nearest alignment.

Reads dict ``params`` (name, source_center, source_axis, target_center,
target_axis, nearest); assigns dict ``result`` ({status, name, world_location,
message}).
"""


def _run(params: dict) -> dict:
    import bpy  # pylint: disable=import-error,no-name-in-module
    import mathutils  # pylint: disable=import-error,no-name-in-module

    name = params["name"]
    obj = bpy.data.objects.get(name)
    if obj is None:
        available = sorted(bpy.data.objects.keys())
        return {
            "status": "error",
            "message": "Object {!r} not found. Available objects: {:s}".format(
                name, ", ".join(available) if available else "(none)",
            ),
        }

    a_s = mathutils.Vector(params["source_axis"])
    a_t = mathutils.Vector(params["target_axis"])
    if a_s.length == 0.0 or a_t.length == 0.0:
        return {"status": "error", "message": "Axis vectors must be non-zero."}
    a_s.normalize()
    a_t.normalize()
    if params.get("nearest", True) and a_s.dot(a_t) < 0.0:
        a_t = -a_t

    c_s = mathutils.Vector(params["source_center"])
    c_t = mathutils.Vector(params["target_center"])

    rot = a_s.rotation_difference(a_t).to_matrix().to_4x4()
    transform = (
        mathutils.Matrix.Translation(c_t)
        @ rot
        @ mathutils.Matrix.Translation(-c_s)
    )
    obj.matrix_world = transform @ obj.matrix_world

    loc = obj.matrix_world.translation
    return {
        "status": "ok",
        "name": obj.name,
        "world_location": [round(float(v), 4) for v in loc],
    }


result = _run(params)  # noqa: F821  (params/result are injected by the sandbox)
