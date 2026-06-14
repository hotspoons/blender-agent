# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Harness-side tools: the skills library (with full-text search), media
recall, agent memory, and the hidden ``continue_working`` budget tool.

Ported from Foyer Studio's ``scripts`` / ``media`` /
``continue_working`` tools, reshaped for Blender. Skills follow Foyer's
polymorphic-subcommand pattern: one tool, a ``subcommand``
discriminator inside the args.
"""

__all__ = (
    "AskUserTool",
    "ContinueWorkingTool",
    "MediaTool",
    "SetAutonomyTool",
    "SkillsTool",
)

from typing import Any, Awaitable, Callable

from .store import AgentStore, search_skills
from .tools import Tool, ToolContext, ToolError, ToolResult


class AskUserTool(Tool):
    name = "ask_user"
    read_only = True  # asking is not scene work; don't burn a full round on it
    description = (
        "Ask the USER a question and wait for their answer before continuing. "
        "Use when you need a decision only the user can make — a choice between "
        "real alternatives, a missing preference, or confirmation of intent — "
        "not for things you can determine yourself. Provide clear 'options' for "
        "a quick pick; the user can always type a freeform answer too. Returns "
        "the user's selection(s) and any freeform text. Prefer this over "
        "guessing when the task is genuinely ambiguous."
    )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The question to ask the user."},
                "options": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Suggested choices (may be empty for a pure freeform ask).",
                },
                "allow_freeform": {
                    "type": "boolean",
                    "description": "Allow a typed answer in addition to the options (default true).",
                },
                "multi": {
                    "type": "boolean",
                    "description": "Allow selecting more than one option (default false).",
                },
            },
            "required": ["question"],
        }

    async def call(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        question = str(args.get("question", "")).strip()
        if not question:
            raise ToolError("question is required")
        options = [str(o) for o in (args.get("options") or [])]
        allow_freeform = bool(args.get("allow_freeform", True))
        multi = bool(args.get("multi", False))
        if ctx.elicit is None:
            # No interactive user attached (e.g. headless chat API): don't block.
            raise ToolError(
                "no interactive user is attached to answer (elicitation unavailable in "
                "this context) — proceed with your best judgement and state your assumption")
        response = await ctx.elicit(
            question=question, options=options, allow_freeform=allow_freeform, multi=multi)
        if response.get("cancelled"):
            return ToolResult(
                summary="user dismissed the question without answering",
                data={"cancelled": True})
        choices = [str(c) for c in (response.get("choices") or [])]
        text = str(response.get("text", "")).strip()
        parts = []
        if choices:
            parts.append("chose: " + ", ".join(choices))
        if text:
            parts.append("said: " + text)
        return ToolResult(
            summary="; ".join(parts) or "(no answer)",
            data={"choices": choices, "text": text})


class SkillsTool(Tool):
    name = "skills"
    # Introspection: list/get/search/memory dominate, and even save writes a
    # cheap skill file (not scene work) — so a pure-skills round is discounted.
    read_only = True
    description = (
        "Playbook library of proven Blender recipes (manifold repair, fillets, "
        "booleans, texturing, lighting, rigging, ...) plus persistent agent memory. "
        "Backed by the shared core skill index: builtin skills, the user's "
        "drop-folder and registered skill git repos, tools-extension bundles "
        "(e.g. rigging-*), and skills you saved. "
        "Subcommands: list (all skills with one-line summaries), "
        "get {name} (full skill body - ALWAYS read a relevant skill before "
        "attempting tedious geometry work), "
        "search {query, max_results?} (full-text search across all skills), "
        "save {name, body} (write a new skill after the user confirms a recipe works), "
        "memory_get, memory_set {content} (persistent notes that survive sessions)."
    )

    def __init__(self, store: AgentStore) -> None:
        self._store = store

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "subcommand": {
                    "type": "string",
                    "enum": ["list", "get", "search", "save", "memory_get", "memory_set"],
                },
                "name": {"type": "string", "description": "Skill name (get/save)."},
                "query": {"type": "string", "description": "Search query (search)."},
                "max_results": {"type": "integer", "default": 5},
                "body": {"type": "string", "description": "Skill markdown body (save)."},
                "content": {"type": "string", "description": "Memory contents (memory_set)."},
            },
            "required": ["subcommand"],
        }

    async def call(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        subcommand = args.get("subcommand", "")
        if subcommand == "list":
            skills = self._store.list_skills()
            return ToolResult(
                summary="{:d} skill(s) available".format(len(skills)),
                data={"skills": [{"name": s.name, "summary": s.summary} for s in skills]},
            )
        if subcommand == "get":
            name = str(args.get("name", ""))
            skill = self._store.get_skill(name)
            if skill is None:
                available = ", ".join(s.name for s in self._store.list_skills())
                raise ToolError("unknown skill {!r}; available: {:s}".format(name, available or "(none)"))
            return ToolResult(
                summary="skill: {:s}".format(skill.name),
                data={"name": skill.name, "body": skill.body},
            )
        if subcommand == "search":
            query = str(args.get("query", ""))
            max_results = int(args.get("max_results", 5))
            hits = search_skills(self._store.list_skills(), query, max_results=max_results)
            return ToolResult(
                summary="{:d} hit(s) for {!r}".format(len(hits), query),
                data={
                    "hits": [
                        {"name": skill.name, "summary": skill.summary, "score": score}
                        for skill, score in hits
                    ],
                },
            )
        if subcommand == "save":
            name = str(args.get("name", "")).strip()
            body = str(args.get("body", ""))
            if not name or not body:
                raise ToolError("save requires both name and body")
            self._store.save_skill(name, body)
            return ToolResult(summary="saved skill: {:s}".format(name), data={"name": name})
        if subcommand == "memory_get":
            return ToolResult(summary="memory read", data={"memory": self._store.read_memory()})
        if subcommand == "memory_set":
            self._store.write_memory(str(args.get("content", "")))
            return ToolResult(summary="memory updated", data={"ok": True})
        raise ToolError("unknown subcommand {!r}".format(subcommand))


class MediaTool(Tool):
    name = "media"
    description = (
        "Recall media produced earlier in this conversation by short id "
        "(i1, i2, ...). Subcommands: list (all media with ids and labels), "
        "get {id} (re-attach an image so you can look at it again)."
    )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "subcommand": {"type": "string", "enum": ["list", "get"]},
                "id": {"type": "string", "description": "Media short id (get)."},
            },
            "required": ["subcommand"],
        }

    async def call(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        subcommand = args.get("subcommand", "")
        if subcommand == "list":
            items = ctx.media.list_public()
            return ToolResult(summary="{:d} media item(s)".format(len(items)), data={"media": items})
        if subcommand == "get":
            media_id = str(args.get("id", ""))
            item = ctx.media.get(media_id)
            if item is None:
                raise ToolError("unknown media id {!r}".format(media_id))
            return ToolResult(
                summary="media: {:s}".format(media_id),
                data={"id": media_id, "mime": item.mime, "label": item.label},
                media_ids=[media_id],
            )
        raise ToolError("unknown subcommand {!r}".format(subcommand))


class ContinueWorkingTool(Tool):
    name = "continue_working"
    description = (
        "Extend the current turn's tool-call budget when you are in the middle "
        "of productive multi-step work and about to run out of rounds. "
        "Call with the number of extra rounds you need and a one-line reason."
    )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "rounds": {"type": "integer", "minimum": 1, "maximum": 16},
                "reason": {"type": "string"},
            },
            "required": ["rounds", "reason"],
        }

    async def call(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        if ctx.turn_budget is None:
            raise ToolError("no turn budget attached")
        balance = ctx.turn_budget.extend(int(args.get("rounds", 1)))
        return ToolResult(
            summary="budget extended; {:g} round(s) left".format(balance),
            data={"rounds_left": balance},
        )


_AUTONOMY_LEVELS = ("ask", "yolo", "orchestrator", "swarm")


class SetAutonomyTool(Tool):
    name = "set_autonomy"
    description = (
        "Adjust YOUR OWN autonomy level for the rest of this session, without the "
        "user touching the UI slider. Levels escalate capability: "
        "'ask' = act directly but pause for confirmation on each mutating tool "
        "call; 'yolo' = act directly, no confirmations; 'orchestrator' = pursue "
        "objectives by delegating to in-process worker agents; 'swarm' = fan "
        "objectives out to parallel workers, each in its own headless Blender. Dial "
        "caution UP before risky/irreversible edits, or escalate to delegation for "
        "large multi-part jobs. Your tool catalog is re-issued to you afterward."
    )

    def __init__(self, set_level: "Callable[[str, str], Any]") -> None:
        self._set_level = set_level

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "level": {"type": "string", "enum": list(_AUTONOMY_LEVELS),
                          "description": "ask | yolo | orchestrator | swarm"},
            },
            "required": ["level"],
        }

    async def call(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        level = str(args.get("level", "")).strip()
        if level == "minimal":  # legacy alias
            level = "ask"
        if level not in _AUTONOMY_LEVELS:
            raise ToolError("level must be one of: " + ", ".join(_AUTONOMY_LEVELS))
        self._set_level(ctx.session_id, level)
        return ToolResult(
            summary="autonomy set to {:s}".format(level),
            data={"autonomy_level": level})
