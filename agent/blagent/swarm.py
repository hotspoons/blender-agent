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
)

import asyncio
import contextlib
import logging
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

_log = logging.getLogger("blagent.swarm")


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
        self.proc = subprocess.Popen(  # pylint: disable=consider-using-with
            argv, env=env, stdout=log_fh, stderr=subprocess.STDOUT)

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
        proc.terminate()
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            with contextlib.suppress(Exception):
                proc.wait(timeout=5.0)

    def tail_log(self, n: int = 2000) -> str:
        try:
            with open(self._log_path, "rb") as fh:
                return fh.read()[-n:].decode("utf-8", "replace")
        except OSError:
            return ""
