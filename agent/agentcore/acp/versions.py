# SPDX-FileCopyrightText: 2026 agentcore contributors
#
# SPDX-License-Identifier: MIT OR Apache-2.0

"""
Protocol version negotiation and capability advertisement.

ACP negotiates with a single integer on ``initialize``: the client sends the
latest version it supports, and the agent answers with that same version when
it can serve it, or with its own highest otherwise. The client then decides
whether to continue or disconnect -- the agent never refuses on version alone.

Capabilities are advertised per version because the two shapes differ: v1 is
flat (``loadSession``, ``promptCapabilities``), v2 nests everything under
``session`` and treats an omitted field as "unsupported". Both are built from
one set of facts about what this build actually implements, so the two can
never drift into claiming different things.
"""

__all__ = (
    "AGENT_INFO_NAME",
    "SUPPORTED",
    "V1",
    "V2",
    "agent_capabilities_v1",
    "agent_capabilities_v2",
    "negotiate",
    "supports",
)

from typing import Any

from agentcore.acp import models_v2 as _m

V1 = 1
V2 = 2

# Highest first. v2 is a DRAFT; it leads because a v2-capable client asking for
# 2 should get 2, while a v1 client asking for 1 still gets 1.
SUPPORTED = (V2, V1)

AGENT_INFO_NAME = "blender-agent"

# What this build actually implements. Both capability builders read from here
# so v1 and v2 cannot advertise different truths.
_IMPLEMENTS_SESSION_DELETE = True
_IMPLEMENTS_SESSION_RESUME = True
_IMPLEMENTS_SESSION_FORK = True
_IMPLEMENTS_PROMPT_IMAGE = True
_IMPLEMENTS_PROMPT_AUDIO = False
_IMPLEMENTS_PROMPT_EMBEDDED_CONTEXT = True
# MCP server provisioning is NOT implemented yet: `session/new` accepts
# mcpServers and ignores them. Advertising it anyway would be a lie a client
# acts on -- it would hand us its tool servers and then wonder why the agent
# never used them. Flip these on in the same change that wires them up.
#
# Note the direction, which is easy to get backwards: these advertise that the
# agent can CONSUME MCP servers the client lends it. The agent exposing its own
# Blender tools outward is a separate thing entirely, served by the standalone
# MCP server on --mcp-port; ACP has no mechanism for it.
_IMPLEMENTS_MCP_STDIO = False
_IMPLEMENTS_MCP_HTTP = False
_IMPLEMENTS_MCP_ACP = False


def negotiate(requested: "int | None") -> int:
    """
    Resolve the version to run this connection at.

    A version we support is honored. Anything else -- newer than us, older than
    us, or missing -- gets our highest, and the client decides whether that is
    acceptable.
    """
    if isinstance(requested, int) and requested in SUPPORTED:
        return requested
    return SUPPORTED[0]


def supports(version: int) -> bool:
    """Whether *version* is one we can serve."""
    return version in SUPPORTED


def agent_capabilities_v2() -> "_m.AgentCapabilities":
    """
    v2 capabilities. Omitted means unsupported, and ``{}`` means supported --
    so every sub-object here is a positive claim we must be able to honor.

    ``nes`` and ``providers`` are deliberately absent: next-edit-suggestions and
    document sync are text-editor features with no meaning for a 3D scene agent.
    """
    prompt = _m.PromptCapabilities(
        image=_m.PromptImageCapabilities() if _IMPLEMENTS_PROMPT_IMAGE else None,
        audio=_m.PromptAudioCapabilities() if _IMPLEMENTS_PROMPT_AUDIO else None,
        embedded_context=(
            _m.PromptEmbeddedContextCapabilities() if _IMPLEMENTS_PROMPT_EMBEDDED_CONTEXT else None),
    )
    # An EMPTY capability object means "supported" in v2, so an all-None
    # McpCapabilities would serialize to `mcp: {}` and claim MCP support with no
    # transports at all. A capability we implement nothing of has to be absent,
    # not empty.
    mcp: "_m.McpCapabilities | None" = None
    if _IMPLEMENTS_MCP_STDIO or _IMPLEMENTS_MCP_HTTP or _IMPLEMENTS_MCP_ACP:
        mcp = _m.McpCapabilities(
            stdio=_m.McpStdioCapabilities() if _IMPLEMENTS_MCP_STDIO else None,
            http=_m.McpHttpCapabilities() if _IMPLEMENTS_MCP_HTTP else None,
            acp=_m.McpAcpCapabilities() if _IMPLEMENTS_MCP_ACP else None,
        )
    session = _m.SessionCapabilities(
        prompt=prompt,
        mcp=mcp,
        delete=_m.SessionDeleteCapabilities() if _IMPLEMENTS_SESSION_DELETE else None,
        fork=_m.SessionForkCapabilities() if _IMPLEMENTS_SESSION_FORK else None,
    )
    return _m.AgentCapabilities(session=session)


def agent_capabilities_v1() -> "dict[str, Any]":
    """
    v1 capabilities, as a plain dict.

    v1's shape is flat and its field set is fixed, so a dict is honest here --
    the SDK's own v1 models would add a translation step without adding
    validation we do not already get from the schema tests.
    """
    return {
        "loadSession": _IMPLEMENTS_SESSION_RESUME,
        "promptCapabilities": {
            "image": _IMPLEMENTS_PROMPT_IMAGE,
            "audio": _IMPLEMENTS_PROMPT_AUDIO,
            "embeddedContext": _IMPLEMENTS_PROMPT_EMBEDDED_CONTEXT,
        },
        "mcpCapabilities": {
            "http": _IMPLEMENTS_MCP_HTTP,
            "sse": False,
        },
    }
