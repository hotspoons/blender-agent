# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Blender build's web wiring: compose the generic agentcore app with the
Blender web overlay (extension, branding, STL viewer) and the optional
OpenAI-compatible chat facade.
"""

__all__ = (
    "create_app",
    "web_roots",
)

import os

from agentcore.app import DEFAULT_WEB_ROOT, create_app as _create_app
from agentcore.runtime import AgentRuntime
from starlette.applications import Starlette

_BLENDER_WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


def web_roots() -> list[str]:
    """Static search path: the Blender overlay first, generic shell behind."""
    return [_BLENDER_WEB, DEFAULT_WEB_ROOT]


def create_app(runtime: AgentRuntime) -> Starlette:
    """
    Build the Blender agent ASGI app.

    Adds the OpenAI-compatible chat front end when ``BLENDER_AGENT_CHAT_API``
    is set (raises at startup when its required remote-LLM env vars are
    missing).
    """
    from . import chat_api

    extra_routes = None
    if chat_api.enabled():
        chat_api.configure(runtime)
        extra_routes = chat_api.routes(runtime)
    return _create_app(runtime, web_roots=web_roots(), extra_routes=extra_routes)
