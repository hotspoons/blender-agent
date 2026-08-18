# SPDX-FileCopyrightText: 2026 agentcore contributors
#
# SPDX-License-Identifier: MIT OR Apache-2.0

"""
The dual-version ACP dispatcher.

One connection, one negotiated version, two method tables. ``initialize``
resolves the version and pins it for the life of the connection; every later
call is routed to the v1 or v2 handler for that method. Both tables call the
same :class:`AgentBridge`, so the versions differ only in payload shape -- they
can never disagree about what the agent actually did.

Why not the SDK's server: ``acp.connection.Connection`` is version-agnostic
(it takes a raw ``(method, params, is_notification)`` handler and owns only
JSON-RPC framing and request correlation), but everything above it --
``AgentSideConnection``, ``build_agent_router``, ``AcpServer`` -- is bound to
the v1 ``Agent`` interface. So we reuse ``Connection`` and supply our own
handler.
"""

__all__ = (
    "AcpConnection",
    "AgentBridge",
    "ClientProxy",
    "INTERNAL_ERROR",
    "INVALID_PARAMS",
    "METHOD_NOT_FOUND",
)

import logging
from typing import Any, Awaitable, Callable, Protocol, runtime_checkable

from acp.exceptions import RequestError

from agentcore.acp import versions, wire
from agentcore.acp import models_v2 as _m

_log = logging.getLogger("agentcore.acp")

# JSON-RPC 2.0 reserved codes. `Connection` already turns a RequestError into a
# proper error response and anything else into -32603, so raising RequestError
# is all a handler has to do.
INVALID_PARAMS = -32602
METHOD_NOT_FOUND = -32601
INTERNAL_ERROR = -32603


@runtime_checkable
class AgentBridge(Protocol):
    """
    The version-independent operations a dispatcher needs.

    Defined here, next to its only consumer, so ``bridge.py`` depends on the
    dispatcher rather than the reverse -- and so the dispatcher can be tested
    against a fake without pulling in ``AgentRuntime``.

    ``session_id`` is the ACP-visible identifier and maps 1:1 onto a harness
    session id.
    """

    async def new_session(
        self,
        cwd: "str | None",
        mcp_servers: "list[dict[str, Any]] | None",
        client: "ClientProxy",
        meta: "dict[str, Any] | None" = None,
    ) -> str: ...

    async def prompt(
        self,
        session_id: str,
        blocks: "list[dict[str, Any]]",
        client: "ClientProxy",
        await_turn: bool = True,
    ) -> "str | None": ...

    async def cancel(self, session_id: str) -> None: ...

    async def list_sessions(self) -> "list[dict[str, Any]]": ...

    async def delete_session(self, session_id: str) -> None: ...

    async def resume_session(
        self,
        session_id: str,
        replay_from: "dict[str, Any] | None",
        client: "ClientProxy",
    ) -> None: ...

    async def close_session(self, session_id: str) -> None: ...

    async def fork_session(self, session_id: str, cwd: "str | None") -> str: ...

    async def set_config_option(
        self,
        session_id: str,
        option_id: str,
        value: "Any",
    ) -> "dict[str, Any]": ...


class ClientProxy:
    """
    The agent's handle on the client: ``session/update``,
    ``session/request_permission``, ``elicitation/create``.

    Payload shape is version-dependent, so the proxy carries the negotiated
    version and the bridge never has to think about it.
    """

    def __init__(
            self,
            send_request: "Callable[[str, dict[str, Any]], Awaitable[Any]]",
            send_notification: "Callable[[str, dict[str, Any]], Awaitable[None]]",
            version: int,
    ) -> None:
        self._send_request = send_request
        self._send_notification = send_notification
        self.version = version

    async def session_update(self, session_id: str, update: "dict[str, Any]") -> None:
        """
        Push one session update. A notification: fire-and-forget by design, so
        a slow client cannot stall the engine mid-turn.
        """
        await self._send_notification(
            "session/update", {"sessionId": session_id, "update": update})

    async def request_permission(
            self,
            session_id: str,
            title: str,
            options: "list[dict[str, Any]]",
            subject: "dict[str, Any] | None" = None,
            description: "str | None" = None,
    ) -> "dict[str, Any]":
        """
        Ask the client to authorize an operation.

        v2 carries a required ``title`` and an extensible ``subject``; v1
        hardwired the request to a tool call. The v1 shape is reconstructed
        from the subject so the bridge only ever speaks v2's vocabulary.
        """
        if self.version >= versions.V2:
            params: "dict[str, Any]" = {
                "sessionId": session_id,
                "title": title,
                "options": options,
            }
            if subject is not None:
                params["subject"] = subject
            if description is not None:
                params["description"] = description
        else:
            tool_call = dict(subject.get("toolCall", {})) if subject else {}
            tool_call.setdefault("title", title)
            params = {
                "sessionId": session_id,
                "toolCall": tool_call,
                "options": options,
            }
        result = await self._send_request("session/request_permission", params)
        return dict(result or {})

    async def create_elicitation(
            self,
            session_id: str,
            message: str,
            requested_schema: "dict[str, Any] | None" = None,
    ) -> "dict[str, Any]":
        """Ask the client for structured input from the user."""
        params: "dict[str, Any]" = {"sessionId": session_id, "message": message}
        if requested_schema is not None:
            params["requestedSchema"] = requested_schema
        result = await self._send_request("elicitation/create", params)
        return dict(result or {})


class AcpConnection:
    """
    One client connection: negotiation state plus the method routing.

    Instantiate per connection -- the negotiated version and the set of
    sessions opened over this link are connection state, not process state.
    """

    def __init__(self, bridge: AgentBridge) -> None:
        self._bridge = bridge
        self._version: "int | None" = None
        self._client_info: "dict[str, Any]" = {}
        self._open_sessions: "set[str]" = set()
        self._client: "ClientProxy | None" = None
        self._send_request: "Callable[[str, dict[str, Any]], Awaitable[Any]] | None" = None
        self._send_notification: "Callable[[str, dict[str, Any]], Awaitable[None]] | None" = None

    # ------------------------------------------------------------------
    # Wiring.

    def attach(
            self,
            send_request: "Callable[[str, dict[str, Any]], Awaitable[Any]]",
            send_notification: "Callable[[str, dict[str, Any]], Awaitable[None]]",
    ) -> None:
        """Bind the outbound half (agent -> client) before serving."""
        self._send_request = send_request
        self._send_notification = send_notification

    @property
    def version(self) -> int:
        """The negotiated version. Reading before ``initialize`` is a bug."""
        if self._version is None:
            raise RequestError(INTERNAL_ERROR, "connection is not initialized")
        return self._version

    def _client_proxy(self) -> ClientProxy:
        if self._client is None:
            if self._send_request is None or self._send_notification is None:
                raise RequestError(INTERNAL_ERROR, "connection has no outbound channel")
            self._client = ClientProxy(self._send_request, self._send_notification, self.version)
        return self._client

    # ------------------------------------------------------------------
    # Dispatch.

    async def handle(
            self,
            method: str,
            params: "dict[str, Any] | None",
            is_notification: bool,
    ) -> "Any | None":
        """
        The ``MethodHandler`` handed to ``acp.connection.Connection``.

        Errors come back as ``RequestError`` so the SDK turns them into
        JSON-RPC error responses; an unexpected exception is logged and
        reported as an internal error rather than tearing down the connection,
        which would take every session on it down too.
        """
        args = params or {}
        try:
            if method == "initialize":
                return await self._initialize(args)
            if self._version is None:
                raise RequestError(
                    INVALID_PARAMS,
                    "'initialize' must be the first call on an ACP connection")
            handler = self._table().get(method)
            if handler is None:
                raise RequestError(
                    METHOD_NOT_FOUND,
                    "method {!r} is not supported at protocol version {:d}".format(
                        method, self._version))
            return await handler(args)
        except RequestError:
            raise
        except Exception as ex:  # pylint: disable=broad-except
            _log.exception("acp: %s failed", method)
            if is_notification:
                return None
            raise RequestError(INTERNAL_ERROR, "{:s}: {!s}".format(type(ex).__name__, ex)) from ex

    def _table(self) -> "dict[str, Callable[[dict[str, Any]], Awaitable[Any]]]":
        common: "dict[str, Callable[[dict[str, Any]], Awaitable[Any]]]" = {
            "session/new": self._session_new,
            "session/prompt": self._session_prompt,
            "session/cancel": self._session_cancel,
            "session/list": self._session_list,
            "session/delete": self._session_delete,
            "session/set_config_option": self._session_set_config_option,
        }
        if self._version and self._version >= versions.V2:
            common.update({
                "session/resume": self._session_resume,
                "session/close": self._session_close,
                "session/fork": self._session_fork,
                "auth/login": self._auth_login,
                "auth/logout": self._auth_logout,
            })
        else:
            # v1 named the same operation `session/load`, and had no close.
            common.update({
                "session/load": self._session_resume,
                "authenticate": self._auth_login,
            })
        return common

    # ------------------------------------------------------------------
    # Methods.

    async def _initialize(self, args: "dict[str, Any]") -> "dict[str, Any]":
        requested = args.get("protocolVersion")
        self._version = versions.negotiate(
            requested if isinstance(requested, int) else None)
        info = args.get("info") or args.get("clientInfo") or {}
        self._client_info = dict(info) if isinstance(info, dict) else {}
        _log.info(
            "acp: client %r requested v%s, serving v%d",
            self._client_info.get("name", "?"), requested, self._version)

        if self._version >= versions.V2:
            return wire.dump(_m.InitializeResponse(
                protocol_version=_m.ProtocolVersion(self._version),
                info=_m.Implementation(
                    name=versions.AGENT_INFO_NAME, version=_agent_version()),
                capabilities=versions.agent_capabilities_v2(),
                auth_methods=[],
            ))
        return {
            "protocolVersion": self._version,
            "agentCapabilities": versions.agent_capabilities_v1(),
            "authMethods": [],
        }

    async def _session_new(self, args: "dict[str, Any]") -> "dict[str, Any]":
        servers = args.get("mcpServers")
        meta = args.get("_meta")
        session_id = await self._bridge.new_session(
            _optional_str(args.get("cwd")),
            list(servers) if isinstance(servers, list) else None,
            self._client_proxy(),
            dict(meta) if isinstance(meta, dict) else None,
        )
        self._open_sessions.add(session_id)
        return {"sessionId": session_id}

    async def _session_prompt(self, args: "dict[str, Any]") -> "dict[str, Any]":
        """
        Deliver a prompt, answering in this version's terms.

        v1's ``PromptResponse`` carries a ``stopReason``, so the call blocks
        until the turn is done. v2's carries nothing but ``_meta`` -- the schema
        is explicit that the response "does not indicate that the agent has
        finished processing", which is reported through ``state_update``
        instead. Returning a stop reason to a v2 client would be inventing a
        field the schema does not have.
        """
        session_id = _require_session_id(args)
        blocks = args.get("prompt")
        if not isinstance(blocks, list):
            raise RequestError(INVALID_PARAMS, "'prompt' must be an array of content blocks")
        await_turn = self._version is not None and self._version < versions.V2
        stop_reason = await self._bridge.prompt(
            session_id, list(blocks), self._client_proxy(), await_turn)
        if await_turn:
            return {"stopReason": stop_reason or "end_turn"}
        return {}

    async def _session_cancel(self, args: "dict[str, Any]") -> None:
        await self._bridge.cancel(_require_session_id(args))
        return None

    async def _session_list(self, _args: "dict[str, Any]") -> "dict[str, Any]":
        return {"sessions": await self._bridge.list_sessions()}

    async def _session_delete(self, args: "dict[str, Any]") -> "dict[str, Any]":
        await self._bridge.delete_session(_require_session_id(args))
        return {}

    async def _session_resume(self, args: "dict[str, Any]") -> "dict[str, Any]":
        session_id = _require_session_id(args)
        replay = args.get("replayFrom")
        await self._bridge.resume_session(
            session_id,
            dict(replay) if isinstance(replay, dict) else None,
            self._client_proxy(),
        )
        self._open_sessions.add(session_id)
        return {}

    async def _session_close(self, args: "dict[str, Any]") -> "dict[str, Any]":
        session_id = _require_session_id(args)
        await self._bridge.close_session(session_id)
        self._open_sessions.discard(session_id)
        return {}

    async def _session_fork(self, args: "dict[str, Any]") -> "dict[str, Any]":
        forked = await self._bridge.fork_session(
            _require_session_id(args), _optional_str(args.get("cwd")))
        self._open_sessions.add(forked)
        return {"sessionId": forked}

    async def _session_set_config_option(self, args: "dict[str, Any]") -> "dict[str, Any]":
        option_id = args.get("optionId")
        if not isinstance(option_id, str) or not option_id:
            raise RequestError(INVALID_PARAMS, "'optionId' is required")
        return await self._bridge.set_config_option(
            _require_session_id(args), option_id, args.get("value"))

    async def _auth_login(self, _args: "dict[str, Any]") -> "dict[str, Any]":
        # We advertise no authMethods, so per spec a client must not call this.
        raise RequestError(
            METHOD_NOT_FOUND,
            "this agent advertises no authMethods; authentication is handled by the "
            "deployment (ingress / API key), not in-protocol")

    async def _auth_logout(self, _args: "dict[str, Any]") -> "dict[str, Any]":
        raise RequestError(METHOD_NOT_FOUND, "this agent advertises no authMethods")

    # ------------------------------------------------------------------

    async def aclose(self) -> None:
        """Release every session opened over this connection."""
        for session_id in sorted(self._open_sessions):
            try:
                await self._bridge.close_session(session_id)
            except Exception:  # pylint: disable=broad-except
                _log.exception("acp: closing session %s failed", session_id)
        self._open_sessions.clear()


def _agent_version() -> str:
    try:
        from importlib.metadata import version
        return version("blender-mcp-agent")
    except Exception:  # pylint: disable=broad-except
        return "0.0.0"


def _optional_str(value: "Any") -> "str | None":
    return value if isinstance(value, str) and value else None


def _require_session_id(args: "dict[str, Any]") -> str:
    session_id = args.get("sessionId")
    if not isinstance(session_id, str) or not session_id:
        raise RequestError(INVALID_PARAMS, "'sessionId' is required")
    return session_id
