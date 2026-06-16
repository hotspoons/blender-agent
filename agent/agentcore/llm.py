# SPDX-FileCopyrightText: 2026 agentcore contributors
#
# SPDX-License-Identifier: MIT OR Apache-2.0

"""
LLM transport, ported from Foyer Studio's ``foyer-agent/src/llm.rs``.

Every endpoint — OpenAI, Anthropic (via its OpenAI-compatible surface),
OpenRouter, local llama.cpp / Ollama / vLLM, or the in-browser
Transformers.js bridge — is treated as a uniform OpenAI-compatible
chat-completions endpoint. Streaming only; deltas are reassembled by
the engine.
"""

__all__ = (
    "LlmChunk",
    "LlmClient",
    "LlmError",
    "LocalLlmBridgeClient",
    "OpenAiHttpClient",
)

import json

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

import httpx

from .trace import trace_llm_request

if TYPE_CHECKING:
    from .local_llm import LocalLlmBridge


class LlmError(Exception):
    """
    Transport or upstream error; surfaced to the UI as a turn failure.
    """


class LlmChunk:
    """
    One streamed delta: optional content text, optional reasoning text
    (for models whose endpoint separates chain-of-thought into a
    ``reasoning_content``/``reasoning`` field — e.g. Kimi/DeepSeek-R1 on
    vLLM/SGLang), optional tool-call fragments, optional finish reason.
    """

    __slots__ = ("content", "reasoning", "tool_calls", "finish_reason")

    def __init__(
            self,
            content: str = "",
            tool_calls: list[dict[str, Any]] | None = None,
            finish_reason: str | None = None,
            reasoning: str = "",
    ) -> None:
        self.content = content
        self.reasoning = reasoning
        self.tool_calls = tool_calls or []
        self.finish_reason = finish_reason

    @classmethod
    def from_openai(cls, payload: dict[str, Any]) -> "LlmChunk | None":
        choices = payload.get("choices") or []
        if not choices:
            return None
        choice = choices[0]
        delta = choice.get("delta") or {}
        # Servers vary: vLLM/SGLang use `reasoning_content`, some use
        # `reasoning`. Capture either so the trace isn't lost (it would
        # otherwise look like dead air while content stays empty).
        return cls(
            content=delta.get("content") or "",
            reasoning=delta.get("reasoning_content") or delta.get("reasoning") or "",
            tool_calls=delta.get("tool_calls") or [],
            finish_reason=choice.get("finish_reason"),
        )


class LlmClient:
    """
    Abstract streaming chat-completions client.
    """

    async def stream(self, request: dict[str, Any]) -> AsyncIterator[LlmChunk]:
        raise NotImplementedError
        # Make this an async generator for type checkers.
        yield LlmChunk()  # pylint: disable=unreachable


class OpenAiHttpClient(LlmClient):
    """
    Streaming client for any OpenAI-compatible HTTP endpoint.

    *base_url* is the API base ending in ``/v1`` (e.g.
    ``https://api.openai.com/v1`` or ``http://127.0.0.1:8080/v1``);
    the ``/chat/completions`` path is appended here.
    """

    def __init__(self, base_url: str, api_key: str = "", timeout: float = 300.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout

    async def stream(self, request: dict[str, Any]) -> AsyncIterator[LlmChunk]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = "Bearer {:s}".format(self._api_key)
        body = dict(request)
        body["stream"] = True
        # Context trace (BLENDER_AGENT_TRACE_CONTEXT): log who-sent-what, then
        # strip the internal label so it never goes on the wire.
        trace_llm_request(str(body.pop("_trace_label", "")), body)

        url = "{:s}/chat/completions".format(self._base_url)
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                async with client.stream("POST", url, json=body, headers=headers) as response:
                    if response.status_code >= 400:
                        detail = (await response.aread()).decode("utf-8", "replace")
                        raise LlmError("LLM endpoint returned {:d}: {:s}".format(
                            response.status_code, detail[:500]))
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        payload_text = line[len("data:"):].strip()
                        if payload_text == "[DONE]":
                            return
                        try:
                            payload = json.loads(payload_text)
                        except ValueError:
                            continue
                        chunk = LlmChunk.from_openai(payload)
                        if chunk is not None:
                            yield chunk
        except httpx.HTTPError as ex:
            raise LlmError("LLM endpoint unreachable at {:s}: {:s}".format(url, str(ex))) from ex


class LocalLlmBridgeClient(LlmClient):
    """
    Streaming client backed by the in-browser local-model reverse
    tunnel (see ``local_llm.py``). From the engine's perspective it is
    just another endpoint.
    """

    def __init__(self, bridge: "LocalLlmBridge") -> None:
        self._bridge = bridge

    async def stream(self, request: dict[str, Any]) -> AsyncIterator[LlmChunk]:
        if not self._bridge.is_ready():
            raise LlmError(
                "local model is not loaded - open the web UI and load one in "
                "Settings, or configure an external endpoint instead."
            )
        request = dict(request)
        trace_llm_request(str(request.pop("_trace_label", "")), request)
        async for payload in self._bridge.send_streaming_request(request):
            chunk = LlmChunk.from_openai(payload)
            if chunk is not None:
                yield chunk
