# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Web-based agent harness for Blender.

Shares a process with the ``blmcp`` tool surface and invokes the tools
directly (no MCP protocol on the agent path); the same registry can
optionally be exposed over streamable-HTTP MCP for external clients.

The harness design is ported from Foyer Studio's ``foyer-agent``
(Rust); the local-model reverse tunnel from zip-ties (Python),
fulfilled in the browser by Transformers.js. See ``agent/readme.md``
for the architecture.
"""

__all__ = (
    "main",
    "pick_free_port",
    "run_server",
)

import argparse
import asyncio
import os
import socket

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 10102
_DEFAULT_MCP_PORT = 10101
# How many sequential ports to try when auto-assigning.
_PORT_SCAN_ATTEMPTS = 20


def pick_free_port(
        host: str,
        preferred: int,
        attempts: int = _PORT_SCAN_ATTEMPTS,
        exclude: "set[int] | None" = None,
) -> int:
    """
    Return the first bindable port at or above *preferred*.

    Supports running several Blender instances side by side: each
    instance's agent (and MCP listener) walks up from the default port
    until it finds a free one. *exclude* skips ports this process has
    already chosen but not yet bound. Raises ``OSError`` when
    *attempts* sequential ports are all taken.
    """
    last_error: OSError | None = None
    for port in range(preferred, preferred + attempts):
        if exclude and port in exclude:
            continue
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, port))
            return port
        except OSError as ex:
            last_error = ex
        finally:
            sock.close()
    raise OSError("no free port in {:d}..{:d}: {:s}".format(
        preferred, preferred + attempts - 1, str(last_error)))


async def run_server(
        host: str = _DEFAULT_HOST,
        port: int = _DEFAULT_PORT,
        mcp_port: int | None = None,
        data_dir: str | None = None,
        open_browser: bool = False,
        port_auto: bool = True,
        title: str | None = None,
        spawn_blender: bool | None = None,
        blend_file: str | None = None,
        bridge_host: str | None = None,
        bridge_port: int | None = None,
) -> None:
    """
    Run the agent server until cancelled. When *mcp_port* is given, the
    same tool registry is also exposed as a streamable-HTTP MCP server
    on that port (stateless, served at ``/``).

    With *port_auto* (the default), ports already taken - e.g. by the
    agent of another Blender instance - are resolved by walking up to
    the next free port.

    *title* labels this instance in the UI (browser tab title), so
    agent tabs of side-by-side Blender instances can be told apart -
    the add-on passes the .blend file name and keeps it updated via
    ``POST /instance``.

    Compute surface: the agent's tools talk to Blender over the add-on's
    TCP bridge. When none is reachable and the agent was not itself
    launched by Blender, it spawns ``blender --background --command
    blender_mcp`` as its own surface (*blend_file* optionally opened)
    and tears it down on exit. *spawn_blender* forces this on/off;
    ``None`` (default) means auto. The recursion guard refuses to spawn
    when the agent is a Blender descendant (see ``blender_surface``).
    """
    import uvicorn

    from .app import create_app
    from .blender_surface import (
        BlenderSurface, bridge_reachable, spawned_by_blender, surface_decision,
    )
    from .blender_tools import build_blender_registry
    from .runtime import AgentRuntime
    from .store import AgentStore

    if port_auto:
        port = pick_free_port(host, port)
        if mcp_port is not None:
            # Exclude the UI port just chosen - it is not bound yet, so
            # the scan would otherwise consider it free.
            mcp_port = pick_free_port(host, mcp_port, exclude={port})

    # Resolve / provision the Blender compute surface before building
    # the tool registry (which reads BLENDER_MCP_HOST/PORT lazily).
    surface = _ensure_blender_surface(
        spawn_blender=spawn_blender,
        blend_file=blend_file,
        bridge_host=bridge_host,
        bridge_port=bridge_port,
        deps=(BlenderSurface, bridge_reachable, spawned_by_blender, surface_decision),
    )

    mcp, blender_tools = await build_blender_registry()
    store = AgentStore(data_dir=data_dir)

    # Harness log: turns, tool calls, LLM failures. The first place to
    # look when a model "stops responding".
    import logging
    import logging.handlers

    log_path = os.path.join(store.data_dir, "agent.log")
    handler = logging.handlers.RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=2)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger("blagent").setLevel(logging.INFO)
    logging.getLogger("blagent").addHandler(handler)
    runtime = AgentRuntime(store, blender_tools)
    runtime.instance_title = title if title is not None else os.environ.get("BLENDER_AGENT_TITLE", "")
    runtime.instance_port = port
    app = create_app(runtime)

    servers = [uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))]

    if mcp_port is not None:
        from mcp.server.fastmcp.server import TransportSecuritySettings  # type: ignore[attr-defined]

        mcp.settings.host = host
        mcp.settings.port = mcp_port
        mcp.settings.streamable_http_path = "/"
        mcp.settings.stateless_http = True
        mcp.settings.transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=False,
        )
        servers.append(uvicorn.Server(uvicorn.Config(
            mcp.streamable_http_app(), host=host, port=mcp_port, log_level="warning",
        )))

    if open_browser:
        import webbrowser

        webbrowser.open("http://{:s}:{:d}/".format(host, port))

    print("blender-agent: web UI at http://{:s}:{:d}/".format(host, port), flush=True)
    print("blender-agent: log file at {:s}".format(log_path), flush=True)
    if mcp_port is not None:
        print("blender-agent: MCP (streamable HTTP) at http://{:s}:{:d}/".format(host, mcp_port), flush=True)

    try:
        await asyncio.gather(*(server.serve() for server in servers))
    finally:
        # Tear down a spawned Blender surface; a bridge we merely
        # attached to is left running.
        if surface is not None:
            surface.stop()


def _ensure_blender_surface(
        *,
        spawn_blender: bool | None,
        blend_file: str | None,
        bridge_host: str | None,
        bridge_port: int | None,
        deps: tuple,
) -> object:
    """
    Decide whether to attach to an existing Blender bridge or spawn one,
    and act on it. Returns the ``BlenderSurface`` when we spawned (so it
    can be stopped later), else ``None``. On a spawn, ``BLENDER_MCP_HOST``
    / ``BLENDER_MCP_PORT`` are set so the tools find the new bridge.

    Kept module-level and dependency-injected so the decision is unit
    testable without importing Blender.
    """
    BlenderSurface, bridge_reachable, spawned_by_blender, surface_decision = deps

    host = bridge_host or os.environ.get("BLENDER_MCP_HOST", "localhost")
    port = bridge_port or int(os.environ.get("BLENDER_MCP_PORT", "9876"))

    decision = surface_decision(
        bridge_up=bridge_reachable(host, port),
        is_blender_child=spawned_by_blender(),
        want_spawn=(spawn_blender is not False),
    )

    if decision == "attach":
        print("blender-agent: attaching to Blender bridge at {:s}:{:d}".format(host, port), flush=True)
        return None
    if decision == "guarded":
        # We are a Blender child; the add-on is bringing the bridge up.
        print("blender-agent: launched by Blender; will use its bridge at {:s}:{:d} "
              "(not spawning)".format(host, port), flush=True)
        return None
    if decision == "none":
        print("blender-agent: no Blender bridge at {:s}:{:d} and spawning disabled - "
              "tools will fail until one is available".format(host, port), flush=True)
        return None

    # decision == "spawn": provision our own headless Blender. Pick a
    # free bridge port so we never collide with an unrelated instance.
    if not bridge_port and not os.environ.get("BLENDER_MCP_PORT"):
        try:
            port = pick_free_port(host, port)
        except OSError:
            pass
    print("blender-agent: no Blender bridge found; spawning a headless one at "
          "{:s}:{:d}".format(host, port), flush=True)
    surface = BlenderSurface(host=host, port=port, blend_file=blend_file)
    surface.start()
    os.environ["BLENDER_MCP_HOST"] = host
    os.environ["BLENDER_MCP_PORT"] = str(port)
    return surface


def main() -> int:
    parser = argparse.ArgumentParser(description="Web-based agent for Blender.")
    parser.add_argument(
        "--host",
        default=_DEFAULT_HOST,
        help="Host to bind to (default: {:s}).".format(_DEFAULT_HOST),
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=_DEFAULT_PORT,
        help="Agent web UI port (default: {:d}).".format(_DEFAULT_PORT),
    )
    parser.add_argument(
        "--mcp-port",
        type=int,
        default=None,
        metavar="PORT",
        help="Also expose the tools over streamable-HTTP MCP on this port "
             "(use {:d} to match the documented .mcp.json).".format(_DEFAULT_MCP_PORT),
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Agent data directory (default: $XDG_DATA_HOME/blender-agent).",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="Open the web UI in a browser after starting.",
    )
    parser.add_argument(
        "--no-port-auto",
        action="store_true",
        help="Fail when a port is taken instead of walking up to the next free one.",
    )
    parser.add_argument(
        "--title",
        default=None,
        help="Instance label shown in the browser tab title "
             "(default: $BLENDER_AGENT_TITLE).",
    )
    surface_group = parser.add_mutually_exclusive_group()
    surface_group.add_argument(
        "--spawn-blender",
        dest="spawn_blender",
        action="store_true",
        default=None,
        help="Spawn a headless Blender as the compute surface when no bridge is "
             "reachable (the default when launched standalone). Uses $BLENDER_PATH "
             "(or 'blender'), which must have the blender-mcp add-on installed.",
    )
    surface_group.add_argument(
        "--no-spawn-blender",
        dest="spawn_blender",
        action="store_false",
        help="Never spawn Blender; only attach to an existing bridge.",
    )
    parser.add_argument(
        "--blend",
        dest="blend_file",
        default=None,
        metavar="FILE",
        help="Open this .blend file in the spawned Blender surface (default: none).",
    )
    parser.add_argument(
        "--bridge-host",
        default=None,
        help="Blender bridge host to attach to / spawn (default: $BLENDER_MCP_HOST or localhost).",
    )
    parser.add_argument(
        "--bridge-port",
        type=int,
        default=None,
        help="Blender bridge port to attach to / spawn (default: $BLENDER_MCP_PORT or 9876).",
    )
    args = parser.parse_args()

    try:
        asyncio.run(run_server(
            host=args.host,
            port=args.port,
            mcp_port=args.mcp_port,
            data_dir=args.data_dir,
            open_browser=args.open,
            port_auto=not args.no_port_auto,
            title=args.title,
            spawn_blender=args.spawn_blender,
            blend_file=args.blend_file,
            bridge_host=args.bridge_host,
            bridge_port=args.bridge_port,
        ))
    except KeyboardInterrupt:
        pass
    return 0
