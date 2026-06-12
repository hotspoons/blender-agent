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

_VERBS = ("list", "import", "export", "info")

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
                "export needs args={'format': blend|stl|obj|ply|gltf|glb|fbx|usd|abc|svg|pdf,"
                " 'objects'?: [names], 'filename'?}")
        objects = args.get("objects")
        if objects is not None and not isinstance(objects, list):
            return _error("objects must be a list of object names")
        return _BOOTSTRAP + (
            "import blmedia\n"
            "_out = blmedia.export_file({fmt!r}, {jail!r}, objects={objects!r}, filename={filename!r})\n"
            "_out['jail_files'] = [_out['file']]\n"
            "result = _out\n"
        ).format(fmt=str(fmt), jail=jail, objects=objects,
                 filename=args.get("filename"))

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
        Move assets between the user and the Blender scene through the
        session media folder (user attachments land there; exports appear
        there for the user to download). One tool, verb-dispatched:

        - media_io("list", {}) — files available to import (user
          attachments of any type: stl, obj, gltf/glb, fbx, usd, abc,
          svg, images, audio) and previous exports.
        - media_io("import", {name}) — bring a listed file into the
          scene: meshes via the native importers, svg as curves, images
          as reference image-empties, audio as a speaker. Returns the
          created object names.
        - media_io("export", {format, objects?, filename?}) — write the
          scene (or just the named objects) to the media folder as
          blend/stl/obj/ply/gltf/glb/fbx/usd/abc (svg/pdf render
          grease-pencil strokes). Filenames never overwrite — collisions
          get a -2/-3 suffix. The user can then download the file.
        - media_io("info", {name}) — size/kind of one file.

        When the user attaches a file or asks for a deliverable file,
        THIS is the tool — never read or write files via
        execute_blender_code. Run `welcome` first if you have not.
        """
        if verb not in _VERBS:
            return _error("unknown verb {!r}; valid: {!r}".format(verb, list(_VERBS)))
        code = _code_for(str(verb), args if isinstance(args, dict) else {})
        if isinstance(code, dict):
            return code
        return send_code(code, strict_json=False)
