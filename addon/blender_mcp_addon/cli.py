# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
CLI command handler for running the MCP server in background mode.

Started via ``blender --background file.blend --command blender_mcp``.
"""

__all__ = (
    "cli_execute",
)

import argparse
import os

from . import execute_blocking
from . import mcp_to_blender_server


def _env_port(default: int) -> int:
    raw = os.environ.get("BLENDER_MCP_PORT", "")
    try:
        return int(raw) if raw else default
    except ValueError:
        print("Warning: BLENDER_MCP_PORT={!r} is not a port; using {:d}".format(raw, default))
        return default


def cli_execute(argv: list[str]) -> int:
    """
    Block and serve MCP requests until interrupted.
    """
    parser = argparse.ArgumentParser(
        prog="blender_mcp",
        description=(
            "Start the Blender MCP server. "
            "Deferred responses are not supported in background mode; "
            "each request must complete before returning."
        ),
    )
    # The defaults read BLENDER_MCP_HOST / BLENDER_MCP_PORT, which is what the MCP client already
    # reads (tools_helpers/connection.py) and what the Makefile documents as "the port the MCP
    # add-on listens on". Before this the server side ignored both, so a client and a server
    # given the SAME environment disagreed: the client dialled the configured port while the
    # server listened on 9876, and the only symptom was "Blender is unreachable".
    # An explicit --host/--port still wins over the environment.
    parser.add_argument(
        "--host",
        default=os.environ.get("BLENDER_MCP_HOST") or mcp_to_blender_server.DEFAULT_HOST,
        help="Host to bind to (default: $BLENDER_MCP_HOST, else localhost).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=_env_port(mcp_to_blender_server.DEFAULT_PORT),
        help="Port to listen on (default: $BLENDER_MCP_PORT, else 9876).",
    )
    args = parser.parse_args(argv)

    try:
        mcp_to_blender_server.start(args.host, args.port)
    except Exception as ex:  # pylint: disable=broad-exception-caught
        print("Error: {:s}".format(str(ex)))
        return 1

    print("MCP server started on {:s}:{:d}, press Ctrl+C to exit.".format(args.host, args.port))

    try:
        execute_blocking.run()
    finally:
        mcp_to_blender_server.stop()
    return 0
