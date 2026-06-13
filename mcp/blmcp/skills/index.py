# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Skill discovery, parsing and search. See package docstring for the model.
"""

__all__ = (
    "Skill",
    "ensure_index",
    "get_index",
    "parse_skill_md",
    "register_extension_skills",
    "register_skills_source",
    "scan_collection",
)

import dataclasses
import hashlib
import os
import re
import subprocess

import yaml

_CONFIG_PATH_DEFAULT = os.path.join("~", ".config", "blender-mcp", "skills.json")

# Baseline skills shipped with the core server. Scanned first, so every
# other source can override them by name.
_BUILTIN_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "skills")
_DROP_DIR_DEFAULT = os.path.join("~", ".config", "blender-mcp", "skills")
_REPO_CACHE_DEFAULT = os.path.join("~", ".cache", "blender-mcp", "skill-repos")

_GIT_TIMEOUT = 60.0

# No underscore in the token class: identifiers like ``rig_hinge`` must
# match the words "rig" and "hinge".
_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    """
    Lowercase word tokens with naive plural stemming (trailing ``s``),
    applied identically to queries and skill text.
    """
    return [
        t[:-1] if len(t) > 3 and t.endswith("s") else t
        for t in _WORD_RE.findall(text.lower())
    ]

# Extension-bundled collections, registered before the index is built.
_EXTENSION_DIRS: list[tuple[str, str]] = []  # (label, path)


@dataclasses.dataclass
class Skill:
    name: str
    description: str
    path: str        # directory containing SKILL.md
    source: str      # human-readable source label ("drop-folder", "repo:...", "extension:...")
    keywords: str = ""   # frontmatter `keywords:` — search synonyms ("spider, arthropod, ...")
    # Frontmatter `aliases:` — other identifiers this doc answers for
    # (e.g. the rig tool's skill names: skills_read("rig_chain") should
    # land on the doc that documents rig_chain).
    aliases: tuple[str, ...] = ()

    @property
    def skill_md(self) -> str:
        return os.path.join(self.path, "SKILL.md")

    def body(self) -> str:
        with open(self.skill_md, encoding="utf-8") as fh:
            return fh.read()

    def files(self) -> list[dict]:
        """
        Ancillary files beside SKILL.md (relative paths + sizes).
        """
        found = []
        for root, dirs, names in os.walk(self.path):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for name in names:
                if name == "SKILL.md" and root == self.path:
                    continue
                full = os.path.join(root, name)
                found.append({
                    "path": os.path.relpath(full, self.path),
                    "size": os.path.getsize(full),
                })
        found.sort(key=lambda f: f["path"])
        return found


def _meta_list(raw: object) -> list[str]:
    """
    A frontmatter value that may be a YAML list or a comma string.
    """
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    return [part.strip() for part in str(raw or "").split(",") if part.strip()]


def parse_skill_md(path: str) -> tuple[str, str, str, tuple[str, ...]]:
    """
    Return ``(name, description, keywords, aliases)`` from a SKILL.md's
    YAML frontmatter. Falls back to the directory name / first body line
    when absent; ``keywords`` (search synonyms, comma string) and
    ``aliases`` (alternate lookup identifiers) are optional.
    """
    with open(path, encoding="utf-8") as fh:
        text = fh.read()

    name = os.path.basename(os.path.dirname(os.path.abspath(path)))
    description = ""
    keywords = ""
    aliases: tuple[str, ...] = ()
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                meta = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                meta = {}
            if isinstance(meta, dict):
                name = str(meta.get("name", name))
                description = str(meta.get("description", ""))
                keywords = ", ".join(_meta_list(meta.get("keywords", "")))
                aliases = tuple(_meta_list(meta.get("aliases", "")))
            body = parts[2]
    if not description:
        for line in body.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                description = stripped
                break
    return name, description, keywords, aliases


def scan_collection(directory: str, source: str) -> list[Skill]:
    """
    Find every skill in *directory*: any folder (the root included)
    containing a ``SKILL.md``.
    """
    skills: list[Skill] = []
    directory = os.path.abspath(os.path.expanduser(directory))
    if not os.path.isdir(directory):
        return skills
    for root, dirs, names in os.walk(directory):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        if "SKILL.md" in names:
            skill_md = os.path.join(root, "SKILL.md")
            try:
                name, description, keywords, aliases = parse_skill_md(skill_md)
            except OSError:
                continue
            skills.append(Skill(
                name=name, description=description, path=root, source=source,
                keywords=keywords, aliases=aliases))
            # A skill dir's subfolders are ancillary, not nested skills.
            dirs[:] = []
    return skills


# -----------------------------------------------------------------------------
# Git-repo sources


def _repo_cache_dir(url: str) -> str:
    cache_root = os.path.expanduser(
        os.environ.get("BLENDER_MCP_SKILLS_REPO_CACHE", _REPO_CACHE_DEFAULT))
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", url.rstrip("/").rsplit("/", 1)[-1])[:48]
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
    return os.path.join(cache_root, "{:s}-{:s}".format(slug or "repo", digest))


def sync_repo(url: str) -> tuple[str | None, str | None]:
    """
    Clone (shallow) or fast-forward *url* into the cache. Returns
    ``(checkout_path, error)`` — a stale cached checkout is still used
    when the network fetch fails.
    """
    checkout = _repo_cache_dir(url)
    try:
        # Windows: keep git from flashing a console window on each sync.
        no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if os.path.isdir(os.path.join(checkout, ".git")):
            subprocess.run(
                ["git", "-C", checkout, "pull", "--ff-only", "--quiet"],
                check=True, capture_output=True, timeout=_GIT_TIMEOUT,
                creationflags=no_window)
        else:
            os.makedirs(os.path.dirname(checkout), exist_ok=True)
            subprocess.run(
                ["git", "clone", "--depth", "1", "--quiet", url, checkout],
                check=True, capture_output=True, timeout=_GIT_TIMEOUT,
                creationflags=no_window)
        return checkout, None
    except subprocess.CalledProcessError as ex:
        error = (ex.stderr or b"").decode("utf-8", "replace").strip() or str(ex)
    except (subprocess.TimeoutExpired, OSError) as ex:
        error = str(ex)
    if os.path.isdir(checkout):
        return checkout, "using stale cache, sync failed: {:s}".format(error)
    return None, error


# -----------------------------------------------------------------------------
# Configuration


def _load_config() -> dict:
    """
    ``{"skill_dirs": [...], "skill_repos": [...]}`` from the JSON config
    (maintained by the Blender add-on preferences UI) plus env overrides
    ``BLENDER_MCP_SKILLS_DIRS`` (pathsep-joined) and
    ``BLENDER_MCP_SKILLS_REPOS`` (comma-joined).
    """
    import json

    path = os.path.expanduser(
        os.environ.get("BLENDER_MCP_SKILLS_CONFIG", _CONFIG_PATH_DEFAULT))
    config = {"skill_dirs": [], "skill_repos": []}
    try:
        with open(path, encoding="utf-8") as fh:
            loaded = json.load(fh)
        if isinstance(loaded, dict):
            for key in config:
                value = loaded.get(key)
                if isinstance(value, list):
                    config[key] = [str(v) for v in value if str(v).strip()]
    except (OSError, ValueError):
        pass

    env_dirs = os.environ.get("BLENDER_MCP_SKILLS_DIRS", "")
    config["skill_dirs"] += [d for d in env_dirs.split(os.pathsep) if d.strip()]
    env_repos = os.environ.get("BLENDER_MCP_SKILLS_REPOS", "")
    config["skill_repos"] += [r.strip() for r in env_repos.split(",") if r.strip()]
    return config


def register_skills_source(label: str, directory: str) -> None:
    """
    Register an extra skill collection at runtime (tools extensions, the
    agent's own skill store, ...). Runtime sources are scanned last, so
    they override builtins and configured sources on name collisions.
    """
    entry = (label, directory)
    if entry not in _EXTENSION_DIRS:
        _EXTENSION_DIRS.append(entry)
    # A late registration invalidates an already-built index.
    global _INDEX
    _INDEX = None


def register_extension_skills(label: str, directory: str) -> None:
    """
    Tools-extension wrapper around :func:`register_skills_source` (kept as
    the documented extension hook name).
    """
    register_skills_source("extension:{:s}".format(label), directory)


# -----------------------------------------------------------------------------
# The index


class SkillIndex:

    def __init__(self) -> None:
        self.skills: dict[str, Skill] = {}
        self.sources: list[dict] = []

    def build(self) -> None:
        self.skills.clear()
        self.sources.clear()
        config = _load_config()

        scan_plan: list[tuple[str, str]] = []
        scan_plan.append(("builtin", _BUILTIN_DIR))
        drop_dir = os.path.expanduser(
            os.environ.get("BLENDER_MCP_SKILLS_DIR", _DROP_DIR_DEFAULT))
        scan_plan.append(("drop-folder", drop_dir))
        for directory in config["skill_dirs"]:
            scan_plan.append(("dir:{:s}".format(directory), directory))
        for url in config["skill_repos"]:
            checkout, error = sync_repo(url)
            if checkout is None:
                self.sources.append({"source": "repo:{:s}".format(url),
                                     "n_skills": 0, "error": error})
                continue
            scan_plan.append(("repo:{:s}".format(url), checkout))
            if error:
                self.sources.append({"source": "repo:{:s}".format(url),
                                     "warning": error})
        for label, directory in _EXTENSION_DIRS:
            scan_plan.append((label, directory))

        for source, directory in scan_plan:
            found = scan_collection(directory, source)
            for skill in found:
                # Later sources win on name collisions (drop folder first,
                # extensions last) — keep it deterministic and report it.
                if skill.name in self.skills:
                    self.sources.append({
                        "source": source,
                        "warning": "skill {!r} overrides {:s}".format(
                            skill.name, self.skills[skill.name].source),
                    })
                self.skills[skill.name] = skill
            self.sources.append({"source": source, "n_skills": len(found),
                                 "path": directory})

    def resolve(self, name: str) -> "Skill | None":
        """
        Look *name* up as a skill name first, then as a frontmatter
        alias (e.g. a rig-tool skill name resolving to the doc that
        documents it). Real names always win over aliases.
        """
        skill = self.skills.get(name)
        if skill is not None:
            return skill
        for candidate in self.skills.values():
            if name in candidate.aliases:
                return candidate
        return None

    def search(self, query: str, max_results: int = 8) -> list[Skill]:
        terms = set(_tokens(query))
        if not terms:
            return []
        scored: list[tuple[int, Skill]] = []
        for skill in self.skills.values():
            name_tokens = set(_tokens(skill.name))
            alias_tokens = set(_tokens(" ".join(skill.aliases)))
            keyword_tokens = set(_tokens(skill.keywords))
            desc_tokens = _tokens(skill.description)
            score = 0
            score += 8 * len(terms & name_tokens)
            score += 8 * len(terms & alias_tokens)
            score += 6 * len(terms & keyword_tokens)
            score += 3 * sum(1 for t in desc_tokens if t in terms)
            if score == 0:
                try:
                    body_tokens = _tokens(skill.body())
                except OSError:
                    body_tokens = []
                score += sum(1 for t in body_tokens if t in terms)
            if score > 0:
                scored.append((score, skill))
        scored.sort(key=lambda pair: (-pair[0], pair[1].name))
        return [skill for _score, skill in scored[:max_results]]


_INDEX: SkillIndex | None = None


def get_index() -> SkillIndex | None:
    return _INDEX


def ensure_index(refresh: bool = False) -> SkillIndex:
    global _INDEX
    if _INDEX is None or refresh:
        index = SkillIndex()
        index.build()
        _INDEX = index
    return _INDEX
