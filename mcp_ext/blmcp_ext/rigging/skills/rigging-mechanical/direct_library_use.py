# Sample: driving blrig directly from execute_blender_code when the
# rigging_* tools' fixed flows don't fit (custom orchestration, batch
# rigging, perception-driven decisions of your own).
#
# Adjust BLRIG_PARENT to the installed blender-mcp-extensions location —
# the `rigging_inspect` tool's own code does exactly this bootstrap, or
# import blmcp_ext.rigging and read BLRIG_PARENT_DIR server-side.

import sys

BLRIG_PARENT = "<path-to>/blmcp_ext/rigging"
if BLRIG_PARENT not in sys.path:
    sys.path.insert(0, BLRIG_PARENT)

from blrig import perception
from blrig import skills

# Perception is pure/read-only and JSON-serializable throughout.
import bpy
obj = bpy.data.objects["Door"]
health = perception.mesh_health(obj)          # gate first, always
sections = perception.cross_sections(obj, axis="z", n=16)

# Skills follow diagnose/run/verify; ctx is a plain dict.
ctx = {"objects": ["Frame", "Door"]}
hinge = skills.get_skill("rig_hinge")
report = hinge.diagnose(ctx)
if report["ok"]:
    outcome = hinge.run(ctx, {"max_angle_deg": 90.0})
    checks = hinge.verify(ctx)                # ctx now carries "armature"
    result = {"run": outcome, "verify": checks}
else:
    result = {"diagnose": report}             # carries fail code + suggest
