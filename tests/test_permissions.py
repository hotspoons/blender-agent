# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for tool RBAC (agent/blagent/permissions.py)."""

__all__ = ()

import importlib
import os
import sys
import tempfile
import unittest

_REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _imp():
    for p in (os.path.join(_REPO_DIR, "mcp"), os.path.join(_REPO_DIR, "agent")):
        if p not in sys.path:
            sys.path.insert(0, p)
    return importlib.import_module("agentcore.permissions")


class _FakeTool:
    def __init__(self, name, group="general"):
        self.name = name
        self.group = group


class TestToolPermissions(unittest.TestCase):

    def test_default_matrix_levels(self):
        m = _imp()
        p = m.ToolPermissions.load()
        self.assertEqual(p.level("worker", "set_autonomy"), m.DISABLED)
        self.assertEqual(p.level("worker", "ask_user"), m.DISABLED)
        self.assertEqual(p.level("worker", "get_objects_summary"), m.ALLOW)
        self.assertEqual(p.level("orchestrator", "set_autonomy"), m.ELICIT)
        self.assertEqual(p.level("orchestrator", "execute_blender_code"), m.ALLOW)
        self.assertEqual(p.level("reviewer", "anything"), m.DISABLED)
        self.assertEqual(p.level("auditor", "get_objects_summary"), m.ALLOW)
        self.assertEqual(p.level("auditor", "execute_blender_code"), m.DISABLED)

    def test_unknown_role_inherits_default(self):
        m = _imp()
        p = m.ToolPermissions.load()
        self.assertEqual(p.level("brand_new_role", "whatever"), m.ALLOW)
        self.assertTrue(p.allowed("brand_new_role", "whatever"))

    def test_filter_and_elicit_helpers(self):
        m = _imp()
        p = m.ToolPermissions.load()
        tools = [_FakeTool("build"), _FakeTool("set_autonomy"), _FakeTool("ask_user")]
        # worker: meta-tools hidden
        names = {t.name for t in p.filter_tools("worker", tools)}
        self.assertEqual(names, {"build"})
        # orchestrator: all visible, set_autonomy requires elicit
        names = {t.name for t in p.filter_tools("orchestrator", tools)}
        self.assertEqual(names, {"build", "set_autonomy", "ask_user"})
        self.assertEqual(p.elicit_tool_names("orchestrator", tools), {"set_autonomy"})
        self.assertEqual(p.elicit_tool_names("worker", tools), set())

    def test_group_level_rule(self):
        m = _imp()
        p = m.ToolPermissions({"r": {"default": m.ALLOW, "groups": {"control": m.DISABLED}}})
        self.assertEqual(p.level("r", "set_autonomy", "control"), m.DISABLED)
        self.assertEqual(p.level("r", "build", "general"), m.ALLOW)
        kept = p.filter_tools("r", [_FakeTool("set_autonomy", "control"), _FakeTool("build")])
        self.assertEqual({t.name for t in kept}, {"build"})

    def test_specificity_exact_beats_wildcard_beats_group(self):
        m = _imp()
        p = m.ToolPermissions({"r": {
            "default": m.DISABLED,
            "groups": {"io": m.ALLOW},
            "tools": {"get_*": m.ELICIT, "get_secret": m.DISABLED},
        }})
        self.assertEqual(p.level("r", "get_secret", "io"), m.DISABLED)  # exact
        self.assertEqual(p.level("r", "get_objects", "io"), m.ELICIT)   # wildcard
        self.assertEqual(p.level("r", "write_file", "io"), m.ALLOW)     # group
        self.assertEqual(p.level("r", "lonely", ""), m.DISABLED)        # default

    def test_load_from_yaml_file(self):
        m = _imp()
        path = os.path.join(tempfile.mkdtemp(), "perm.yaml")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("roles:\n  worker:\n    default: allow\n    tools:\n      danger: disabled\n")
        p = m.ToolPermissions.load(path)
        self.assertEqual(p.level("worker", "danger"), m.DISABLED)
        self.assertEqual(p.level("worker", "safe"), m.ALLOW)

    def test_bad_yaml_falls_back_to_default(self):
        m = _imp()
        p = m.ToolPermissions.load("/nonexistent/permissions.yaml")
        self.assertEqual(p.level("worker", "set_autonomy"), m.DISABLED)  # built-in default


if __name__ == "__main__":
    unittest.main()
