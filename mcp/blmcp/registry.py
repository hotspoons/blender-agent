# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Single place all tool registration flows through — the stdio/HTTP server
and the in-process agent harness both call :func:`register_all_tools`, so
core tools and optional extensions behave identically everywhere.

Tools extensions
================

An extension is a Python module exposing ``register(mcp)`` (same hook as
core tool modules) and optionally ``skills_dir() -> str`` for a bundled
skill collection. Extensions are discovered from:

- the ``blender_mcp.extensions`` entry-point group (installed packages,
  e.g. ``blender-mcp-extensions``); and
- the ``BLENDER_MCP_EXTENSIONS`` env var (comma-separated module paths),
  for checkouts that are not pip-installed.

Extensions are optional by design: a missing or broken extension logs a
warning and the core keeps working.
"""

__all__ = (
    "register_all_tools",
)

import importlib
import importlib.metadata
import os
import pkgutil
import sys

_ENTRY_POINT_GROUP = "blender_mcp.extensions"

# Core tools whose descriptions get the run-welcome-first nudge appended.
_WELCOME_NUDGE_TOOLS = (
    "execute_blender_code",
    "execute_blender_code_for_cli",
    "get_objects_summary",
)
_WELCOME_NUDGE = (
    "\n\nFIRST ACTION this session: call the `welcome` tool before this one. "
    "It lists the skills installed right now (rigging, media, ...) and the "
    "conventions these tools assume - skipping it means you won't know those "
    "skills exist or how this toolset expects to be driven."
)


def _iter_extension_modules():
    seen = set()
    try:
        entry_points = importlib.metadata.entry_points(group=_ENTRY_POINT_GROUP)
    except Exception:  # pylint: disable=broad-except
        entry_points = ()
    for entry in entry_points:
        if entry.value not in seen:
            seen.add(entry.value)
            yield entry.name, entry.value
    for value in os.environ.get("BLENDER_MCP_EXTENSIONS", "").split(","):
        value = value.strip()
        if value and value not in seen:
            seen.add(value)
            yield value.rsplit(".", 1)[-1], value


def _register_extensions(mcp) -> None:
    from blmcp.skills import register_extension_skills

    for name, module_path in _iter_extension_modules():
        try:
            module = importlib.import_module(module_path)
        except Exception as ex:  # pylint: disable=broad-except
            print("blender-mcp: extension {!r} failed to import: {!s}".format(
                module_path, ex), file=sys.stderr)
            continue
        try:
            if hasattr(module, "register"):
                module.register(mcp)
            if hasattr(module, "skills_dir"):
                register_extension_skills(name, module.skills_dir())
        except Exception as ex:  # pylint: disable=broad-except
            print("blender-mcp: extension {!r} failed to register: {!s}".format(
                module_path, ex), file=sys.stderr)


def _apply_welcome_nudge(mcp) -> None:
    """
    Append the run-welcome-first nudge to key tool descriptions. Reaches
    into FastMCP's tool manager — guarded, cosmetic-only on failure.
    """
    try:
        for name in _WELCOME_NUDGE_TOOLS:
            tool = mcp._tool_manager._tools.get(name)  # pylint: disable=protected-access
            if tool is not None and _WELCOME_NUDGE not in (tool.description or ""):
                tool.description = (tool.description or "") + _WELCOME_NUDGE
    except Exception:  # pylint: disable=broad-except
        pass


def register_all_tools(mcp) -> None:
    """
    Register core tools (auto-discovered from ``blmcp.tools``), then
    optional extensions, then cosmetic cross-tool description tweaks.
    """
    import blmcp.tools as tools_pkg

    for _importer, modname, _ispkg in pkgutil.iter_modules(tools_pkg.__path__):
        if modname.endswith("_toolcode") or modname.startswith("_template_"):
            continue
        module = importlib.import_module("blmcp.tools.{:s}".format(modname))
        if hasattr(module, "register"):
            module.register(mcp)

    _register_extensions(mcp)
    _apply_welcome_nudge(mcp)
