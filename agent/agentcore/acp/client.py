# SPDX-FileCopyrightText: 2026 agentcore contributors
#
# SPDX-License-Identifier: MIT OR Apache-2.0

"""
An ACP client -- the orchestrator side of the protocol.

The same agent that SERVES ACP to an outside harness also CONSUMES it, to drive
its own worker sub-agents. That is the whole reason ACP fits here: a worker is
just an agent, and an orchestrator is just a client, so one protocol covers both
directions and the homegrown worker wire can go away.

Version is negotiated like any other client: we ask for v2 because v2 is what
makes steering possible. v1 treats a session as strictly turn-based, so
``session/prompt`` while a turn runs is out of contract; v2 explicitly drops
that, which is exactly what injecting guidance into a running worker needs.

Inbound requests get answered here rather than passed up:

- ``session/request_permission`` -> allowed. A worker runs unattended, there is
  no user behind it, and it already runs with autonomy forced to auto. Blocking
  would deadlock the run.
- ``elicitation/create`` -> cancelled. Same reason, opposite answer: a question
  has no one to answer it, and cancelling lets the worker's tool take its
  no-user path instead of waiting out a timeout.
"""

__all__ = (
    "AcpClient",
    "AcpClientError",
    "UpdateSink",
)

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable

from acp.connection import Connection

from agentcore.acp import versions

_log = logging.getLogger("agentcore.acp.client")

# Sink for translated worker activity (session/update -> harness events).
UpdateSink = Callable[[str, "dict[str, Any]"], Awaitable[None]]


class AcpClientError(RuntimeError):
    """The peer could not be reached, or answered outside the protocol."""


class _WebSocketTransport:
    """``acp.Transport`` over a ``websockets`` client connection."""

    def __init__(self, socket: Any) -> None:
        self._socket = socket
        self._lock = asyncio.Lock()

    async def send(self, message: "dict[str, Any]") -> None:
        async with self._lock:
            await self._socket.send(json.dumps(message))

    async def receive(self) -> "dict[str, Any] | None":
        try:
            raw = await self._socket.recv()
        except Exception:  # pylint: disable=broad-except
            return None
        try:
            decoded = json.loads(raw)
        except ValueError:
            _log.warning("acp/client: discarding unparseable frame")
            return await self.receive()
        return decoded if isinstance(decoded, dict) else None

    async def close(self) -> None:
        with_suppress = getattr(self._socket, "close", None)
        if with_suppress is not None:
            try:
                await self._socket.close()
            except Exception:  # pylint: disable=broad-except
                pass


class AcpClient:
    """
    One ACP connection to one agent.

    Use as an async context manager; ``initialize`` is done on entry so a
    caller never holds a connection that has not negotiated.
    """

    def __init__(
            self,
            url: str,
            *,
            api_key: str = "",
            client_name: str = "agentcore-orchestrator",
            on_update: "UpdateSink | None" = None,
            open_timeout: float = 30.0,
    ) -> None:
        self._url = url
        self._api_key = api_key
        self._client_name = client_name
        self._on_update = on_update
        self._open_timeout = open_timeout
        self._socket: "Any | None" = None
        self._connection: "Connection | None" = None
        self._pump: "asyncio.Task[None] | None" = None
        # Turns awaiting an idle state_update, by session. v2 reports turn
        # completion there rather than in the prompt reply.
        self._idle_waiters: "dict[str, list[asyncio.Future[str]]]" = {}
        self.version = 0

    # ------------------------------------------------------------------
    # Lifecycle.

    async def __aenter__(self) -> "AcpClient":
        await self.connect()
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        await self.aclose()

    async def connect(self) -> None:
        """Open the socket, start the receive loop, and negotiate."""
        from websockets.asyncio.client import connect

        headers = {"Authorization": "Bearer " + self._api_key} if self._api_key else None
        try:
            self._socket = await asyncio.wait_for(
                connect(self._url, additional_headers=headers, max_size=None),
                timeout=self._open_timeout)
        except Exception as ex:
            raise AcpClientError(
                "could not open an ACP connection to {:s}: {!s}".format(self._url, ex)) from ex

        transport = _WebSocketTransport(self._socket)
        self._connection = Connection(self._handle, transport, listening=False)
        self._pump = asyncio.create_task(self._connection.main_loop())
        await self._initialize()

    async def aclose(self) -> None:
        if self._pump is not None and not self._pump.done():
            self._pump.cancel()
            try:
                await self._pump
            except (asyncio.CancelledError, Exception):  # pylint: disable=broad-except
                pass
        if self._connection is not None:
            try:
                await self._connection.close()
            except Exception:  # pylint: disable=broad-except
                pass
        self._socket = None
        self._connection = None
        self._pump = None

    async def _initialize(self) -> None:
        result = await self._request("initialize", {
            "protocolVersion": versions.V2,
            "info": {"name": self._client_name, "version": "1"},
            "capabilities": {},
        })
        served = result.get("protocolVersion")
        self.version = int(served) if isinstance(served, int) else 0
        if not versions.supports(self.version):
            raise AcpClientError(
                "agent at {:s} serves protocol v{!s}, which we do not implement".format(
                    self._url, served))
        _log.info("acp/client: %s negotiated v%d", self._url, self.version)

    # ------------------------------------------------------------------
    # Agent methods.

    async def new_session(
            self,
            cwd: str = "/",
            mcp_servers: "list[dict[str, Any]] | None" = None,
            meta: "dict[str, Any] | None" = None,
    ) -> str:
        params: "dict[str, Any]" = {"cwd": cwd}
        if mcp_servers:
            params["mcpServers"] = mcp_servers
        if meta:
            # `_meta` is what v2 reserves for implementation extensions. The
            # context fork rides here because ACP has no seed field.
            params["_meta"] = meta
        result = await self._request("session/new", params)
        session_id = result.get("sessionId")
        if not isinstance(session_id, str) or not session_id:
            raise AcpClientError("agent returned no sessionId from session/new")
        return session_id

    async def prompt(self, session_id: str, text: str) -> str:
        """
        Send a prompt and wait for the turn to finish. Returns the stop reason.

        How the end of the turn is detected depends on the version. In v1 the
        prompt reply carries ``stopReason``. In v2 it carries nothing -- the
        schema states the response "does not indicate that the agent has
        finished processing" -- so completion arrives as a ``state_update``
        with state ``idle``, and that is what we wait on.
        """
        waiter: "asyncio.Future[str] | None" = None
        if self.version >= versions.V2:
            waiter = asyncio.get_running_loop().create_future()
            self._idle_waiters.setdefault(session_id, []).append(waiter)
        try:
            result = await self._request("session/prompt", {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": text}],
            })
        except Exception:
            if waiter is not None:
                self._drop_waiter(session_id, waiter)
            raise
        if waiter is None:
            reason = result.get("stopReason")
            return str(reason) if reason else "end_turn"
        return await waiter

    def _drop_waiter(self, session_id: str, waiter: "asyncio.Future[str]") -> None:
        waiters = self._idle_waiters.get(session_id) or []
        if waiter in waiters:
            waiters.remove(waiter)
        if not waiters:
            self._idle_waiters.pop(session_id, None)

    def _resolve_idle(self, session_id: str, update: "dict[str, Any]") -> None:
        """Hand an idle state update to whoever is waiting on this turn."""
        if update.get("sessionUpdate") != "state_update" or update.get("state") != "idle":
            return
        waiters = self._idle_waiters.pop(session_id, None) or []
        reason = str(update.get("stopReason") or "end_turn")
        for waiter in waiters:
            if not waiter.done():
                waiter.set_result(reason)

    async def steer(self, session_id: str, text: str) -> None:
        """
        Send a message into a session that is already working.

        Legal in v2, which dropped turn-based session semantics; this is the
        protocol form of injecting guidance into a running worker. Fired as a
        task because the prompt call does not return until the turn ends, and
        the caller is steering, not waiting.
        """
        if self.version < versions.V2:
            raise AcpClientError(
                "steering needs protocol v2; this connection negotiated v{:d}".format(
                    self.version))
        asyncio.create_task(self._steer_quietly(session_id, text))

    async def _steer_quietly(self, session_id: str, text: str) -> None:
        try:
            await self.prompt(session_id, text)
        except Exception as ex:  # pylint: disable=broad-except
            _log.info("acp/client: steer of %s ended: %s", session_id, ex)

    async def cancel(self, session_id: str) -> None:
        """Interrupt the session. A notification -- nothing comes back."""
        await self._notify("session/cancel", {"sessionId": session_id})

    async def close_session(self, session_id: str) -> None:
        try:
            await self._request("session/close", {"sessionId": session_id})
        except Exception as ex:  # pylint: disable=broad-except
            _log.debug("acp/client: close of %s failed: %s", session_id, ex)

    # ------------------------------------------------------------------
    # Plumbing.

    async def _request(self, method: str, params: "dict[str, Any]") -> "dict[str, Any]":
        if self._connection is None:
            raise AcpClientError("not connected")
        result = await self._connection.send_request(method, params)
        return dict(result) if isinstance(result, dict) else {}

    async def _notify(self, method: str, params: "dict[str, Any]") -> None:
        if self._connection is None:
            raise AcpClientError("not connected")
        await self._connection.send_notification(method, params)

    async def _handle(
            self,
            method: str,
            params: "Any | None",
            _is_notification: bool,
    ) -> "Any | None":
        """Answer the agent's calls back at us."""
        args = params if isinstance(params, dict) else {}

        if method == "session/update":
            update = args.get("update")
            if isinstance(update, dict):
                session_id = str(args.get("sessionId") or "")
                self._resolve_idle(session_id, update)
                if self._on_update is not None:
                    await self._on_update(session_id, update)
            return None

        if method == "session/request_permission":
            return {"outcome": self._allow(args)}

        if method == "elicitation/create":
            return {"outcome": {"outcome": "cancelled"}}

        if method == "elicitation/complete":
            return None

        _log.debug("acp/client: ignoring unhandled %s", method)
        return None

    @staticmethod
    def _allow(args: "dict[str, Any]") -> "dict[str, Any]":
        """
        Pick the option that lets the work proceed.

        A worker has no user to consult, so anything other than approval
        deadlocks the run. Prefer an explicit allow-always option, then any
        allow, and fall back to the first offered -- an agent that offers no
        allow at all is refusing, and we should not pretend otherwise.
        """
        options = [o for o in args.get("options") or [] if isinstance(o, dict)]
        for wanted in ("allow_always", "allow_once"):
            for option in options:
                if option.get("kind") == wanted:
                    return {"outcome": "selected", "optionId": option.get("optionId")}
        for option in options:
            if str(option.get("kind", "")).startswith("allow"):
                return {"outcome": "selected", "optionId": option.get("optionId")}
        if options:
            return {"outcome": "selected", "optionId": options[0].get("optionId")}
        return {"outcome": "cancelled"}
