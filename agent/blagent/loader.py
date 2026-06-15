# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
``load_agent(agent.yaml)`` — build a fully-wired ``AgentRuntime`` from one
YAML file: the UI/prompt profile, the LLM endpoint, the autonomy knobs, the
tool RBAC matrix, and the domain backend (an in-process Python factory or, in
future, an HTTP base_url). This is the configuration seam that lets a different
agent be assembled without forking the core — see docs/AGENT_CORE.md.

The Blender build reduces to a ``make_backend()`` factory + an ``agent.yaml``.
"""

__all__ = ("load_agent", "load_agent_config")

import importlib
import inspect
import os
from typing import Any

from agentcore.backend import PythonToolBackend, ToolBackend
from .permissions import ToolPermissions
from .profile import AgentProfile
from .runtime import AgentRuntime
from .store import AgentStore


def load_agent_config(path: str) -> dict[str, Any]:
    import yaml
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError("agent config must be a YAML mapping")
    return data


def _profile_from_yaml(block: dict[str, Any]) -> AgentProfile:
    ui = block.get("ui") or {}
    welcome = ui.get("welcome") or {}
    prompts = block.get("prompts") or {}
    # Accept either {"brand": {"word","rest"}} or flat strings.
    brand = ui.get("brand") or {}
    if isinstance(brand, str):
        brand = {"word": brand, "rest": ""}
    return AgentProfile(
        noun=str(block.get("noun", "workspace")),
        chat_field_prefix=str(block.get("chat_field_prefix", "agent")),
        title=str(ui.get("title", block.get("name", "Agent"))),
        brand_word=str(brand.get("word", "Agent")),
        brand_rest=str(brand.get("rest", "")),
        welcome_word=str(welcome.get("word", brand.get("word", "Agent"))),
        welcome_rest=str(welcome.get("rest", brand.get("rest", ""))),
        welcome_body=str(welcome.get("body", "Connected.")),
        welcome_hint=str(welcome.get("hint", "")),
        composer_placeholder=str(ui.get("composer_placeholder", "Ask the agent…")),
        swarm_blurb=str(ui.get("swarm_blurb",
                              "Parallel workers, each running its own instance, merged at the end.")),
        favicon=str(ui.get("favicon", "")),
        prompts={k: str(v) for k, v in prompts.items() if v},
    )


def _apply_llm_config(store: AgentStore, block: dict[str, Any]) -> None:
    if block.get("endpoint"):
        store.config.endpoint = str(block["endpoint"])
        store.config.use_local_llm = False
    if block.get("model"):
        store.config.model = str(block["model"])
    # Secrets come from the environment, never inlined in YAML.
    if block.get("api_key_env"):
        store.config.api_key = os.environ.get(str(block["api_key_env"]), "")
    if "use_local_llm" in block:
        store.config.use_local_llm = bool(block["use_local_llm"])


def _apply_autonomy_config(store: AgentStore, block: dict[str, Any]) -> None:
    mapping = {
        "policy": "autonomy_policy", "max_rounds": "max_autonomy_rounds",
        "audit": "autonomy_audit", "qa": "autonomy_qa", "workers": "autonomy_workers",
        "share_context": "autonomy_share_context", "level": "autonomy_level",
    }
    for key, attr in mapping.items():
        if key in block:
            setattr(store.config, attr, block[key])


def _import_callable(ref: str) -> Any:
    """Resolve ``module.path:callable`` (or ``module.path.callable``)."""
    if ":" in ref:
        mod_name, _, attr = ref.partition(":")
    else:
        mod_name, _, attr = ref.rpartition(".")
    if not mod_name or not attr:
        raise ValueError("bad factory reference: {!r}".format(ref))
    module = importlib.import_module(mod_name)
    return getattr(module, attr)


async def _build_backend(block: dict[str, Any]) -> ToolBackend:
    btype = str(block.get("type", "python")).lower()
    if btype == "python":
        factory = _import_callable(str(block.get("factory", "")))
        result = factory(**(block.get("options") or {}))
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, ToolBackend):
            raise TypeError("backend factory must return a ToolBackend, got {!r}".format(type(result)))
        return result
    if btype == "http":
        from agentcore.http_backend import HttpToolBackend  # lands with the HTTP transport
        base_url = str(block.get("base_url", ""))
        api_key = os.environ.get(str(block.get("api_key_env", "")), "")
        return HttpToolBackend(base_url, api_key=api_key)
    raise ValueError("unknown backend type: {!r}".format(btype))


async def load_agent(path: str, *, data_dir: str | None = None) -> AgentRuntime:
    """Build a wired ``AgentRuntime`` from an ``agent.yaml``."""
    cfg = load_agent_config(path)
    profile = _profile_from_yaml(cfg.get("profile") or {})
    store = AgentStore(data_dir=data_dir)
    _apply_llm_config(store, cfg.get("llm") or {})
    _apply_autonomy_config(store, cfg.get("autonomy") or {})
    store.save_config()
    permissions = (ToolPermissions.load(cfg["permissions"])
                   if isinstance(cfg.get("permissions"), str) else ToolPermissions.load())
    backend = await _build_backend(cfg.get("backend") or {})

    # In-process Python backend keeps the full-ToolContext execution path
    # (sync ctor); a generic/HTTP backend routes through the adapter (create()).
    if isinstance(backend, PythonToolBackend):
        return AgentRuntime(store, backend, profile=profile, permissions=permissions)
    return await AgentRuntime.create(store, backend, profile=profile, permissions=permissions)
