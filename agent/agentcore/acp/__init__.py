# SPDX-FileCopyrightText: 2026 agentcore contributors
#
# SPDX-License-Identifier: MIT OR Apache-2.0

"""
Agent Client Protocol (ACP) service for the agent harness.

Serves the ACP v2 DRAFT alongside v1 on one endpoint, so a stand-alone pod can
be driven by any ACP-capable client or orchestrator. Version negotiation is a
single integer on ``initialize``; the agent answers with the client's version
when it supports it, else its own highest. Two endpoints would not be
negotiation, hence one dispatcher over two method tables.

Layout:
  - ``models_v2``  generated Pydantic models for the v2 draft (do not edit).
  - ``wire``       readable aliases over the generated positional union names,
                   with the drift guard that keeps them honest.
  - ``schema/``    the vendored, pinned schema + the regen script.

v1 types and the version-agnostic JSON-RPC ``Connection`` come from the
official ``agent-client-protocol`` SDK; everything above ``Connection`` in that
SDK is v1-bound, so the dispatcher and transports are ours.
"""

__all__ = ()
