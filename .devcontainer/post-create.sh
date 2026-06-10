#!/usr/bin/env bash
# Set up the Python dev environment for blender-mcp.
#
# Installs the MCP server, the optional web agent, dev tooling, and the
# pinned Blender version so the Blender-backed tests run in-container.
set -euo pipefail

python -m pip install --upgrade pip

# Install the MCP server package (editable) plus its runtime deps.
pip install -e ./mcp

# Dev tooling used by the Makefile checks (ruff is referenced by check_ruff but
# is not in requirements_dev.txt, so add it explicitly).
pip install -r ./mcp/requirements_dev.txt ruff

# The optional web agent (editable, with its dependencies).
pip install -e ./agent

# Yaml stubs for mypy/Pylance.
pip install types-PyYAML

# bpy type stubs for Pylance only (python.analysis.stubPath points at
# .devcontainer/typings). Kept out of site-packages on purpose: as a
# PEP 561 package the stubs would also be used by mypy, whose strict
# run trips over signature mismatches in the community stubs.
_TYPINGS_DIR="$(dirname "${BASH_SOURCE[0]}")/typings"
if [ ! -d "$_TYPINGS_DIR/bpy" ]; then
    _FBM_TMP=$(mktemp -d)
    pip install -q fake-bpy-module-latest --target "$_FBM_TMP"
    mkdir -p "$_TYPINGS_DIR"
    cp -r "$_FBM_TMP/bpy-stubs" "$_TYPINGS_DIR/bpy"
    rm -rf "$_FBM_TMP"
fi

# ---------------------------------------------------------------------------
# Blender, pinned by .devcontainer/blender.env, for running the
# Blender-backed tests in-container (`make test_integration` and
# tests/test_blender_mcp_with_blender.py need `blender` on PATH).
#
# x86_64 gets the official binary; architectures blender.org does not
# ship (e.g. Linux ARM64) are built from source at the pinned tag -
# which can take an hour or two. The build is FORKED so container
# creation finishes immediately; every new shell reports its status
# (see the bashrc block below) and the log lives at
# ~/.cache/blender-build.log. Set BLENDER_SKIP_INSTALL=1 to opt out.
_SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
nohup bash "$_SCRIPT_DIR/build-blender.sh" > "$HOME/.cache/blender-build.log" 2>&1 &
echo "Blender install/build started in the background (log: ~/.cache/blender-build.log)"

# Per-shell status hint for the background Blender build.
if ! grep -q "blender-build-status" "$HOME/.bashrc" 2>/dev/null; then
    cat >> "$HOME/.bashrc" <<'BASHRC'

# blender-build-status: report the pinned in-container Blender's state.
if [ -f /workspaces/blender_mcp/.devcontainer/blender.env ]; then
    . /workspaces/blender_mcp/.devcontainer/blender.env
    _bl_installed=$(command -v blender >/dev/null 2>&1 &&
        blender --version 2>/dev/null | head -n1 | awk '{print $2}' || true)
    if [ "$_bl_installed" != "$BLENDER_VERSION" ]; then
        if pgrep -f "build-blender.sh" >/dev/null 2>&1; then
            echo "[blender-mcp] Blender ${BLENDER_VERSION} is still building in the background."
            echo "[blender-mcp] Watch it with: tail -f ~/.cache/blender-build.log"
        else
            echo "[blender-mcp] Blender ${BLENDER_VERSION} is not installed (found: ${_bl_installed:-none})."
            echo "[blender-mcp] Check ~/.cache/blender-build.log, then rerun: bash .devcontainer/build-blender.sh"
        fi
    fi
    unset _bl_installed BLENDER_VERSION BLENDER_GIT_TAG BLENDER_RELEASE_DIR
fi
BASHRC
fi

# Headless Wayland compositor for the interactive-mode Blender tests,
# and the runtime dir it requires (also set via containerEnv).
sudo apt-get install -y -qq --no-install-recommends weston
mkdir -p /tmp/xdg-runtime && chmod 700 /tmp/xdg-runtime

echo "Done. Try: make check_all && make test"
