# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
The single polymorphic ``media_io`` MCP tool (named to avoid the agent's
own ``media`` recall tool). Server side validates inputs and ships code
over the bridge; ``blmedia`` (inside Blender) owns the file IO and the
jail.
"""

__all__ = (
    "register",
)

from blmcp.tools_helpers.connection import send_code
from mcp.server.fastmcp import FastMCP  # pylint: disable=import-error,no-name-in-module
from mcp.types import ToolAnnotations  # pylint: disable=import-error,no-name-in-module

from . import BLMEDIA_PARENT_DIR

_VERBS = ("list", "import", "export", "render", "stage", "info")

_BOOTSTRAP = (
    "import sys\n"
    "if {path!r} not in sys.path:\n"
    "    sys.path.insert(0, {path!r})\n"
).format(path=BLMEDIA_PARENT_DIR)


def _error(message: str) -> dict[str, object]:
    return {"error": message}


def _code_for(verb: str, args: dict) -> dict[str, object] | str:
    jail = args.get("jail_root")
    if jail is not None and not isinstance(jail, str):
        return _error("jail_root must be a string path")

    if verb == "list":
        return _BOOTSTRAP + (
            "import blmedia\n"
            "result = blmedia.list_files({jail!r})\n"
        ).format(jail=jail)

    if verb == "info":
        name = args.get("name")
        if not name:
            return _error("info needs args={'name': <file in the media folder>}")
        return _BOOTSTRAP + (
            "import blmedia\n"
            "result = blmedia.info_file({name!r}, {jail!r})\n"
        ).format(name=str(name), jail=jail)

    if verb == "import":
        name = args.get("name")
        if not name:
            return _error("import needs args={'name': <file in the media folder>, 'options'?}")
        return _BOOTSTRAP + (
            "import blmedia\n"
            "result = blmedia.import_file({name!r}, {jail!r}, {options!r})\n"
        ).format(name=str(name), jail=jail, options=args.get("options") or {})

    if verb == "export":
        fmt = args.get("format")
        if not fmt:
            return _error(
                "export needs args={'format': blend|stl|obj|ply|gltf|glb|fbx|usd|abc|svg|pdf"
                " (or png/jpg/webp/exr to render the scene), 'objects'?: [names], 'filename'?}")
        objects = args.get("objects")
        if objects is not None and not isinstance(objects, list):
            return _error("objects must be a list of object names")
        return _BOOTSTRAP + (
            "import blmedia\n"
            "_out = blmedia.export_file({fmt!r}, {jail!r}, objects={objects!r}, "
            "filename={filename!r}, options={options!r})\n"
            "_out['jail_files'] = [_out['file']]\n"
            "result = _out\n"
        ).format(fmt=str(fmt), jail=jail, objects=objects,
                 filename=args.get("filename"), options=args.get("options") or {})

    if verb == "render":
        return _BOOTSTRAP + (
            "import blmedia\n"
            "_out = blmedia.render_frame({jail!r}, frame={frame!r}, "
            "filename={filename!r}, format={fmt!r}, camera={camera!r})\n"
            "_out['jail_files'] = [_out['file']]\n"
            "result = _out\n"
        ).format(jail=jail, frame=args.get("frame"),
                 filename=args.get("filename"),
                 fmt=str(args.get("format") or "png"),
                 camera=args.get("camera"))

    if verb == "stage":
        path = args.get("path")
        if not path:
            return _error("stage needs args={'path': <existing file on disk>, 'filename'?}")
        return _BOOTSTRAP + (
            "import blmedia\n"
            "_out = blmedia.stage_file({path!r}, {jail!r}, filename={filename!r})\n"
            "_out['jail_files'] = [_out['file']]\n"
            "result = _out\n"
        ).format(path=str(path), jail=jail, filename=args.get("filename"))

    return _error("unknown verb {!r}; valid: {!r}".format(verb, list(_VERBS)))


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        annotations=ToolAnnotations(
            title="Media Import/Export",
            destructiveHint=True,
        )
    )
    def media_io(verb: str, args: dict) -> dict[str, object]:
        """
        EVERY file between the user and the scene goes through this tool
        and its media folder: user attachments land there, and anything
        you put there the user can see and download. One tool,
        verb-dispatched:

        - media_io("list", {}) — files available (user attachments of
          any type: stl, obj, gltf/glb, fbx, usd, abc, svg, images,
          audio — and your previous exports/renders).
        - media_io("import", {name}) — bring a listed file into the
          scene: meshes via the native importers, svg as curves, images
          as reference image-empties, audio as a speaker. Returns the
          created object names.
        - media_io("export", {format, objects?, filename?}) — write the
          scene (or just the named objects) as blend/stl/obj/ply/gltf/
          glb/fbx/usd/abc (svg/pdf = grease-pencil strokes). An image
          format (png/jpg/webp/exr) renders the scene instead — same as
          "render".
        - media_io("render", {frame?, filename?, format?, camera?}) —
          render ONE frame straight to the media folder and return the
          filename. The way to SHOW the user an image; works headless.
          Uses the scene camera (or the only camera) and current render
          settings.
        - media_io("stage", {path, filename?}) — copy a file that
          already exists on disk (a render output, a baked cache) into
          the media folder so the user gets it.
        - media_io("info", {name}) — size/kind of one file.

        Filenames never overwrite — collisions get a -2/-3 suffix. When
        the user attaches a file or asks for a deliverable (file OR
        image), THIS is the tool — never read or write files via
        execute_blender_code. Run `welcome` first if you have not.
        """
        if verb not in _VERBS:
            return _error("unknown verb {!r}; valid: {!r}".format(verb, list(_VERBS)))
        code = _code_for(str(verb), args if isinstance(args, dict) else {})
        if isinstance(code, dict):
            return code
        return send_code(code, strict_json=False)
