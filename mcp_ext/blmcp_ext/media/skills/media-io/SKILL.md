---
name: media-io
description: Importing user attachments (stl, obj, gltf, fbx, usd, svg, images, audio) into the scene and exporting deliverable files (blend, stl, obj, gltf/glb, fbx, usd, abc, svg/pdf) with the media_io tool — jail rules, collision handling, format notes.
---

# Media import & export

All user-facing file IO goes through the `media_io` tool and ONE media
folder per conversation (the "jail"): user attachments appear there, and
anything you export there becomes downloadable by the user. Never read or
write files from `execute_blender_code` — paths outside the jail are not
served to the user and won't survive the session.

## Workflow

1. The user mentions an attachment or you need to deliver a file →
   `media_io("list", {})` to see what exists.
2. Import: `media_io("import", {"name": "dragon.stl"})` — returns the
   created object names (importers may add `.001` suffixes; use the
   returned names, don't guess).
3. Export: `media_io("export", {"format": "stl", "objects": ["Dragon"]})`
   — omit `objects` to export the whole scene. Returns the actual
   filename written: collisions never overwrite, they suffix
   (`dragon-2.stl`), so ALWAYS relay the returned name to the user.

## Import dispatch (by extension)

| Type | Extensions | Lands as |
|---|---|---|
| Mesh/scene | stl obj ply gltf glb fbx usd usda usdc usdz abc | imported objects |
| Vector | svg | curve objects (scaled tiny — svg units are mm; scale up as needed) |
| Image | png jpg jpeg webp tif tiff exr bmp hdr | reference image-empty (`options.display_size` to size it) |
| Audio | wav mp3 ogg flac aif aiff | speaker object carrying the sound |

To use an imported image as a material texture instead of a reference
empty, load it onto a material via `execute_blender_code`
(`bpy.data.images` already holds it after import).

## Export formats

`blend` (full project copy), `stl` `obj` `ply` (geometry), `gltf` `glb`
(scene+materials, glb = single binary file — prefer it for delivery),
`fbx`, `usd`/`usdc`/`usda`, `abc`. `svg`/`pdf` render grease-pencil
strokes only — a scene without grease pencil cannot export svg; offer
glb/stl instead.

When the user asks for "the file" without a format: a .blend if they use
Blender, .glb for sharing/web, .stl for printing.

## Failure notes

- `path ... escapes the media folder` — only bare filenames from
  `list` are valid; no directories, no absolute paths.
- `unsupported import type` — tell the user which types are supported
  rather than converting blindly.
- Large meshes import fine but thumbnails in the chat UI only render
  under 20 MB.
