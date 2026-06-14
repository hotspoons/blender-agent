# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Unit tests for the agent capability registry (Tier B): the import-jail
sandbox, the filesystem tool store + search, and the loader that composes
a guarded bridge payload. Pure-Python — no Blender; the bridge is faked by
exec'ing the composed payload locally (it is self-contained).
"""

import os
import tempfile
import unittest

from blmcp.agent_registry import loader, sandbox, store


def _fake_bridge(code, strict_json):  # noqa: ARG001
    ns: dict = {}
    exec(compile(code, "<bridge>", "exec"), ns)  # pylint: disable=exec-used
    return {"status": "ok", "result": ns.get("result")}


class TestSandbox(unittest.TestCase):

    def test_allowlisted_ok(self):
        v = sandbox.classify("import math\nresult={'x': math.pi}")
        self.assertTrue(v["ok"])
        self.assertEqual(v["outside_imports"], [])

    def test_escape_detected(self):
        v = sandbox.classify("import requests\nimport os\nresult={}")
        self.assertFalse(v["ok"])
        self.assertEqual(v["outside_imports"], ["os", "requests"])

    def test_dynamic_flagged(self):
        v = sandbox.classify("x = eval('1+1')\nresult={}")
        self.assertFalse(v["ok"])
        self.assertIn("eval()", v["flags"])

    def test_granted_clears_escape(self):
        v = sandbox.classify("import requests\nresult={}", granted=["requests"])
        self.assertTrue(v["ok"])

    def test_bpy_extras_and_benign_stdlib_allowlisted(self):
        for mod in ("bpy_extras", "time", "contextlib", "fnmatch", "traceback"):
            v = sandbox.classify("import {:s}\nresult={{}}".format(mod))
            self.assertTrue(v["ok"], mod)

    def test_importlib_is_dynamic_flag_not_grantable(self):
        v = sandbox.classify("import importlib\nresult={}")
        self.assertFalse(v["ok"])
        self.assertEqual(v["outside_imports"], [])  # NOT a simple import to grant
        self.assertTrue(any("dynamic import" in f for f in v["flags"]))
        # Even explicitly "granting" importlib cannot clear it.
        v2 = sandbox.classify("import importlib\nresult={}", granted=["importlib"])
        self.assertFalse(v2["ok"])

    def test_filesystem_deletion_flagged(self):
        v = sandbox.classify("import shutil\nshutil.rmtree('/x')\nresult={}")
        self.assertIn("*.rmtree()", v["flags"])
        # bare list.remove must NOT false-positive.
        self.assertEqual(sandbox.classify("[].remove(1)\nresult={}")["flags"], [])

    def test_syntax_error(self):
        v = sandbox.classify("def (:\n")
        self.assertTrue(v["syntax_error"])
        self.assertFalse(v["ok"])

    def test_payload_runs_and_injects_params(self):
        payload = sandbox.build_payload(
            "t", "result={'n2': params['n']*2}", {"n": 21}, sandbox.DEFAULT_ALLOWLIST)
        self.assertEqual(_fake_bridge(payload, False)["result"], {"n2": 42})

    def test_payload_blocks_tool_own_bad_import(self):
        payload = sandbox.build_payload(
            "t", "import socket\nresult={}", {}, sandbox.DEFAULT_ALLOWLIST)
        with self.assertRaises(ImportError):
            _fake_bridge(payload, False)

    def test_payload_allows_transitive_library_imports(self):
        # dataclasses internally imports copy/inspect/re — NOT in the
        # allowed set, but they come from dataclasses' frame, not the tool's.
        payload = sandbox.build_payload(
            "t",
            "import dataclasses\n"
            "@dataclasses.dataclass\nclass P:\n    x: int = 7\n"
            "result={'x': P().x}",
            {}, {"dataclasses"})
        self.assertEqual(_fake_bridge(payload, False)["result"], {"x": 7})

    def test_payload_blocks_relative_import(self):
        payload = sandbox.build_payload("t", "from . import x\nresult={}", {}, {"x"})
        with self.assertRaises(ImportError):
            _fake_bridge(payload, False)


class TestSdkBridge(unittest.TestCase):
    """A registered framework SDK module is importable by authored tools
    without elicitation — the Tier-A-composition bridge."""

    def setUp(self):
        self._saved = sandbox.sdk_modules()

    def tearDown(self):
        sandbox._SDK_MODULES.clear()
        sandbox._SDK_MODULES.update(self._saved)

    def test_sdk_module_auto_allowed_after_registration(self):
        # base64: stdlib, NOT in the default allowlist — perfect SDK stand-in.
        self.assertFalse(sandbox.classify("import base64\nresult={}")["ok"])
        sandbox.register_sdk_modules("test", ["base64"])
        self.assertTrue(sandbox.classify("import base64\nresult={}")["ok"])
        self.assertIn("base64", sandbox.allowed_modules())

    def test_sdk_module_passes_runtime_guard(self):
        sandbox.register_sdk_modules("test", ["base64"])
        payload = sandbox.build_payload(
            "t", "import base64\nresult={'x': base64.b64encode(b'hi').decode()}",
            {}, sandbox.allowed_modules())
        ns: dict = {}
        exec(compile(payload, "<b>", "exec"), ns)  # pylint: disable=exec-used
        self.assertEqual(ns["result"], {"x": "aGk="})


class TestStore(unittest.TestCase):

    def setUp(self):
        self._dir = tempfile.mkdtemp(prefix="agtools_")
        os.environ["BLENDER_MCP_AGENT_TOOLS_DIR"] = self._dir
        # Isolate from the shipped bundled-tool library (blmcp/data/agent_tools),
        # which list_all() always scans, so exact-list assertions stay stable
        # regardless of which tools ship in the package.
        self._seed = tempfile.mkdtemp(prefix="agseed_")
        os.environ["BLENDER_MCP_AGENT_TOOLS_SEED_DIR"] = self._seed

    def tearDown(self):
        import shutil
        shutil.rmtree(self._dir, ignore_errors=True)
        shutil.rmtree(self._seed, ignore_errors=True)
        os.environ.pop("BLENDER_MCP_AGENT_TOOLS_DIR", None)
        os.environ.pop("BLENDER_MCP_AGENT_TOOLS_SEED_DIR", None)

    def test_roundtrip_and_version_bump(self):
        t = store.save(name="make_gear", description="Make a gear.",
                       code="result={}", params_schema={"required": ["teeth"]},
                       granted_imports=(), approved=True)
        self.assertEqual(t.version, 1)
        self.assertEqual(store.get("make_gear").description, "Make a gear.")
        t2 = store.save(name="make_gear", description="v2", code="result={}",
                        params_schema={}, approved=True)
        self.assertEqual(t2.version, 2)

    def test_bad_name_rejected(self):
        for bad in ("../evil", "Has Space", "x", "UPPER", ""):
            with self.assertRaises(ValueError):
                store.save(name=bad, description="", code="result={}",
                           params_schema={}, approved=True)

    def test_search_ranks_by_name_then_body(self):
        store.save(name="bevel_edges", description="Bevel the selected edges.",
                   code="result={}", params_schema={}, approved=True)
        store.save(name="unrelated", description="Spin a wheel.",
                   code="# bevel mentioned only in code\nresult={}",
                   params_schema={}, approved=True)
        names = [t.name for t in store.search("bevel")]
        self.assertEqual(names[0], "bevel_edges")  # name match outranks body
        self.assertIn("unrelated", names)

    def test_list_and_remove(self):
        store.save(name="aa", description="", code="result={}", params_schema={}, approved=True)
        self.assertEqual([t.name for t in store.list_all()], ["aa"])
        self.assertTrue(store.remove("aa"))
        self.assertEqual(store.list_all(), [])


class TestLoader(unittest.TestCase):

    def setUp(self):
        self._dir = tempfile.mkdtemp(prefix="agtools_")
        os.environ["BLENDER_MCP_AGENT_TOOLS_DIR"] = self._dir

    def tearDown(self):
        import shutil
        shutil.rmtree(self._dir, ignore_errors=True)
        os.environ.pop("BLENDER_MCP_AGENT_TOOLS_DIR", None)

    def _tool(self, **kw):
        defaults = dict(name="tt", description="", code="result={'ok': True}",
                        params_schema={}, granted_imports=(), approved=True)
        defaults.update(kw)
        return store.save(**defaults)

    def test_run_happy_path(self):
        t = self._tool(code="result={'doubled': params['n']*2}",
                       params_schema={"properties": {"n": {}}, "required": ["n"]})
        self.assertEqual(loader.run(t, {"n": 5}, _fake_bridge)["result"], {"doubled": 10})

    def test_unapproved_blocked(self):
        t = self._tool(name="pending", approved=False)
        self.assertIn("not approved", loader.run(t, {}, _fake_bridge)["error"])

    def test_missing_required_arg(self):
        t = self._tool(params_schema={"required": ["n"]})
        self.assertIn("missing required", loader.run(t, {}, _fake_bridge)["error"])

    def test_unknown_arg(self):
        t = self._tool(params_schema={"properties": {"n": {}}})
        self.assertIn("unknown arg", loader.run(t, {"z": 1}, _fake_bridge)["error"])


class TestBundles(unittest.TestCase):
    """Multi-file authored tools: siblings importable by bare name, external
    imports still jailed, stale siblings pruned, siblings survive approval."""

    def setUp(self):
        self._dir = tempfile.mkdtemp(prefix="agtools_")
        os.environ["BLENDER_MCP_AGENT_TOOLS_DIR"] = self._dir

    def tearDown(self):
        import shutil
        shutil.rmtree(self._dir, ignore_errors=True)
        os.environ.pop("BLENDER_MCP_AGENT_TOOLS_DIR", None)

    def test_save_read_siblings(self):
        t = store.save(name="areas", description="", code="import helper\nresult={}",
                       params_schema={}, approved=True,
                       siblings={"helper": "def f(): return 1"})
        self.assertTrue(t.is_bundle())
        self.assertEqual(set(t.siblings()), {"helper"})

    def test_loader_runs_bundle(self):
        t = store.save(
            name="areas", description="",
            code="import helper\nresult={'a': helper.circle_area(params['r'])}",
            params_schema={"required": ["r"]}, approved=True,
            siblings={"helper": "import math\ndef circle_area(r):\n    return round(math.pi*r*r, 2)"})
        self.assertEqual(loader.run(t, {"r": 2}, _fake_bridge)["result"], {"a": 12.57})

    def test_bundle_helper_external_import_still_jailed(self):
        t = store.save(name="xx", description="", code="import helper\nresult={}",
                       params_schema={}, approved=True,
                       siblings={"helper": "import socket"})
        with self.assertRaises(ImportError):
            _fake_bridge(
                sandbox.build_bundle_payload(t.name, t.code(), t.siblings(), {},
                                             sandbox.allowed_modules()), False)

    def test_stale_siblings_pruned_on_resave(self):
        store.save(name="xx", description="", code="result={}", params_schema={},
                   approved=True, siblings={"helper": "x=1", "extra": "y=2"})
        t = store.save(name="xx", description="", code="result={}", params_schema={},
                       approved=True, siblings={"helper": "x=1"})
        self.assertEqual(set(t.siblings()), {"helper"})

    def test_siblings_survive_approval(self):
        store.save(name="net", description="", code="import helper\nresult={}",
                   params_schema={}, approved=False, pending_imports=["requests"],
                   siblings={"helper": "import requests"})
        t = store.set_approval("net", True)
        self.assertTrue(t.approved)
        self.assertEqual(set(t.siblings()), {"helper"})

    def test_invalid_module_name_rejected(self):
        for bad in ("tool", "Helper", "with-dash", "1mod"):
            with self.assertRaises(ValueError):
                store.save(name="xx", description="", code="result={}",
                           params_schema={}, approved=True, siblings={bad: "x=1"})


class TestBundledSeed(unittest.TestCase):
    """The shipped Tier-B library: a read-only seed dir scanned alongside the
    user dir, with user-local tools shadowing bundled ones."""

    def setUp(self):
        self._user = tempfile.mkdtemp(prefix="agtools_user_")
        self._seed = tempfile.mkdtemp(prefix="agtools_seed_")
        os.environ["BLENDER_MCP_AGENT_TOOLS_DIR"] = self._user
        os.environ["BLENDER_MCP_AGENT_TOOLS_SEED_DIR"] = self._seed
        # Hand-place a bundled tool (as it would ship in blmcp/data/agent_tools).
        import json
        d = os.path.join(self._seed, "measure_joints")
        os.makedirs(d)
        with open(os.path.join(d, "tool.json"), "w") as fh:
            json.dump({"name": "measure_joints", "description": "Detect joints.",
                       "params_schema": {}, "granted_imports": [], "approved": True,
                       "author": "blender-agent", "version": 1}, fh)
        with open(os.path.join(d, "tool.py"), "w") as fh:
            fh.write("result = {'measured': params.get('n', 0) + 1}")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._user, ignore_errors=True)
        shutil.rmtree(self._seed, ignore_errors=True)
        os.environ.pop("BLENDER_MCP_AGENT_TOOLS_DIR", None)
        os.environ.pop("BLENDER_MCP_AGENT_TOOLS_SEED_DIR", None)

    def test_bundled_discovered_and_runnable(self):
        t = store.get("measure_joints")
        self.assertIsNotNone(t)
        self.assertTrue(t.bundled)
        self.assertTrue(t.approved)
        self.assertIn("measure_joints", [x.name for x in store.list_all()])
        self.assertIn("measure_joints", [x.name for x in store.search("detect joints")])
        self.assertEqual(loader.run(t, {"n": 4}, _fake_bridge)["result"], {"measured": 5})
        self.assertTrue(t.summary().get("bundled"))

    def test_user_local_shadows_bundled(self):
        store.save(name="measure_joints", description="user override",
                   code="result={'mine': True}", params_schema={}, approved=True)
        t = store.get("measure_joints")
        self.assertFalse(t.bundled)
        self.assertEqual(t.description, "user override")
        # exactly one entry by that name in the merged list
        self.assertEqual([x.name for x in store.list_all()].count("measure_joints"), 1)

    def test_bundled_not_removable(self):
        self.assertFalse(store.remove("measure_joints"))  # nothing in user dir
        self.assertIsNotNone(store.get("measure_joints"))  # still shipped


class TestPendingApprovalAndPromotion(unittest.TestCase):

    def setUp(self):
        self._dir = tempfile.mkdtemp(prefix="agtools_")
        os.environ["BLENDER_MCP_AGENT_TOOLS_DIR"] = self._dir

    def tearDown(self):
        import shutil
        shutil.rmtree(self._dir, ignore_errors=True)
        os.environ.pop("BLENDER_MCP_AGENT_TOOLS_DIR", None)

    def test_pending_tool_is_inert_until_approved(self):
        t = store.save(name="net_tool", description="fetch",
                       code="import requests\nresult={}", params_schema={},
                       approved=False, pending_imports=["requests"])
        self.assertFalse(t.approved)
        self.assertEqual(t.pending_imports, ("requests",))
        self.assertIn("not approved", loader.run(t, {}, _fake_bridge)["error"])

    def test_approve_makes_pending_imports_granted_and_live(self):
        store.save(name="net_tool", description="", code="result={}",
                   params_schema={}, approved=False, pending_imports=["requests"])
        t = store.set_approval("net_tool", True)
        self.assertTrue(t.approved)
        self.assertIn("requests", t.granted_imports)
        self.assertEqual(t.pending_imports, ())

    def test_reject_removes_pending_tool(self):
        store.save(name="bad_tool", description="", code="result={}",
                   params_schema={}, approved=False, pending_imports=["socket"])
        self.assertIsNone(store.set_approval("bad_tool", False))
        self.assertIsNone(store.get("bad_tool"))

    def test_promotion_scaffold_compiles(self):
        from blmcp.agent_registry import promote
        store.save(name="make_gear", description="Make a gear.",
                   code="import bmesh\nresult={'ok': True}", params_schema={},
                   granted_imports=(), approved=True)
        src = promote.scaffold_core_tool(store.get("make_gear"))
        compile(src, "<scaffold>", "exec")
        self.assertIn("def make_gear(", src)
        self.assertIn("build_payload", src)  # import guard preserved


if __name__ == "__main__":
    unittest.main()
