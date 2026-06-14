# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Filesystem store for agent-authored tools (the dynamic "Tier B" registry).

One directory per tool under ``~/.config/blender-mcp/agent_tools/<name>/``
(override with ``BLENDER_MCP_AGENT_TOOLS_DIR``), mirroring the skills
layout so both the MCP server and the in-process agent — which share this
filesystem — see the same library:

    <name>/
      tool.json   # name, description, params_schema, granted_imports,
                  # approved, author, version, created
      tool.py     # body: reads `params` (dict), assigns `result` (dict)

Authored *skills* are NOT stored here — they reuse the core skills index
(``blmcp.skills``), which already propagates everywhere. This module is
tools only. Every author/approve/remove is appended to ``audit.jsonl``.
"""

__all__ = (
    "AuthoredTool",
    "audit",
    "get",
    "list_all",
    "remove",
    "save",
    "search",
    "set_approval",
    "tools_dir",
    "valid_name",
)

import dataclasses
import glob
import json
import os
import re
from typing import Any

_DEFAULT_DIR = os.path.join("~", ".config", "blender-mcp", "agent_tools")
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")
_MODULE_RE = re.compile(r"^[a-z_][a-z0-9_]{0,63}$")
_WORD_RE = re.compile(r"[a-z0-9]+")


def tools_dir() -> str:
    return os.path.expanduser(
        os.environ.get("BLENDER_MCP_AGENT_TOOLS_DIR", _DEFAULT_DIR))


def valid_name(name: str) -> bool:
    """Lowercase slug; guards against path traversal and tool-list noise."""
    return bool(_NAME_RE.match(name or ""))


def valid_module_name(name: str) -> bool:
    """A bundle sibling must be a lowercase Python identifier (and not the entry)."""
    return name != "tool" and bool(_MODULE_RE.match(name or ""))


def _tokens(text: str) -> list[str]:
    # Same naive plural-stemming tokenizer the skills index uses, so search
    # behaves consistently across skills and tools.
    return [t[:-1] if len(t) > 3 and t.endswith("s") else t
            for t in _WORD_RE.findall((text or "").lower())]


@dataclasses.dataclass
class AuthoredTool:
    name: str
    description: str
    params_schema: dict[str, Any]
    granted_imports: tuple[str, ...]
    approved: bool
    author: str
    version: int
    created: str
    path: str  # the tool's directory
    # Imports outside the allowlist that a human must approve before this
    # tool can run; non-empty only while approved is False (awaiting a
    # decision). Cleared into granted_imports on approval.
    pending_imports: tuple[str, ...] = ()
    # True when this tool ships with the package (read-only seed) rather than
    # the user's writable dir. User-local tools shadow bundled ones by name.
    bundled: bool = False

    @property
    def code_path(self) -> str:
        return os.path.join(self.path, "tool.py")

    def code(self) -> str:
        with open(self.code_path, encoding="utf-8") as fh:
            return fh.read()

    def siblings(self) -> dict[str, str]:
        """
        Bundle sibling modules ``{name: source}`` — every ``*.py`` beside
        ``tool.py`` (the entry). Empty for a single-file tool.
        """
        out: dict[str, str] = {}
        for path in sorted(glob.glob(os.path.join(self.path, "*.py"))):
            stem = os.path.splitext(os.path.basename(path))[0]
            if stem == "tool":
                continue
            try:
                with open(path, encoding="utf-8") as fh:
                    out[stem] = fh.read()
            except OSError:
                continue
        return out

    def is_bundle(self) -> bool:
        return bool(self.siblings())

    def summary(self) -> dict[str, Any]:
        # One-line view for list/search (no code body).
        out: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "approved": self.approved,
            "version": self.version,
        }
        if self.pending_imports:
            out["pending_imports"] = list(self.pending_imports)
        if self.bundled:
            out["bundled"] = True
        return out


def _bundled_dir() -> str:
    """Read-only Tier-B tools that ship in the package (blmcp/data/agent_tools)."""
    return os.environ.get("BLENDER_MCP_AGENT_TOOLS_SEED_DIR") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "agent_tools")


def _load_dir(path: str, bundled: bool = False) -> "AuthoredTool | None":
    meta_path = os.path.join(path, "tool.json")
    if not (os.path.isfile(meta_path) and os.path.isfile(os.path.join(path, "tool.py"))):
        return None
    try:
        with open(meta_path, encoding="utf-8") as fh:
            meta = json.load(fh)
    except (OSError, ValueError):
        return None
    return AuthoredTool(
        name=meta.get("name", os.path.basename(path)),
        description=meta.get("description", ""),
        params_schema=meta.get("params_schema") or {},
        granted_imports=tuple(meta.get("granted_imports") or ()),
        approved=bool(meta.get("approved", False)),
        author=meta.get("author", ""),
        version=int(meta.get("version", 1)),
        created=meta.get("created", ""),
        path=path,
        pending_imports=tuple(meta.get("pending_imports") or ()),
        bundled=bundled,
    )


def list_all() -> list["AuthoredTool"]:
    """
    All tools (bundled seed + user-local), name-sorted. A user-local tool
    shadows a bundled one of the same name. Unreadable dirs are skipped.
    """
    merged: dict[str, "AuthoredTool"] = {}
    for root, is_bundled in ((_bundled_dir(), True), (tools_dir(), False)):
        if not os.path.isdir(root):
            continue
        for entry in sorted(os.listdir(root)):
            full = os.path.join(root, entry)
            if os.path.isdir(full):
                tool = _load_dir(full, bundled=is_bundled)
                if tool is not None:
                    merged[tool.name] = tool  # user (scanned last) wins
    return [merged[name] for name in sorted(merged)]


def get(name: str) -> "AuthoredTool | None":
    if not valid_name(name):
        return None
    # User-local shadows bundled.
    user = _load_dir(os.path.join(tools_dir(), name), bundled=False)
    if user is not None:
        return user
    return _load_dir(os.path.join(_bundled_dir(), name), bundled=True)


def save(*, name: str, description: str, code: str, params_schema: dict[str, Any],
         granted_imports: tuple[str, ...] = (), approved: bool, author: str = "agent",
         created: str = "", pending_imports: tuple[str, ...] = (),
         siblings: dict[str, str] | None = None) -> "AuthoredTool":
    """
    Write/overwrite a tool, bumping ``version`` when it already exists.
    *siblings* (name->source) are extra bundle modules written beside the
    entry ``tool.py``; stale siblings from a previous version are pruned.
    Caller is responsible for policy (approval / import grants).
    """
    if not valid_name(name):
        raise ValueError(
            "tool name must be a lowercase slug [a-z0-9_-], 2-64 chars: {!r}".format(name))
    siblings = dict(siblings or {})
    for sib in siblings:
        if not valid_module_name(sib):
            raise ValueError(
                "bundle module name must be a lowercase identifier (not 'tool'): {!r}".format(sib))
    root = tools_dir()
    path = os.path.join(root, name)
    os.makedirs(path, exist_ok=True)
    existing = _load_dir(path)
    version = (existing.version + 1) if existing else 1
    meta = {
        "name": name,
        "description": description,
        "params_schema": params_schema or {},
        "granted_imports": sorted(set(granted_imports)),
        "approved": bool(approved),
        "author": author,
        "version": version,
        "created": created or (existing.created if existing else ""),
        "pending_imports": sorted(set(pending_imports)),
    }
    tmp_meta = os.path.join(path, "tool.json.tmp")
    with open(tmp_meta, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2, sort_keys=True)
    os.replace(tmp_meta, os.path.join(path, "tool.json"))
    tmp_code = os.path.join(path, "tool.py.tmp")
    with open(tmp_code, "w", encoding="utf-8") as fh:
        fh.write(code)
    os.replace(tmp_code, os.path.join(path, "tool.py"))
    # Bundle siblings: prune any *.py no longer part of the tool, then write.
    keep = {"tool.py"} | {"{:s}.py".format(n) for n in siblings}
    for stale_py in glob.glob(os.path.join(path, "*.py")):
        if os.path.basename(stale_py) not in keep:
            os.remove(stale_py)
    for sib_name, sib_src in siblings.items():
        tmp_sib = os.path.join(path, "{:s}.py.tmp".format(sib_name))
        with open(tmp_sib, "w", encoding="utf-8") as fh:
            fh.write(sib_src)
        os.replace(tmp_sib, os.path.join(path, "{:s}.py".format(sib_name)))
    loaded = _load_dir(path)
    assert loaded is not None, "tool written but failed to reload: {!r}".format(name)
    return loaded


def set_approval(name: str, approve: bool) -> "AuthoredTool | None":
    """
    Trusted approval flip for a pending tool — NOT reachable as an MCP tool,
    so the model cannot self-approve. On approve, the pending imports become
    granted and the tool goes live; on reject, the (inert) tool is removed.
    Returns the updated tool, or None when unknown / on reject.
    """
    tool = get(name)
    if tool is None:
        return None
    if not approve:
        remove(name)
        return None
    return save(
        name=tool.name, description=tool.description, code=tool.code(),
        params_schema=tool.params_schema,
        granted_imports=tuple(tool.granted_imports) + tuple(tool.pending_imports),
        approved=True, author=tool.author, created=tool.created,
        pending_imports=(), siblings=tool.siblings())


def remove(name: str) -> bool:
    if not valid_name(name):
        return False
    import shutil
    path = os.path.join(tools_dir(), name)
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)
        return True
    return False


def search(query: str, max_results: int = 8) -> list["AuthoredTool"]:
    """
    Rank authored tools by query overlap with name / description / code,
    mirroring the skills search so agents discover tools the same way.
    """
    terms = set(_tokens(query))
    if not terms:
        return []
    scored: list[tuple[int, "AuthoredTool"]] = []
    for tool in list_all():
        name_tokens = set(_tokens(tool.name.replace("_", " ")))
        desc_tokens = _tokens(tool.description)
        score = 8 * len(terms & name_tokens)
        score += 3 * sum(1 for t in desc_tokens if t in terms)
        if score == 0:
            try:
                body_tokens = _tokens(tool.code())
            except OSError:
                body_tokens = []
            score += sum(1 for t in body_tokens if t in terms)
        if score > 0:
            scored.append((score, tool))
    scored.sort(key=lambda pair: (-pair[0], pair[1].name))
    return [tool for _score, tool in scored[:max_results]]


def audit(event: dict[str, Any]) -> None:
    """Append a one-line JSON audit record (never raises)."""
    try:
        root = tools_dir()
        os.makedirs(root, exist_ok=True)
        with open(os.path.join(root, "audit.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, sort_keys=True) + "\n")
    except OSError:
        pass
