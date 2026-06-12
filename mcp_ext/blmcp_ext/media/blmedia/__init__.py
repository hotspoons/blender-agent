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
    "import_file",
    "info_file",
    "list_files",
    "resolve_jail",
    "unique_path",
)

import os
import re

import bpy

_DEFAULT_JAIL = os.path.join("~", ".local", "share", "blender-mcp", "media")

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._ ()+-]+")

_MESH_EXTS = ("stl", "obj", "ply", "gltf", "glb", "fbx",
              "usd", "usda", "usdc", "usdz", "abc")
_IMAGE_EXTS = ("png", "jpg", "jpeg", "webp", "tif", "tiff", "exr", "bmp", "hdr")
_AUDIO_EXTS = ("wav", "mp3", "ogg", "flac", "aif", "aiff")

_EXPORT_FORMATS = ("blend", "stl", "obj", "ply", "gltf", "glb", "fbx",
                   "usd", "usdc", "usda", "abc", "svg", "pdf")


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


def export_file(format: str, jail: str | None = None,
                objects: list | None = None,
                filename: str | None = None,
                options: dict | None = None) -> dict:
    """
    Export the scene (or the named *objects*) as *format* into the jail.
    Returns the (collision-suffixed) filename and size.
    """
    del options  # reserved
    format = (format or "").lower().lstrip(".")
    if format not in _EXPORT_FORMATS:
        raise ValueError("unsupported export format {!r}; supported: {}".format(
            format, ", ".join(_EXPORT_FORMATS)))

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
