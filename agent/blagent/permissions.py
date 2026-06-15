# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Tool RBAC: a role → tool permissions matrix, loaded from a YAML file that
ships with the app (``data/permissions.yaml``) and is overridable per
deployment. Each (role, tool) resolves to one of three LEVELS:

    allow      the role may call the tool freely
    elicit     the tool is offered, but the harness asks the user to confirm
               before it runs (e.g. the orchestrator changing autonomy)
    disabled   the tool is hidden from the role entirely (not in its registry)

A level can be set per tool (exact name or shell wildcard), per tool GROUP
(tools declare ``group`` — see ``Tool.group``), or as the role ``default``.
Most specific wins: exact tool > wildcard tool > group > role default >
"allow". A role inherits ``default`` when missing/unknown, so adding a caller
never locks it out before the matrix is updated.

The matrix is deliberately standalone, data-driven, and introspectable
(``as_public``) so a live RBAC editor / group enable-disable UI / dynamic
roles can be built on top later without touching call sites.
"""

__all__ = (
    "ALLOW",
    "DISABLED",
    "ELICIT",
    "ToolPermissions",
    "WORKER_DENY",
)

import fnmatch
import os
from typing import Any, Iterable

ALLOW = "allow"
ELICIT = "elicit"
DISABLED = "disabled"
_LEVELS = (ALLOW, ELICIT, DISABLED)

# The hardcoded floor for the worker role — also the default matrix value.
# Workers must never reach orchestrator/user-facing meta-tools, regardless of
# (mis)configuration; the runtime applies this as defense in depth too.
WORKER_DENY = ("set_autonomy", "ask_user")

# Built-in starting roles. NOT hardcoded into call sites — roles are looked up
# by string against the (YAML-overridable) matrix, so deployments can add roles
# without code changes. `default` is the catch-all (e.g. the interactive agent).
_DEFAULT_MATRIX: dict[str, dict[str, Any]] = {
    "default": {"default": ALLOW},
    # Delegates objectives to workers; full surface, but autonomy changes
    # are confirmed with the user.
    "orchestrator": {"default": ALLOW, "tools": {"set_autonomy": ELICIT}},
    # Autonomous sub-agent on one task: no user to ask, no self-autonomy.
    "worker": {"default": ALLOW, "tools": {name: DISABLED for name in WORKER_DENY}},
    # Decomposes a goal/objectives into worker tasks (LlmPlanner + the draft
    # step). A pure LLM call — no tools.
    "planner": {"default": DISABLED},
    # Context-blind budget judge (reviewer.py): a pure adjudicator — no tools.
    "reviewer": {"default": DISABLED},
    # Dedicated per-worker QA reviewer: read-only state probes to judge a
    # worker's proof against the actual scene (evidence, not narrative). Covers
    # both the legacy get_*/*summary* tools AND the verb-dispatched core tools
    # (scene/blendfile/capture/docs) so the allow-list survives the tool collapse.
    "qa": {"default": DISABLED, "tools": {
        "get_*": ALLOW, "*summary*": ALLOW, "*diagnostics*": ALLOW,
        "scene": ALLOW, "blendfile": ALLOW, "capture": ALLOW, "docs": ALLOW,
        "skills": ALLOW, "media_io": ALLOW}},
    # Independent verifier: read-only state probes only (same dual coverage).
    "auditor": {"default": DISABLED, "tools": {
        "get_*": ALLOW, "*summary*": ALLOW, "*diagnostics*": ALLOW,
        "scene": ALLOW, "blendfile": ALLOW, "capture": ALLOW, "docs": ALLOW,
        "skills": ALLOW, "media_io": ALLOW}},
}

_DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "permissions.yaml")


def _coerce_level(value: Any, fallback: str = ALLOW) -> str:
    text = str(value).strip().lower()
    return text if text in _LEVELS else fallback


class ToolPermissions:
    """A role→tool 3-level permissions matrix."""

    def __init__(self, roles: dict[str, dict[str, Any]] | None = None) -> None:
        self._roles = roles or {k: dict(v) for k, v in _DEFAULT_MATRIX.items()}
        self._roles.setdefault("default", {"default": ALLOW})

    # -- construction -------------------------------------------------------
    @classmethod
    def default(cls) -> "ToolPermissions":
        return cls()

    @classmethod
    def load(cls, path: str | None = None) -> "ToolPermissions":
        """Load the matrix from YAML; fall back to the built-in default when
        the file is absent or unparseable (RBAC must never hard-fail boot)."""
        target = path or os.environ.get("BLENDER_AGENT_PERMISSIONS") or _DATA_PATH
        try:
            import yaml
            with open(target, encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
        except FileNotFoundError:
            return cls()
        except Exception:  # pylint: disable=broad-except
            return cls()
        roles = data.get("roles") if isinstance(data, dict) else None
        if not isinstance(roles, dict):
            return cls()
        clean: dict[str, dict[str, Any]] = {}
        for role, spec in roles.items():
            if not isinstance(spec, dict):
                continue
            entry: dict[str, Any] = {"default": _coerce_level(spec.get("default", ALLOW))}
            for key in ("tools", "groups"):
                table = spec.get(key)
                if isinstance(table, dict):
                    entry[key] = {str(k): _coerce_level(v) for k, v in table.items()}
            clean[str(role)] = entry
        return cls(clean or None)

    # -- queries ------------------------------------------------------------
    def _spec(self, role: str) -> dict[str, Any]:
        return self._roles.get(role) or self._roles.get("default") or {"default": ALLOW}

    def level(self, role: str, tool_name: str, group: str = "") -> str:
        """Resolve the permission level for (role, tool). Most specific wins:
        exact tool > wildcard tool > group > role default > allow."""
        spec = self._spec(role)
        tools = spec.get("tools") or {}
        if tool_name in tools:                                  # exact tool
            return tools[tool_name]
        for pattern, lvl in tools.items():                      # wildcard tool
            if pattern != tool_name and fnmatch.fnmatchcase(tool_name, pattern):
                return lvl
        groups = spec.get("groups") or {}
        if group and group in groups:                           # group
            return groups[group]
        for pattern, lvl in groups.items():
            if group and fnmatch.fnmatchcase(group, pattern):
                return lvl
        return _coerce_level(spec.get("default", ALLOW))

    def allowed(self, role: str, tool_name: str, group: str = "") -> bool:
        """True when the tool is visible to the role (allow OR elicit)."""
        return self.level(role, tool_name, group) != DISABLED

    def requires_elicit(self, role: str, tool_name: str, group: str = "") -> bool:
        return self.level(role, tool_name, group) == ELICIT

    def filter_tools(self, role: str, tools: Iterable[Any]) -> list[Any]:
        """Keep the tools the role may see (drops ``disabled``)."""
        return [t for t in tools
                if self.allowed(role, getattr(t, "name", ""), getattr(t, "group", ""))]

    def elicit_tool_names(self, role: str, tools: Iterable[Any]) -> set[str]:
        """Names of tools at the ``elicit`` level for this role."""
        return {getattr(t, "name", "") for t in tools
                if self.requires_elicit(role, getattr(t, "name", ""), getattr(t, "group", ""))}

    def roles(self) -> list[str]:
        return [r for r in self._roles if r != "default"]

    def as_public(self) -> dict[str, dict[str, Any]]:
        """The matrix as plain data (for a future RBAC editor / introspection)."""
        return {role: dict(spec) for role, spec in self._roles.items()}
