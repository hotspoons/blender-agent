# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Unit tests for the shared tool registry: core discovery, tools-extension
loading (entry points + env var), failure isolation, welcome nudge.
No Blender required.
"""

__all__ = ()

import asyncio
import os
import sys
import tempfile
import textwrap
import unittest

from mcp.server.fastmcp import FastMCP

from blmcp.registry import register_all_tools


def _tool_names(mcp: FastMCP) -> list[str]:
    return sorted(t.name for t in asyncio.run(mcp.list_tools()))


class TestRegistry(unittest.TestCase):

    def test_core_plus_new_tools(self) -> None:
        mcp = FastMCP("test")
        register_all_tools(mcp)
        names = _tool_names(mcp)
        for expected in ("execute_blender_code", "skills_list", "skills_search",
                         "skills_read", "welcome"):
            self.assertIn(expected, names)

    def test_rigging_extension_via_entry_point(self) -> None:
        # blender-mcp-extensions is installed in the dev environment.
        mcp = FastMCP("test")
        register_all_tools(mcp)
        names = _tool_names(mcp)
        for expected in ("rigging_inspect", "rigging_diagnose", "rigging_run",
                         "rigging_verify", "rigging_validate_rig"):
            self.assertIn(expected, names)

    def test_welcome_nudge_applied(self) -> None:
        mcp = FastMCP("test")
        register_all_tools(mcp)
        tools = {t.name: t for t in asyncio.run(mcp.list_tools())}
        self.assertIn("welcome", tools["execute_blender_code"].description)

    def test_env_extension_and_broken_extension(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "fake_ext_ok.py"), "w", encoding="utf-8") as fh:
                fh.write(textwrap.dedent("""
                    def register(mcp):
                        @mcp.tool()
                        def fake_ext_tool() -> str:
                            \"\"\"Fake.\"\"\"
                            return "ok"
                """))
            with open(os.path.join(tmp, "fake_ext_broken.py"), "w", encoding="utf-8") as fh:
                fh.write("raise RuntimeError('broken on import')\n")

            sys.path.insert(0, tmp)
            previous = os.environ.get("BLENDER_MCP_EXTENSIONS")
            os.environ["BLENDER_MCP_EXTENSIONS"] = "fake_ext_ok,fake_ext_broken"
            try:
                mcp = FastMCP("test")
                register_all_tools(mcp)  # broken one must not raise
                self.assertIn("fake_ext_tool", _tool_names(mcp))
            finally:
                sys.path.remove(tmp)
                if previous is None:
                    os.environ.pop("BLENDER_MCP_EXTENSIONS", None)
                else:
                    os.environ["BLENDER_MCP_EXTENSIONS"] = previous


if __name__ == "__main__":
    unittest.main()
