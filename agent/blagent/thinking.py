# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
The chain-of-thought codec — one place, at the LLM IO boundary, that decides
how reasoning traces are handled, with two explicit paths for every piece of
assistant text:

  * DISPLAY  — what the UI / downstream clients see: reasoning lifted into a
               normalized ``<think>…</think>`` block (collapsible), the answer
               clean. Built by the streaming ``ThinkingDecoder`` as tokens
               arrive, or by ``to_display`` from a stored string.
  * CONTEXT  — what goes back to the model next turn: ``to_context`` strips the
               reasoning (reasoning-model chat templates drop prior-turn
               thinking, and it is pure context-budget waste). The original
               assistant *answer* is preserved verbatim; only the trace is
               dropped.

Two trace SOURCES are unified so the harness behaves the same whether or not
the LLM server has a reasoning parser configured:

  * server channel — deltas carry ``reasoning_content``/``reasoning`` (vLLM /
    SGLang with a parser; e.g. Kimi, DeepSeek-R1),
  * inline tags    — the model emits ``<think>…</think>`` (or ``<thinking>``)
    in ``content`` (no server parser, or a prompt-instructed model).

``ThinkingDecoder`` takes either (or both) and produces one normalized stream.
"""

__all__ = (
    "THINK_RE",
    "ThinkingDecoder",
    "to_context",
    "to_display",
)

import re

# A reasoning block in assistant content. An unterminated block (aborted
# generation, or a model prefilled into <think> that never closes) runs to EOT.
THINK_RE = re.compile(r"<think(?:ing)?>.*?(?:</think(?:ing)?>|\Z)", re.DOTALL)

_THINK_OPENS = ("<think>", "<thinking>")
_THINK_CLOSES = ("</think>", "</thinking>")
# Longest token we might need to hold back mid-stream to detect a split tag.
_MAX_TAG = max(len(t) for t in _THINK_OPENS + _THINK_CLOSES)


def to_context(text: str) -> str:
    """CONTEXT path: drop reasoning blocks before the text is sent back to the
    model. The answer survives; the trace does not. (KV-cache safe — this is
    what reasoning-model chat templates do themselves.)"""
    if "<think" not in text:
        return text
    return THINK_RE.sub("", text).strip()


def to_display(reasoning: str, content: str) -> str:
    """DISPLAY path for a finished message: a normalized ``<think>`` block
    (when there is a separate reasoning trace) followed by the clean answer.
    If the content already carries inline ``<think>`` tags (server had no
    parser), it is returned as-is."""
    if not reasoning:
        return content
    block = "<think>\n{:s}\n</think>".format(reasoning.strip())
    return block if not content else "{:s}\n\n{:s}".format(block, content)


class ThinkingDecoder:
    """
    Streaming codec. Feed each delta's ``(content, reasoning)``; get back a
    list of ``(channel, text)`` segments where ``channel`` is ``"reasoning"``
    or ``"content"``. Inline ``<think>`` tags in *content* are parsed out
    (stateful — a tag may split across deltas); a server ``reasoning`` delta is
    routed straight to the reasoning channel. Call ``finish()`` to flush the
    tail (an unterminated inline block stays reasoning).
    """

    def __init__(self) -> None:
        self._buf = ""
        self._in_think = False
        self.content_parts: list[str] = []
        self.reasoning_parts: list[str] = []

    def feed(self, content: str = "", reasoning: str = "") -> list[tuple[str, str]]:
        events: list[tuple[str, str]] = []
        if reasoning:
            self.reasoning_parts.append(reasoning)
            events.append(("reasoning", reasoning))
        if content:
            self._buf += content
            events.extend(self._drain(final=False))
        return events

    def finish(self) -> list[tuple[str, str]]:
        return self._drain(final=True)

    def _emit(self, text: str) -> tuple[str, str] | None:
        if not text:
            return None
        if self._in_think:
            self.reasoning_parts.append(text)
            return ("reasoning", text)
        self.content_parts.append(text)
        return ("content", text)

    def _earliest(self) -> "tuple[int, str, bool] | None":
        """(index, tag, is_open) of the earliest think tag in the buffer."""
        best: "tuple[int, str, bool] | None" = None
        tags = ([(t, True) for t in _THINK_OPENS] if not self._in_think
                else [(t, False) for t in _THINK_CLOSES])
        for tag, is_open in tags:
            at = self._buf.find(tag)
            if at >= 0 and (best is None or at < best[0]):
                best = (at, tag, is_open)
        return best

    def _held_back(self) -> int:
        """Longest buffer suffix that could be the start of a (not-yet-complete)
        think tag, so a tag split across deltas still parses."""
        relevant = _THINK_OPENS if not self._in_think else _THINK_CLOSES
        upper = min(len(self._buf), _MAX_TAG)
        for length in range(upper, 0, -1):
            tail = self._buf[len(self._buf) - length:]
            if any(t.startswith(tail) and len(t) > length for t in relevant):
                return length
        return 0

    def _drain(self, final: bool) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        while True:
            hit = self._earliest()
            if hit is None:
                break
            at, tag, is_open = hit
            seg = self._emit(self._buf[:at])
            if seg:
                out.append(seg)
            self._buf = self._buf[at + len(tag):]
            self._in_think = is_open
        hold = 0 if final else self._held_back()
        if len(self._buf) > hold:
            seg = self._emit(self._buf[:len(self._buf) - hold] if hold else self._buf)
            if seg:
                out.append(seg)
            self._buf = self._buf[len(self._buf) - hold:] if hold else ""
        return out

    # -- accumulated views --------------------------------------------------
    @property
    def content(self) -> str:
        return "".join(self.content_parts)

    @property
    def reasoning(self) -> str:
        return "".join(self.reasoning_parts).strip()

    def display(self) -> str:
        """The finished DISPLAY string (normalized <think> + clean answer)."""
        return to_display(self.reasoning, self.content)
