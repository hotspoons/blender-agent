# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Standalone launch surface: let ``blender-agent`` run without a Blender
session in front of it.

The agent's tools reach Blender through the add-on's TCP bridge (see
``blmcp.tools_helpers.connection``). Normally Blender is already running
- the add-on starts the bridge and spawns the agent pointed at it. This
module covers the inverse: a headless deployment where the agent is the
entry point and Blender is its *compute surface*. When no bridge is
reachable and the agent was not itself launched by Blender, it spawns
``blender --background --command blender_mcp`` (the add-on's own bridge
CLI), waits for the bridge, points the tools at it, and tears it down on
exit.

The hard constraint is the recursion guard. The add-on launches the
agent as a child process, so if a Blender-spawned agent also spawned
Blender we would get Blender -> agent -> Blender -> agent ... a fork
bomb. Before spawning we therefore check, by process-tree
introspection, whether any ancestor is a Blender process (plus an
explicit env marker the add-on sets); if so, spawning is refused and we
attach to the bridge the add-on is bringing up instead.
"""

__all__ = (
    "BlenderSurface",
    "blender_ancestor_pid",
    "bridge_reachable",
    "build_blender_argv",
    "spawned_by_blender",
    "surface_decision",
)

import logging
import os
import re
import socket
import subprocess
import sys
import time

_log = logging.getLogger("blagent.surface")

# Set by the add-on's agent launcher (see addon/.../agent_launch.py) so
# the guard is reliable even where process introspection is not (e.g.
# Windows without psutil). Authoritative when present.
_SPAWNED_MARKER = "BLENDER_AGENT_SPAWNED_BY_BLENDER"

# A Blender executable basename: "blender", "Blender", "blender.exe",
# "blender-4.2" - but NOT "blender-agent" / "blender-mcp" / "blender_mcp"
# (those are ours, and an ancestor of that name must not look like
# Blender or the guard would misfire on a wrapper).
_BLENDER_NAME_RE = re.compile(r"(?i)\Ablender(?:[-_.]?\d[\d.\-]*)?(?:\.exe)?\Z")

_MAX_ANCESTOR_DEPTH = 40


def _name_is_blender(name: str) -> bool:
    return bool(name) and _BLENDER_NAME_RE.match(os.path.basename(name)) is not None


def _proc_parent_and_name(pid: int) -> "tuple[int, str] | None":
    """
    Return ``(ppid, name)`` for *pid*, or ``None`` when it cannot be
    determined. Linux reads ``/proc``; other POSIX systems shell out to
    ``ps``. *name* prefers the resolved executable basename (``comm`` is
    truncated to 15 chars on Linux, which still fits "blender" but a
    longer real name would be cut).
    """
    if sys.platform.startswith("linux"):
        try:
            with open("/proc/{:d}/stat".format(pid), encoding="utf-8", errors="replace") as fh:
                data = fh.read()
            # comm sits in parentheses and may itself contain spaces or
            # parens; split on the LAST ')'. Fields after it are
            # state(0) ppid(1) ...
            rparen = data.rfind(")")
            fields = data[rparen + 2:].split()
            ppid = int(fields[1])
        except (OSError, ValueError, IndexError):
            return None
        name = ""
        try:
            name = os.path.basename(os.readlink("/proc/{:d}/exe".format(pid)))
        except OSError:
            name = data[data.find("(") + 1:data.rfind(")")]
        return ppid, name

    # macOS / BSD: ps gives ppid and the command path.
    try:
        out = subprocess.run(
            ["ps", "-o", "ppid=,comm=", "-p", str(pid)],
            capture_output=True, text=True, timeout=2.0, check=False,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    if not out:
        return None
    parts = out.split(None, 1)
    try:
        ppid = int(parts[0])
    except (ValueError, IndexError):
        return None
    name = parts[1] if len(parts) > 1 else ""
    return ppid, name


def blender_ancestor_pid(parent_of: "int | None" = None, _reader=_proc_parent_and_name) -> "int | None":
    """
    Walk the process-ancestor chain looking for a Blender process.
    Returns the first matching ancestor PID, or ``None``. Starts from
    the parent of *parent_of* (default: this process). *_reader* is the
    ``(ppid, name)`` lookup, injectable for tests.
    """
    pid = os.getpid() if parent_of is None else parent_of
    seen: set[int] = set()
    for _ in range(_MAX_ANCESTOR_DEPTH):
        info = _reader(pid)
        if info is None:
            return None
        ppid, _name = info
        if ppid <= 0 or ppid in seen:
            return None
        seen.add(ppid)
        parent = _reader(ppid)
        if parent is None:
            return None
        if _name_is_blender(parent[1]):
            return ppid
        pid = ppid
    return None


def spawned_by_blender(env: "dict[str, str] | None" = None, _reader=_proc_parent_and_name) -> bool:
    """
    True when this agent is a descendant of Blender (so a bridge is, or
    will be, provided for it) - the explicit add-on marker, or a Blender
    process found in the ancestor chain.
    """
    environ = os.environ if env is None else env
    if environ.get(_SPAWNED_MARKER):
        return True
    return blender_ancestor_pid(_reader=_reader) is not None


def bridge_reachable(host: str, port: int, timeout: float = 0.5) -> bool:
    """
    True when something accepts a TCP connection at *host:port* - a
    proxy for "a Blender bridge is already serving here".
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def surface_decision(*, bridge_up: bool, is_blender_child: bool, want_spawn: bool) -> str:
    """
    Pure decision for what to do about the compute surface:

    - ``"attach"``  - a bridge is already reachable; use it.
    - ``"guarded"`` - no bridge yet, but we are a Blender child; must
      NOT spawn (recursion). Attach to the bridge being brought up.
    - ``"spawn"``   - standalone with no bridge and spawning allowed.
    - ``"none"``    - no bridge and spawning disabled; tools will error
      until one appears.
    """
    if bridge_up:
        return "attach"
    if is_blender_child:
        return "guarded"
    if want_spawn:
        return "spawn"
    return "none"


def build_blender_argv(
        blender_path: str,
        host: str,
        port: int,
        blend_file: "str | None",
        online_mode: bool,
) -> "list[str]":
    """
    Argv for a headless bridge surface: the add-on's ``blender_mcp`` CLI
    command, bound to *host:port*. ``--online-mode`` grants the network
    permission the bridge's TCP server needs in background mode.
    """
    argv = [blender_path, "--background"]
    if blend_file:
        argv.append(blend_file)
    if online_mode:
        argv.append("--online-mode")
    argv += ["--command", "blender_mcp", "--host", host, "--port", str(port)]
    return argv


class BlenderSurface:
    """
    A Blender process spawned to serve as the agent's compute surface.
    Starts ``blender --background --command blender_mcp``, waits for the
    bridge to accept connections, and terminates it on ``stop()``.
    """

    def __init__(
            self,
            host: str,
            port: int,
            blender_path: "str | None" = None,
            blend_file: "str | None" = None,
            online_mode: bool = True,
    ) -> None:
        self.host = host
        self.port = port
        # Reuse the same resolution blmcp's CLI helper uses.
        self.blender_path = blender_path or os.environ.get("BLENDER_PATH", "blender")
        self.blend_file = blend_file
        self.online_mode = online_mode
        self.proc: "subprocess.Popen[bytes] | None" = None

    def start(self, timeout: float = 60.0, poll: float = 0.25) -> None:
        """
        Spawn Blender and block until the bridge is reachable. Raises
        ``RuntimeError`` if Blender exits early or the bridge never
        comes up within *timeout*.
        """
        argv = build_blender_argv(
            self.blender_path, self.host, self.port, self.blend_file, self.online_mode)
        _log.info("spawning Blender compute surface: %s", " ".join(argv))
        try:
            # pylint: disable-next=consider-using-with
            self.proc = subprocess.Popen(argv)
        except FileNotFoundError as ex:
            raise RuntimeError(
                "Blender executable not found at '{:s}'. Set BLENDER_PATH to the "
                "Blender binary (it must have the blender-mcp add-on installed).".format(
                    self.blender_path)
            ) from ex

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(
                    "Blender exited (code {:d}) before its MCP bridge came up. Is the "
                    "blender-mcp add-on installed and enabled in that Blender, and does "
                    "it support `--command blender_mcp`?".format(self.proc.returncode or 0))
            if bridge_reachable(self.host, self.port, timeout=poll):
                _log.info("Blender bridge up at %s:%d (pid %d)", self.host, self.port, self.proc.pid)
                return
            time.sleep(poll)
        self.stop()
        raise RuntimeError(
            "Blender bridge did not come up at {:s}:{:d} within {:.0f}s".format(
                self.host, self.port, timeout))

    def stop(self) -> None:
        """Terminate the spawned Blender. Never raises."""
        proc = self.proc
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.terminate()
            try:
                proc.wait(timeout=10.0)
            except subprocess.TimeoutExpired:
                proc.kill()
        except OSError:
            pass
        finally:
            _log.info("stopped Blender compute surface (pid %d)", proc.pid)
