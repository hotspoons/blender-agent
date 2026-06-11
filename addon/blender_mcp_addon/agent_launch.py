# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Launch and manage the optional web agent (``blagent``) from the add-on.

Two launch paths, tried in order:

1. **In-process**: when the ``blagent`` package is importable inside
   Blender's Python (installed into Blender's site-packages or bundled
   as extension wheels), the agent server runs on a daemon thread with
   its own asyncio loop. The agent never touches ``bpy`` from that
   thread - its Blender tools marshal through the add-on's TCP bridge,
   which executes on the main thread.

2. **Subprocess**: when a ``blender-agent`` executable is on PATH
   (e.g. a development virtualenv), it is spawned as a child process.

Neither path is required for the core MCP bridge - everything here is
optional and degrades to a helpful error message.
"""

__all__ = (
    "is_available",
    "is_running",
    "launch_kind",
    "running_ports",
    "start",
    "stop",
    "update_title",
)

import importlib.util
import os
import shutil
import socket
import subprocess
import threading

from typing import Any


class _AgentState:
    """
    Module-level handle on the running agent (thread or subprocess).
    """

    thread: threading.Thread | None = None
    loop: Any = None
    task: Any = None
    proc: subprocess.Popen[bytes] | None = None
    # Actual ports in use (after auto-assignment), 0 when stopped.
    port: int = 0
    mcp_port: int = 0
    host: str = "127.0.0.1"


def _pick_free_port(host: str, preferred: int, attempts: int = 20) -> int:
    """
    First bindable port at or above *preferred*. Multiple Blender
    instances each walk up from the defaults to a free slot.
    """
    last_error: OSError | None = None
    for port in range(preferred, preferred + attempts):
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


def running_ports() -> tuple[int, int]:
    """
    Return ``(agent_port, mcp_port)`` actually bound (0 when unused).
    """
    return _AgentState.port, _AgentState.mcp_port


def is_available() -> tuple[bool, str]:
    """
    Return ``(available, how)`` where *how* is ``"in-process"``,
    ``"subprocess"`` or an explanatory message when unavailable.
    """
    if importlib.util.find_spec("blagent") is not None:
        return True, "in-process"
    if shutil.which("blender-agent"):
        return True, "subprocess"
    return False, (
        "The blagent package is not importable and no blender-agent "
        "executable was found on PATH. Install it with: pip install <repo>/agent"
    )


def launch_kind() -> str:
    """
    Return how the agent is currently running: ``"thread"``,
    ``"subprocess"`` or ``""`` when stopped.
    """
    if _AgentState.thread is not None and _AgentState.thread.is_alive():
        return "thread"
    if _AgentState.proc is not None and _AgentState.proc.poll() is None:
        return "subprocess"
    return ""


def is_running() -> bool:
    return launch_kind() != ""


def start(
        host: str,
        port: int,
        mcp_port: int | None,
        bridge_host: str,
        bridge_port: int,
        title: str = "",
) -> str:
    """
    Start the agent server, auto-assigning ports when the preferred
    ones are taken (other Blender instances). *bridge_host*/*bridge_port*
    point the agent's tools at THIS instance's TCP bridge. *title*
    labels the instance in the browser tab (the open .blend file name);
    keep it updated later via ``update_title``.

    Returns the launch kind. Raises ``RuntimeError`` with a user-facing
    message on failure. Actual ports are exposed via ``running_ports``.
    """
    if is_running():
        raise RuntimeError("the agent is already running")

    available, how = is_available()
    if not available:
        raise RuntimeError(how)

    # Resolve ports up front so the UI/browser know where to point even
    # when the defaults are taken by another Blender instance.
    try:
        actual_port = _pick_free_port(host, port)
        actual_mcp_port = _pick_free_port(host, mcp_port) if mcp_port is not None else None
    except OSError as ex:
        raise RuntimeError(str(ex)) from ex

    # The agent's blmcp tools read these to find the bridge. For the
    # in-process path this is process-global, which is correct: this
    # process IS the one Blender instance the agent should talk to.
    bridge_env = {
        "BLENDER_MCP_HOST": bridge_host,
        "BLENDER_MCP_PORT": str(bridge_port),
    }

    if how == "in-process":
        import asyncio

        from blagent import run_server  # pylint: disable=import-error

        os.environ.update(bridge_env)
        loop = asyncio.new_event_loop()

        def _run() -> None:
            asyncio.set_event_loop(loop)
            task = loop.create_task(run_server(
                host=host, port=actual_port, mcp_port=actual_mcp_port, port_auto=False,
                title=title,
            ))
            _AgentState.task = task
            try:
                loop.run_until_complete(task)
            except asyncio.CancelledError:
                pass
            except Exception as ex:  # pylint: disable=broad-exception-caught
                print("blender-agent thread exited with error: {:s}".format(str(ex)))
            finally:
                loop.close()

        thread = threading.Thread(target=_run, name="blender-agent", daemon=True)
        _AgentState.loop = loop
        _AgentState.thread = thread
        _AgentState.port = actual_port
        _AgentState.mcp_port = actual_mcp_port or 0
        _AgentState.host = host
        thread.start()
        return "thread"

    cli = shutil.which("blender-agent")
    assert cli is not None
    argv = [cli, "--host", host, "--port", str(actual_port), "--no-port-auto"]
    if actual_mcp_port is not None:
        argv += ["--mcp-port", str(actual_mcp_port)]
    if title:
        argv += ["--title", title]
    # pylint: disable-next=consider-using-with
    _AgentState.proc = subprocess.Popen(argv, env={**os.environ, **bridge_env})
    _AgentState.port = actual_port
    _AgentState.mcp_port = actual_mcp_port or 0
    _AgentState.host = host
    return "subprocess"


def update_title(title: str) -> None:
    """
    Push a new instance label (browser tab title) to the running agent
    via ``POST /instance``. Fire-and-forget on a daemon thread so save
    and load handlers never block the UI; silently a no-op when the
    agent is not running.
    """
    if not is_running() or not _AgentState.port:
        return
    url = "http://{:s}:{:d}/instance".format(_AgentState.host, _AgentState.port)

    def _post() -> None:
        import json
        import urllib.request

        request = urllib.request.Request(
            url,
            data=json.dumps({"title": title}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=2.0):
                pass
        except OSError:
            pass

    threading.Thread(target=_post, name="blender-agent-title", daemon=True).start()


def stop() -> None:
    """
    Stop the agent however it was started. Never raises.
    """
    kind = launch_kind()
    if kind == "thread":
        loop = _AgentState.loop
        task = _AgentState.task
        thread = _AgentState.thread
        if loop is not None and task is not None:
            try:
                loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:
                pass
        if thread is not None:
            thread.join(timeout=5.0)
    elif kind == "subprocess":
        proc = _AgentState.proc
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                proc.kill()
    _AgentState.thread = None
    _AgentState.loop = None
    _AgentState.task = None
    _AgentState.proc = None
