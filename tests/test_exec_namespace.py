# SPDX-License-Identifier: GPL-3.0-or-later
"""
LLM-generated code routinely uses Blender's common ``mathutils`` types
(``Matrix``, ``Vector``, ...) WITHOUT importing them, producing
``NameError: name 'Matrix' is not defined``. Both exec paths now seed the
namespace with ``bpy`` + those types. These tests pin that:

  * the ``blender --background`` CLI wrapper string seeds them (no Blender);
  * the interactive add-on ``_execute_code`` path runs Matrix/Vector code with
    no import against a REAL Blender (gated on ``BLENDER_PATH``).

    BLENDER_PATH=/path/to/blender pytest tests/test_exec_namespace.py
"""
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import types

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "mcp"))


def test_cli_wrapper_seeds_mathutils(monkeypatch):
    """run_blender_cli's --background wrapper seeds bpy + mathutils types."""
    from blmcp.tools_helpers import blender_cli

    captured = {}

    def _fake_run(argv, **_kwargs):
        captured["wrapper"] = argv[argv.index("--python-expr") + 1]
        return types.SimpleNamespace(
            stdout=blender_cli._RESULT_PREFIX + json.dumps({"status": "ok"}), stderr="")

    monkeypatch.setattr(blender_cli, "_get_blender_path", lambda: "blender")
    monkeypatch.setattr(blender_cli.subprocess, "run", _fake_run)

    blender_cli.run_blender_cli("/tmp/none.blend", "result = {'ok': isinstance(Matrix.Identity(4), Matrix)}")

    wrapper = captured["wrapper"]
    assert "import bpy, mathutils" in wrapper
    for name in ("Matrix", "Vector", "Euler", "Quaternion", "Color"):
        assert "'{}': mathutils.{}".format(name, name) in wrapper, name


@pytest.mark.skipif(not os.environ.get("BLENDER_PATH"), reason="needs BLENDER_PATH")
def test_interactive_exec_seeds_mathutils_real_blender():
    """The worker's path (_execute_code) runs Matrix/Vector code with NO import."""
    script = textwrap.dedent("""
        import json, sys
        sys.path.insert(0, {addon!r})
        from blender_mcp_addon.mcp_to_blender_server import _execute_code
        code = (
            "import bpy\\n"
            "m = Matrix.Identity(4)\\n"
            "v = Vector((1.0, 2.0, 3.0))\\n"
            "result = {{'ok': isinstance(m, Matrix) and tuple(v) == (1.0, 2.0, 3.0)}}\\n"
        )
        res = _execute_code(code, False)
        print("EXEC_NS_RESULT::" + json.dumps(res.response))
    """).format(addon=os.path.join(_REPO, "addon"))

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
        fh.write(script)
        script_path = fh.name
    try:
        proc = subprocess.run(
            [os.environ["BLENDER_PATH"], "--background", "--factory-startup", "--python", script_path],
            capture_output=True, text=True, timeout=180, check=False)
    finally:
        os.unlink(script_path)

    line = next((ln for ln in proc.stdout.splitlines() if ln.startswith("EXEC_NS_RESULT::")), None)
    assert line is not None, "no result marker\nstdout:\n{}\nstderr:\n{}".format(proc.stdout, proc.stderr)
    response = json.loads(line[len("EXEC_NS_RESULT::"):])
    assert response.get("status") == "ok", "Matrix/Vector without import failed: {!r}".format(response)
    assert response["result"]["ok"] is True


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "-s"]))
