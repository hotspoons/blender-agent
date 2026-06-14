# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Import jail for agent-authored tools.

Authored tools run through the SAME bridge transport as
``execute_blender_code`` (so they grant no new execution power), but
because they PERSIST and get invoked later — possibly unattended, by the
primary agent — they carry a stricter, explicit import policy than
interactive one-shot exec.

Two layers, and honest about the limit (like ``addon/weak_sandbox.py``,
this is a strong guardrail, not a true jail — real isolation needs a
subprocess/seccomp, which in-Blender exec can't provide):

1. **AST scan at author time** (:func:`scan` / :func:`classify`) — the
   AUTHORITATIVE policy. We statically read exactly which modules the tool
   imports and which dynamic-execution escapes it uses; anything outside
   the 3D-modeling allowlist drives a human elicitation before the tool is
   ever persisted.

2. **Runtime import guard** (:func:`build_payload`) — baked into the code
   sent to Blender. It gates ONLY the tool body's own imports (matched by a
   sentinel frame filename) so transitive imports from allowlisted
   libraries (numpy pulling in ctypes, etc.) are NOT broken, while the
   tool's own ``import requests`` is blocked unless granted.
"""

__all__ = (
    "DEFAULT_ALLOWLIST",
    "ImportScan",
    "allowed_modules",
    "build_bundle_payload",
    "build_payload",
    "classify",
    "classify_modules",
    "register_sdk_modules",
    "scan",
    "sdk_modules",
)

import ast
import dataclasses
import json
from collections.abc import Iterable
from typing import Any

# The "normal for 3D-modeling tools" set. Imports outside this require
# per-tool human approval (elicitation) and are then recorded as granted.
DEFAULT_ALLOWLIST = frozenset({
    # First-party Blender (same trust class).
    "bpy", "bpy_extras", "bmesh", "mathutils", "gpu", "freestyle", "aud",
    # Math / numerics.
    "numpy", "math", "cmath", "random", "statistics",
    # Benign stdlib with no dangerous surface.
    "json", "re", "itertools", "functools", "collections", "contextlib",
    "dataclasses", "typing", "enum", "string", "datetime", "uuid",
    "fnmatch", "time", "traceback",
})

# Modules whose whole purpose is dynamic importing — granting them would
# defeat the jail (e.g. importlib.import_module("os").system(...) imports
# from importlib's frame, which the runtime guard does NOT gate). Treated
# as a dynamic-execution FLAG, never a grantable import.
_DYNAMIC_IMPORT_MODULES = frozenset({"importlib"})

# Dynamic-execution constructs that defeat static import analysis. Their
# presence forces elicitation regardless of the import set.
_DANGER_CALLS = frozenset({"eval", "exec", "compile", "__import__", "import_module"})
# Attribute calls that are almost always destructive/escaping. ``unlink`` /
# ``rmtree`` flag filesystem deletion even if a dual-use module is granted;
# bare ``remove`` is deliberately omitted (list.remove/set.remove noise).
_DANGER_ATTRS = frozenset({"system", "popen", "spawn", "spawnl", "spawnv",
                           "fork", "execv", "execve", "import_module",
                           "unlink", "rmtree"})


# Curated, vetted FRAMEWORK module roots that authored tools may import
# WITHOUT elicitation — the bridge that lets a single jailed tool stand on
# Tier A's shoulders (compose perception/contract/skills) instead of
# reinventing them. Extensions opt in from their register() via
# register_sdk_modules; nothing is exposed by default. Importing an SDK
# module is safe by the same property as numpy: the framework's own
# transitive imports run in ITS frames, which the runtime guard never gates.
_SDK_MODULES: set[str] = set()


def register_sdk_modules(label: str, modules: Iterable[str]) -> None:
    """
    Declare *modules* (module roots, e.g. ``"blrig"``) as importable by
    authored tools. Idempotent; *label* is for human traceability only.
    """
    del label
    for mod in modules or ():
        root = str(mod).split(".")[0].strip()
        if root:
            _SDK_MODULES.add(root)


def sdk_modules() -> set[str]:
    """The currently-registered framework SDK roots (a copy)."""
    return set(_SDK_MODULES)


def allowed_modules(granted: Iterable[str] = ()) -> set[str]:
    """Everything an authored tool may import: allowlist + SDK + per-tool grants."""
    return set(DEFAULT_ALLOWLIST) | set(_SDK_MODULES) | set(granted)


@dataclasses.dataclass
class ImportScan:
    modules: set[str]       # top-level module roots the tool imports
    flags: list[str]        # dynamic/dangerous constructs (human-readable)
    syntax_error: str = ""  # non-empty when the code does not parse


def scan(code: str) -> ImportScan:
    """
    Statically collect imported module roots and dynamic-execution flags.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as ex:
        return ImportScan(modules=set(), flags=[], syntax_error=str(ex))

    modules: set[str] = set()
    flags: list[str] = []

    def _note(root: str) -> None:
        if root in _DYNAMIC_IMPORT_MODULES:
            flags.append("dynamic import ({:s})".format(root))
        else:
            modules.add(root)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                _note(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                flags.append("relative import (level {:d})".format(node.level))
            elif node.module:
                _note(node.module.split(".")[0])
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in _DANGER_CALLS:
                flags.append("{:s}()".format(func.id))
            elif isinstance(func, ast.Attribute) and func.attr in _DANGER_ATTRS:
                flags.append("*.{:s}()".format(func.attr))
    return ImportScan(modules=modules, flags=sorted(set(flags)))


def classify(code: str, granted: Iterable[str] = ()) -> dict[str, Any]:
    """
    Policy verdict for a single-file tool. ``{"ok", "syntax_error",
    "outside_imports", "flags"}``; *ok* is True when there is nothing to
    elicit (no out-of-allowlist imports, no dynamic-exec flags, parses).
    """
    return classify_modules(code, {}, granted)


def classify_modules(entry_src: str, siblings: dict[str, str], granted: Iterable[str] = ()) -> dict[str, Any]:
    """
    Policy verdict for a (possibly multi-file) bundle: *entry_src* plus
    *siblings* (name->source). The bundle's own sibling module names are
    importable within it (not "outside"); external imports are gated by
    allowlist+SDK+granted; an out-of-allowlist import or dynamic-exec flag
    in ANY module forces elicitation.
    """
    permitted = allowed_modules(granted) | set(siblings)
    outside: set[str] = set()
    flags: list[str] = []
    for label, src in [("<entry>", entry_src)] + sorted(siblings.items()):
        sc = scan(src)
        if sc.syntax_error:
            return {"ok": False,
                    "syntax_error": "{:s}: {:s}".format(label, sc.syntax_error),
                    "outside_imports": [], "flags": []}
        outside |= (sc.modules - permitted)
        flags.extend(sc.flags)
    return {
        "ok": not outside and not flags,
        "syntax_error": "",
        "outside_imports": sorted(outside),
        "flags": sorted(set(flags)),
    }


# The runtime guard generalizes to BUNDLES: each module (entry + siblings)
# is compiled under its own sentinel filename, so the guard gates imports
# from ANY of the tool's own frames. Sibling modules are importable by bare
# name (materialized on demand); transitive imports from allowlisted/SDK
# libraries come from other frames and pass through. Relative imports stay
# blocked. Bundle modules are removed from sys.modules after the run.
_PAYLOAD_HEAD = '''\
import sys as _sys, json as _json, builtins as _bi, types as _types
_ALLOWED = set({allowed})
_BUNDLE = set({bundle})
_MODSRC = _json.loads({modsrc})
_SENT = _json.loads({sent})
_FILES = set(_SENT.values())
_ENTRY = {entry}
_real_import = _bi.__import__
_added = []


def _load_bundle_module(modname):
    mod = _types.ModuleType(modname)
    mod.__file__ = _SENT[modname]
    _sys.modules[modname] = mod
    _added.append(modname)
    exec(compile(_MODSRC[modname], _SENT[modname], "exec"), mod.__dict__)
    return mod


def _guard(name, globals=None, locals=None, fromlist=(), level=0):
    if level and level != 0:
        raise ImportError("relative imports are not allowed in agent tools")
    root = name.split(".")[0]
    if root in _BUNDLE:
        # a sibling module of this tool's own bundle — materialize on demand.
        if root not in _sys.modules:
            _load_bundle_module(root)
        return _real_import(name, globals, locals, fromlist, level)
    try:
        caller = _sys._getframe(1).f_code.co_filename
    except ValueError:
        caller = ""
    if caller in _FILES and root not in _ALLOWED:
        raise ImportError(
            "import {{!r}} is blocked: not in this tool's approved set {{!r}}".format(
                root, sorted(_ALLOWED)))
    return _real_import(name, globals, locals, fromlist, level)


_bi.__import__ = _guard
try:
    _ns = {{"params": _json.loads({params})}}
    exec(compile({entry_src}, _SENT[_ENTRY], "exec"), _ns)
    result = _ns.get("result")
finally:
    _bi.__import__ = _real_import
    for _m in _added:
        _sys.modules.pop(_m, None)
'''

_ENTRY_KEY = "__entry__"


def _build(tool_name: str, entry_src: str, siblings: dict[str, str], params: dict[str, Any], allowed: Iterable[str]) -> str:
    sent = {_ENTRY_KEY: "<agent_tool:{:s}>".format(tool_name)}
    for sib in siblings:
        sent[sib] = "<agent_tool:{:s}/{:s}>".format(tool_name, sib)
    return _PAYLOAD_HEAD.format(
        allowed=repr(sorted(allowed)),
        bundle=repr(sorted(siblings)),
        modsrc=repr(json.dumps(dict(siblings))),
        sent=repr(json.dumps(sent)),
        entry=repr(_ENTRY_KEY),
        params=repr(json.dumps(params)),
        entry_src=repr(entry_src),
    )


def build_payload(tool_name: str, code: str, params: dict[str, Any], allowed: Iterable[str]) -> str:
    """Single-file tool payload (a bundle with no siblings)."""
    return _build(tool_name, code, {}, params, allowed)


def build_bundle_payload(tool_name: str, entry_src: str, siblings: dict[str, str],
                         params: dict[str, Any], allowed: Iterable[str]) -> str:
    """
    Multi-file bundle payload: *siblings* (name->source) are importable by
    bare name from the entry and from each other. External imports stay
    gated; relative imports stay blocked.
    """
    return _build(tool_name, entry_src, dict(siblings), params, allowed)
