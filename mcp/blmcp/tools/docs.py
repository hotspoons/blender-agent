# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

# pylint: disable=C0114  # See tool doc-string.

__all__ = (
    "register",
)

from typing import Any

from blmcp.tools.get_python_api_docs import lookup
from blmcp.tools_helpers.rst_doc_search import search
from mcp.server.fastmcp import FastMCP  # pylint: disable=import-error,no-name-in-module
from mcp.types import ToolAnnotations  # pylint: disable=import-error,no-name-in-module


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        annotations=ToolAnnotations(
            title="Blender documentation",
            readOnlyHint=True,
        )
    )
    def docs(verb: str, args: dict[str, Any]) -> dict[str, object]:
        """
        Consult the bundled Blender docs before writing or debugging bpy
        code. One tool, verb-dispatched (args in {}):

        - docs("api", {query, max_results?, context?, index?}) —
          full-text search of the Python API reference. Hits carry
          path, text, breadcrumb, index, score. Tokens are matched
          case-insensitively in any order; stop-words dropped. Use
          context to widen surrounding paragraphs; re-call with index
          (same query) to widen one hit to its enclosing section.
        - docs("manual", {query, max_results?, context?, index?}) —
          same, over the Blender user manual (concepts, workflows).
        - docs("lookup", {identifier}) — exact docs for a fully-qualified
          name (e.g. "bpy.types.Scene.frame_current"). Trailing "*"
          discovers a namespace: "*" lists top-level modules, "bpy.*"
          lists direct children. Returns kind/found/identifier plus
          content/examples/submodules/suggestions depending on the match.
        """
        a = args if isinstance(args, dict) else {}
        if verb in ("api", "manual"):
            query = a.get("query")
            if not query:
                return {"error": "docs({!r}, {{'query': ...}}) requires 'query'".format(verb)}
            return search(
                query=str(query),
                scope=verb,
                max_results=int(a.get("max_results", 20)),
                context=int(a.get("context", 0)),
                index=a.get("index"),
            )
        if verb == "lookup":
            identifier = a.get("identifier")
            if not identifier:
                return {"error": "docs('lookup', {'identifier': ...}) requires 'identifier'"}
            return lookup(str(identifier))
        return {"error": "unknown verb {!r}; valid: ['api', 'manual', 'lookup']".format(verb)}
