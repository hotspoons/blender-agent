# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

# pylint: disable=C0114  # See per-tool doc-strings.

__all__ = (
    "register",
)

import datetime
import os
from typing import Any

from blmcp.agent_registry import loader, sandbox, store
from blmcp.tools_helpers.connection import send_code
from mcp.server.fastmcp import Context, FastMCP  # pylint: disable=import-error,no-name-in-module
from mcp.types import ToolAnnotations  # pylint: disable=import-error,no-name-in-module

# Skill index sources that count as "authored" (vs shipped builtins and
# tools-extension bundles) for list_agent_skills.
_SHIPPED_PREFIXES = ("builtin", "extension")


def _now() -> str:
    # Stamped on the Blender side would need a bridge hop; the server clock
    # is fine for a created-at marker.
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _skills_drop_dir() -> str:
    return os.path.expanduser(os.environ.get(
        "BLENDER_MCP_SKILLS_DIR",
        os.path.join("~", ".config", "blender-mcp", "skills")))


def _write_skill(name: str, body: str) -> str:
    """Write ``<drop>/<name>/SKILL.md`` (adding frontmatter if absent)."""
    if not store.valid_name(name):
        raise ValueError("skill name must be a lowercase slug [a-z0-9_-], 2-64 chars")
    text = body
    if not body.lstrip().startswith("---"):
        first = next((ln.strip() for ln in body.splitlines()
                      if ln.strip() and not ln.strip().startswith("#")), name)
        text = "---\nname: {:s}\ndescription: {:s}\n---\n\n{:s}".format(
            name, first[:200], body)
    path = os.path.join(_skills_drop_dir(), name)
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "SKILL.md"), "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


async def _elicit_approval(ctx: "Context | None", message: str) -> str:  # type: ignore[type-arg]
    """
    Ask the human to approve an out-of-policy authoring. Tri-state:
    ``"accept"`` (approved), ``"decline"`` (explicitly refused), or
    ``"unavailable"`` (the client has no elicitation capability — e.g. the
    in-process agent, which approves later via the UI pending-tool path).
    Never silently allows.
    """
    if ctx is None:
        return "unavailable"
    try:
        from pydantic import BaseModel  # pylint: disable=import-outside-toplevel

        class _Approve(BaseModel):
            approve: bool

        result = await ctx.elicit(message=message, schema=_Approve)
        if getattr(result, "action", None) != "accept":
            return "decline"
        data = getattr(result, "data", None)
        return "accept" if bool(getattr(data, "approve", False)) else "decline"
    except Exception:  # pylint: disable=broad-except
        return "unavailable"


def register(mcp: FastMCP) -> None:

    # --- discovery (search-first) -------------------------------------------

    @mcp.tool(annotations=ToolAnnotations(title="Search agent tools", readOnlyHint=True))
    def search_agent_tools(query: str, max_results: int = 8) -> dict[str, object]:
        """
        Search the agent-authored tool library by intent. ALWAYS try this
        before solving a task from scratch with execute_blender_code — a
        tested tool may already exist. Returns ranked {name, description}.
        """
        hits = store.search(query, max_results=max(1, min(int(max_results), 25)))
        return {"query": query, "results": [t.summary() for t in hits],
                "hint": "Use agent_tool_details(name) for the schema, then run_agent_tool(name, args)."}

    @mcp.tool(annotations=ToolAnnotations(title="List agent tools", readOnlyHint=True))
    def list_agent_tools() -> dict[str, object]:
        """List every agent-authored tool with a one-line summary."""
        tools = store.list_all()
        return {"n": len(tools), "tools": [t.summary() for t in tools]}

    @mcp.tool(annotations=ToolAnnotations(title="List agent skills", readOnlyHint=True))
    def list_agent_skills() -> dict[str, object]:
        """
        List agent/user-authored skills (excludes shipped builtins and
        tools-extension bundles). Read one with skills_read(name).
        """
        from blmcp.skills import ensure_index
        index = ensure_index()
        out = []
        for skill in sorted(index.skills.values(), key=lambda s: s.name):
            src = skill.source or ""
            if any(src.startswith(p) for p in _SHIPPED_PREFIXES):
                continue
            out.append({"name": skill.name, "description": skill.description, "source": src})
        return {"n": len(out), "skills": out}

    @mcp.tool(annotations=ToolAnnotations(title="Agent tool details", readOnlyHint=True))
    def agent_tool_details(name: str) -> dict[str, object]:
        """
        Full detail for one capability: an authored tool's input schema +
        code + approval/imports, or — if *name* is a skill — its body.
        """
        tool = store.get(name)
        if tool is not None:
            try:
                code = tool.code()
            except OSError:
                code = ""
            return {
                "kind": "tool", "name": tool.name, "description": tool.description,
                "params_schema": tool.params_schema, "approved": tool.approved,
                "granted_imports": list(tool.granted_imports), "version": tool.version,
                "code": code,
            }
        from blmcp.skills import ensure_index
        skill = ensure_index().skills.get(name)
        if skill is not None:
            try:
                body = skill.body()
            except OSError:
                body = ""
            return {"kind": "skill", "name": skill.name,
                    "description": skill.description, "body": body}
        return {"error": "no agent tool or skill named {!r}".format(name)}

    # --- execution ----------------------------------------------------------

    @mcp.tool(annotations=ToolAnnotations(title="Run agent tool", destructiveHint=True))
    def run_agent_tool(name: str, args: dict[str, Any] | None = None) -> dict[str, object]:
        """
        Run an agent-authored tool by name with *args* (an object matching
        its params_schema). Executes in Blender through the same path as
        execute_blender_code, under the tool's approved import policy.
        """
        tool = store.get(name)
        if tool is None:
            return {"error": "no agent tool named {!r}; try search_agent_tools".format(name)}
        return loader.run(tool, args or {}, send_code)

    # --- authoring ----------------------------------------------------------

    @mcp.tool(annotations=ToolAnnotations(title="Author agent tool"))
    async def author_tool(name: str, description: str, code: str,
                          params_schema: dict[str, Any] | None = None,
                          modules: dict[str, str] | None = None,
                          ctx: Context = None,  # type: ignore[assignment, type-arg]
                          dry_run: bool = False) -> dict[str, object]:
        """
        Create (or update) a reusable agent tool. *code* (the entry) receives
        a dict ``params`` and must assign a dict ``result``; it runs in Blender
        with bpy. For bigger tools, pass *modules* = {name: source} — extra
        files importable by bare name from the entry and each other (a bundle).
        You may also import curated framework SDKs (e.g. `blrig`) to compose
        existing skills. Imports are jailed to a 3D-modeling allowlist; anything
        outside it (network, subprocess, etc.) prompts you for approval before
        the tool is saved. dry_run validates without saving.
        """
        if not store.valid_name(name):
            return {"error": "name must be a lowercase slug [a-z0-9_-], 2-64 chars"}
        schema = params_schema or {}
        modules = dict(modules or {})
        for sib in modules:
            if not store.valid_module_name(sib):
                return {"error": "bundle module {!r} must be a lowercase identifier "
                                 "(not 'tool')".format(sib)}
            if sib in sandbox.allowed_modules():
                return {"error": "bundle module {!r} collides with an allowed module; "
                                 "rename it".format(sib)}
        verdict = sandbox.classify_modules(code, modules, granted=())
        if verdict["syntax_error"]:
            return {"error": "code does not parse: {:s}".format(verdict["syntax_error"])}

        granted: list[str] = []
        pending: list[str] = []
        if not verdict["ok"]:
            bits = []
            if verdict["outside_imports"]:
                bits.append("imports outside the 3D allowlist: {:s}".format(
                    ", ".join(verdict["outside_imports"])))
            if verdict["flags"]:
                bits.append("dynamic execution: {:s}".format(", ".join(verdict["flags"])))
            detail = "; ".join(bits)
            message = ("Agent tool {!r} requests {:s}. Approve and save this tool? "
                       "(These run in Blender's Python.)".format(name, detail))
            decision = await _elicit_approval(ctx, message)
            store.audit({"ts": _now(), "event": "author_tool", "name": name,
                         "escapes": detail, "decision": decision})
            if decision == "decline":
                return {"error": "not approved: {:s}. Tool not saved.".format(detail),
                        "needs_approval": {"imports": verdict["outside_imports"],
                                           "flags": verdict["flags"]}}
            if decision == "accept":
                granted = list(verdict["outside_imports"])
            else:  # "unavailable" — persist INERT, awaiting human approval in the UI
                pending = list(verdict["outside_imports"])
        else:
            store.audit({"ts": _now(), "event": "author_tool", "name": name,
                         "escapes": "", "decision": "auto"})

        approved = not pending  # pending tools save approved=False (run_agent_tool refuses)
        if dry_run:
            return {"dry_run": True, "would_save": name, "approved": approved,
                    "granted_imports": granted, "pending_imports": pending}

        tool = store.save(name=name, description=description, code=code,
                          params_schema=schema, granted_imports=tuple(granted),
                          approved=approved, author="agent", created=_now(),
                          pending_imports=tuple(pending), siblings=modules)
        if pending:
            # The UI surfaces this (see chat-stage) so a human can Approve/Reject;
            # external MCP clients had the inline elicitation above instead.
            return {"ok": True, "name": tool.name, "version": tool.version,
                    "approved": False,
                    "needs_approval": {"imports": pending, "flags": verdict["flags"]},
                    "hint": ("Saved but INERT pending human approval of imports: {:s}. "
                             "Approve it in the agent UI; until then run_agent_tool "
                             "refuses it.").format(", ".join(pending))}
        return {"ok": True, "name": tool.name, "version": tool.version, "approved": True,
                "granted_imports": list(tool.granted_imports),
                "hint": "Discoverable via search_agent_tools; run with run_agent_tool."}

    @mcp.tool(annotations=ToolAnnotations(title="Author agent skill"))
    def author_skill(name: str, body: str) -> dict[str, object]:
        """
        Save a reusable skill (markdown recipe) so future agents can find
        it via skills_search / list_agent_skills. Write one after a recipe
        is confirmed to work. Skills are knowledge, not executed directly.
        """
        try:
            path = _write_skill(name, body)
        except (ValueError, OSError) as ex:
            return {"error": str(ex)}
        from blmcp.skills import ensure_index
        ensure_index(refresh=True)
        store.audit({"ts": _now(), "event": "author_skill", "name": name})
        return {"ok": True, "name": name, "path": path,
                "hint": "Now visible to skills_read / skills_search / list_agent_skills."}
