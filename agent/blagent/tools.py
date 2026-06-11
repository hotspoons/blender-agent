# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Agent tool abstractions, ported from Foyer Studio's ``foyer-agent`` tool
registry (``ext/foyer-studio/crates/foyer-agent/src/tools/mod.rs``).

A tool exposes a name, description, JSON input schema, and a
``destructive`` flag consumed by the autonomy gate. The registry keeps
iteration order sorted by name so the tools array sent to the LLM is
byte-stable across restarts (helps upstream prefix caches).
"""

__all__ = (
    "Tool",
    "ToolContext",
    "ToolError",
    "ToolRegistry",
    "ToolResult",
    "TurnBudget",
)

import dataclasses

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .media import MediaLibrary


class ToolError(Exception):
    """
    Raised by tools; the message is fed back to the model verbatim so
    it can correct course.
    """


@dataclasses.dataclass
class TurnBudget:
    """
    Per-turn round budget. The hidden ``continue_working`` tool extends
    the cap mid-turn (mirrors Foyer's ``TurnBudgetHandle``).
    """

    rounds_left: int
    rounds_max: int

    def extend(self, rounds: int) -> int:
        """
        Add *rounds* (clamped to the original max) and return the new balance.
        """
        self.rounds_left = min(self.rounds_left + rounds, self.rounds_max)
        return self.rounds_left


@dataclasses.dataclass
class ToolResult:
    """
    What a tool returns. ``summary`` is the short human-readable status
    shown on the tool card; ``data`` is the structured result fed back
    to the model; ``media_ids`` reference images registered in the
    session's media library (fed back to vision-capable models).
    """

    summary: str
    data: object = None
    media_ids: list[str] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class ToolContext:
    """
    Per-invocation context handed to every tool call.
    """

    media: "MediaLibrary"
    turn_budget: TurnBudget | None = None
    session_id: str = ""


class Tool:
    """
    Base class for agent tools.
    """

    name: str = ""
    description: str = ""
    destructive: bool = False
    # Read-only queries whose results go stale as the scene changes;
    # the engine ages these out of the context harder (they are cheap
    # to re-run).
    volatile: bool = False

    def input_schema(self) -> dict[str, Any]:
        raise NotImplementedError

    async def call(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        raise NotImplementedError


class ToolRegistry:
    """
    Name-keyed tool collection with stable (sorted) iteration order.
    """

    def __init__(self, tools: list[Tool]) -> None:
        self._tools: dict[str, Tool] = {t.name: t for t in tools}

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def __len__(self) -> int:
        return len(self._tools)

    def __iter__(self) -> "Any":
        for name in sorted(self._tools):
            yield self._tools[name]

    def specs(self) -> list[dict[str, Any]]:
        """
        OpenAI-style function specs for the chat-completions request,
        sorted by name for wire stability.
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema(),
                },
            }
            for tool in self
        ]
