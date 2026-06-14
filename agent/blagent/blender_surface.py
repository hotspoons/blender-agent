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
    "offscreen_gl_support",
    "spawned_by_blender",
    "surface_decision",
    "swarm_preflight",
)

import logging
import os
import re
import shutil
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
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
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


def offscreen_gl_support(blender_path: "str | None" = None) -> "tuple[bool, str]":
    """
    Whether the OFF-SCREEN GL surface (headed Blender on a virtual display, so
    viewport screenshot / GPU tools work) is usable here — with per-OS guidance
    when it is not. ``blender_path`` is accepted for symmetry/future use.

    Off-screen GL needs a virtual display + a working OpenGL stack:
      - Linux: Xvfb, plus a GPU or a software GL (Mesa) for the GL context.
      - macOS / Windows: no Xvfb; this mechanism does not apply. Use RENDER
        (works headless everywhere) instead of screenshots.
    """
    del blender_path
    plat = sys.platform
    if plat.startswith("linux"):
        if shutil.which("Xvfb") is not None:
            return True, (
                "off-screen GL: Xvfb found. On a host with NO GPU you also need a "
                "software OpenGL (Mesa) — install it (Debian/Ubuntu: "
                "'apt-get install libgl1-mesa-dri libglu1-mesa'; Fedora: "
                "'dnf install mesa-dri-drivers') and, if a GL context still fails, "
                "set LIBGL_ALWAYS_SOFTWARE=1.")
        return False, (
            "off-screen GL needs Xvfb, which is not installed (Debian/Ubuntu: "
            "'apt-get install xvfb'; Fedora: 'dnf install xorg-x11-server-Xvfb'), "
            "plus a software OpenGL on GPU-less hosts (Mesa: 'libgl1-mesa-dri'). "
            "Without them, screenshots are unavailable — workers must RENDER instead.")
    if plat == "darwin":
        return False, (
            "off-screen GL screenshots via a virtual display are NOT supported on "
            "macOS (Blender uses Metal/Cocoa, there is no Xvfb). Swarm mode itself "
            "works on macOS — workers RENDER images (works headless) instead of "
            "taking viewport screenshots.")
    if plat.startswith("win"):
        return False, (
            "off-screen GL screenshots via a virtual display are NOT supported on "
            "Windows (no Xvfb). Swarm mode itself works on Windows — workers RENDER "
            "images (works headless) instead of taking viewport screenshots.")
    return False, (
        "off-screen GL support is unknown on this platform; workers should RENDER "
        "(media_io 'render') rather than rely on viewport screenshots.")


def swarm_preflight(blender_path: "str | None" = None) -> "tuple[bool, str]":
    """
    Cross-platform readiness report for swarm mode. Returns
    ``(ready, message)`` where *ready* means the hard requirement (a spawnable
    Blender) is met; the message lists every requirement and its status so it
    can be surfaced to the user before/at swarm launch.

    Hard requirement: each worker spawns its OWN headless Blender, so Blender
    must be on PATH (or BLENDER_PATH) with the blender-mcp add-on installed +
    enabled. Soft: off-screen GL (for screenshots) — see ``offscreen_gl_support``.
    """
    blender = blender_path or os.environ.get("BLENDER_PATH", "blender")
    found = shutil.which(blender) is not None or os.path.isfile(blender)
    lines = ["Swarm mode requirements ({:s}):".format(sys.platform)]
    if found:
        lines.append("  ✓ Blender found ({:s}).".format(blender))
    else:
        lines.append(
            "  ✗ Blender NOT found. Each swarm worker spawns its own headless "
            "Blender — install Blender and put it on PATH (or set BLENDER_PATH). "
            "It must have the blender-mcp add-on installed AND enabled.")
    ok, detail = offscreen_gl_support(blender)
    lines.append("  {:s} {:s}".format("✓" if ok else "•", detail))
    lines.append(
        "  ✓ RENDER (media_io 'render') works headless on every platform — it is "
        "the portable way for workers to capture images, no display required.")
    return found, "\n".join(lines)


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


# Startup script for the OFF-SCREEN GL surface: a *full GUI* Blender (running
# on a virtual X display) where the add-on's interactive bridge server is
# started via its operator. This path has a real window/GPU context, so
# ``bpy.app.background`` is False and the screenshot / GPU tools work — unlike
# ``--command blender_mcp``, which runs background-style even when headed.
_OFFSCREEN_STARTUP = """\
import bpy
_HOST, _PORT = {host!r}, {port}
# Find the enabled add-on that provides the bridge operator; enable known
# module names if needed (extension install vs legacy add-on).
if not hasattr(bpy.ops, "blmcp") or not hasattr(bpy.ops.blmcp, "server_start"):
    for _mod in ("bl_ext.user_default.mcp", "blender_mcp_addon"):
        try:
            bpy.ops.preferences.addon_enable(module=_mod)
            break
        except Exception:
            continue
for _name in bpy.context.preferences.addons.keys():
    if _name.endswith("mcp") or _name.endswith("blender_mcp_addon"):
        _prefs = bpy.context.preferences.addons[_name].preferences
        try:
            _prefs.host = _HOST
            _prefs.port = _PORT
            _prefs.use_port_auto = False
        except Exception:
            pass
        break
bpy.ops.blmcp.server_start()
"""


def build_blender_argv(
        blender_path: str,
        host: str,
        port: int,
        blend_file: "str | None",
        online_mode: bool,
        offscreen_gl: bool = False,
        startup_script: "str | None" = None,
) -> "list[str]":
    """
    Argv for the Blender compute surface, bound to *host:port*.

    Default (``offscreen_gl`` False): ``blender --background --command
    blender_mcp`` — cheap, but runs background-style, so viewport screenshot
    tools and GPU offscreen draw are unavailable; only the offline render
    engine works.

    ``offscreen_gl`` True: a *full GUI* ``blender --python <startup_script>``
    (no ``--background``, no ``--command``), meant to run on a virtual X
    display (see ``BlenderSurface``). The startup script starts the add-on's
    interactive bridge server, so there is a real window/GPU context and the
    screenshot tools work — off-screen, with no window ever shown to a user.
    ``--online-mode`` grants the bridge's network permission either way.
    """
    argv = [blender_path]
    if offscreen_gl:
        if blend_file:
            argv.append(blend_file)
        if online_mode:
            argv.append("--online-mode")
        argv += ["--python", startup_script or ""]
        return argv
    argv.append("--background")
    if blend_file:
        argv.append(blend_file)
    if online_mode:
        argv.append("--online-mode")
    argv += ["--command", "blender_mcp", "--host", host, "--port", str(port)]
    return argv


def _start_xvfb(width: int = 1280, height: int = 1024, depth: int = 24) -> "tuple[subprocess.Popen[bytes], str]":
    """
    Start an Xvfb virtual X server on a free display and return
    ``(process, ":N")``. Raises ``RuntimeError`` if Xvfb is unavailable or
    never comes up. The display has no physical screen — Blender renders into
    it off-screen, so screenshots work with no window ever shown.
    """
    import shutil  # local: only needed on the offscreen path
    if shutil.which("Xvfb") is None:
        raise RuntimeError(
            "offscreen GL surface needs Xvfb, which is not installed "
            "(apt-get install xvfb). Falling back is the caller's choice.")
    # Pick a display number unlikely to collide; Xvfb fails fast if taken.
    for display_num in range(99, 130):
        lock = "/tmp/.X{:d}-lock".format(display_num)
        if os.path.exists(lock):
            continue
        display = ":{:d}".format(display_num)
        # pylint: disable-next=consider-using-with
        proc = subprocess.Popen(
            ["Xvfb", display, "-screen", "0", "{:d}x{:d}x{:d}".format(width, height, depth),
             "-nolisten", "tcp"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                break  # this display was taken / Xvfb died; try the next
            if os.path.exists(lock):
                return proc, display
            time.sleep(0.1)
        try:
            proc.terminate()
        except OSError:
            pass
    raise RuntimeError("could not start Xvfb on any display :99-:129")


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
            offscreen_gl: "bool | None" = None,
    ) -> None:
        self.host = host
        self.port = port
        # Reuse the same resolution blmcp's CLI helper uses.
        self.blender_path = blender_path or os.environ.get("BLENDER_PATH", "blender")
        self.blend_file = blend_file
        self.online_mode = online_mode
        # Off-screen GL: run Blender headed on a virtual X display (Xvfb) so
        # screenshot/GPU tools work, with no window ever shown. Opt-in (heavier
        # than --background); default off. Env BLENDER_AGENT_OFFSCREEN_GL=1.
        if offscreen_gl is None:
            offscreen_gl = os.environ.get("BLENDER_AGENT_OFFSCREEN_GL", "").lower() in (
                "1", "true", "yes", "on")
        self.offscreen_gl = offscreen_gl
        self.proc: "subprocess.Popen[bytes] | None" = None
        self._xvfb: "subprocess.Popen[bytes] | None" = None
        self._startup_script: "str | None" = None

    def _write_startup_script(self) -> str:
        """Write the off-screen GUI startup script to a temp file; return its path."""
        import tempfile
        fd, path = tempfile.mkstemp(prefix="blmcp_offscreen_", suffix=".py")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(_OFFSCREEN_STARTUP.format(host=self.host, port=self.port))
        return path

    def start(self, timeout: float = 60.0, poll: float = 0.25) -> None:
        """
        Spawn Blender and block until the bridge is reachable. Raises
        ``RuntimeError`` if Blender exits early or the bridge never
        comes up within *timeout*.
        """
        env = dict(os.environ)
        if self.offscreen_gl:
            try:
                self._xvfb, display = _start_xvfb()
                env["DISPLAY"] = display
                self._startup_script = self._write_startup_script()
                _log.info("offscreen GL: full-GUI Blender on virtual display %s", display)
            except (RuntimeError, OSError) as ex:
                _log.warning(
                    "offscreen GL unavailable (%s); falling back to --background "
                    "(render works, viewport screenshots do not). %s",
                    ex, offscreen_gl_support(self.blender_path)[1])
                self.offscreen_gl = False
        argv = build_blender_argv(
            self.blender_path, self.host, self.port, self.blend_file, self.online_mode,
            offscreen_gl=self.offscreen_gl, startup_script=self._startup_script)
        _log.info("spawning Blender compute surface: %s", " ".join(argv))
        try:
            # pylint: disable-next=consider-using-with
            self.proc = subprocess.Popen(
                argv, env=env,
                # Windows: spawn headless Blender without a console window flash.
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
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
        """Terminate the spawned Blender (and its Xvfb, if any). Never raises."""
        proc = self.proc
        if proc is not None and proc.poll() is None:
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
        # Tear down the virtual display last (after its Blender client is gone).
        xvfb = self._xvfb
        if xvfb is not None and xvfb.poll() is None:
            try:
                xvfb.terminate()
                try:
                    xvfb.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    xvfb.kill()
            except OSError:
                pass
        self._xvfb = None
        if self._startup_script:
            try:
                os.unlink(self._startup_script)
            except OSError:
                pass
            self._startup_script = None
