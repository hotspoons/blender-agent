# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Run an agent-authored tool: validate args against its schema, compose the
guarded bridge payload (:func:`sandbox.build_payload`), and execute it
through the SAME transport as ``execute_blender_code``. No new execution
power — persistence + a stricter import policy is the whole difference.
"""

__all__ = (
    "check_args",
    "run",
)

from collections.abc import Callable
from typing import Any

from . import sandbox
from . import store


def check_args(schema: dict[str, Any], args: dict[str, Any]) -> str:
    """
    Light JSON-Schema-ish validation: required keys present, no unknown
    keys when the schema declares ``properties``. Returns "" when ok, else
    an error message. The tool body is free to validate further.
    """
    if not isinstance(args, dict):
        return "args must be an object"
    required = schema.get("required") or []
    missing = [k for k in required if k not in args]
    if missing:
        return "missing required arg(s): {:s}".format(", ".join(missing))
    props = schema.get("properties")
    if isinstance(props, dict):
        unknown = [k for k in args if k not in props]
        if unknown:
            return "unknown arg(s): {:s} (expected: {:s})".format(
                ", ".join(unknown), ", ".join(sorted(props)) or "none")
    return ""


def run(tool: "store.AuthoredTool", args: dict[str, Any],
        send_code: Callable[[str, bool], dict[str, object]]) -> dict[str, object]:
    """
    Execute *tool* with *args* via *send_code(code, strict_json=False)*.
    Returns the bridge response, or an ``{"error": ...}`` dict on a policy
    failure (unapproved tool, bad args).
    """
    if not tool.approved:
        return {"error": "tool {!r} is not approved to run".format(tool.name)}
    err = check_args(tool.params_schema, args)
    if err:
        return {"error": err}
    # allowlist + framework SDK + this tool's granted imports.
    allowed = sandbox.allowed_modules(tool.granted_imports)
    siblings = tool.siblings()
    if siblings:
        payload = sandbox.build_bundle_payload(tool.name, tool.code(), siblings, args, allowed)
    else:
        payload = sandbox.build_payload(tool.name, tool.code(), args, allowed)
    return send_code(payload, False)
