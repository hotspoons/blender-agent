# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
The budget reviewer: a lightweight orchestrator that arbitrates
round-budget extensions when a worker turn exhausts its tool rounds.

Deliberately context-blind: the reviewer sees ONLY the worker's
self-report (objectives / evidence / continue-or-stop), never the
worker's conversation. It verifies claims through two tools — the
user's actual requests, and a transcript search — then returns a
verdict the engine acts on. Blindness is the point: a worker that has
talked itself into a loop will also have talked its own context into
justifying the loop; the reviewer judges evidence, not narrative.
"""

__all__ = (
    "ReviewResult",
    "review_budget",
)

import dataclasses
import json
import logging
import re
from typing import Any

from .llm import LlmClient

_log = logging.getLogger(__name__)

# The reviewer is bounded hard: a few verification rounds, small
# result snippets. It must stay cheap relative to the work it judges.
_MAX_REVIEW_ROUNDS = 4
_MAX_SEARCH_HITS = 8
_SNIPPET_CHARS = 320
_USER_REQUEST_CLIP = 1_500

_SYSTEM_PROMPT = (
    "You are a strict but fair reviewer overseeing a Blender agent that "
    "exhausted its tool-call budget mid-task. You see ONLY the worker's "
    "self-report - not its conversation. Verify before you trust: "
    "get_user_requests() returns what the user actually asked; "
    "search_history(query) searches the transcript, tool results included. "
    "Judge three things: do the stated objectives match the user's "
    "requests; is the evidence concrete (object names, counts, verify "
    "output) rather than hand-waving; would more tool rounds plausibly "
    "finish the job, or is the worker stuck repeating itself? A worker "
    "honestly reporting an unmet objective with a credible plan deserves "
    "rounds; confident vagueness does not. Spot-check with at most a few "
    "tool calls, then decide."
)

_VERDICT_INSTRUCTION = (
    "When you have decided, reply with ONLY a JSON object:\n"
    '{{"verdict": "continue" or "stop", "grant_rounds": <0-{max_grant:d}>, '
    '"summary": "<2-4 sentences for the END USER: what the worker set out '
    'to do, what the evidence shows, and why you grant more rounds or '
    'stop>"}}'
)

_TOOL_SPECS = [
    {
        "type": "function",
        "function": {
            "name": "get_user_requests",
            "description": "The user's actual messages this session (newest last).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_history",
            "description": "Case-insensitive search over the conversation "
                           "transcript including tool results; returns snippets.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
]


@dataclasses.dataclass
class ReviewResult:
    verdict: str            # "continue" | "stop"
    grant_rounds: int
    summary: str            # user-facing 2-4 sentences
    detail: dict[str, Any]  # {"self_report", "assessment", "checks": [...]}


def _get_user_requests(records: list[dict[str, Any]]) -> list[str]:
    requests = [
        str(r.get("content", ""))[:_USER_REQUEST_CLIP]
        for r in records
        if r.get("role") == "user" and not r.get("synthetic")
    ]
    return requests[-12:]


def _search_history(records: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    terms = [t for t in re.findall(r"[a-z0-9_.]+", query.lower()) if len(t) > 1]
    if not terms:
        return []
    hits: list[dict[str, Any]] = []
    for record in reversed(records):
        content = str(record.get("content", ""))
        lowered = content.lower()
        positions = [lowered.find(t) for t in terms if t in lowered]
        if not positions:
            continue
        at = min(positions)
        start = max(0, at - _SNIPPET_CHARS // 4)
        hits.append({
            "role": str(record.get("role", "")),
            "name": str(record.get("name", "")),
            "snippet": content[start:start + _SNIPPET_CHARS],
        })
        if len(hits) >= _MAX_SEARCH_HITS:
            break
    return hits


def _parse_verdict(text: str, max_grant: int) -> tuple[str, int, str] | None:
    """
    Extract the verdict JSON from *text* (models often wrap it in prose
    or fences). Returns ``(verdict, grant, summary)`` or None.
    """
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        return None
    if not isinstance(data, dict) or "verdict" not in data:
        return None
    verdict = "continue" if str(data.get("verdict", "")).lower() == "continue" else "stop"
    try:
        grant = int(data.get("grant_rounds", 0))
    except (TypeError, ValueError):
        grant = 0
    grant = max(0, min(max_grant, grant))
    if verdict == "continue" and grant == 0:
        grant = max_grant // 2 or 1
    if verdict == "stop":
        grant = 0
    return verdict, grant, str(data.get("summary", "")).strip()


async def _collect(llm: LlmClient, request: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    """
    Run one non-streamed-to-UI LLM round; assemble content + tool calls.
    """
    parts: list[str] = []
    calls: dict[int, dict[str, Any]] = {}
    async for chunk in llm.stream(request):
        if chunk.content:
            parts.append(chunk.content)
        for delta in chunk.tool_calls:
            index = int(delta.get("index", 0))
            slot = calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
            if delta.get("id"):
                slot["id"] = delta["id"]
            function = delta.get("function") or {}
            if function.get("name"):
                slot["name"] += function["name"]
            if function.get("arguments"):
                slot["arguments"] += function["arguments"]
    ordered = []
    for index in sorted(calls):
        slot = calls[index]
        if not slot["id"]:
            slot["id"] = "review_call_{:d}".format(index)
        if slot["name"]:
            ordered.append(slot)
    return "".join(parts), ordered


async def review_budget(
        llm: LlmClient,
        model: str,
        self_report: str,
        records: list[dict[str, Any]],
        max_grant: int,
) -> ReviewResult:
    """
    Judge *self_report* against the transcript and return a verdict.
    Fails safe: any error or unparseable reply becomes a "stop".
    """
    checks: list[dict[str, Any]] = []
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content":
            "WORKER SELF-REPORT (budget exhausted):\n\n{:s}\n\n{:s}".format(
                self_report.strip() or "(the worker produced no report)",
                _VERDICT_INSTRUCTION.format(max_grant=max_grant))},
    ]

    assessment = ""
    for _round in range(_MAX_REVIEW_ROUNDS):
        request: dict[str, Any] = {"model": model, "messages": messages, "tools": _TOOL_SPECS}
        content, calls = await _collect(llm, request)
        if not calls:
            assessment = content
            break
        message: dict[str, Any] = {"role": "assistant", "content": content or ""}
        message["tool_calls"] = [
            {"id": c["id"], "type": "function",
             "function": {"name": c["name"], "arguments": c["arguments"]}}
            for c in calls
        ]
        messages.append(message)
        for call in calls:
            try:
                args = json.loads(call["arguments"]) if call["arguments"].strip() else {}
            except ValueError:
                args = {}
            if call["name"] == "get_user_requests":
                result: object = _get_user_requests(records)
            elif call["name"] == "search_history":
                result = _search_history(records, str(args.get("query", "")))
            else:
                result = {"error": "unknown tool"}
            checks.append({"tool": call["name"], "args": args, "result": result})
            messages.append({
                "role": "tool",
                "tool_call_id": call["id"],
                "name": call["name"],
                "content": json.dumps(result),
            })
    else:
        # Verification rounds exhausted without a verdict: one final,
        # tool-less request for the decision.
        messages.append({"role": "user", "content":
            "No more tool calls - reply with the verdict JSON now.\n"
            + _VERDICT_INSTRUCTION.format(max_grant=max_grant)})
        assessment, _ = await _collect(llm, {"model": model, "messages": messages})

    parsed = _parse_verdict(assessment, max_grant)
    if parsed is None:
        _log.warning("budget review verdict unparseable; stopping turn")
        verdict, grant, summary = "stop", 0, (
            "The reviewer could not produce a structured verdict; "
            "stopping for user input.")
    else:
        verdict, grant, summary = parsed
        if not summary:
            summary = "Reviewer verdict: {:s}.".format(verdict)
    return ReviewResult(
        verdict=verdict,
        grant_rounds=grant,
        summary=summary,
        detail={
            "self_report": self_report,
            "assessment": assessment,
            "checks": checks,
        },
    )
