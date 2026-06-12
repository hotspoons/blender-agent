# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Single-turn agent loop, ported from Foyer Studio's
``foyer-agent/src/engine.rs``.

One turn = the user speaks once, then the loop alternates LLM rounds
and tool dispatch until the model stops calling tools or the round
budget runs out (extendable mid-turn via ``continue_working``).

Destructive tool calls pause for confirmation when autonomy is
``ask`` - the gate awaits a decision delivered by the runtime.

Tool-produced images are registered in the media library and fed back
into the next round's context as a synthetic user message so
vision-capable models can see what they just did.
"""

__all__ = (
    "AgentEngine",
    "EngineEvents",
)

import asyncio
import json
import logging
import re
import time

from typing import Any, Awaitable, Callable

from .llm import LlmClient, LlmError
from .media import MediaLibrary
from .tools import ToolContext, ToolError, ToolRegistry, TurnBudget

_log = logging.getLogger("blagent.engine")

# Records the model sees, counted from the end of the transcript.
_CONTEXT_RECORD_LIMIT = 80
# Cap on tool result JSON fed back to the model, per call.
_TOOL_RESULT_CHAR_LIMIT = 24_000
# Seconds to wait on the ask-mode confirmation gate before giving up.
_CONFIRM_TIMEOUT = 600.0
# Rough chars-per-token for budget estimation (no tokenizer here; the
# point is the order of magnitude, not exactness).
_CHARS_PER_TOKEN = 4
# Estimated token cost of one inline image attachment.
_IMAGE_TOKEN_ESTIMATE = 800
# Tokens reserved for the model's own output within the budget.
_GENERATION_HEADROOM_TOKENS = 1_024
# When trimming an old tool result, this much of its head survives.
_TRIMMED_TOOL_RESULT_CHARS = 600
# Volatile (read-only scene query) results go stale the moment the
# scene changes and are cheap to re-run; old ones keep only this much.
_TRIMMED_VOLATILE_RESULT_CHARS = 300
# Newest images kept inline in the LLM projection; older ones demote
# to text placeholders (images are the most expensive content).
_MAX_CONTEXT_IMAGES = 3
# Summarization compaction: trigger when the projection exceeds this
# share of the context budget; the kept tail targets the keep share.
_COMPACT_TRIGGER_RATIO = 0.7
_COMPACT_KEEP_RATIO = 0.35
# Floor on the history text handed to the summarizer request (the
# actual cap scales with the context budget — see ``maybe_compact``).
_COMPACT_INPUT_CHAR_LIMIT = 60_000
# Summary length scales with the context budget between these bounds: a
# briefing replacing ~half of a 128k context deserves far more than a
# fixed 400 words, or it silently drops names/values the agent needs.
_COMPACT_WORDS_MIN = 400
_COMPACT_WORDS_MAX = 2500

# The LLM-silence watchdog: some streaming backends (vLLM tool-call
# parsers, reasoning passthroughs) buffer server-side and emit nothing
# for long stretches; report the silence so the UI can show life.
_QUIET_AFTER_SECONDS = 2.0
_QUIET_EMIT_INTERVAL = 1.0

# Budget reviews per turn: the orchestrator can replenish at most this
# many times — the backstop against a reviewer too generous to a
# worker stuck in a loop.
_MAX_BUDGET_REVIEWS = 2

_CLOSING_PROMPT = (
    "(Your tool budget for this turn is exhausted and your pending tool "
    "calls were skipped. Close out for the USER now: state plainly what "
    "you accomplished this turn, citing concrete results from tool "
    "output you actually received; state what remains undone; then ask "
    "whether they want you to continue - their reply starts a fresh "
    "budget. Plain text only - no tool calls.)"
)

_SELF_REPORT_PROMPT = (
    "(Budget checkpoint - your tool-round budget is exhausted; your "
    "pending tool calls have NOT run. Before more rounds can be granted, "
    "report to the reviewer:\n"
    "1. OBJECTIVES: what the user asked for in this conversation, as "
    "they stated it.\n"
    "2. EVIDENCE: for each objective, whether it is met or NOT met - "
    "plainly, citing concrete names/numbers from tool results you "
    "actually received. Do not embellish; unmet is a valid answer.\n"
    "3. VERDICT REQUEST: whether another block of tool rounds would let "
    "you finish (state exactly what remains), or whether you should "
    "stop here.\n"
    "Plain text only - no tool calls.)"
)

_TRIM_NOTICE = "[Note: earlier conversation was trimmed to fit the context window.]"

# Model reasoning embedded in assistant content as <think>/<thinking>
# blocks (the local-model pipeline normalizes everything to <think>;
# remote endpoints such as LM Studio pass the tags through verbatim).
# An unterminated block (aborted generation) runs to end of text.
_THINK_RE = re.compile(r"<think(?:ing)?>.*?(?:</think(?:ing)?>|\Z)", re.DOTALL)


def _strip_thinking(text: str) -> str:
    """
    Remove reasoning blocks before content goes back to a model.
    Chat templates expect previous-turn thinking to be dropped (Qwen's
    own template strips it), and it is pure context-budget waste. The
    transcript keeps the full text; the chat UI renders the blocks as
    collapsible cards.
    """
    if "<think" not in text:
        return text
    return _THINK_RE.sub("", text).strip()

_SUMMARY_SYSTEM_PROMPT = (
    "You compress conversation history for a Blender assistant agent. "
    "Produce a compact briefing the agent can rely on IN PLACE of the "
    "original messages. Be specific: object/material/collection names, "
    "values, file paths. No preamble."
)

_SUMMARY_USER_PROMPT = (
    "Summarize this conversation history in at most {words:d} words, structured as:\n"
    "## Scene state (what exists in the .blend NOW)\n"
    "## Decisions & user preferences\n"
    "## Completed work\n"
    "## Technical lessons (APIs that errored and the fix that worked, "
    "tool parameters that worked)\n"
    "## Open items\n\n"
    "Use the word budget — a too-short summary loses state the agent "
    "needs. Prefer dropping pleasantries over specifics: keep exact "
    "object/bone/material names, parameter values, file paths, media "
    "ids and frame numbers that may be referenced later.\n\n"
    "History:\n{history:s}"
)

EngineEvents = Callable[[dict[str, Any]], Awaitable[None]]


def _now() -> float:
    return time.time()


def _messages_have_images(messages: list[dict[str, Any]]) -> bool:
    """
    True when any message carries image content parts.
    """
    for message in messages:
        content = message.get("content")
        if isinstance(content, list) and any(
                isinstance(p, dict) and p.get("type") == "image_url" for p in content):
            return True
    return False


def _clip_result_data(data: object, limit: int = 20_000) -> object:
    """
    Result payload for tool-status UI events, size-capped so a huge
    tool result never bloats the socket (the full payload still goes
    to the model via the transcript, separately truncated).
    """
    try:
        text = json.dumps(data)
    except (TypeError, ValueError):
        return {"repr": repr(data)[:limit]}
    if len(text) <= limit:
        return data
    return {"truncated_preview": text[:limit]}


class AgentEngine:
    """
    Runs turns for one session. The runtime owns instances of this and
    serializes turns per session.
    """

    def __init__(
            self,
            registry: ToolRegistry,
            media: MediaLibrary,
            system_prompt: str,
            emit: EngineEvents,
            append_record: Callable[[dict[str, Any]], None],
    ) -> None:
        self._registry = registry
        self._media = media
        self._system_prompt = system_prompt
        self._emit = emit
        self._append_record = append_record
        # Read-only scene queries: results go stale and age out harder.
        self._volatile_tools = {
            tool.name for tool in registry if getattr(tool, "volatile", False)}
        self.records: list[dict[str, Any]] = []
        # call_id -> Future resolved by the runtime on user confirm/deny.
        self.pending_confirms: dict[str, asyncio.Future[bool]] = {}
        # Cleared when the endpoint rejects image content (text-only
        # model, e.g. vLLM without an image encoder) - the transcript
        # then renders media as text placeholders instead.
        self.vision_ok = True

    # ------------------------------------------------------------------
    # Transcript helpers.

    def push_record(self, record: dict[str, Any]) -> None:
        record.setdefault("ts", _now())
        self.records.append(record)
        self._append_record(record)

    def _latest_summary(self) -> dict[str, Any] | None:
        """
        The most recent compaction summary record, if any. It
        supersedes the first ``covers_count`` transcript records in the
        LLM projection (the on-disk transcript is never rewritten).
        """
        for record in reversed(self.records):
            if record.get("role") == "summary":
                return record
        return None

    def _llm_messages(self, context_tokens: int = 0) -> list[dict[str, Any]]:
        """
        Project the transcript into OpenAI chat messages. A compaction
        summary, when present, stands in for the records it covers.
        When *context_tokens* is positive, the result is trimmed to fit
        that budget (see ``_fit_context``).
        """
        messages: list[dict[str, Any]] = [{"role": "system", "content": self._system_prompt}]
        start = 0
        summary = self._latest_summary()
        if summary is not None:
            start = int(summary.get("covers_count", 0))
            messages.append({
                "role": "user",
                "content": "[Conversation summary - earlier messages were compacted]\n"
                           + str(summary.get("content", "")),
            })
        for record in self.records[start:][-_CONTEXT_RECORD_LIMIT:]:
            role = record.get("role")
            if role == "summary":
                continue
            if role == "user":
                media_ids = record.get("media_ids") or []
                text = str(record.get("content", ""))
                if media_ids and not self.vision_ok:
                    # Tell a blind model the truth - a bare "[Attached:
                    # media i4]" placeholder reads like an image it
                    # should describe, and text-only models will
                    # confidently confabulate a description.
                    text += (
                        "\n(note: media {:s} exists but you are connected as a TEXT-ONLY "
                        "model and cannot see images. Never describe or pretend to see "
                        "them - inspect the scene with tools, or ask the user to look.)"
                    ).format(", ".join(media_ids))
                    media_ids = []
                content = self._content_with_images(text, media_ids)
                messages.append({"role": "user", "content": content})
            elif role == "assistant":
                message: dict[str, Any] = {
                    "role": "assistant",
                    "content": _strip_thinking(str(record.get("content", ""))),
                }
                tool_calls = record.get("tool_calls") or []
                if tool_calls:
                    message["tool_calls"] = [
                        {
                            "id": call["id"],
                            "type": "function",
                            "function": {"name": call["name"], "arguments": call["arguments"]},
                        }
                        for call in tool_calls
                    ]
                messages.append(message)
            elif role == "tool":
                messages.append({
                    "role": "tool",
                    "tool_call_id": record.get("tool_call_id", ""),
                    "content": str(record.get("content", "")),
                    # Used by the retention passes, and kept on the
                    # wire: the local-model path needs tool names to
                    # render Gemma/Harmony tool-response blocks, and
                    # OpenAI-style endpoints accept the field.
                    "name": str(record.get("name", "")),
                })
        self._demote_old_images(messages)
        if context_tokens > 0:
            self._fit_context(messages, context_tokens)
        return messages

    def _demote_old_images(self, messages: list[dict[str, Any]]) -> None:
        """
        Keep only the newest ``_MAX_CONTEXT_IMAGES`` images inline;
        older ones become text placeholders (recallable via the media
        tool). Images dominate token cost on vision endpoints.
        """
        seen = 0
        for message in reversed(messages):
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for index, part in enumerate(content):
                if not (isinstance(part, dict) and part.get("type") == "image_url"):
                    continue
                seen += 1
                if seen > _MAX_CONTEXT_IMAGES:
                    content[index] = {
                        "type": "text",
                        "text": "[an older image was omitted here - "
                                "use the media tool to view it again]",
                    }

    @staticmethod
    def _estimate_tokens(messages: list[dict[str, Any]]) -> int:
        """
        Order-of-magnitude token estimate (chars/4 + flat image cost).
        Deliberately tokenizer-free: the budget is a guard rail, not an
        exact accounting.
        """
        total = 0
        for message in messages:
            content = message.get("content")
            if isinstance(content, str):
                total += len(content) // _CHARS_PER_TOKEN
            elif isinstance(content, list):
                for part in content:
                    if part.get("type") == "text":
                        total += len(part.get("text", "")) // _CHARS_PER_TOKEN
                    else:
                        total += _IMAGE_TOKEN_ESTIMATE
            for call in message.get("tool_calls") or []:
                total += len(str(call.get("function", {}).get("arguments", ""))) // _CHARS_PER_TOKEN
            total += 8  # role/framing overhead
        return total

    def _fit_context(self, messages: list[dict[str, Any]], context_tokens: int) -> None:
        """
        Trim *messages* in place to roughly fit *context_tokens* (minus
        generation headroom). Cheap deterministic passes, oldest first:

        1. truncate old tool results to their head,
        2. drop whole old exchanges (keeping tool replies attached to
           the assistant message that called them, which OpenAI-style
           endpoints require), inserting one trim notice.

        The system prompt and the latest exchange always survive. This
        is the guard rail; smarter compaction (summarization) is a
        planned layer on top - see agent/docs/context-compaction.md.
        """
        budget = max(context_tokens - _GENERATION_HEADROOM_TOKENS, 1_024)

        # Pass 0: volatile (read-only scene query) results age out hard
        # - they are stale the moment the scene changes and cheap to
        # re-run. All but the newest one shrink to a stub.
        tool_indexes = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
        volatile_indexes = [
            i for i in tool_indexes if messages[i].get("name") in self._volatile_tools]
        for index in volatile_indexes[:-1]:
            if self._estimate_tokens(messages) <= budget:
                return
            content = messages[index].get("content", "")
            if isinstance(content, str) and len(content) > _TRIMMED_VOLATILE_RESULT_CHARS * 2:
                messages[index]["content"] = (
                    content[:_TRIMMED_VOLATILE_RESULT_CHARS]
                    + "\n[... stale scene-query result trimmed - re-run the tool for current state]")

        # Pass 1: truncate old tool results (newest two stay intact -
        # the model usually still needs those verbatim).
        for index in tool_indexes[:-2]:
            if self._estimate_tokens(messages) <= budget:
                return
            content = messages[index].get("content", "")
            if isinstance(content, str) and len(content) > _TRIMMED_TOOL_RESULT_CHARS * 2:
                messages[index]["content"] = (
                    content[:_TRIMMED_TOOL_RESULT_CHARS]
                    + "\n[... tool result trimmed to fit the context window]")

        # Pass 2: drop whole exchanges from the front (index 1 onward;
        # 0 is the system prompt). An assistant message takes its tool
        # replies with it. Keep at least the final user message.
        dropped = False
        while self._estimate_tokens(messages) > budget:
            start = 2 if dropped else 1  # skip the notice once inserted
            if start >= len(messages) - 1:
                break
            end = start + 1
            if messages[start].get("tool_calls"):
                while end < len(messages) - 1 and messages[end].get("role") == "tool":
                    end += 1
            del messages[start:end]
            if not dropped:
                messages.insert(1, {"role": "user", "content": _TRIM_NOTICE})
                dropped = True
        if dropped:
            _log.info("context trimmed to ~%d tokens (budget %d)",
                      self._estimate_tokens(messages), budget)

    # ------------------------------------------------------------------
    # Summarization compaction (run by the runtime between turns).

    async def maybe_compact(self, llm: LlmClient, model: str, context_tokens: int) -> bool:
        """
        When the projection has outgrown ``_COMPACT_TRIGGER_RATIO`` of
        the budget, ask *llm* to summarize the older part of the
        transcript and append a ``summary`` record superseding it in
        future projections. The on-disk transcript keeps everything;
        the UI keeps showing everything. Returns True when a summary
        was produced. One bounded LLM request, between turns only.
        """
        if context_tokens <= 0 or len(self.records) < 4:
            return False
        if self._estimate_tokens(self._llm_messages()) <= context_tokens * _COMPACT_TRIGGER_RATIO:
            return False

        previous = self._latest_summary()
        previous_covers = int(previous.get("covers_count", 0)) if previous else 0

        # Keep a verbatim tail of roughly the keep share of the budget;
        # everything older gets summarized.
        keep_budget_chars = int(context_tokens * _COMPACT_KEEP_RATIO) * _CHARS_PER_TOKEN
        accumulated = 0
        covers = 0
        for index in range(len(self.records) - 1, -1, -1):
            accumulated += len(str(self.records[index].get("content", ""))) + 32
            if accumulated > keep_budget_chars:
                covers = index + 1
                break
        # Tool replies must stay with their assistant call: grow the
        # summarized side until the kept tail starts cleanly.
        while covers < len(self.records) and self.records[covers].get("role") == "tool":
            covers += 1
        if covers <= previous_covers or covers >= len(self.records):
            return False

        # Both the summary length and the history shown to the
        # summarizer scale with the context budget: a 128k-context
        # session compacted into 400 words loses too much state.
        target_words = max(_COMPACT_WORDS_MIN,
                           min(_COMPACT_WORDS_MAX, context_tokens // 50))
        input_chars = max(_COMPACT_INPUT_CHAR_LIMIT,
                          min(context_tokens * _CHARS_PER_TOKEN // 2, 400_000))
        history = self._render_history_for_summary(
            previous, previous_covers, covers, input_chars)
        request = {
            "model": model,
            "messages": [
                {"role": "system", "content": _SUMMARY_SYSTEM_PROMPT},
                {"role": "user", "content": _SUMMARY_USER_PROMPT.format(
                    words=target_words, history=history)},
            ],
        }
        parts: list[str] = []
        async for chunk in llm.stream(request):
            if chunk.content:
                parts.append(chunk.content)
        summary = "".join(parts).strip()
        if not summary:
            return False
        self.push_record({"role": "summary", "content": summary, "covers_count": covers})
        _log.info("compacted session history: %d records -> summary (%d chars)", covers, len(summary))
        return True

    def _render_history_for_summary(
            self,
            previous: dict[str, Any] | None,
            previous_covers: int,
            covers: int,
            char_limit: int = _COMPACT_INPUT_CHAR_LIMIT,
    ) -> str:
        """
        Plain-text rendering of the records a new summary will replace.
        Includes the previous summary so nothing it carried is lost.
        """
        lines: list[str] = []
        if previous is not None:
            lines.append("EARLIER SUMMARY:\n{:s}\n".format(str(previous.get("content", ""))))
        for record in self.records[previous_covers:covers]:
            role = record.get("role")
            if role == "summary":
                continue
            content = str(record.get("content", ""))
            if role == "tool":
                lines.append("TOOL {:s}: {:s}".format(
                    str(record.get("name", "")), content[:1_200]))
            elif role == "assistant":
                calls = "".join(
                    " [called {:s}({:s})]".format(c.get("name", ""), str(c.get("arguments", ""))[:200])
                    for c in record.get("tool_calls") or [])
                lines.append("ASSISTANT: {:s}{:s}".format(_strip_thinking(content), calls))
            else:
                lines.append("USER: {:s}".format(content))
        text = "\n".join(lines)
        if len(text) > char_limit:
            text = text[-char_limit:]
        return text

    def _content_with_images(self, text: str, media_ids: list[str]) -> object:
        if not media_ids:
            return text
        parts: list[dict[str, Any]] = [{"type": "text", "text": text}]
        for media_id in media_ids:
            payload = self._media.read_base64(media_id)
            item = self._media.get(media_id)
            if payload is None or item is None:
                continue
            parts.append({
                "type": "image_url",
                "image_url": {"url": "data:{:s};base64,{:s}".format(item.mime, payload)},
            })
        return parts

    # ------------------------------------------------------------------
    # The turn loop.

    async def run_turn(
            self,
            session_id: str,
            user_text: str,
            llm: LlmClient,
            model: str,
            autonomy: str,
            max_rounds: int,
            media_ids: list[str] | None = None,
            context_tokens: int = 0,
            budget_review: bool = True,
    ) -> None:
        """
        Run one full turn. Events are emitted through the runtime's
        broadcast callback; records are appended to the transcript.
        *media_ids* are user-attached images (pasted/dropped in the UI).
        """
        _log.info("turn start session=%s model=%s attachments=%s", session_id, model, media_ids or [])
        user_record: dict[str, Any] = {"role": "user", "content": user_text}
        if media_ids:
            user_record["media_ids"] = media_ids
        self.push_record(user_record)
        await self._emit({
            "type": "user_record",
            "session_id": session_id,
            "content": user_text,
            "media_ids": media_ids or [],
        })

        budget = TurnBudget(rounds_left=max_rounds, rounds_max=max_rounds * 2)
        ctx = ToolContext(media=self._media, turn_budget=budget, session_id=session_id)
        # Media produced by tools in the previous round, fed to the
        # model as a synthetic user record on the next one.
        feedback_media: list[str] = []
        # Some models go silent after tool results (no text, no calls).
        # Nudge them to wrap up for the user - a bounded number of times.
        nudges_left = 2
        turn_had_tool_calls = False
        reviews_done = 0

        while True:
            if feedback_media:
                self.push_record({
                    "role": "user",
                    "content": "[Attached: tool-produced media {:s} from the previous step]".format(
                        ", ".join(feedback_media)),
                    "media_ids": feedback_media,
                    "synthetic": True,
                })
                feedback_media = []

            request: dict[str, Any] = {
                "model": model,
                "messages": self._llm_messages(context_tokens),
                "tools": self._registry.specs(),
            }

            try:
                content, tool_calls = await self._stream_round(session_id, request, llm)
            except LlmError as ex:
                if self.vision_ok and _messages_have_images(request["messages"]):
                    # Endpoint rejected image content (text-only model,
                    # e.g. vLLM without an image encoder). Degrade to
                    # text placeholders for the rest of this session
                    # and retry the round once.
                    self.vision_ok = False
                    _log.warning("endpoint rejected image content; retrying text-only: %s", ex)
                    await self._emit({
                        "type": "error",
                        "session_id": session_id,
                        "message": "Model rejected image input (text-only model?) - "
                                   "continuing with text placeholders for media.",
                    })
                    request["messages"] = self._llm_messages(context_tokens)
                    content, tool_calls = await self._stream_round(session_id, request, llm)
                else:
                    _log.error("LLM round failed: %s", ex)
                    raise

            record: dict[str, Any] = {"role": "assistant", "content": content}
            if tool_calls:
                record["tool_calls"] = tool_calls
            self.push_record(record)
            await self._emit({
                "type": "assistant_done",
                "session_id": session_id,
                "content": content,
                "tool_calls": [
                    {"id": c["id"], "name": c["name"], "arguments": c["arguments"]}
                    for c in tool_calls
                ],
            })

            if not tool_calls:
                if not content.strip() and turn_had_tool_calls and nudges_left > 0:
                    # Empty close-out after tool work: nudge for a
                    # user-facing summary instead of ending in silence.
                    nudges_left -= 1
                    self.push_record({
                        "role": "user",
                        "content": (
                            "(Your last message was empty. Briefly tell the user what was "
                            "done and what the outcome was, or continue with tool calls "
                            "if the work is unfinished.)"
                        ),
                        "synthetic": True,
                    })
                    continue
                break
            turn_had_tool_calls = True
            # A note for the worker that must NOT split the assistant
            # message from its tool replies — it is pushed after the
            # dispatch loop below.
            post_dispatch_note = ""
            if budget.rounds_left <= 0:
                # Budget gone with calls still pending. Run the
                # orchestrator review (worker self-reports, a blind
                # reviewer judges and may replenish) before giving up.
                granted, self_report, review_summary = 0, "", ""
                final_review = False
                if budget_review and reviews_done < _MAX_BUDGET_REVIEWS:
                    reviews_done += 1
                    final_review = reviews_done >= _MAX_BUDGET_REVIEWS
                    granted, self_report, review_summary = await self._budget_review(
                        session_id, llm, model, tool_calls,
                        max_grant=max_rounds, context_tokens=context_tokens)
                if granted <= 0:
                    # The assistant message above already carries these
                    # tool calls — leaving them unanswered would both
                    # render as a silent dead call in the UI and hand
                    # the next LLM round an assistant message with no
                    # tool replies. Record each as not-executed, visibly.
                    message = ("not executed: the turn's round budget "
                               "was exhausted; send a follow-up to continue")
                    for call in tool_calls:
                        self._push_tool_record(
                            call["id"], {"status": "skipped", "message": message}, call["name"])
                        await self._emit({
                            "type": "tool_status",
                            "session_id": session_id,
                            "call_id": call["id"],
                            "name": call["name"],
                            "arguments": call["arguments"],
                            "state": "error",
                            "summary": message,
                        })
                    # Never end on a dead call: one tool-less closing
                    # round so the user gets an accounting and an
                    # explicit "want me to continue?" (their reply is
                    # the natural budget refill). The skipped-call tool
                    # records are already in the transcript, so the
                    # projection is protocol-valid.
                    closing = ""
                    try:
                        close_messages = self._llm_messages(context_tokens)
                        close_messages.append(
                            {"role": "user", "content": _CLOSING_PROMPT})
                        closing, _ = await self._stream_round(
                            session_id, {"model": model, "messages": close_messages}, llm)
                    except LlmError as ex:
                        _log.warning("closing summary failed: %s", ex)
                    if not closing.strip():
                        # Fall back to the reviewer-facing self-report
                        # rather than silence.
                        closing = self_report
                    if closing.strip():
                        self.push_record({"role": "assistant", "content": closing})
                        await self._emit({
                            "type": "assistant_done",
                            "session_id": session_id,
                            "content": closing,
                            "tool_calls": [],
                        })
                    await self._emit({
                        "type": "error",
                        "session_id": session_id,
                        "message": "Turn round budget exhausted; stopping. Send a follow-up "
                                   "(e.g. \"continue\") to let the agent pick up where it stopped.",
                    })
                    break
                budget.rounds_left = granted
                post_dispatch_note = (
                    "(Budget review: the reviewer granted {:d} more tool rounds. "
                    "Reviewer's note: {:s}{:s})").format(
                        granted, review_summary,
                        " This is the FINAL extension - finish or report."
                        if final_review else "")
            budget.rounds_left -= 1
            if budget.rounds_left == 1 and not post_dispatch_note:
                # Forewarn the worker instead of cutting it off cold.
                post_dispatch_note = (
                    "(Budget notice: only 1 tool round remains before a budget "
                    "review. Prioritize what completes the user's request, or "
                    "prepare to report your progress with concrete evidence.)")

            declined = False
            for index, call in enumerate(tool_calls):
                if declined:
                    # A declined call ends the batch: record the rest as
                    # skipped so the model sees an honest transcript.
                    message = "skipped: an earlier tool call in this batch was declined by the user"
                    self._push_tool_record(call["id"], {"status": "skipped", "message": message}, call["name"])
                    await self._emit({
                        "type": "tool_status",
                        "session_id": session_id,
                        "call_id": call["id"],
                        "name": call["name"],
                        "arguments": call["arguments"],
                        "state": "rejected",
                        "summary": message,
                    })
                    continue
                media_ids, was_declined = await self._dispatch_tool(session_id, ctx, call, autonomy)
                feedback_media.extend(media_ids)
                declined = declined or was_declined
                del index

            if post_dispatch_note:
                # Now that every tool reply is recorded, the note can
                # follow without splitting the call/reply sequence.
                self.push_record({
                    "role": "user", "content": post_dispatch_note, "synthetic": True})

            if declined:
                # Pause the whole turn instead of letting the model retry
                # into more declines - the user steers with their next
                # message (the rejected results are in the transcript).
                await self._emit({
                    "type": "error",
                    "session_id": session_id,
                    "message": "Tool call declined - turn paused. Send a message to tell the agent how to proceed.",
                })
                break

        await self._emit({"type": "turn_done", "session_id": session_id})

    async def _stream_round(
            self,
            session_id: str,
            request: dict[str, Any],
            llm: LlmClient,
    ) -> tuple[str, list[dict[str, Any]]]:
        """
        Stream one LLM round, emitting token events; reassemble content
        and tool calls from the deltas.
        """
        content_parts: list[str] = []
        # index -> {id, name, arguments}
        calls: dict[int, dict[str, Any]] = {}
        # While the model writes a long tool call (hundreds of lines of
        # code in `arguments`) no token events flow, so the UI would sit
        # visually frozen. Emit throttled progress so it can show a
        # "writing <tool>..." heartbeat instead.
        drafting_last = 0.0
        # And when the backend sends NOTHING at all (vLLM's tool-call
        # parsers buffer the whole call server-side and flush the deltas
        # in one burst at the end), even drafting can't fire — a
        # watchdog measures the dead air itself.
        last_chunk_at = [_now()]
        watchdog = asyncio.create_task(
            self._quiet_watchdog(session_id, last_chunk_at))

        try:
            async for chunk in llm.stream(request):
                last_chunk_at[0] = _now()
                if chunk.content:
                    content_parts.append(chunk.content)
                    await self._emit({"type": "token", "session_id": session_id, "text": chunk.content})
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
                if chunk.tool_calls and _now() - drafting_last > 0.25:
                    drafting_last = _now()
                    active = calls[max(calls)] if calls else {}
                    await self._emit({
                        "type": "tool_drafting",
                        "session_id": session_id,
                        "name": active.get("name", ""),
                        "chars": sum(len(c["arguments"]) for c in calls.values()),
                        "n_calls": len(calls),
                    })
        finally:
            watchdog.cancel()
            try:
                await watchdog
            except asyncio.CancelledError:
                pass

        tool_calls = []
        for index in sorted(calls):
            slot = calls[index]
            if not slot["id"]:
                slot["id"] = "call_{:d}_{:d}".format(int(_now() * 1000), index)
            if slot["name"]:
                tool_calls.append(slot)
        return "".join(content_parts), tool_calls

    async def _budget_review(
            self,
            session_id: str,
            llm: LlmClient,
            model: str,
            pending_calls: list[dict[str, Any]],
            max_grant: int,
            context_tokens: int,
    ) -> tuple[int, str, str]:
        """
        The orchestrator checkpoint at budget exhaustion. The worker
        self-reports OUT OF BAND (the request gets placeholder tool
        replies for the pending calls; nothing enters the transcript),
        a context-blind reviewer judges it (see ``reviewer.py``), and
        the verdict is recorded as a ``review`` record + event for the
        UI. Returns ``(granted_rounds, self_report, summary)`` — the
        caller owns transcript placement of both texts, because they
        must not split an assistant message from its tool replies.
        Fails safe: any error means no grant.
        """
        from .reviewer import review_budget

        try:
            # 1. Elicit the worker's self-report.
            messages = self._llm_messages(context_tokens)
            for call in pending_calls:
                messages.append({
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "name": call["name"],
                    "content": "(not executed yet - budget review in progress)",
                })
            messages.append({"role": "user", "content": _SELF_REPORT_PROMPT})
            parts: list[str] = []
            async for chunk in llm.stream({"model": model, "messages": messages}):
                if chunk.content:
                    parts.append(chunk.content)
            self_report = _strip_thinking("".join(parts))

            # 2. Blind review.
            result = await review_budget(llm, model, self_report, self.records, max_grant)
        except Exception as ex:  # pylint: disable=broad-exception-caught
            _log.warning("budget review failed (falling back to stop): %s", ex)
            return 0, "", ""

        granted = result.grant_rounds if result.verdict == "continue" else 0
        self.push_record({
            "role": "review",
            "content": result.summary,
            "verdict": result.verdict,
            "granted_rounds": granted,
            "detail": result.detail,
        })
        await self._emit({
            "type": "orchestrator_review",
            "session_id": session_id,
            "verdict": result.verdict,
            "granted_rounds": granted,
            "summary": result.summary,
            "detail": result.detail,
        })
        _log.info("budget review session=%s verdict=%s granted=%d",
                  session_id, result.verdict, granted)
        return granted, self_report, result.summary

    async def _quiet_watchdog(self, session_id: str, last_chunk_at: list[float]) -> None:
        """
        Emit ``llm_quiet`` once per second while the LLM stream has been
        silent past the threshold — the generation is running but the
        backend is buffering (tool-call parsing, server-side reasoning).
        Cancelled by ``_stream_round`` when the stream ends.
        """
        while True:
            await asyncio.sleep(_QUIET_EMIT_INTERVAL)
            quiet = _now() - last_chunk_at[0]
            if quiet >= _QUIET_AFTER_SECONDS:
                await self._emit({
                    "type": "llm_quiet",
                    "session_id": session_id,
                    "seconds": round(quiet, 1),
                })

    async def _dispatch_tool(
            self,
            session_id: str,
            ctx: ToolContext,
            call: dict[str, Any],
            autonomy: str,
    ) -> tuple[list[str], bool]:
        """
        Run one tool call through the autonomy gate and dispatch.
        Returns ``(media_ids, declined)`` - media for the vision
        feedback loop, and whether the user declined the call.
        """
        name = call["name"]
        call_id = call["id"]
        tool = self._registry.get(name)

        async def status(state: str, **extra: object) -> None:
            await self._emit({
                "type": "tool_status",
                "session_id": session_id,
                "call_id": call_id,
                "name": name,
                "arguments": call["arguments"],
                "state": state,
                **extra,
            })

        if tool is None:
            import difflib
            close = difflib.get_close_matches(
                name, [t.name for t in self._registry], n=2, cutoff=0.5)
            message = "unknown tool: {:s}".format(name)
            if close:
                message += "; did you mean {:s}?".format(" or ".join(close))
            await status("error", summary=message)
            self._push_tool_record(call_id, {"status": "error", "message": message}, name)
            return [], False

        try:
            args = json.loads(call["arguments"]) if call["arguments"].strip() else {}
        except ValueError as ex:
            message = "tool arguments are not valid JSON: {:s}".format(str(ex))
            await status("error", summary=message)
            self._push_tool_record(call_id, {"status": "error", "message": message}, name)
            return [], False

        # Autonomy gate: destructive tools pause in ask mode.
        if tool.destructive and autonomy == "ask":
            future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
            self.pending_confirms[call_id] = future
            await status("pending_confirm")
            try:
                approved = await asyncio.wait_for(future, timeout=_CONFIRM_TIMEOUT)
            except asyncio.TimeoutError:
                approved = False
            finally:
                self.pending_confirms.pop(call_id, None)
            if not approved:
                message = "user declined this tool call"
                await status("rejected", summary=message)
                self._push_tool_record(call_id, {"status": "rejected", "message": message}, name)
                return [], True

        await status("running")
        _log.info("tool call %s %s", name, call["arguments"][:200])
        try:
            result = await tool.call(ctx, args)
        except ToolError as ex:
            await status("error", summary=str(ex))
            self._push_tool_record(call_id, {"status": "error", "message": str(ex)}, name)
            return [], False
        except Exception as ex:  # pylint: disable=broad-exception-caught
            message = "{:s}: {:s}".format(type(ex).__name__, str(ex))
            await status("error", summary=message)
            self._push_tool_record(call_id, {"status": "error", "message": message}, name)
            return [], False

        payload: dict[str, Any] = {"status": "ok", "result": result.data}
        if result.media_ids:
            payload["media_ids"] = result.media_ids
        self._push_tool_record(call_id, payload, name)
        await status(
            "done",
            summary=result.summary,
            media_ids=result.media_ids,
            data=_clip_result_data(result.data),
        )
        return result.media_ids, False

    def _push_tool_record(self, call_id: str, payload: dict[str, Any], name: str = "") -> None:
        text = json.dumps(payload)
        if len(text) > _TOOL_RESULT_CHAR_LIMIT:
            text = text[:_TOOL_RESULT_CHAR_LIMIT] + "... [truncated]"
        self.push_record({"role": "tool", "tool_call_id": call_id, "name": name, "content": text})

    # ------------------------------------------------------------------
    # Confirm gate plumbing (called by the runtime).

    def resolve_confirm(self, call_id: str, approve: bool) -> bool:
        future = self.pending_confirms.get(call_id)
        if future is None or future.done():
            return False
        future.set_result(approve)
        return True
