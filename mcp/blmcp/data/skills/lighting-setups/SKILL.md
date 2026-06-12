---
name: lighting-setups
description: Two dependable lighting starts: a classic three-point rig scaled to the subject, and HDRI world lighting.
keywords: light, lighting, lamp, key, fill, rim, three-point, hdri, environment, world, render, studio, illumination
---

# Lighting: three-point and HDRI environment setups

Two dependable lighting starts: a classic three-point rig scaled to the subject, and HDRI world lighting.

## Three-point rig scaled to subject

```python
import bpy, math
from mathutils import Vector

subject = bpy.data.objects["TARGET"]
center = subject.matrix_world.translation
size = max(subject.dimensions) or 1.0

def area_light(name, power_w, loc, size_m):
    light = bpy.data.lights.get(name) or bpy.data.lights.new(name, type="AREA")
    light.energy = power_w
    light.size = size_m
    obj = bpy.data.objects.get(name) or bpy.data.objects.new(name, light)
    if obj.name not in {o.name for o in bpy.context.scene.collection.all_objects}:
        bpy.context.scene.collection.objects.link(obj)
    obj.location = loc
    # Aim at the subject.
    direction = center - Vector(loc)
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    return obj

key = area_light("LGT-key", 400 * size, (center.x + 2.2 * size, center.y - 2.2 * size, center.z + 1.8 * size), size)
fill = area_light("LGT-fill", 120 * size, (center.x - 2.6 * size, center.y - 1.8 * size, center.z + 0.9 * size), 1.6 * size)
rim = area_light("LGT-rim", 250 * size, (center.x - 0.6 * size, center.y + 2.6 * size, center.z + 2.0 * size), 0.7 * size)
result = {"lights": [key.name, fill.name, rim.name], "subject_size": size}
```

Ratios: fill ~1/3 of key, rim between key and fill; warm the key
(`light.color = (1.0, 0.94, 0.88)`) and cool the rim slightly for a
studio look.

## HDRI environment

```python
import bpy
world = bpy.context.scene.world or bpy.data.worlds.new("World")
bpy.context.scene.world = world
world.use_nodes = True
nodes, links = world.node_tree.nodes, world.node_tree.links
env = nodes.get("Environment Texture") or nodes.new("ShaderNodeTexEnvironment")
env.image = bpy.data.images.load("//hdri/studio.exr", check_existing=True)
background = nodes["Background"]
links.new(env.outputs["Color"], background.inputs["Color"])
background.inputs["Strength"].default_value = 1.0
result = {"world": world.name}
```

## Gotchas

- Light `energy` is in watts and does NOT scale with the scene - a rig
  that flatters a 10 cm prop is invisible on a building. Scale power
  by subject size as above, then iterate from a test render.
- EEVEE vs Cycles disagree about area-light falloff and HDRI shadows;
  always check `scene.render.engine` and judge from a render in the
  engine the user will ship.
- If everything is washed out, look at view transform
  (`scene.view_settings.view_transform`, AgX vs Standard) before
  touching lights.
- Use `render_thumbnail_to_path` for fast iteration; only do full
  renders once the balance looks right.
