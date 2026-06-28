# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Blender swarm: the Blender-specific worker strategy.

Subclasses the domain-agnostic ``agentcore.swarm.RemoteWorkerStrategy``,
supplying only the Blender bits: how to launch a worker (a ``blagent``
subprocess that spawns its OWN headless Blender), what an artifact is (a
real ``.blend`` file), the export/merge prompts, and the OpenAI chat
field names that ``blagent.chat_api`` uses (``blender_tool_calls`` /
``blender_media``). The lifecycle, SSE streaming and gather
orchestration all live in the base class.

Requirements in the worker's environment: the ``mcp`` add-on installed +
enabled, and Blender 5.x reachable (``BlenderSurface`` spawns it with
``--online-mode``). The worker is pointed at a remote LLM via
``BLENDER_AGENT_ENDPOINT`` / ``BLENDER_AGENT_MODEL``.
"""

__all__ = (
    "BlenderSwarmProvider",
    "BlenderWorkerStrategy",
    "PortAllocator",
    "RemoteWorkerStrategy",
    "WorkerInstance",
    "blender_worker",
)

import asyncio
import glob
import os
import sys

from typing import Any, Awaitable, Callable

# A real .blend (even an empty scene) is comfortably larger than this; a file
# below it is almost certainly a failed/partial export, surfaced as suspect.
_MIN_BLEND_BYTES = 1024

from agentcore.swarm import (
    PortAllocator,
    RemoteWorkerStrategy,
    WorkerInstance,
    _DATA_URL_MD_RE,  # noqa: F401  (re-exported for tests / callers)
)


def _is_blend(path: str) -> bool:
    """True if *path* looks like a real Blender file (uncompressed 'BLENDER'
    magic, or a gzip/zstd-compressed .blend) rather than a truncated stub."""
    try:
        if os.path.getsize(path) < 1024:
            return False
        with open(path, "rb") as fh:
            head = fh.read(8)
    except OSError:
        return False
    return (head[:7] == b"BLENDER"          # uncompressed
            or head[:2] == b"\x1f\x8b"        # gzip-compressed
            or head[:4] == b"\x28\xb5\x2f\xfd")  # zstd-compressed (Blender 3+)


_WORKER_TASK_TEMPLATE = (
    "You are an autonomous worker sub-agent. There is NO user to ask — do not "
    "ask clarifying questions or offer options; make the most reasonable "
    "interpretation, act, verify, and report.\n\n"
    "## YOUR TASK\n{instruction}\n\n"
    "## OBJECTIVE THIS SERVES\n{goal}\n\n"
    "## DONE WHEN\n{acceptance}\n\n"
    "This is ONE component of a larger assembly being built in parallel by other "
    "agents. FIRST start from a clean scene — delete the default Camera, Cube and "
    "Light so only your component remains. Work only on your component. Before any "
    "heavy or crash-prone operation (large boolean/remesh/voxel ops, high "
    "subdivision or applying modifiers on dense meshes, big imports, physics/"
    "particle bakes), first snapshot with media_io (export, format 'blend') so a "
    "Blender hang or crash doesn't lose prior work. When "
    "finished, export the whole scene as a Blender file with the media_io tool "
    "(export, format 'blend', filename '{component}') so it can be merged "
    "into the master scene. Then end with a short PROOF OF WORK: the objects you "
    "created, with counts.\n\n"
    "NOTE: your Blender runs HEADLESS (no GUI) — viewport screenshot tools do "
    "not work here. To show your work visually, RENDER an image (media_io with "
    "verb 'render', or capture with verb 'render'), don't try to screenshot. The "
    "render tool AUTO-FRAMES the scene, so you do NOT need to add a camera or "
    "lights — don't, they'd just clutter your component."
)


def blender_worker(
        *,
        worker_id: str,
        api_port: int,
        bridge_port: int,
        data_dir: str,
        endpoint: str,
        model: str,
        host: str = "localhost",
        api_key: str = "",
) -> WorkerInstance:
    """
    Build a Blender worker: a ``blagent`` subprocess that serves the chat API
    on *api_port* and spawns its own headless Blender on *bridge_port*.
    """
    env = {
        "BLENDER_AGENT_CHAT_API": "1",
        "BLENDER_AGENT_ENDPOINT": endpoint,
        "BLENDER_AGENT_MODEL": model,
        # Run as the "worker" RBAC role: a leaf executor with no set_autonomy /
        # ask_user (it has no user and no authority over its own autonomy).
        "BLENDER_AGENT_ROLE": "worker",
        # Pin the bridge port so the spawned Blender lands exactly here.
        "BLENDER_MCP_PORT": str(bridge_port),
    }
    if api_key:
        env["BLENDER_AGENT_CHAT_API_KEY"] = api_key
    command = [
        sys.executable, "-m", "blagent",
        "--host", host,
        "--port", str(api_port),
        "--spawn-blender",
        "--bridge-port", str(bridge_port),
        "--data-dir", data_dir,
    ]
    return WorkerInstance(
        worker_id=worker_id, api_port=api_port, data_dir=data_dir,
        command=command, env=env, host=host, api_key=api_key,
        release_ports=(api_port, bridge_port))


class BlenderWorkerStrategy(RemoteWorkerStrategy):
    """``RemoteWorkerStrategy`` specialised for Blender: components are real
    ``.blend`` files, workers spawn headless Blender, prompts demand a
    ``.blend`` export and merge via ``bpy``."""

    # blagent.chat_api emits tool calls / media under these keys; the worker
    # serves the "blender-agent" model.
    _TOOL_CALLS_KEY = "blender_tool_calls"
    _MEDIA_KEY = "blender_media"
    _CHAT_MODEL = "blender-agent"

    _ARTIFACT_EXT = ".blend"
    _ARTIFACT_SOURCE_GLOB = "**/*.blend"
    _COMPONENT_GLOB = "component_*.blend"

    def _make_worker(self, worker_id: str, api_port: int, data_dir: str) -> WorkerInstance:
        bridge_port = self._allocator.allocate()
        return blender_worker(
            worker_id=worker_id, api_port=api_port, bridge_port=bridge_port,
            data_dir=data_dir, endpoint=self._endpoint, model=self._model,
            host=self._host, api_key=self._api_key)

    def _is_artifact(self, path: str) -> bool:
        return _is_blend(path)

    def _build_prompt(self, task: object, component: str) -> str:
        prompt = _WORKER_TASK_TEMPLATE.format(
            instruction=getattr(task, "instruction", ""),
            component=component + self._ARTIFACT_EXT,
            goal=getattr(task, "goal", "") or "(not specified)",
            acceptance=getattr(task, "acceptance", "") or "the task is accomplished and verifiable")
        if getattr(task, "context", ""):
            prompt = "Orchestrator context:\n{:s}\n\n{:s}".format(task.context, prompt)  # type: ignore[attr-defined]
        return self._with_welcome(prompt)

    def _gather_prompt(self, components: "list[str]", master: str) -> str:
        files = "\n".join("- {:s}".format(c) for c in components)
        return self._with_welcome((
            "You are the GATHER agent for a parallel assembly. Start from a clean "
            "empty scene (delete the default Camera, Cube and Light). Merge these "
            "component Blender files into that ONE scene: for each file, append "
            "ONLY its MESH objects (use bpy, e.g. bpy.ops.wm.append from each "
            "file's Object directory) — SKIP any cameras, lights and empties, "
            "which are per-component render scaffolding, not part of the assembly. "
            "DEDUPLICATE by object name: components may overlap (e.g. an "
            "integration component re-exports parts another component already "
            "owns). Append each uniquely-named object only ONCE — if an object's "
            "base name already exists in the scene, SKIP it. The result must NOT "
            "contain duplicate parts (no 'Body' AND 'Body.001'). "
            "Then export the merged scene as a Blender file via the media_io tool "
            "(export, format 'blend', filename '{master}.blend'). Component files "
            "(absolute paths on this machine):\n{files}\n\n"
            "End with a PROOF OF WORK: the total object count and the object names "
            "in the merged scene (confirm no '.001' duplicates remain)."
        ).format(master=master, files=files))


class BlenderSwarmProvider:
    """
    The Blender build's swarm surface, injected onto ``AgentRuntime`` (which
    is otherwise swarm-surface-agnostic). Supplies the worker strategy plus
    the ground-truth probe that reads the component ``.blend`` files workers
    write — the orchestrator has no Blender of its own in swarm mode.
    """

    def make_strategy(self, **kwargs: Any) -> BlenderWorkerStrategy:
        return BlenderWorkerStrategy(**kwargs)

    def preflight(self) -> "tuple[bool, str]":
        """Whether the host can run a Blender swarm, + a requirements report."""
        from .blender_surface import swarm_preflight
        return swarm_preflight()

    async def read_result_objects(self, path: str) -> "list[str]":
        """Open a .blend headless and return its object names (best-effort)."""
        blender = os.environ.get("BLENDER_PATH", "blender")
        try:
            proc = await asyncio.create_subprocess_exec(
                blender, "-b", "--online-mode", path, "--python-expr",
                "import bpy;print('OBJ:'+'|'.join(sorted(o.name for o in bpy.data.objects)))",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
        except Exception:  # pylint: disable=broad-except
            return []
        for line in out.decode("utf-8", "replace").splitlines():
            if line.startswith("OBJ:"):
                return [x for x in line[4:].split("|") if x]
        return []

    def make_probe(self, exchange_dir: str) -> "Callable[[], Awaitable[str]]":
        """
        Ground truth for the evaluator in swarm mode: read the object lists of
        the component .blend files workers have written to the exchange dir.
        """
        async def probe() -> str:
            comps = sorted(glob.glob(os.path.join(exchange_dir, "component_*.blend")))
            if not comps:
                return "(no component .blend files produced yet)"
            lines = ["Components produced so far (objects per file):"]
            total = 0
            for path in comps:
                size = os.path.getsize(path) if os.path.isfile(path) else 0
                objs = await self.read_result_objects(path)
                total += len(objs)
                if not os.path.isfile(path):
                    detail = "(missing on disk)"
                elif size < _MIN_BLEND_BYTES:
                    detail = "(suspect: only {:d} bytes — export may have failed)".format(size)
                elif objs:
                    detail = "{:d} object(s): {:s}".format(len(objs), ", ".join(objs))
                else:
                    detail = "0 objects (empty or unreadable scene)"
                lines.append("- {:s} [{:d} B]: {:s}".format(
                    os.path.basename(path), size, detail))
            lines.append("Total: {:d} component file(s), {:d} object(s) across them.".format(
                len(comps), total))
            return "\n".join(lines)

        return probe
