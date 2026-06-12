# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
``blmedia``: jailed media import/export for LLM agents driving Blender.

Runs inside Blender's Python. All file IO is confined to one "jail"
directory: the agent injects its per-session media folder; standalone MCP
clients get a global folder (``BLENDER_MCP_MEDIA_DIR`` env on the Blender
side, default ``~/.local/share/blender-mcp/media``). Paths are resolved
against the jail with containment checks, and written filenames are
collision-suffixed (``name-2.ext``) rather than overwritten.
"""

__all__ = (
    "export_file",
    "find_ffmpeg",
    "render_video",
    "import_file",
    "info_file",
    "list_files",
    "render_frame",
    "resolve_jail",
    "stage_file",
    "unique_path",
)

import glob
import os
import re
import shutil
import subprocess
import tempfile

import bpy

_DEFAULT_JAIL = os.path.join("~", ".local", "share", "blender-mcp", "media")

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._ ()+-]+")

_MESH_EXTS = ("stl", "obj", "ply", "gltf", "glb", "fbx",
              "usd", "usda", "usdc", "usdz", "abc")
_IMAGE_EXTS = ("png", "jpg", "jpeg", "webp", "tif", "tiff", "exr", "bmp", "hdr")
_AUDIO_EXTS = ("wav", "mp3", "ogg", "flac", "aif", "aiff")

_EXPORT_FORMATS = ("blend", "stl", "obj", "ply", "gltf", "glb", "fbx",
                   "usd", "usdc", "usda", "abc", "svg", "pdf")

# Image formats accepted by export_file (delegated to render_frame —
# "export me a png" intuitively means "render the scene to an image").
_IMAGE_RENDER_FORMATS = {
    "png": "PNG",
    "jpg": "JPEG",
    "jpeg": "JPEG",
    "webp": "WEBP",
    "exr": "OPEN_EXR",
}

# Container formats the video verb encodes (frames -> clip via ffmpeg).
_VIDEO_FORMATS = ("mp4", "mov", "webm", "gif")

# Where ffmpeg commonly lives, checked AFTER $PATH so an explicit/PATH
# binary always wins. Covers Linux distros, Homebrew (Intel + Apple
# Silicon), MacPorts, snap, and the usual Windows drops.
_FFMPEG_COMMON = (
    "/usr/bin/ffmpeg",
    "/usr/local/bin/ffmpeg",
    "/opt/homebrew/bin/ffmpeg",
    "/opt/local/bin/ffmpeg",
    "/snap/bin/ffmpeg",
    r"C:\ffmpeg\bin\ffmpeg.exe",
    r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
    r"C:\Program Files\ffmpeg\ffmpeg.exe",
)

_VIDEO_CRF = {"high": 18, "medium": 23, "low": 28}


def kind_of(name: str) -> str:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext in _MESH_EXTS:
        return "mesh"
    if ext == "svg":
        return "vector"
    if ext in _IMAGE_EXTS:
        return "image"
    if ext in _AUDIO_EXTS:
        return "audio"
    if ext == "blend":
        return "blend"
    return "other"


def resolve_jail(jail: str | None) -> str:
    """
    Absolute jail directory (created on demand). *jail* of ``None`` falls
    back to ``BLENDER_MCP_MEDIA_DIR`` / the user-global default — both
    evaluated HERE, inside Blender, which may be a different machine from
    the MCP server.
    """
    path = jail or os.environ.get("BLENDER_MCP_MEDIA_DIR") or _DEFAULT_JAIL
    path = os.path.abspath(os.path.expanduser(path))
    os.makedirs(path, exist_ok=True)
    return path


def safe_name(filename: str) -> str:
    base = os.path.basename(filename.replace("\\", "/")).strip()
    base = _SAFE_NAME_RE.sub("_", base).lstrip(".")
    return base or "file"


def jail_path(jail: str, name: str, must_exist: bool = False) -> str:
    """
    Resolve *name* inside *jail*; raises ``ValueError`` on escape attempts
    or (optionally) missing files.
    """
    candidate = os.path.abspath(os.path.join(jail, name))
    if not candidate.startswith(jail + os.sep):
        raise ValueError("path {!r} escapes the media folder".format(name))
    if must_exist and not os.path.isfile(candidate):
        raise ValueError("no such file {!r} in the media folder".format(name))
    return candidate


def unique_path(jail: str, name: str) -> str:
    """
    Collision-safe target path: ``name.ext`` then ``name-2.ext`` ...
    """
    name = safe_name(name)
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    candidate = jail_path(jail, name)
    counter = 2
    while os.path.exists(candidate):
        suffixed = "{:s}-{:d}{:s}".format(stem or ext, counter, dot + ext if stem else "")
        candidate = jail_path(jail, suffixed)
        counter += 1
    return candidate


def list_files(jail: str | None = None) -> dict:
    root = resolve_jail(jail)
    files = []
    for entry in sorted(os.listdir(root)):
        path = os.path.join(root, entry)
        if not os.path.isfile(path):
            continue
        files.append({
            "name": entry,
            "size": os.path.getsize(path),
            "kind": kind_of(entry),
            "modified": os.path.getmtime(path),
        })
    return {"folder": root, "files": files}


def info_file(name: str, jail: str | None = None) -> dict:
    root = resolve_jail(jail)
    path = jail_path(root, name, must_exist=True)
    return {
        "name": os.path.relpath(path, root),
        "size": os.path.getsize(path),
        "kind": kind_of(name),
        "modified": os.path.getmtime(path),
    }


# -----------------------------------------------------------------------------
# Import


def _new_datablocks(before: set, collection) -> list:
    return [item for item in collection if item.name not in before]


def import_file(name: str, jail: str | None = None, options: dict | None = None) -> dict:
    """
    Import jail file *name* into the current scene. Dispatch is by
    extension: meshes via the native importers, SVG as curves, images as
    image-empties (reference objects), audio as a speaker object.
    Returns the created object names.
    """
    options = options or {}
    root = resolve_jail(jail)
    path = jail_path(root, name, must_exist=True)
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    kind = kind_of(name)

    before = {o.name for o in bpy.data.objects}

    if kind == "mesh":
        operator = {
            "stl": lambda: bpy.ops.wm.stl_import(filepath=path),
            "obj": lambda: bpy.ops.wm.obj_import(filepath=path),
            "ply": lambda: bpy.ops.wm.ply_import(filepath=path),
            "gltf": lambda: bpy.ops.import_scene.gltf(filepath=path),
            "glb": lambda: bpy.ops.import_scene.gltf(filepath=path),
            "fbx": lambda: bpy.ops.wm.fbx_import(filepath=path),
            "usd": lambda: bpy.ops.wm.usd_import(filepath=path),
            "usda": lambda: bpy.ops.wm.usd_import(filepath=path),
            "usdc": lambda: bpy.ops.wm.usd_import(filepath=path),
            "usdz": lambda: bpy.ops.wm.usd_import(filepath=path),
            "abc": lambda: bpy.ops.wm.alembic_import(filepath=path),
        }[ext]
        operator()
    elif kind == "vector":
        import addon_utils
        addon_utils.enable("io_curve_svg", default_set=False)
        bpy.ops.import_curve.svg(filepath=path)
    elif kind == "image":
        image = bpy.data.images.load(path)
        empty = bpy.data.objects.new(safe_name(name), None)
        empty.empty_display_type = "IMAGE"
        empty.data = image
        empty.empty_display_size = float(options.get("display_size", 1.0))
        bpy.context.scene.collection.objects.link(empty)
    elif kind == "audio":
        sound = bpy.data.sounds.load(path)
        speaker_data = bpy.data.speakers.new(safe_name(name))
        speaker_data.sound = sound
        speaker = bpy.data.objects.new(safe_name(name), speaker_data)
        bpy.context.scene.collection.objects.link(speaker)
    else:
        raise ValueError(
            "unsupported import type {!r}; supported: {}".format(
                ext, ", ".join(_MESH_EXTS + ("svg",) + _IMAGE_EXTS + _AUDIO_EXTS)))

    created = sorted(o.name for o in bpy.data.objects if o.name not in before)
    return {
        "imported": os.path.relpath(path, root),
        "kind": kind,
        "objects": created,
        "n_objects": len(created),
    }


# -----------------------------------------------------------------------------
# Export


def _select_only(objects: list) -> tuple:
    """
    Set selection/active to *objects*, returning previous state for restore.
    """
    view_layer = bpy.context.view_layer
    previous = ([o for o in view_layer.objects if o.select_get()],
                view_layer.objects.active)
    for o in view_layer.objects:
        o.select_set(False)
    for o in objects:
        o.select_set(True)
    view_layer.objects.active = objects[0] if objects else None
    return previous


def _restore_selection(previous: tuple) -> None:
    selected, active = previous
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    for o in selected:
        try:
            o.select_set(True)
        except ReferenceError:
            pass
    try:
        bpy.context.view_layer.objects.active = active
    except ReferenceError:
        pass


def stage_file(path: str, jail: str | None = None,
               filename: str | None = None) -> dict:
    """
    Copy an EXISTING file on disk (a render output, a baked cache, a
    file produced by other code) into the jail so the user can see and
    download it. The intuitive "I already made this file - hand it to
    the user" verb.
    """
    import shutil

    source = os.path.abspath(os.path.expanduser(str(path)))
    if not os.path.isfile(source):
        raise ValueError("no file at {!r} to stage".format(path))
    root = resolve_jail(jail)
    target = unique_path(root, filename or os.path.basename(source))
    shutil.copyfile(source, target)
    name = os.path.relpath(target, root)
    return {
        "file": name,
        "folder": root,
        "size": os.path.getsize(target),
        "kind": kind_of(name),
        "staged_from": source,
    }


def render_frame(jail: str | None = None, frame: int | None = None,
                 filename: str | None = None, format: str = "png",
                 camera: str | None = None) -> dict:
    """
    Render one frame of the current scene straight into the jail and
    return the filename — the one-call "show the user an image" path.
    Uses the scene's render settings (engine, resolution) as they are;
    only the output path/format are overridden and then restored.
    """
    format = (format or "png").lower().lstrip(".")
    file_format = _IMAGE_RENDER_FORMATS.get(format)
    if file_format is None:
        raise ValueError("unsupported image format {!r}; supported: {}".format(
            format, ", ".join(sorted(_IMAGE_RENDER_FORMATS))))

    scene = bpy.context.scene
    cam = bpy.data.objects.get(camera) if camera else scene.camera
    if camera and (cam is None or cam.type != "CAMERA"):
        raise ValueError("no camera object named {!r}".format(camera))
    if cam is None:
        # One camera in the scene is unambiguous — use it.
        cameras = [o for o in bpy.data.objects if o.type == "CAMERA"]
        if len(cameras) == 1:
            cam = cameras[0]
        else:
            raise ValueError(
                "the scene has no active camera ({:d} camera objects); add one "
                "(bpy.ops.object.camera_add) or pass {{'camera': name}}".format(
                    len(cameras)))

    root = resolve_jail(jail)
    stem = safe_name(filename or "render")
    ext = "jpg" if format == "jpeg" else format
    if not stem.lower().endswith("." + ext):
        stem += "." + ext
    path = unique_path(root, stem)

    previous = (scene.camera, scene.frame_current,
                scene.render.filepath, scene.render.image_settings.file_format)
    try:
        scene.camera = cam
        if frame is not None:
            scene.frame_set(int(frame))
        scene.render.filepath = path
        scene.render.image_settings.file_format = file_format
        bpy.ops.render.render(write_still=True)
    finally:
        (scene.camera, scene.frame_current,
         scene.render.filepath,
         scene.render.image_settings.file_format) = previous

    if not os.path.isfile(path):
        raise RuntimeError("render produced no file at {!r}".format(path))
    return {
        "file": os.path.relpath(path, root),
        "folder": root,
        "size": os.path.getsize(path),
        "format": format,
        "frame": int(frame) if frame is not None else previous[1],
        "camera": cam.name,
    }


def export_file(format: str, jail: str | None = None,
                objects: list | None = None,
                filename: str | None = None,
                options: dict | None = None) -> dict:
    """
    Export the scene (or the named *objects*) as *format* into the jail.
    Returns the (collision-suffixed) filename and size. Image formats
    delegate to :func:`render_frame` — asking to "export a png" means
    rendering the scene.
    """
    format = (format or "").lower().lstrip(".")
    if format in _IMAGE_RENDER_FORMATS:
        return render_frame(
            jail=jail, filename=filename, format=format,
            frame=(options or {}).get("frame"),
            camera=(options or {}).get("camera"))
    del options  # reserved for the non-image exporters
    if format not in _EXPORT_FORMATS:
        raise ValueError(
            "unsupported export format {!r}; supported: {} (or an image "
            "format {} to render the scene; or media_io('stage', ...) for "
            "a file that already exists on disk)".format(
                format, ", ".join(_EXPORT_FORMATS),
                "/".join(sorted(_IMAGE_RENDER_FORMATS))))

    root = resolve_jail(jail)
    targets = []
    if objects:
        for name in objects:
            obj = bpy.data.objects.get(name)
            if obj is None:
                raise ValueError("no object named {!r}".format(name))
            targets.append(obj)

    stem = filename or (targets[0].name if targets else
                        os.path.splitext(os.path.basename(bpy.data.filepath))[0] or "scene")
    stem = safe_name(stem)
    if not stem.lower().endswith("." + format):
        stem += "." + format
    path = unique_path(root, stem)

    selection = None
    use_selection = bool(targets)
    if use_selection:
        selection = _select_only(targets)
    try:
        if format == "blend":
            bpy.ops.wm.save_as_mainfile(filepath=path, copy=True, compress=True)
        elif format == "stl":
            bpy.ops.wm.stl_export(filepath=path, export_selected_objects=use_selection)
        elif format == "obj":
            bpy.ops.wm.obj_export(filepath=path, export_selected_objects=use_selection)
        elif format == "ply":
            bpy.ops.wm.ply_export(filepath=path, export_selected_objects=use_selection)
        elif format in ("gltf", "glb"):
            bpy.ops.export_scene.gltf(
                filepath=path, use_selection=use_selection,
                export_format="GLB" if format == "glb" else "GLTF_EMBEDDED")
        elif format == "fbx":
            bpy.ops.export_scene.fbx(filepath=path, use_selection=use_selection)
        elif format in ("usd", "usda", "usdc"):
            bpy.ops.wm.usd_export(filepath=path, selected_objects_only=use_selection)
        elif format == "abc":
            bpy.ops.wm.alembic_export(filepath=path, selected=use_selection)
        elif format in ("svg", "pdf"):
            # Grease-pencil line export — the only native vector output.
            has_gp = any(o.type in ("GPENCIL", "GREASEPENCIL") for o in bpy.data.objects)
            if not has_gp:
                raise ValueError(
                    "svg/pdf export renders grease-pencil strokes and this scene "
                    "has none; for mesh outlines convert or use stl/gltf instead")
            op = (bpy.ops.wm.grease_pencil_export_svg if format == "svg"
                  else bpy.ops.wm.grease_pencil_export_pdf)
            op(filepath=path, use_uniform_width=True)
    finally:
        if selection is not None:
            _restore_selection(selection)

    if not os.path.isfile(path):
        raise RuntimeError("exporter produced no file at {!r}".format(path))
    return {
        "file": os.path.relpath(path, root),
        "folder": root,
        "size": os.path.getsize(path),
        "format": format,
        "objects": [o.name for o in targets] if targets else "scene",
    }


def find_ffmpeg(explicit: str | None = None) -> str | None:
    """
    Locate the ``ffmpeg`` binary. Priority: an explicit path (a file, or
    a directory containing the binary), then ``$PATH``, then the common
    per-OS install locations. Returns the path or ``None``. Blender
    bundles libav for *encoding* but not the ffmpeg CLI, so the agent
    relies on a system ffmpeg here.
    """
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    if explicit:
        cand = os.path.expanduser(explicit)
        if os.path.isdir(cand):
            cand = os.path.join(cand, exe)
        return cand if (os.path.isfile(cand) and os.access(cand, os.X_OK)) else None
    found = shutil.which("ffmpeg")
    if found:
        return found
    for cand in _FFMPEG_COMMON:
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


def _ffmpeg_encode_cmd(binary: str, pattern: str, fps: int, fmt: str,
                       quality: str, out_path: str) -> list:
    """Argv to encode the zero-padded PNG sequence *pattern* to *out_path*."""
    crf = _VIDEO_CRF.get(quality, _VIDEO_CRF["medium"])
    cmd = [binary, "-y", "-loglevel", "error", "-framerate", str(fps), "-i", pattern]
    # h264/vp9 need even dimensions and a broadly-playable pixel format.
    even = "scale=trunc(iw/2)*2:trunc(ih/2)*2"
    if fmt in ("mp4", "mov"):
        return cmd + ["-vf", even, "-c:v", "libx264", "-crf", str(crf),
                      "-pix_fmt", "yuv420p", out_path]
    if fmt == "webm":
        return cmd + ["-vf", even, "-c:v", "libvpx-vp9", "-crf", str(crf),
                      "-b:v", "0", "-pix_fmt", "yuv420p", out_path]
    # gif: build a palette in one filtergraph for decent color.
    return cmd + ["-vf", "split[a][b];[a]palettegen[p];[b][p]paletteuse", out_path]


def render_video(jail: str | None = None, start: int | None = None,
                 end: int | None = None, step: int = 1, fps: int = 24,
                 format: str = "mp4", filename: str | None = None,
                 camera: str | None = None, quality: str = "medium",
                 ffmpeg: str | None = None) -> dict:
    """
    Render the frame range ``start..end`` (current scene settings) and
    encode it into a single video in the jail with ffmpeg — the
    headless "show the user a clip" path (e.g. a looping walk cycle).

    Frames render to sequential PNGs in a temp dir, then ffmpeg stitches
    them; the intermediate frames are discarded. *ffmpeg* optionally
    overrides binary discovery (see :func:`find_ffmpeg`). Render
    settings (engine, resolution, frame range) are used as-is and
    restored afterwards.
    """
    format = (format or "mp4").lower().lstrip(".")
    if format not in _VIDEO_FORMATS:
        raise ValueError("unsupported video format {!r}; supported: {}".format(
            format, ", ".join(_VIDEO_FORMATS)))
    quality = (quality or "medium").lower()

    binary = find_ffmpeg(ffmpeg)
    if binary is None:
        if ffmpeg:
            raise RuntimeError("no ffmpeg binary at {!r}".format(ffmpeg))
        raise RuntimeError(
            "ffmpeg not found on PATH or in common locations. Install it "
            "(e.g. `apt install ffmpeg`, `brew install ffmpeg`) or pass "
            "{'ffmpeg': '/path/to/ffmpeg'}.")

    scene = bpy.context.scene
    cam = bpy.data.objects.get(camera) if camera else scene.camera
    if camera and (cam is None or cam.type != "CAMERA"):
        raise ValueError("no camera object named {!r}".format(camera))
    if cam is None:
        cameras = [o for o in bpy.data.objects if o.type == "CAMERA"]
        if len(cameras) == 1:
            cam = cameras[0]
        else:
            raise ValueError(
                "the scene has no active camera ({:d} camera objects); add one "
                "or pass {{'camera': name}}".format(len(cameras)))

    start = scene.frame_start if start is None else int(start)
    end = scene.frame_end if end is None else int(end)
    step = max(1, int(step))
    fps = max(1, int(fps))
    if end < start:
        raise ValueError("end frame {:d} is before start frame {:d}".format(end, start))

    root = resolve_jail(jail)
    stem = safe_name(filename or "render")
    if not stem.lower().endswith("." + format):
        stem += "." + format
    out_path = unique_path(root, stem)

    tmpdir = tempfile.mkdtemp(prefix="blmedia_frames_")
    previous = (scene.camera, scene.frame_current,
                scene.render.filepath, scene.render.image_settings.file_format)
    try:
        scene.camera = cam
        scene.render.image_settings.file_format = "PNG"
        # Sequential names (seq_00000.png ...) so ffmpeg reads a clean
        # consecutive pattern regardless of the actual frame numbers or
        # step - write_still uses the path literally + the format ext.
        n_frames = 0
        for frame in range(start, end + 1, step):
            scene.frame_set(frame)
            scene.render.filepath = os.path.join(tmpdir, "seq_{:05d}".format(n_frames))
            bpy.ops.render.render(write_still=True)
            n_frames += 1
        if n_frames == 0:
            raise RuntimeError("no frames to encode in range {:d}..{:d}".format(start, end))
        if not glob.glob(os.path.join(tmpdir, "seq_*.png")):
            raise RuntimeError("render produced no frame images")

        cmd = _ffmpeg_encode_cmd(
            binary, os.path.join(tmpdir, "seq_%05d.png"), fps, format, quality, out_path)
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0 or not os.path.isfile(out_path):
            raise RuntimeError("ffmpeg encode failed: {}".format(
                (proc.stderr or proc.stdout or "no output").strip()[-800:]))
    finally:
        (scene.camera, scene.frame_current,
         scene.render.filepath,
         scene.render.image_settings.file_format) = previous
        shutil.rmtree(tmpdir, ignore_errors=True)

    return {
        "file": os.path.relpath(out_path, root),
        "folder": root,
        "size": os.path.getsize(out_path),
        "format": format,
        "fps": fps,
        "frames": n_frames,
        "range": [start, end],
        "step": step,
        "camera": cam.name,
        "ffmpeg": binary,
    }
