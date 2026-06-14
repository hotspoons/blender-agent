# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
``AgentProfile`` — the domain *flavor* of an agent, separate from its
*capabilities* (which live behind the ``ToolBackend``). It absorbs the
"string" coupling: the brand/copy the UI shows, the chat-API extension
field prefix, the domain noun, and prompt overrides. Core ships neutral
defaults; a build (or a YAML file) overrides them. The Blender build is
just ``blender_profile()``.

The UI block (``as_ui_public``) is JSON shaped exactly like the web
``core/profile.js`` default, so the server can push branding to the
frontend over the control socket (YAML → server → ``applyProfile``).
Visual assets that can't cross JSON (the logo mark, registered media
viewers) stay in the web extension module; text + an optional favicon
data-URL travel here.
"""

__all__ = (
    "AgentProfile",
    "blender_profile",
)

import dataclasses
from typing import Any


@dataclasses.dataclass
class AgentProfile:
    # Domain noun woven into neutral prompts ("the scene", "the project"…).
    noun: str = "workspace"
    # chat-API extension field prefix; "blender" keeps blender_tool_calls /
    # blender_media for back-compat. Neutral builds use "agent".
    chat_field_prefix: str = "agent"

    # --- UI block (mirrors web/core/profile.js defaults) ------------------
    title: str = "Agent"
    brand_word: str = "Agent"
    brand_rest: str = ""
    welcome_word: str = "Agent"
    welcome_rest: str = ""
    welcome_body: str = "Connected. Ask for anything and I'll get to work."
    welcome_hint: str = ""
    composer_placeholder: str = "Ask the agent…"
    swarm_blurb: str = "Parallel workers, each running its own instance, merged at the end."
    favicon: str = ""        # optional data: URL; empty → web extension supplies it

    # --- prompt overrides (None → core/neutral default) -------------------
    # Threaded incrementally; carried here so a YAML build can override them.
    prompts: dict[str, str] = dataclasses.field(default_factory=dict)

    def prompt(self, key: str, default: str) -> str:
        """An override for *key* if the profile defines one, else *default*."""
        return self.prompts.get(key) or default

    def as_ui_public(self) -> dict[str, Any]:
        """The JSON the web ``applyProfile`` consumes (see core/profile.js)."""
        block: dict[str, Any] = {
            "title": self.title,
            "brand": {"word": self.brand_word, "rest": self.brand_rest},
            "welcome": {
                "word": self.welcome_word, "rest": self.welcome_rest,
                "body": self.welcome_body, "hint": self.welcome_hint,
            },
            "composerPlaceholder": self.composer_placeholder,
            "swarmBlurb": self.swarm_blurb,
        }
        if self.favicon:
            block["favicon"] = self.favicon
        return block


def blender_profile() -> AgentProfile:
    """The Blender build's profile (the default until a YAML build overrides)."""
    return AgentProfile(
        noun="scene",
        chat_field_prefix="blender",
        title="Blender Agent",
        brand_word="Blender",
        brand_rest=" Agent",
        welcome_word="Blender",
        welcome_rest=" Agent",
        welcome_body="Connected to your Blender session through the MCP tool surface.",
        welcome_hint='Try: "what\'s in my scene?" or "make the selected mesh manifold".',
        composer_placeholder="Ask the Blender agent…",
        swarm_blurb="Parallel workers, each its own headless Blender, merged at the end.",
    )
