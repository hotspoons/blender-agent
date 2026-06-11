# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
WebLLM reverse tunnel: the browser hosts an LLM via WebGPU/WebLLM and
serves it to this backend over a WebSocket.

Direct port of the zip-ties bridge
(``ext/zip-ties/zip-ties-web/zip_ties_web/webllm_bridge.py``), and the
same wire protocol, so the browser component ports over unchanged:

Browser -> server: ``{"type": "model_info", "model_id": ..., "status": ...}``
Server -> browser: ``{"id": <uuid>, ...openai chat completions request...}``
Browser -> server: ``{"id": <uuid>, "type": "chunk", "choices": [...]}``
                   ``{"id": <uuid>, "type": "done"}``
                   ``{"id": <uuid>, "error": "..."}``
"""

__all__ = (
    "WebLlmBridge",
)

import asyncio
import uuid

from collections.abc import AsyncIterator
from typing import Any, Protocol

_REQUEST_TIMEOUT = 120.0

_SENTINEL: object = object()


class _WsLike(Protocol):
    async def send_json(self, data: Any) -> None: ...  # noqa: E704


class WebLlmBridge:
    """
    Correlates backend chat-completion requests with streamed responses
    fulfilled by the single connected browser tab.
    """

    def __init__(self) -> None:
        self._ws: _WsLike | None = None
        self._lock = asyncio.Lock()
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._streams: dict[str, asyncio.Queue[object]] = {}
        self.model_id: str = ""
        self.status: str = "disconnected"

    def is_ready(self) -> bool:
        return self._ws is not None and self.status == "ready"

    def public_status(self) -> dict[str, object]:
        return {"status": self.status, "model_id": self.model_id, "connected": self._ws is not None}

    async def connect(self, ws: _WsLike) -> None:
        async with self._lock:
            self._ws = ws
            self.status = "loading"

    async def disconnect(self) -> None:
        async with self._lock:
            self._ws = None
            self.status = "disconnected"
            self.model_id = ""
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(ConnectionError("WebLLM browser disconnected"))
            self._pending.clear()
            for queue in self._streams.values():
                queue.put_nowait(_SENTINEL)
            self._streams.clear()

    async def handle_message(self, data: dict[str, Any]) -> None:
        """
        Process one message from the browser side of the tunnel.
        """
        msg_type = data.get("type")
        if msg_type == "model_info":
            self.model_id = str(data.get("model_id", ""))
            self.status = str(data.get("status", "unknown"))
            return

        request_id = data.get("id")
        if not isinstance(request_id, str):
            return

        if msg_type == "chunk" and request_id in self._streams:
            payload = dict(data)
            payload.pop("id", None)
            payload.pop("type", None)
            self._streams[request_id].put_nowait(payload)
            return

        if msg_type == "done" and request_id in self._streams:
            self._streams[request_id].put_nowait(_SENTINEL)
            return

        if request_id in self._streams and "error" in data:
            self._streams[request_id].put_nowait(RuntimeError(str(data["error"])))
            return

        future = self._pending.get(request_id)
        if future is not None and not future.done():
            if "error" in data:
                future.set_exception(RuntimeError("WebLLM error: {:s}".format(str(data["error"]))))
            else:
                payload = dict(data)
                payload.pop("id", None)
                future.set_result(payload)

    async def send_request(self, request_body: dict[str, Any]) -> dict[str, Any]:
        """
        Non-streaming request; returns the full response payload.
        """
        ws = self._ws
        if ws is None:
            raise ConnectionError("WebLLM browser is not connected")
        request_id = str(uuid.uuid4())
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            await ws.send_json({"id": request_id, **request_body})
            return await asyncio.wait_for(future, timeout=_REQUEST_TIMEOUT)
        finally:
            self._pending.pop(request_id, None)

    async def send_streaming_request(self, request_body: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        """
        Streaming request; yields OpenAI-shaped chunk payloads.
        """
        ws = self._ws
        if ws is None:
            raise ConnectionError("WebLLM browser is not connected")
        request_id = str(uuid.uuid4())
        queue: asyncio.Queue[object] = asyncio.Queue()
        self._streams[request_id] = queue
        try:
            await ws.send_json({"id": request_id, "stream": True, **request_body})
            while True:
                item = await asyncio.wait_for(queue.get(), timeout=_REQUEST_TIMEOUT)
                if item is _SENTINEL:
                    return
                if isinstance(item, Exception):
                    raise item
                assert isinstance(item, dict)
                yield item
        finally:
            self._streams.pop(request_id, None)
