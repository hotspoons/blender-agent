# SPDX-FileCopyrightText: 2026 agentcore contributors
#
# SPDX-License-Identifier: MIT OR Apache-2.0

"""
Readable names over the generated v2 models, plus the guard that keeps them
honest.

``datamodel-code-generator`` names anonymous union members positionally --
the ``session/update`` variants come out as ``SessionUpdate1`` ...
``SessionUpdate18``, which says nothing about which is which. This module
binds them to their discriminator names once, so the bridge reads as
``AgentMessageChunk`` rather than ``SessionUpdate3``.

The positional names are NOT stable across schema regens: ACP v2 is a draft,
and inserting one variant upstream renumbers everything after it. So the
bindings are checked against their discriminator literals at import time
(``_verify``). A regen that shuffles the union fails loudly here instead of
silently putting the wrong shape on the wire.
"""

__all__ = (
    "AgentMessage",
    "AgentMessageChunk",
    "AgentThought",
    "AgentThoughtChunk",
    "AudioBlock",
    "AvailableCommandsUpdate",
    "ConfigOptionUpdate",
    "ContentBlock",
    "ImageBlock",
    "PlanRemoved",
    "PlanUpdate",
    "ResourceBlock",
    "ResourceLinkBlock",
    "SessionIdle",
    "SessionInfoUpdate",
    "SessionRequiresAction",
    "SessionRunning",
    "SessionUpdate",
    "TerminalOutputChunk",
    "TerminalUpdate",
    "TextBlock",
    "ToolCallContentChunk",
    "ToolCallUpdate",
    "UsageUpdate",
    "UserMessage",
    "UserMessageChunk",
    "dump",
    "message_id",
    "stop_reason",
    "text",
)

import typing
from typing import Any

from pydantic import BaseModel

from agentcore.acp import models_v2 as _m

SessionUpdate = _m.SessionUpdate

UserMessageChunk = _m.SessionUpdate1
UserMessage = _m.SessionUpdate2
AgentMessageChunk = _m.SessionUpdate3
AgentMessage = _m.SessionUpdate4
AgentThoughtChunk = _m.SessionUpdate5
AgentThought = _m.SessionUpdate6
ToolCallContentChunk = _m.SessionUpdate8
ToolCallUpdate = _m.SessionUpdate9
TerminalUpdate = _m.SessionUpdate10
TerminalOutputChunk = _m.SessionUpdate11
PlanUpdate = _m.SessionUpdate12
PlanRemoved = _m.SessionUpdate13
AvailableCommandsUpdate = _m.SessionUpdate14
ConfigOptionUpdate = _m.SessionUpdate15
SessionInfoUpdate = _m.SessionUpdate16
UsageUpdate = _m.SessionUpdate17

# `state_update` is a nested union; its members carry a second `state`
# discriminator. `idle` is the one that matters most to us -- it is how v2
# says "turn over, ready for input" without the v1 turn framing.
SessionRunning = _m.SessionUpdate76
SessionIdle = _m.SessionUpdate77
SessionRequiresAction = _m.SessionUpdate78

ContentBlock = _m.ContentBlock
TextBlock = _m.ContentBlock1
ImageBlock = _m.ContentBlock2
AudioBlock = _m.ContentBlock3
ResourceLinkBlock = _m.ContentBlock4
ResourceBlock = _m.ContentBlock5

# (bound name, session_update literal, state literal or None)
_BINDINGS: "tuple[tuple[str, str, str | None], ...]" = (
    ("UserMessageChunk", "user_message_chunk", None),
    ("UserMessage", "user_message", None),
    ("AgentMessageChunk", "agent_message_chunk", None),
    ("AgentMessage", "agent_message", None),
    ("AgentThoughtChunk", "agent_thought_chunk", None),
    ("AgentThought", "agent_thought", None),
    ("ToolCallContentChunk", "tool_call_content_chunk", None),
    ("ToolCallUpdate", "tool_call_update", None),
    ("TerminalUpdate", "terminal_update", None),
    ("TerminalOutputChunk", "terminal_output_chunk", None),
    ("PlanUpdate", "plan_update", None),
    ("PlanRemoved", "plan_removed", None),
    ("AvailableCommandsUpdate", "available_commands_update", None),
    ("ConfigOptionUpdate", "config_option_update", None),
    ("SessionInfoUpdate", "session_info_update", None),
    ("UsageUpdate", "usage_update", None),
    ("SessionRunning", "state_update", "running"),
    ("SessionIdle", "state_update", "idle"),
    ("SessionRequiresAction", "state_update", "requires_action"),
)

# ContentBlock is discriminated on `type` rather than `sessionUpdate`.
_BLOCK_BINDINGS: "tuple[tuple[str, str], ...]" = (
    ("TextBlock", "text"),
    ("ImageBlock", "image"),
    ("AudioBlock", "audio"),
    ("ResourceLinkBlock", "resource_link"),
    ("ResourceBlock", "resource"),
)


def _literal(model: "type[BaseModel]", field: str) -> "str | None":
    info = model.model_fields.get(field)
    if info is None:
        return None
    args = typing.get_args(info.annotation)
    if len(args) == 1 and isinstance(args[0], str):
        return args[0]
    return None


def _verify() -> None:
    """
    Assert every alias still points at the variant its name claims.

    Raises ``RuntimeError`` rather than ``AssertionError`` so the check
    survives ``python -O``: a mis-bound variant would corrupt the wire
    format, which is not something to skip in an optimized run.
    """
    for name, session_update, state in _BINDINGS:
        model = globals()[name]
        found = _literal(model, "session_update")
        if found != session_update:
            raise RuntimeError(
                "ACP v2 model drift: {:s} is bound to a {!r} variant, expected {!r}. "
                "Re-check the aliases in agentcore/acp/wire.py against the regenerated "
                "models_v2.py.".format(name, found, session_update))
        if state is not None and _literal(model, "state") != state:
            raise RuntimeError(
                "ACP v2 model drift: {:s} has state {!r}, expected {!r}.".format(
                    name, _literal(model, "state"), state))
    for name, kind in _BLOCK_BINDINGS:
        found = _literal(globals()[name], "type")
        if found != kind:
            raise RuntimeError(
                "ACP v2 model drift: {:s} is bound to a {!r} block, expected {!r}.".format(
                    name, found, kind))


_verify()


def text(body: str) -> "_m.ContentBlock":
    """
    A plain text content block -- by far the most common one we emit.

    Wrapped in the ``ContentBlock`` root model: the schema's content union is a
    RootModel, so the bare variant is not assignable where a block is expected.
    """
    return ContentBlock(TextBlock(type="text", text=body))


def message_id(value: str) -> "_m.MessageId":
    """Wrap a message id. v2 patches messages by id, so this is load-bearing."""
    return _m.MessageId(value)


def stop_reason(value: str) -> "_m.StopReason":
    """Wrap a stop reason; unknown values stay legal via the schema's str arm."""
    return _m.StopReason(value)


def dump(model: BaseModel) -> "dict[str, Any]":
    """
    Serialize a v2 model to its wire form.

    Every ACP field is camelCase on the wire and snake_case in the generated
    models, and optional fields are omitted rather than sent as null -- v2
    gives ``null`` the distinct meaning "clear this value", so a blanket
    null-fill would erase client state.
    """
    return model.model_dump(by_alias=True, exclude_none=True)
