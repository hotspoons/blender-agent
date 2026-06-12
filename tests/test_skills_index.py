# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Unit tests for the core skills subsystem: SKILL.md parsing, collection
scanning, sources (drop folder, git repo, extension), search and the MCP
tool surface. No Blender required.
"""

__all__ = ()

import asyncio
import json
import os
import subprocess
import tempfile
import unittest

from blmcp.skills import index as skills_index


def _write_skill(root: str, dirname: str, name: str, description: str,
                 body: str = "Steps here.", files: dict | None = None,
                 keywords: str = "", aliases: str = "") -> str:
    skill_dir = os.path.join(root, dirname)
    os.makedirs(skill_dir, exist_ok=True)
    extra = ""
    if keywords:
        extra += "keywords: {:s}\n".format(keywords)
    if aliases:
        extra += "aliases: {:s}\n".format(aliases)
    with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as fh:
        fh.write("---\nname: {:s}\ndescription: {:s}\n{:s}---\n\n# {:s}\n\n{:s}\n".format(
            name, description, extra, name, body))
    for rel, content in (files or {}).items():
        path = os.path.join(skill_dir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
    return skill_dir


class _IndexTestCase(unittest.TestCase):
    """
    Isolates the module globals and env vars the index reads.
    """

    def setUp(self) -> None:
        self._env = {
            key: os.environ.get(key)
            for key in ("BLENDER_MCP_SKILLS_DIR", "BLENDER_MCP_SKILLS_DIRS",
                        "BLENDER_MCP_SKILLS_REPOS", "BLENDER_MCP_SKILLS_CONFIG",
                        "BLENDER_MCP_SKILLS_REPO_CACHE")
        }
        self._tmp = tempfile.TemporaryDirectory()
        # Point every source somewhere empty by default.
        os.environ["BLENDER_MCP_SKILLS_DIR"] = os.path.join(self._tmp.name, "drop")
        os.environ["BLENDER_MCP_SKILLS_CONFIG"] = os.path.join(self._tmp.name, "none.json")
        os.environ["BLENDER_MCP_SKILLS_REPO_CACHE"] = os.path.join(self._tmp.name, "cache")
        os.environ.pop("BLENDER_MCP_SKILLS_DIRS", None)
        os.environ.pop("BLENDER_MCP_SKILLS_REPOS", None)
        self._saved_ext = list(skills_index._EXTENSION_DIRS)
        skills_index._EXTENSION_DIRS.clear()
        # Isolate from the builtin collection shipped with blmcp — these
        # tests assert exact skill sets.
        self._saved_builtin = skills_index._BUILTIN_DIR
        skills_index._BUILTIN_DIR = os.path.join(self._tmp.name, "builtin-empty")

    def tearDown(self) -> None:
        skills_index._BUILTIN_DIR = self._saved_builtin
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        skills_index._EXTENSION_DIRS[:] = self._saved_ext
        skills_index._INDEX = None
        self._tmp.cleanup()


class TestParsing(_IndexTestCase):

    def test_frontmatter(self) -> None:
        skill_dir = _write_skill(self._tmp.name, "x", "my-skill", "Does a thing.")
        name, description, keywords, aliases = skills_index.parse_skill_md(
            os.path.join(skill_dir, "SKILL.md"))
        self.assertEqual(name, "my-skill")
        self.assertEqual(description, "Does a thing.")
        self.assertEqual(keywords, "")
        self.assertEqual(aliases, ())

    def test_frontmatter_keywords(self) -> None:
        skill_dir = _write_skill(self._tmp.name, "k", "kw-skill", "K.",
                                 keywords="spider, arthropod, legs")
        _name, _description, keywords, _aliases = skills_index.parse_skill_md(
            os.path.join(skill_dir, "SKILL.md"))
        self.assertEqual(keywords, "spider, arthropod, legs")

    def test_frontmatter_keywords_list(self) -> None:
        skill_dir = _write_skill(self._tmp.name, "kl", "kw-list", "K.",
                                 keywords="[alpha, beta]")
        _name, _description, keywords, _aliases = skills_index.parse_skill_md(
            os.path.join(skill_dir, "SKILL.md"))
        self.assertEqual(keywords, "alpha, beta")

    def test_frontmatter_aliases(self) -> None:
        skill_dir = _write_skill(self._tmp.name, "al", "doc-name", "D.",
                                 aliases="[rig_thing, thing]")
        _name, _description, _keywords, aliases = skills_index.parse_skill_md(
            os.path.join(skill_dir, "SKILL.md"))
        self.assertEqual(aliases, ("rig_thing", "thing"))

    def test_no_frontmatter_falls_back(self) -> None:
        skill_dir = os.path.join(self._tmp.name, "bare-skill")
        os.makedirs(skill_dir)
        with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as fh:
            fh.write("# Title\n\nFirst body line.\n")
        name, description, _keywords, _aliases = skills_index.parse_skill_md(
            os.path.join(skill_dir, "SKILL.md"))
        self.assertEqual(name, "bare-skill")
        self.assertEqual(description, "First body line.")

    def test_scan_collection(self) -> None:
        _write_skill(self._tmp.name, "a", "skill-a", "A.")
        _write_skill(self._tmp.name, "nested/b", "skill-b", "B.",
                     files={"helper.py": "print()\n", "ref/notes.md": "n\n"})
        skills = skills_index.scan_collection(self._tmp.name, "test")
        names = sorted(s.name for s in skills)
        self.assertEqual(names, ["skill-a", "skill-b"])
        skill_b = next(s for s in skills if s.name == "skill-b")
        self.assertEqual(
            [f["path"] for f in skill_b.files()],
            ["helper.py", os.path.join("ref", "notes.md")])


class TestSources(_IndexTestCase):

    def test_drop_folder(self) -> None:
        _write_skill(os.environ["BLENDER_MCP_SKILLS_DIR"], "d", "dropped", "Dropped.")
        index = skills_index.ensure_index(refresh=True)
        self.assertIn("dropped", index.skills)
        self.assertEqual(index.skills["dropped"].source, "drop-folder")

    def test_config_dirs(self) -> None:
        collection = os.path.join(self._tmp.name, "coll")
        _write_skill(collection, "c", "configured", "Configured.")
        with open(os.environ["BLENDER_MCP_SKILLS_CONFIG"], "w", encoding="utf-8") as fh:
            json.dump({"skill_dirs": [collection], "skill_repos": []}, fh)
        index = skills_index.ensure_index(refresh=True)
        self.assertIn("configured", index.skills)

    def test_git_repo_source(self) -> None:
        repo = os.path.join(self._tmp.name, "skillrepo")
        _write_skill(repo, "g", "from-git", "From git.")
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        for cmd in (["git", "init", "-q"], ["git", "add", "-A"],
                    ["git", "commit", "-q", "-m", "x"]):
            subprocess.run(cmd, cwd=repo, check=True, env=env, capture_output=True)

        os.environ["BLENDER_MCP_SKILLS_REPOS"] = "file://" + repo
        index = skills_index.ensure_index(refresh=True)
        self.assertIn("from-git", index.skills)
        self.assertTrue(index.skills["from-git"].source.startswith("repo:"))
        # Second refresh exercises the pull path.
        index = skills_index.ensure_index(refresh=True)
        self.assertIn("from-git", index.skills)

    def test_bad_repo_is_nonfatal(self) -> None:
        os.environ["BLENDER_MCP_SKILLS_REPOS"] = "file:///nonexistent/nowhere"
        index = skills_index.ensure_index(refresh=True)
        errors = [s for s in index.sources if s.get("error")]
        self.assertEqual(len(errors), 1)

    def test_extension_skills_and_override(self) -> None:
        _write_skill(os.environ["BLENDER_MCP_SKILLS_DIR"], "d", "shared-name", "Drop version.")
        ext = os.path.join(self._tmp.name, "ext")
        _write_skill(ext, "e", "shared-name", "Extension version.")
        skills_index.register_extension_skills("testext", ext)
        index = skills_index.ensure_index(refresh=True)
        # Extensions scan last and win; the override is reported.
        self.assertEqual(index.skills["shared-name"].source, "extension:testext")
        self.assertTrue(any("overrides" in s.get("warning", "") for s in index.sources))


class TestBuiltinSource(_IndexTestCase):

    def test_builtin_collection_indexed(self) -> None:
        skills_index._BUILTIN_DIR = self._saved_builtin
        index = skills_index.ensure_index(refresh=True)
        for name in ("make-manifold", "boolean-modeling", "fillets-and-bevels",
                     "lighting-setups", "texturing-basics"):
            self.assertIn(name, index.skills)
            self.assertEqual(index.skills[name].source, "builtin")

    def test_runtime_source_overrides_builtin(self) -> None:
        skills_index._BUILTIN_DIR = self._saved_builtin
        store_dir = os.path.join(self._tmp.name, "agent-store")
        _write_skill(store_dir, "m", "make-manifold", "User-customized version.")
        skills_index.register_skills_source("agent-store", store_dir)
        index = skills_index.ensure_index(refresh=True)
        self.assertEqual(index.skills["make-manifold"].source, "agent-store")
        self.assertEqual(index.skills["make-manifold"].description,
                         "User-customized version.")


class TestSearch(_IndexTestCase):

    def test_ranking(self) -> None:
        drop = os.environ["BLENDER_MCP_SKILLS_DIR"]
        _write_skill(drop, "a", "rig-doors", "Rig a door hinge so it swings.")
        _write_skill(drop, "b", "texture-walls", "Paint textures onto walls.")
        index = skills_index.ensure_index(refresh=True)
        matches = index.search("how do I rig a swinging door")
        self.assertEqual(matches[0].name, "rig-doors")

    def test_body_fallback(self) -> None:
        drop = os.environ["BLENDER_MCP_SKILLS_DIR"]
        _write_skill(drop, "a", "alpha", "Something else.", body="mentions zanzibar once")
        index = skills_index.ensure_index(refresh=True)
        matches = index.search("zanzibar")
        self.assertEqual([m.name for m in matches], ["alpha"])

    def test_keywords_beat_description(self) -> None:
        # The production miss: "spider" must find the rigging skill even
        # though no skill is NAMED spider — keywords carry the synonyms.
        drop = os.environ["BLENDER_MCP_SKILLS_DIR"]
        _write_skill(drop, "a", "rigging-things", "Rig creatures and machines.",
                     keywords="spider, arthropod, robot, legs")
        _write_skill(drop, "b", "web-design", "Spider webs as wireframes.")
        index = skills_index.ensure_index(refresh=True)
        matches = index.search("rig a spider")
        self.assertEqual(matches[0].name, "rigging-things")


class TestMcpToolSurface(_IndexTestCase):

    def _mcp(self):
        from mcp.server.fastmcp import FastMCP
        from blmcp.tools import skills as skills_tools
        from blmcp.tools import welcome as welcome_tool
        mcp = FastMCP("test")
        skills_tools.register(mcp)
        welcome_tool.register(mcp)
        return mcp

    def _call(self, mcp, name: str, args: dict) -> dict:
        _blocks, structured = asyncio.run(mcp.call_tool(name, args))
        return structured

    def test_list_read_roundtrip(self) -> None:
        _write_skill(os.environ["BLENDER_MCP_SKILLS_DIR"], "s", "round-trip",
                     "Round trips.", files={"extra.py": "x = 1\n"})
        skills_index.ensure_index(refresh=True)
        mcp = self._mcp()

        listed = self._call(mcp, "skills_list", {})
        self.assertEqual([s["name"] for s in listed["skills"]], ["round-trip"])

        read = self._call(mcp, "skills_read", {"name": "round-trip"})
        self.assertIn("Round trips.", read["body"])
        self.assertEqual(read["files"][0]["path"], "extra.py")

        content = self._call(mcp, "skills_read", {"name": "round-trip", "file": "extra.py"})
        self.assertEqual(content["content"], "x = 1\n")

    def test_read_escape_blocked(self) -> None:
        _write_skill(os.environ["BLENDER_MCP_SKILLS_DIR"], "s", "locked", "Locked.")
        skills_index.ensure_index(refresh=True)
        result = self._call(self._mcp(), "skills_read",
                            {"name": "locked", "file": "../../etc/passwd"})
        self.assertIn("error", result)

    def test_read_resolves_alias(self) -> None:
        # The production confusion (2026-06-12): the rig tool's skill
        # names and the doc names share the word "skill" — a read of
        # "rig_thing" must land on the doc that documents it.
        _write_skill(os.environ["BLENDER_MCP_SKILLS_DIR"], "m", "mech-doc",
                     "Mechanical skills.", aliases="[rig_thing, rig_other]")
        skills_index.ensure_index(refresh=True)
        result = self._call(self._mcp(), "skills_read", {"name": "rig_thing"})
        self.assertEqual(result["name"], "mech-doc")
        self.assertIn("alias", result["note"])
        # A real skill name always beats an alias.
        _write_skill(os.environ["BLENDER_MCP_SKILLS_DIR"], "r", "rig_thing", "Real doc.")
        skills_index.ensure_index(refresh=True)
        result = self._call(self._mcp(), "skills_read", {"name": "rig_thing"})
        self.assertEqual(result["name"], "rig_thing")
        self.assertNotIn("note", result)

    def test_search_ranks_alias_like_name(self) -> None:
        drop = os.environ["BLENDER_MCP_SKILLS_DIR"]
        _write_skill(drop, "a", "mech-doc", "Machines.", aliases="[rig_widget]")
        _write_skill(drop, "b", "other-doc", "Mentions rig widget once in passing.")
        index = skills_index.ensure_index(refresh=True)
        matches = index.search("rig_widget")
        self.assertEqual(matches[0].name, "mech-doc")

    def test_search_miss_returns_catalog(self) -> None:
        _write_skill(os.environ["BLENDER_MCP_SKILLS_DIR"], "s", "only-skill", "The only one.")
        skills_index.ensure_index(refresh=True)
        result = self._call(self._mcp(), "skills_search", {"query": "xyzzy"})
        self.assertEqual(result["matches"], [])
        self.assertEqual([s["name"] for s in result["all_skills"]], ["only-skill"])
        self.assertIn("note", result)

    def test_unknown_skill_suggests(self) -> None:
        _write_skill(os.environ["BLENDER_MCP_SKILLS_DIR"], "s", "rig-doors", "Doors.")
        skills_index.ensure_index(refresh=True)
        result = self._call(self._mcp(), "skills_read", {"name": "rig-door"})
        self.assertIn("error", result)
        self.assertEqual(result["did_you_mean"], ["rig-doors"])

    def test_welcome(self) -> None:
        _write_skill(os.environ["BLENDER_MCP_SKILLS_DIR"], "s", "present", "Here.")
        skills_index.ensure_index(refresh=True)
        result = self._call(self._mcp(), "welcome", {})
        self.assertIn("Operating principles", result["instructions"])
        self.assertIn("present", result["available_skills"])


if __name__ == "__main__":
    unittest.main()
