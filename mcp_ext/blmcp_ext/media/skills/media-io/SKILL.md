---
name: media-io
description: Importing user attachments (stl, obj, gltf, fbx, usd, svg, images, audio), exporting deliverable files (blend, stl, obj, gltf/glb, fbx, usd, abc, svg/pdf), rendering frames and encoding videos (mp4/webm/gif via ffmpeg) for the user, and staging existing files — the media_io tool, jail rules, collision handling, format notes.
keywords: import, export, render, screenshot, picture, file, save, load, attachment, stl, obj, gltf, glb, fbx, usd, svg, image, png, jpg, audio, video, movie, clip, animation, walk cycle, turntable, mp4, webm, gif, ffmpeg, encode, download, upload, deliverable, stage
aliases: [media_io, media]
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
4. Show an image: `media_io("render", {"frame": 12})` — renders one
   frame straight to the media folder (works headless; no
   window/viewport needed). Picks the scene camera, or the only camera,
   or errors asking for one — it never invents a viewpoint. `format`
   png (default) / jpg / webp / exr. `media_io("export", {"format":
   "png"})` does the same thing.
5. Show an animation: `media_io("video", {"start": 1, "end": 48, "fps":
   24})` — renders the frame range and encodes ONE clip
   (`mp4` default / `mov` / `webm` / `gif`) straight to the media folder
   (works headless). Defaults to the scene frame range and 24fps; `step`
   subsamples, `quality` is high/medium/low, `camera` overrides. This is
   the way to deliver a turntable or a looping walk cycle. Needs a
   system `ffmpeg` (auto-located on PATH / common OS paths); pass
   `{"ffmpeg": "/path/to/ffmpeg"}` only if it lives somewhere unusual.
6. Already wrote a file somewhere else (a render output path, a baked
   cache)? `media_io("stage", {"path": "/tmp/out.png"})` copies it into
   the media folder — don't copy by hand in execute_blender_code.

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
