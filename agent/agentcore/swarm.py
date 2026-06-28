# SPDX-FileCopyrightText: 2026 agentcore contributors
#
# SPDX-License-Identifier: MIT OR Apache-2.0

"""
Swarm: real-subprocess worker instances for autonomy mode.

The orchestrator fans tasks out to worker agents, each a full agent
SUBPROCESS on its own ports with its OWN compute surface, driven
agent-to-agent over the worker's OpenAI-compatible
``/v1/chat/completions`` endpoint. Workers export an artifact into a
shared exchange dir; a gather agent merges them.

This module is domain-agnostic. It owns process/port lifecycle and the
SSE streaming/gather orchestration:
  - ``PortAllocator`` — race-safe distinct free ports per worker.
  - ``WorkerInstance`` — spawn / wait-ready / stop one worker subprocess,
    launched by an explicit command + env (the domain builds those).
  - ``RemoteWorkerStrategy`` — the drop-in ``worker_runner`` that POSTs
    tasks to a worker's endpoint, streams its activity onto the
    orchestrator's cards, collects its artifact, and gathers the lot.

The Blender-specific bits (how to launch a worker, what an artifact is,
the worker/gather prompts, the chat field names) live in a subclass —
see ``blagent.swarm.BlenderWorkerStrategy``.
"""

__all__ = (
    "PortAllocator",
    "RemoteWorkerStrategy",
    "WorkerInstance",
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
import time
import urllib.error
import urllib.request
from typing import Any, Awaitable, Callable

_log = logging.getLogger("agentcore.swarm")

# Markdown image with an inlined data: URL — chat_api adds these to the
# assistant text so plain clients still receive tool media. We surface media
# as its own event, so these (often huge) blobs are stripped from the prose.
_DATA_URL_MD_RE = re.compile(r"!\[[^\]]*\]\(data:[^)]*\)")


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
    One worker agent subprocess: a chat-API server on ``api_port`` with its
    own data/media jail under ``data_dir``, launched by an explicit
    *command* and *env* overrides (the domain builds those — they encode how
    to spin up a worker for that surface). ``release_ports`` are the
    allocator-held ports handed back to the OS right before the child binds
    them (defaults to the api port).
    """

    def __init__(
            self,
            *,
            worker_id: str,
            api_port: int,
            data_dir: str,
            command: "list[str]",
            env: "dict[str, str] | None" = None,
            host: str = "localhost",
            api_key: str = "",
            release_ports: "tuple[int, ...]" = (),
            log_name: str = "worker.log",
    ) -> None:
        self.worker_id = worker_id
        self.api_port = api_port
        self.host = host
        self._data_dir = data_dir
        self._command = list(command)
        self._env_overrides = dict(env or {})
        self._api_key = api_key
        self._release_ports = tuple(release_ports) or (api_port,)
        self.proc: "subprocess.Popen[bytes] | None" = None
        self._log_path = os.path.join(data_dir, log_name)

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
        env.update(self._env_overrides)
        if allocator is not None:
            for port in self._release_ports:
                allocator.release(port)
        _log.info("spawning worker %s: api=%d", self.worker_id, self.api_port)
        log_fh = open(self._log_path, "wb")  # pylint: disable=consider-using-with
        # Own session/process-group so stop() can reap the whole tree (the
        # agent AND any compute surface it spawns) — no orphaned processes.
        self.proc = subprocess.Popen(  # pylint: disable=consider-using-with
            self._command, env=env, stdout=log_fh, stderr=subprocess.STDOUT,
            start_new_session=True)

    async def wait_ready(self, timeout: float = 150.0, poll: float = 1.0) -> bool:
        """
        Poll the worker's ``/v1/models`` until it answers (the chat API is up
        and its compute surface has come online). False if it dies or times out.
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
        # Reap the whole process group (agent + any compute surface), so a
        # spawned surface can't be orphaned. Falls back to the bare process
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
    "You are an autonomous worker sub-agent. There is NO user to ask — do not "
    "ask clarifying questions or offer options; make the most reasonable "
    "interpretation, act, verify, and report.\n\n"
    "## YOUR TASK\n{instruction}\n\n"
    "## OBJECTIVE THIS SERVES\n{goal}\n\n"
    "## DONE WHEN\n{acceptance}\n\n"
    "This is ONE component of a larger result being built in parallel by other "
    "agents. Work only on your component. When finished, export your component "
    "as an artifact named '{component}' so it can be merged into the final "
    "result. Then end with a short PROOF OF WORK describing what you produced."
)


class RemoteWorkerStrategy:
    """
    Swarm worker_runner: for each task, spawn a real worker subprocess (its own
    chat API + compute surface), drive it over its OpenAI endpoint to build a
    component and export an artifact, copy that artifact into the shared
    exchange dir, and return the proof + artifact. Drop-in for
    ``AutonomyOrchestrator``'s ``worker_runner``; pair with ``ParallelScheduler``.

    Domain-agnostic. A subclass supplies how to launch a worker
    (``_make_worker``) and may override the artifact model and prompts; the
    lifecycle, SSE streaming and gather orchestration are all here.
    """

    # OpenAI tool-call status (chat_api) -> the runtime's tool_status states,
    # so streamed swarm activity matches what in-process workers emit.
    _STATUS_TO_STATE = {"running": "running", "done": "ok", "error": "error"}

    # Delta fields a worker's chat_api uses for tool calls / media, and the
    # model label sent in the request body. A branded build overrides these.
    _TOOL_CALLS_KEY = "tool_calls"
    _MEDIA_KEY = "media"
    _CHAT_MODEL = "agent"

    # How the domain's artifacts look in the exchange dir / worker jail.
    _ARTIFACT_EXT = ""
    _ARTIFACT_SOURCE_GLOB = "**/*"
    _COMPONENT_GLOB = "component_*"

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
            welcome: str = "",
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
        # Pre-fetched welcome block pinned into every worker/gather prompt so the
        # fresh subprocess sessions skip re-calling `welcome` on identical,
        # static content (the parent fetched it once). Empty == self-welcome.
        self._welcome = welcome
        # Parent (orchestrator) session id: streamed worker events are tagged
        # with it so the UI files them under the matching bounded agent card.
        self._session_id = session_id
        self._register_stop = register_stop
        self._unregister_stop = unregister_stop
        os.makedirs(exchange_dir, exist_ok=True)

    # --- domain hooks ------------------------------------------------------
    # A subclass MUST implement _make_worker (how to launch one for its
    # surface); the rest have generic defaults a domain can keep or override.

    def _with_welcome(self, prompt: str) -> str:
        """Pin the pre-fetched welcome block ahead of *prompt* (no-op if empty)."""
        return "{:s}\n\n{:s}".format(self._welcome, prompt) if self._welcome else prompt

    def _make_worker(self, worker_id: str, api_port: int, data_dir: str) -> WorkerInstance:
        """Build (but don't start) a worker subprocess for this surface."""
        raise NotImplementedError("subclass must build the worker launch command")

    def _artifact_name(self, task_id: str) -> str:
        return "component_{:s}".format(_safe(task_id))

    def _build_prompt(self, task: Any, component: str) -> str:
        prompt = _WORKER_TASK_TEMPLATE.format(
            instruction=task.instruction, component=component + self._ARTIFACT_EXT,
            goal=getattr(task, "goal", "") or "(not specified)",
            acceptance=getattr(task, "acceptance", "") or "the task is accomplished and verifiable")
        if getattr(task, "context", ""):
            prompt = "Orchestrator context:\n{:s}\n\n{:s}".format(task.context, prompt)
        return self._with_welcome(prompt)

    def _gather_prompt(self, components: "list[str]", master: str) -> str:
        files = "\n".join("- {:s}".format(c) for c in components)
        return self._with_welcome((
            "You are the GATHER agent for a parallel assembly. Merge these "
            "component artifacts into ONE result, then export it as an artifact "
            "named '{master}'. If the same entity appears in more than one "
            "component, keep it ONCE — the merged result must contain no "
            "duplicates. Component files (absolute paths on this "
            "machine):\n{files}\n\n"
            "End with a PROOF OF WORK describing the merged result."
        ).format(master=master + self._ARTIFACT_EXT, files=files))

    def _is_artifact(self, path: str) -> bool:
        """True if *path* is a complete artifact (not a truncated stub)."""
        try:
            return os.path.getsize(path) > 0
        except OSError:
            return False

    # --- artifact collection ----------------------------------------------

    def _collect_artifact(self, worker_dir: str, component: str) -> "str | None":
        """
        Find the worker's exported artifact under its jail and copy it to the
        exchange dir under ``<component><ext>``. Validates it via
        ``_is_artifact`` so a failed/partial export isn't passed downstream.
        """
        cands = [c for c in glob.glob(os.path.join(worker_dir, self._ARTIFACT_SOURCE_GLOB),
                                      recursive=True)
                 if self._is_artifact(c)]
        if not cands:
            return None
        newest = max(cands, key=os.path.getmtime)
        dest = os.path.join(self._exchange_dir, "{:s}{:s}".format(component, self._ARTIFACT_EXT))
        shutil.copy2(newest, dest)
        return dest

    def list_artifacts(self) -> "list[str]":
        """Component artifacts produced by workers, in the exchange dir."""
        return sorted(glob.glob(os.path.join(self._exchange_dir, self._COMPONENT_GLOB)))

    # --- streaming ---------------------------------------------------------

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
            "model": self._CHAT_MODEL,
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
        # Strip inlined data-URL images from the proof; media is surfaced
        # separately and the raw blobs would bloat the report.
        return _DATA_URL_MD_RE.sub("", "".join(text_parts)).strip()

    async def _stream_delta(self, agent_id: str, delta: dict[str, Any],
                            text_parts: list[str]) -> None:
        """Translate one OpenAI delta into worker-card events."""
        content = delta.get("content")
        if content:
            text_parts.append(str(content))
            # chat_api inlines tool media as a markdown ![](data:...) in the
            # text for plain clients; we surface media as its own event, so
            # strip the (huge) data-URL blobs from the streamed prose.
            shown = _DATA_URL_MD_RE.sub("", str(content))
            if shown:
                await self._emit_worker(agent_id, {"type": "token", "text": shown})
        for call in delta.get(self._TOOL_CALLS_KEY) or ():
            state = self._STATUS_TO_STATE.get(str(call.get("status")), "error")
            await self._emit_worker(agent_id, {
                "type": "tool_status",
                "call_id": str(call.get("call_id", "")),
                "name": str(call.get("name", "")),
                "arguments": call.get("args_json", ""),
                "state": state,
                "summary": call.get("summary", ""),
            })
        for media in delta.get(self._MEDIA_KEY) or ():
            data_url = media.get("data_url")
            if data_url:
                await self._emit_worker(agent_id, {
                    "type": "worker_media",
                    "media_id": str(media.get("id", "")),
                    "data_url": str(data_url),
                })

    # --- run + gather ------------------------------------------------------

    async def gather(self, components: "list[str] | None" = None,
                     master: str = "master") -> "str | None":
        """
        Spawn the final GATHER worker: it merges every component artifact into
        one result and exports ``<master>`` to the exchange dir. Returns the
        master path, or None if nothing to gather / it failed.
        """
        components = components if components is not None else self.list_artifacts()
        if not components:
            return None
        api_port = self._allocator.allocate()
        worker_dir = os.path.join(self._exchange_dir, "gather")
        worker = self._make_worker("gather", api_port, worker_dir)
        worker.start(allocator=self._allocator)
        try:
            if not await worker.wait_ready(self._ready_timeout):
                _log.warning("gather worker failed to start:\n%s", worker.tail_log(800))
                return None
            prompt = self._gather_prompt(components, master)
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
            master_path = self._collect_artifact(worker_dir, master)
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
        from agentcore.autonomy import WorkerResult

        agent_id = self._agent_id(task.id)
        component = self._artifact_name(task.id)
        api_port = self._allocator.allocate()
        worker_dir = os.path.join(self._exchange_dir, "worker_{:s}".format(_safe(task.id)))
        worker = self._make_worker(task.id, api_port, worker_dir)
        # Stop hook: cancel the live stream + kill the subprocess (with its
        # compute surface). Registered before start so a "lala land" worker
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
                    proof="worker chat failed: {:s}".format(str(ex)), ok=False,
                    transcript_ref=worker.base_url)
            if cancel.is_set():
                return WorkerResult(
                    task_id=task.id, objective_id=task.objective_id,
                    proof="worker stopped by user", ok=False,
                    transcript_ref=worker.base_url)
            artifact = self._collect_artifact(worker_dir, component)
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
