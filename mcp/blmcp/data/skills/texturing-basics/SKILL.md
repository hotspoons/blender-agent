---
name: texturing-basics
description: Set up a PBR material with image textures, including UV unwrap and correct color spaces.
keywords: texture, texturing, material, pbr, shader, uv, unwrap, albedo, roughness, normal map, color, paint
---

# Texturing: UVs and a principled material

Set up a PBR material with image textures, including UV unwrap and correct color spaces.

## Smart unwrap when no UVs exist

```python
import bpy
obj = bpy.data.objects["TARGET"]
if not obj.data.uv_layers:
    with bpy.context.temp_override(object=obj, active_object=obj, selected_objects=[obj]):
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.smart_project(angle_limit=1.15192, island_margin=0.003)
        bpy.ops.object.mode_set(mode="OBJECT")
result = {"uv_layers": [uv.name for uv in obj.data.uv_layers]}
```

For hard-surface objects prefer seams + `unwrap`; smart_project is the
dependable default when nobody will hand-paint.

## Principled material with texture maps

```python
import bpy
mat = bpy.data.materials.get("MAT") or bpy.data.materials.new("MAT")
mat.use_nodes = True
nodes = mat.node_tree.nodes
links = mat.node_tree.links
bsdf = nodes["Principled BSDF"]

def tex(path, colorspace):
    node = nodes.new("ShaderNodeTexImage")
    node.image = bpy.data.images.load(path, check_existing=True)
    node.image.colorspace_settings.name = colorspace
    return node

base = tex("//textures/base_color.png", "sRGB")
rough = tex("//textures/roughness.png", "Non-Color")
nrm_img = tex("//textures/normal.png", "Non-Color")
nrm = nodes.new("ShaderNodeNormalMap")

links.new(base.outputs["Color"], bsdf.inputs["Base Color"])
links.new(rough.outputs["Color"], bsdf.inputs["Roughness"])
links.new(nrm_img.outputs["Color"], nrm.inputs["Color"])
links.new(nrm.outputs["Normal"], bsdf.inputs["Normal"])

obj = bpy.data.objects["TARGET"]
if mat.name not in [m.name for m in obj.data.materials if m]:
    obj.data.materials.append(mat)
result = {"material": mat.name, "slots": len(obj.data.materials)}
```

## Gotchas

- Color space is the #1 silent mistake: ONLY base color is sRGB;
  roughness/metallic/normal/AO must be Non-Color or shading looks flat
  or plasticky.
- `//` path prefix is blend-file-relative; verify the file is saved
  before relying on it (`bpy.data.filepath`).
- Principled input names differ across Blender versions (e.g.
  "Specular" became "Specular IOR Level" in 4.x). Check
  `get_python_api_docs` or `bsdf.inputs.keys()` at runtime instead of
  hardcoding from memory.
- Verify in a render, not the solid viewport: switch to Material
  Preview or do a small `render_thumbnail_to_path` and inspect it.
