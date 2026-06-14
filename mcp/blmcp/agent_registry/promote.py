# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Tier B -> Tier A promotion: turn an approved agent-authored tool (dynamic,
discovered by search) into a scaffolded CORE tool module
(``mcp/blmcp/tools/<name>.py``) for a human to review, refine, and commit.

Deliberately NOT an MCP tool — promotion into the shipped product is a
human/dev decision; agents must not promote themselves. Run it from a
checkout:

    python -m blmcp.agent_registry.promote <name>            # print scaffold
    python -m blmcp.agent_registry.promote <name> --write    # write the module

The scaffolded tool still runs its body under the same import guard (with
the granted imports baked in), so it is safe before the dev hardens it —
the promotion just gives it a stable, curated home in the golden tool set.
"""

__all__ = (
    "scaffold_core_tool",
)

import os

from . import sandbox
from . import store

_TEMPLATE = '''\
# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

# pylint: disable=C0114  # See tool doc-string.
#
# PROMOTED from an agent-authored tool (Tier B -> Tier A). Review before
# shipping: give it typed parameters instead of a bare ``args`` dict,
# tighten the docstring, and decide whether the import guard is still
# wanted now that this is curated code.

__all__ = ("register",)

from blmcp.agent_registry import sandbox
from blmcp.tools_helpers.connection import send_code
from mcp.server.fastmcp import FastMCP  # pylint: disable=import-error,no-name-in-module
from mcp.types import ToolAnnotations  # pylint: disable=import-error,no-name-in-module

_CODE = {code}
_ALLOWED = set({allowed})


def register(mcp: FastMCP) -> None:
    @mcp.tool(annotations=ToolAnnotations(title={title}, destructiveHint=True))
    def {name}(args: dict | None = None) -> dict[str, object]:
        """{doc}"""
        payload = sandbox.build_payload({name!r}, _CODE, args or {{}}, _ALLOWED)
        return send_code(payload, strict_json=False)
'''


def scaffold_core_tool(tool: "store.AuthoredTool") -> str:
    """Render a core-tool module source string for *tool*."""
    allowed = sorted(set(sandbox.DEFAULT_ALLOWLIST) | set(tool.granted_imports))
    doc = (tool.description or tool.name).replace("\\", "\\\\").replace('"', '\\"')
    if len(doc) > 300:
        doc = doc[:297] + "..."
    title = tool.name.replace("_", " ").title()
    return _TEMPLATE.format(
        code=repr(tool.code()),
        allowed=repr(allowed),
        title=repr(title),
        name=tool.name,
        doc=doc,
    )


def _core_tools_dir() -> str:
    # mcp/blmcp/tools/ relative to this file (works from a checkout).
    return os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "tools"))


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Promote an agent-authored tool to a core module.")
    parser.add_argument("name", help="authored tool name (see list_agent_tools)")
    parser.add_argument("--write", action="store_true",
                        help="write mcp/blmcp/tools/<name>.py instead of printing")
    args = parser.parse_args(argv)

    tool = store.get(args.name)
    if tool is None:
        parser.error("no agent tool named {!r}".format(args.name))
    if not tool.approved:
        parser.error("tool {!r} is not approved; approve it before promoting".format(args.name))

    source = scaffold_core_tool(tool)
    if not args.write:
        print(source)
        return 0
    dest = os.path.join(_core_tools_dir(), "{:s}.py".format(tool.name))
    if os.path.exists(dest):
        parser.error("refusing to overwrite existing {:s}".format(dest))
    with open(dest, "w", encoding="utf-8") as fh:
        fh.write(source)
    print("wrote {:s} — review, add a test + golden entry, then commit.".format(dest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
