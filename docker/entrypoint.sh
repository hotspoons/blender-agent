#!/usr/bin/env bash
# Entry point for the Blender Agent container.
#
# Translates a handful of environment variables into blender-agent CLI
# flags so the Helm chart can drive the process declaratively, then execs
# the agent as PID 1. Any extra arguments passed to the container are
# appended verbatim.
#
# The agent's OpenAI-compatible chat API is enabled by Helm via
# BLENDER_AGENT_CHAT_API=1 (which additionally requires BLENDER_AGENT_ENDPOINT
# and BLENDER_AGENT_MODEL). With no external Blender bridge reachable, the
# agent spawns its own headless Blender ($BLENDER_PATH) as the compute surface.
set -euo pipefail

args=(
    --host "${BLENDER_AGENT_HOST:-0.0.0.0}"
    --port "${BLENDER_AGENT_PORT:-10102}"
)

# Fixed ports in a container - never walk up to a different one.
if [ "${BLENDER_AGENT_NO_PORT_AUTO:-1}" = "1" ]; then
    args+=(--no-port-auto)
fi

# Optionally co-host the tools over streamable-HTTP MCP.
if [ -n "${BLENDER_AGENT_MCP_PORT:-}" ]; then
    args+=(--mcp-port "${BLENDER_AGENT_MCP_PORT}")
fi

# Explicit data dir override (otherwise $XDG_DATA_HOME/blender-agent).
if [ -n "${BLENDER_AGENT_DATA_DIR:-}" ]; then
    args+=(--data-dir "${BLENDER_AGENT_DATA_DIR}")
fi

exec blender-agent "${args[@]}" "$@"
