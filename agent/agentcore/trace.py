# SPDX-FileCopyrightText: 2026 agentcore contributors
#
# SPDX-License-Identifier: MIT OR Apache-2.0

"""
Context tracing for the agent harness.

Every LLM call in the system — the main chat turn, each orchestrator worker
turn, and the planner / evaluator / draft / auditor calls — funnels through
``LlmClient.stream(request)``. When ``BLENDER_AGENT_TRACE_CONTEXT`` is set,
this logs exactly WHAT each one was sent: who is calling (label), the model,
and a per-message breakdown (role, size, preview, image count) plus the tool
count. That makes "the agent had zero context" answerable from the log — you
can see whether the conversation actually reached the draft/planner/worker.

Enable: ``BLENDER_AGENT_TRACE_CONTEXT=1`` (logs to the ``agentcore.trace``
logger, which the blagent build routes to agent.log). ``=full`` logs whole
message bodies instead of previews.
"""

__all__ = ("context_trace_enabled", "trace_llm_request")

import json
import logging
import os

from typing import Any

_log = logging.getLogger("agentcore.trace")

_PREVIEW = 240


def context_trace_enabled() -> bool:
    return os.environ.get("BLENDER_AGENT_TRACE_CONTEXT", "").strip().lower() not in ("", "0", "false", "no")


def _full() -> bool:
    return os.environ.get("BLENDER_AGENT_TRACE_CONTEXT", "").strip().lower() == "full"


def _flatten(content: object) -> "tuple[str, int]":
    """Return (text, image_count) for a message's content (str or block list)."""
    if isinstance(content, str):
        return content, 0
    if isinstance(content, list):
        parts, images = [], 0
        for block in content:
            if not isinstance(block, dict):
                parts.append(str(block))
                continue
            kind = block.get("type")
            if kind == "text":
                parts.append(str(block.get("text", "")))
            elif kind in ("image_url", "image"):
                images += 1
                parts.append("<image>")
            else:
                parts.append("<{}>".format(kind or "block"))
        return " ".join(parts), images
    return ("" if content is None else str(content)), 0


def trace_llm_request(label: str, request: "dict[str, Any]") -> None:
    """Log one LLM request's full message context, if tracing is enabled."""
    if not context_trace_enabled():
        return
    messages = request.get("messages") or []
    tools = request.get("tools") or []
    total = 0
    for m in messages:
        text, _ = _flatten(m.get("content"))
        total += len(text)
    _log.info("LLM[%s] model=%s messages=%d tools=%d total_chars=%d",
              label or "?", request.get("model", "?"), len(messages), len(tools), total)
    for i, m in enumerate(messages):
        text, images = _flatten(m.get("content"))
        role = m.get("role", "?")
        tag = "+{:d}img".format(images) if images else ""
        if _full():
            _log.info("  [%d] %-9s %6dch %s\n%s", i, role, len(text), tag, text)
        else:
            preview = " ".join(text.split())[:_PREVIEW]
            _log.info("  [%d] %-9s %6dch %s | %s", i, role, len(text), tag, preview)
