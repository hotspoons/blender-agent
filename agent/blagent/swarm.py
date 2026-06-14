# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Swarm: real-subprocess worker instances for autonomy mode (Phase 4).

The orchestrator fans objectives out to worker agents, each a full
blender-agent SUBPROCESS on its own ports with its OWN headless Blender,
driven agent-to-agent over the worker's OpenAI-compatible
``/v1/chat/completions`` endpoint (``chat_api``). Workers export their
component ``.blend`` into a shared exchange dir; a gather agent merges them.

This module owns process/port lifecycle:
  - ``PortAllocator`` — race-safe distinct free ports per worker.
  - ``WorkerInstance`` — spawn / wait-ready / stop one worker subprocess.

``RemoteWorkerStrategy`` (the drop-in ``worker_runner`` that POSTs tasks to a
worker's endpoint) builds on these; it lands alongside the gather step.

Requirements in the worker's environment: the ``mcp`` add-on installed +
enabled, and Blender 5.x reachable (``BlenderSurface`` spawns it with
``--online-mode``). The worker is pointed at a remote LLM via
``BLENDER_AGENT_ENDPOINT`` / ``BLENDER_AGENT_MODEL``.
"""

__all__ = (
    "PortAllocator",
    "WorkerInstance",
    "RemoteWorkerStrategy",
)

import asyncio
import contextlib
import glob
import json
import logging
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Awaitable, Callable

_log = logging.getLogger("blagent.swarm")


def _safe(name: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "_", name.lower()).strip("_") or "x"


class PortAllocator:
    """
    Hand out distinct, currently-free TCP ports — race-safe. Each allocated
    port is held BOUND (SO_REUSEADDR) until ``release``, so concurrent
    allocations can never pick the same port before a worker binds it.
    Release a port immediately before launching the worker that takes it.
    """

    def __init__(self, host: str = "localhost") -> None:
        self._host = host
        self._held: "dict[int, socket.socket]" = {}

    def allocate(self) -> int:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self._host, 0))
        port = int(sock.getsockname()[1])
        self._held[port] = sock
        return port

    def release(self, port: int) -> None:
        sock = self._held.pop(port, None)
        if sock is not None:
            with contextlib.suppress(OSError):
                sock.close()

    def release_all(self) -> None:
        for port in list(self._held):
            self.release(port)


class WorkerInstance:
    """
    One worker blender-agent subprocess: a chat-API server on ``api_port``
    with its own headless Blender on ``bridge_port`` and its own data/media
    jail under ``data_dir``. Pointed at a remote LLM (``endpoint``/``model``).
    """

    def __init__(
            self,
            *,
            worker_id: str,
            api_port: int,
            bridge_port: int,
            data_dir: str,
            endpoint: str,
            model: str,
            host: str = "localhost",
            api_key: str = "",
            python: "str | None" = None,
            extra_env: "dict[str, str] | None" = None,
    ) -> None:
        self.worker_id = worker_id
        self.api_port = api_port
        self.bridge_port = bridge_port
        self.host = host
        self._data_dir = data_dir
        self._endpoint = endpoint
        self._model = model
        self._api_key = api_key
        self._python = python or sys.executable
        self._extra_env = dict(extra_env or {})
        self.proc: "subprocess.Popen[bytes] | None" = None
        self._log_path = os.path.join(data_dir, "worker.log")

    @property
    def base_url(self) -> str:
        return "http://{:s}:{:d}/v1".format(self.host, self.api_port)

    def start(self, allocator: "PortAllocator | None" = None) -> None:
        """
        Launch the worker subprocess. If *allocator* is given, its hold on
        this worker's ports is released right before the child binds them.
        """
        os.makedirs(self._data_dir, exist_ok=True)
        env = dict(os.environ)
        env["BLENDER_AGENT_CHAT_API"] = "1"
        env["BLENDER_AGENT_ENDPOINT"] = self._endpoint
        env["BLENDER_AGENT_MODEL"] = self._model
        # Pin the bridge port so the spawned Blender lands exactly here.
        env["BLENDER_MCP_PORT"] = str(self.bridge_port)
        if self._api_key:
            env["BLENDER_AGENT_CHAT_API_KEY"] = self._api_key
        env.update(self._extra_env)
        argv = [
            self._python, "-m", "blagent",
            "--host", self.host,
            "--port", str(self.api_port),
            "--spawn-blender",
            "--bridge-port", str(self.bridge_port),
            "--data-dir", self._data_dir,
        ]
        if allocator is not None:
            allocator.release(self.api_port)
            allocator.release(self.bridge_port)
        _log.info("spawning worker %s: api=%d bridge=%d", self.worker_id, self.api_port, self.bridge_port)
        log_fh = open(self._log_path, "wb")  # pylint: disable=consider-using-with
        # Own session/process-group so stop() can reap the whole tree (the
        # agent AND the headless Blender it spawns) — no orphaned Blenders.
        self.proc = subprocess.Popen(  # pylint: disable=consider-using-with
            argv, env=env, stdout=log_fh, stderr=subprocess.STDOUT,
            start_new_session=True)

    async def wait_ready(self, timeout: float = 150.0, poll: float = 1.0) -> bool:
        """
        Poll the worker's ``/v1/models`` until it answers (the chat API is up
        and its Blender bridge has come online). False if it dies or times out.
        """
        deadline = time.monotonic() + timeout
        url = self.base_url + "/models"
        while time.monotonic() < deadline:
            if self.proc is not None and self.proc.poll() is not None:
                _log.warning("worker %s exited early (rc=%s); see %s",
                             self.worker_id, self.proc.returncode, self._log_path)
                return False
            if await asyncio.to_thread(self._probe, url):
                return True
            await asyncio.sleep(poll)
        return False

    def _probe(self, url: str) -> bool:
        req = urllib.request.Request(url)
        if self._api_key:
            req.add_header("Authorization", "Bearer " + self._api_key)
        try:
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                return bool(200 <= int(resp.status) < 300)
        except (urllib.error.URLError, OSError, ValueError):
            return False

    def stop(self, timeout: float = 20.0) -> None:
        proc = self.proc
        if proc is None or proc.poll() is not None:
            return
        # Reap the whole process group (agent + its headless Blender), so the
        # spawned Blender can't be orphaned. Falls back to the bare process
        # where process groups aren't available (e.g. Windows).
        pgid = None
        try:
            pgid = os.getpgid(proc.pid)
        except (AttributeError, OSError):
            pgid = None
        try:
            if pgid is not None:
                os.killpg(pgid, signal.SIGTERM)
            else:
                proc.terminate()
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(Exception):
                if pgid is not None:
                    os.killpg(pgid, signal.SIGKILL)
                else:
                    proc.kill()
                proc.wait(timeout=5.0)
        except Exception:  # pylint: disable=broad-except
            with contextlib.suppress(Exception):
                proc.kill()

    def tail_log(self, n: int = 2000) -> str:
        try:
            with open(self._log_path, "rb") as fh:
                return fh.read()[-n:].decode("utf-8", "replace")
        except OSError:
            return ""


_WORKER_TASK_TEMPLATE = (
    "{instruction}\n\n"
    "This is ONE component of a larger assembly being built in parallel by other "
    "agents. FIRST start from a clean scene — delete the default Camera, Cube and "
    "Light so only your component remains. Work only on your component. When "
    "finished, export the whole scene as a Blender file with the media_io tool "
    "(export, format 'blend', filename '{component}.blend') so it can be merged "
    "into the master scene. Then end with a short PROOF OF WORK: the objects you "
    "created, with counts."
)


class RemoteWorkerStrategy:
    """
    Swarm worker_runner: for each task, spawn a real worker subprocess (its own
    headless Blender + chat API), drive it over its OpenAI endpoint to build a
    component and export a ``.blend``, copy that ``.blend`` into the shared
    exchange dir, and return the proof + artifact. Drop-in for
    ``AutonomyOrchestrator``'s ``worker_runner``; pair with ``ParallelScheduler``.
    """

    def __init__(
            self,
            *,
            endpoint: str,
            model: str,
            exchange_dir: str,
            allocator: "PortAllocator | None" = None,
            host: str = "localhost",
            api_key: str = "",
            ready_timeout: float = 180.0,
            task_timeout: float = 900.0,
            emit: "Callable[[dict[str, Any]], Awaitable[None]] | None" = None,
            session_id: str = "",
            register_stop: "Callable[[str, Callable[[], None]], None] | None" = None,
            unregister_stop: "Callable[[str], None] | None" = None,
    ) -> None:
        self._endpoint = endpoint
        self._model = model
        self._exchange_dir = exchange_dir
        self._allocator = allocator or PortAllocator(host)
        self._host = host
        self._api_key = api_key
        self._ready_timeout = ready_timeout
        self._task_timeout = task_timeout
        self._emit = emit
        # Parent (orchestrator) session id: streamed worker events are tagged
        # with it so the UI files them under the matching bounded agent card.
        self._session_id = session_id
        self._register_stop = register_stop
        self._unregister_stop = unregister_stop
        os.makedirs(exchange_dir, exist_ok=True)

    def _agent_id(self, task_id: str) -> str:
        # Mirror AutonomyOrchestrator._run_one_worker so streamed events land
        # on the same card the orchestrator opened with agent_spawned.
        return "{:s}:w:{:s}".format(self._session_id, task_id)

    async def _emit_worker(self, agent_id: str, event: dict[str, Any]) -> None:
        """Tag an event as belonging to *agent_id*'s worker card and emit it."""
        if self._emit is None:
            return
        await self._emit({
            **event,
            "session_id": agent_id,
            "parent_session_id": self._session_id,
            "role": event.get("role", "worker"),
        })

    def _build_prompt(self, task: Any, component: str) -> str:
        prompt = _WORKER_TASK_TEMPLATE.format(instruction=task.instruction, component=component)
        if getattr(task, "context", ""):
            prompt = "Orchestrator context:\n{:s}\n\n{:s}".format(task.context, prompt)
        return prompt

    def _collect_blend(self, worker_dir: str, component: str) -> "str | None":
        """Find the worker's exported .blend under its jail; copy to exchange."""
        cands = glob.glob(os.path.join(worker_dir, "**", "*.blend"), recursive=True)
        if not cands:
            return None
        newest = max(cands, key=os.path.getmtime)
        dest = os.path.join(self._exchange_dir, "{:s}.blend".format(component))
        shutil.copy2(newest, dest)
        return dest

    # OpenAI tool-call status (chat_api) -> the runtime's tool_status states,
    # so streamed swarm activity matches what in-process workers emit.
    _STATUS_TO_STATE = {"running": "running", "done": "ok", "error": "error"}

    async def _chat(self, base_url: str, prompt: str, user: str,
                    agent_id: "str | None" = None,
                    cancel: "asyncio.Event | None" = None) -> str:
        """
        Drive a worker over its OpenAI endpoint and return its final text.

        When *agent_id* is given and an emit sink is configured, stream the
        response (SSE) and translate each delta into ``token`` / ``tool_status``
        events tagged for that worker's card — so the user sees the worker's
        tool calls and prose live, not just the final proof. *cancel* breaks
        the stream early (the caller also kills the subprocess).
        """
        import httpx  # pylint: disable=import-error

        headers = {"Authorization": "Bearer " + self._api_key} if self._api_key else {}
        stream = agent_id is not None and self._emit is not None
        body = {
            "model": "blender-agent",
            "messages": [{"role": "user", "content": prompt}],
            "user": user,
            "stream": stream,
        }
        if not stream:
            async with httpx.AsyncClient(timeout=self._task_timeout) as client:
                resp = await client.post(base_url + "/chat/completions", json=body, headers=headers)
                resp.raise_for_status()
                data = resp.json()
            message = (data.get("choices") or [{}])[0].get("message") or {}
            return str(message.get("content") or "")

        assert agent_id is not None
        text_parts: list[str] = []
        async with httpx.AsyncClient(timeout=self._task_timeout) as client:
            async with client.stream(
                    "POST", base_url + "/chat/completions",
                    json=body, headers=headers) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if cancel is not None and cancel.is_set():
                        break
                    if not line.startswith("data: "):
                        continue
                    payload = line[len("data: "):].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                    except ValueError:
                        continue
                    delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
                    await self._stream_delta(agent_id, delta, text_parts)
        return "".join(text_parts)

    async def _stream_delta(self, agent_id: str, delta: dict[str, Any],
                            text_parts: list[str]) -> None:
        """Translate one OpenAI delta into worker-card events."""
        content = delta.get("content")
        if content:
            text_parts.append(str(content))
            await self._emit_worker(agent_id, {"type": "token", "text": str(content)})
        for call in delta.get("blender_tool_calls") or ():
            state = self._STATUS_TO_STATE.get(str(call.get("status")), "error")
            await self._emit_worker(agent_id, {
                "type": "tool_status",
                "call_id": str(call.get("call_id", "")),
                "name": str(call.get("name", "")),
                "arguments": call.get("args_json", ""),
                "state": state,
                "summary": call.get("summary", ""),
            })
        for media in delta.get("blender_media") or ():
            data_url = media.get("data_url")
            if data_url:
                await self._emit_worker(agent_id, {
                    "type": "worker_media",
                    "media_id": str(media.get("id", "")),
                    "data_url": str(data_url),
                })

    def list_components(self) -> "list[str]":
        """Component .blend files produced by workers, in the exchange dir."""
        return sorted(glob.glob(os.path.join(self._exchange_dir, "component_*.blend")))

    async def gather(self, components: "list[str] | None" = None,
                     master: str = "master") -> "str | None":
        """
        Spawn the final GATHER worker: it appends every component .blend's
        objects into one scene and exports ``<master>.blend`` to the exchange
        dir. Returns the master path, or None if nothing to gather / it failed.
        """
        components = components if components is not None else self.list_components()
        if not components:
            return None
        api_port = self._allocator.allocate()
        bridge_port = self._allocator.allocate()
        worker_dir = os.path.join(self._exchange_dir, "gather")
        worker = WorkerInstance(
            worker_id="gather", api_port=api_port, bridge_port=bridge_port,
            data_dir=worker_dir, endpoint=self._endpoint, model=self._model,
            host=self._host, api_key=self._api_key)
        worker.start(allocator=self._allocator)
        try:
            if not await worker.wait_ready(self._ready_timeout):
                _log.warning("gather worker failed to start:\n%s", worker.tail_log(800))
                return None
            files = "\n".join("- {:s}".format(c) for c in components)
            prompt = (
                "You are the GATHER agent for a parallel assembly. Start from a clean "
                "empty scene (delete the default Camera, Cube and Light). Merge these "
                "component Blender files into that ONE scene: for each file, append "
                "its real objects (use bpy, e.g. bpy.ops.wm.append from each file's "
                "Object directory), but SKIP each component's leftover default Camera, "
                "Cube and Light so they don't pile up as duplicates. Then export the "
                "merged scene as a Blender file via the media_io tool (export, format "
                "'blend', filename '{master}.blend'). Component files (absolute paths "
                "on this machine):\n{files}\n\n"
                "End with a PROOF OF WORK: the total object count in the merged scene."
            ).format(master=master, files=files)
            gather_id = "{:s}:gather".format(self._session_id)
            if self._emit is not None:
                await self._emit({
                    "type": "agent_spawned", "session_id": self._session_id,
                    "agent_id": gather_id, "role": "gather",
                    "task": "merge {:d} components".format(len(components))})
            try:
                proof = await self._chat(worker.base_url, prompt, user="gather",
                                         agent_id=gather_id)
            except Exception as ex:  # pylint: disable=broad-except
                _log.warning("gather chat failed: %s", ex)
                return None
            master_path = self._collect_blend(worker_dir, master)
            if self._emit is not None:
                await self._emit({
                    "type": "agent_done", "session_id": self._session_id,
                    "agent_id": gather_id, "role": "gather",
                    "ok": master_path is not None,
                    "proof": proof, "master": master_path})
            return master_path
        finally:
            worker.stop()

    async def __call__(self, task: Any) -> Any:
        from .autonomy import WorkerResult

        agent_id = self._agent_id(task.id)
        component = "component_{:s}".format(_safe(task.id))
        api_port = self._allocator.allocate()
        bridge_port = self._allocator.allocate()
        worker_dir = os.path.join(self._exchange_dir, "worker_{:s}".format(_safe(task.id)))
        worker = WorkerInstance(
            worker_id=task.id, api_port=api_port, bridge_port=bridge_port,
            data_dir=worker_dir, endpoint=self._endpoint, model=self._model,
            host=self._host, api_key=self._api_key)
        # Stop hook: cancel the live stream + kill the subprocess (with its
        # headless Blender). Registered before start so a "lala land" worker
        # can be stopped even while it is still coming up.
        cancel = asyncio.Event()

        def _stop() -> None:
            cancel.set()
            worker.stop()

        if self._register_stop is not None:
            self._register_stop(agent_id, _stop)
        worker.start(allocator=self._allocator)
        try:
            ready = await worker.wait_ready(self._ready_timeout)
            if not ready:
                return WorkerResult(
                    task_id=task.id, objective_id=task.objective_id,
                    proof="worker failed to start:\n" + worker.tail_log(800),
                    ok=False, transcript_ref=worker.base_url)
            prompt = self._build_prompt(task, component)
            try:
                proof = await self._chat(worker.base_url, prompt, user=task.id,
                                         agent_id=agent_id, cancel=cancel)
            except Exception as ex:  # pylint: disable=broad-except
                if cancel.is_set():
                    return WorkerResult(
                        task_id=task.id, objective_id=task.objective_id,
                        proof="worker stopped by user", ok=False,
                        transcript_ref=worker.base_url)
                _log.warning("worker %s chat failed: %s", task.id, ex)
                return WorkerResult(
                    task_id=task.id, objective_id=task.objective_id,
                    proof="worker chat failed: {:s}".format(ex), ok=False,
                    transcript_ref=worker.base_url)
            if cancel.is_set():
                return WorkerResult(
                    task_id=task.id, objective_id=task.objective_id,
                    proof="worker stopped by user", ok=False,
                    transcript_ref=worker.base_url)
            artifact = self._collect_blend(worker_dir, component)
            artifacts = [artifact] if artifact else []
            return WorkerResult(
                task_id=task.id, objective_id=task.objective_id,
                proof=proof or "(worker produced no report)",
                ok=bool(proof) and artifact is not None,
                transcript_ref=worker.base_url, artifacts=artifacts)
        finally:
            worker.stop()
            if self._unregister_stop is not None:
                self._unregister_stop(agent_id)
