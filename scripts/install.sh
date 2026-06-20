#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Install the Blender MCP plugin without needing `make` (or a host
# Python): works on Linux, macOS and WSL2 under bash or zsh.
#
# One-liner (nothing to clone):
#
#   curl -fsSL https://raw.githubusercontent.com/hotspoons/blender-agent/main/scripts/install.sh | bash
#
# It fetches the repo into $XDG_CACHE_HOME/blender-agent and installs from
# there. Pass options through the pipe with `bash -s --`:
#
#   curl -fsSL .../scripts/install.sh | bash -s -- --uninstall
#
# From a checkout it uses the files on disk (no download):
#
#   ./scripts/install.sh                 full install
#   ./scripts/install.sh --uninstall     remove everything again
#   ./scripts/install.sh --reinstall     uninstall + purge wheel cache + install
#                                        (a clean slate - guarantees current code)
#   ./scripts/install.sh --packages-only    pip packages, skip the add-on
#   ./scripts/install.sh --extension-only   add-on, skip the pip packages
#
# Env: BLENDER_BIN / BLENDER_PYTHON pin the binary / interpreter;
#      BLENDER_AGENT_REF picks the branch or tag to fetch (default main).
#
# Two halves, both idempotent:
#   1. pip-install mcp/ + agent/ + mcp_ext/ into Blender's BUNDLED
#      Python (discovered via _misc/find_blender_python.sh; override
#      with BLENDER_PYTHON or BLENDER_BIN).
#   2. Build the add-on as a Blender extension and install+enable it
#      into the user_default repository via Blender's own extension CLI.
#
# Native Windows (no WSL): use scripts/install.ps1 instead.

set -eu

note() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

REPO_URL="${BLENDER_AGENT_REPO:-https://github.com/hotspoons/blender-agent}"
REF="${BLENDER_AGENT_REF:-main}"

DO_PACKAGES=1
DO_EXTENSION=1
UNINSTALL=0
REINSTALL=0
for arg in "$@"; do
	case "$arg" in
		--packages-only) DO_EXTENSION=0 ;;
		--extension-only) DO_PACKAGES=0 ;;
		--uninstall) UNINSTALL=1 ;;
		--reinstall) REINSTALL=1 ;;
		-h|--help)
			cat <<'EOF'
Install the Blender MCP plugin (Linux / macOS / WSL).

  curl -fsSL https://raw.githubusercontent.com/hotspoons/blender-agent/main/scripts/install.sh | bash
  ... | bash -s -- --uninstall        remove everything again
  ... | bash -s -- --reinstall        clean slate: uninstall + purge cache + install
  ... | bash -s -- --packages-only    pip packages, skip the add-on
  ... | bash -s -- --extension-only   add-on, skip the pip packages

From a checkout: ./scripts/install.sh [--uninstall|--reinstall|--packages-only|--extension-only]
Env: BLENDER_BIN, BLENDER_PYTHON, BLENDER_AGENT_REF (branch/tag), BLENDER_AGENT_REPO.
EOF
			exit 0 ;;
		*)
			echo "install.sh: unknown argument '$arg' (try --help)" >&2
			exit 1 ;;
	esac
done

# --- Locate the repo: a checkout, or fetch it (the curl | bash one-liner) ---
# Piped through bash there is no script file on disk, so we download the
# source tarball. From a real checkout we use it as-is.
resolve_repo_dir() {
	_self="${BASH_SOURCE:-$0}"
	if [ -f "$_self" ]; then
		_local="$(cd -- "$(dirname -- "$_self")/.." && pwd)"
		if [ -d "$_local/addon/blender_mcp_addon" ]; then
			note "Using local checkout: $_local" >&2
			echo "$_local"; return 0
		fi
	fi
	_cache="${XDG_CACHE_HOME:-$HOME/.cache}/blender-agent"
	rm -rf "$_cache/src"; mkdir -p "$_cache/src"
	_url="$REPO_URL/archive/$REF.tar.gz"
	note "Fetching $_url" >&2
	if command -v curl >/dev/null 2>&1; then
		curl -fsSL "$_url" | tar -xz -C "$_cache/src" || die "download/extract failed: $_url"
	elif command -v wget >/dev/null 2>&1; then
		wget -qO- "$_url" | tar -xz -C "$_cache/src" || die "download/extract failed: $_url"
	else
		die "need curl or wget to bootstrap the install"
	fi
	_addon="$(find "$_cache/src" -type d -path '*/addon/blender_mcp_addon' 2>/dev/null | head -1)"
	[ -n "$_addon" ] || die "fetched archive has no addon/ - wrong repo or ref ($REF)?"
	(cd -- "$_addon/../.." && pwd)
}

REPO_DIR="$(resolve_repo_dir)"
ADDON_DIR="$REPO_DIR/addon/blender_mcp_addon"
DIST_DIR="$REPO_DIR/dist"

# --- Locate the Blender binary (for the extension CLI) ----------------------
find_blender() {
	if [ -n "${BLENDER_BIN:-${BLENDER_PATH:-}}" ]; then
		echo "${BLENDER_BIN:-$BLENDER_PATH}"
		return 0
	fi
	if command -v blender >/dev/null 2>&1; then
		command -v blender
		return 0
	fi
	# macOS app bundle.
	for app in "/Applications/Blender.app" "$HOME/Applications/Blender.app"; do
		if [ -x "$app/Contents/MacOS/Blender" ]; then
			echo "$app/Contents/MacOS/Blender"
			return 0
		fi
	done
	# WSL2: a Windows Blender under /mnt/c (newest version first).
	if grep -qi microsoft /proc/version 2>/dev/null; then
		_win=$(ls -1d "/mnt/c/Program Files/Blender Foundation"/*/blender.exe 2>/dev/null | sort -r | head -1)
		if [ -n "$_win" ]; then
			echo "$_win"
			return 0
		fi
	fi
	return 1
}

BLENDER="$(find_blender)" || die "could not find a Blender binary - set BLENDER_BIN=/path/to/blender"
note "Blender: $BLENDER"

# --- 1. Python packages into Blender's bundled interpreter ------------------
if [ "$DO_PACKAGES" = 1 ]; then
	BLPY="$(BLENDER_BIN="$BLENDER" sh "$REPO_DIR/_misc/find_blender_python.sh")" \
		|| die "could not locate Blender's bundled Python (see message above)"
	note "Blender Python: $BLPY"
	if [ "$UNINSTALL" = 1 ] || [ "$REINSTALL" = 1 ]; then
		note "Removing python packages"
		"$BLPY" -m pip uninstall -y blender-mcp-extensions blender-mcp-agent blender-mcp || true
	fi
	if [ "$UNINSTALL" != 1 ]; then
		note "Installing python packages (mcp, agent, mcp_ext)"
		"$BLPY" -m ensurepip --upgrade >/dev/null 2>&1 || true
		# Scrub the in-tree setuptools build dirs FIRST. setuptools' build_py
		# copies sources into build/lib but never PRUNES files that have since
		# been deleted from source, so a file removed from the tree (e.g. an
		# old blagent/web overlay component that was consolidated into
		# agentcore) lingers in build/lib and gets re-packaged into every wheel
		# - shadowing the current code at runtime. Removing build/ guarantees a
		# wheel that matches the source exactly. Must run on every install, not
		# just --reinstall: a normal install rebuilds from the same stale dir.
		note "Removing stale build dirs (mcp, agent, mcp_ext)"
		rm -rf "$REPO_DIR/mcp/build" "$REPO_DIR/agent/build" "$REPO_DIR/mcp_ext/build"
		if [ "$REINSTALL" = 1 ]; then
			# A stale same-version (0.1.0) wheel in the cache would defeat the
			# point of a clean reinstall - drop it so the source is rebuilt.
			note "Purging pip wheel cache"
			"$BLPY" -m pip cache purge || true
		fi
		# Pass 1: resolve + install dependencies. Force wheels for the compiled
		# deps: the newest cryptography (pulled in via mcp -> pyjwt[crypto]) has
		# no win_arm64 wheel, so plain pip builds it from source and fails on
		# ARM. --only-binary makes pip backtrack to a version that ships an
		# arm64 wheel. Harmless on x86 / Linux / macOS.
		"$BLPY" -m pip install --upgrade --only-binary=cryptography,cffi \
			"$REPO_DIR/mcp" "$REPO_DIR/agent" "$REPO_DIR/mcp_ext"
		# Pass 2: our package versions are static (0.1.0), so pass 1 treats an
		# unchanged version as "already satisfied" and may NOT copy in fresh
		# local edits. Force-reinstall just our three packages (--no-deps keeps
		# it fast) so the current source on disk always lands.
		"$BLPY" -m pip install --force-reinstall --no-deps \
			"$REPO_DIR/mcp" "$REPO_DIR/agent" "$REPO_DIR/mcp_ext"
	fi
fi

# --- 2. The add-on, as a Blender extension ----------------------------------
if [ "$DO_EXTENSION" = 1 ]; then
	if [ "$UNINSTALL" = 1 ] || [ "$REINSTALL" = 1 ]; then
		note "Removing the add-on extension"
		if ! "$BLENDER" --command extension remove user_default.mcp; then
			if [ "$REINSTALL" = 1 ]; then
				note "(add-on was not installed; continuing to a fresh install)"
			else
				die "extension removal failed (was it installed?)"
			fi
		fi
	fi
	if [ "$UNINSTALL" != 1 ]; then
		note "Building the add-on extension"
		mkdir -p "$DIST_DIR"
		"$BLENDER" --command extension build \
			--source-dir "$ADDON_DIR" --output-dir "$DIST_DIR" \
			|| die "extension build failed"
		ZIP=$(ls -1t "$DIST_DIR"/*.zip 2>/dev/null | head -1)
		[ -n "$ZIP" ] || die "no extension zip produced in $DIST_DIR"
		note "Installing $(basename "$ZIP") into Blender (user_default, enabled)"
		"$BLENDER" --command extension install-file -r user_default -e "$ZIP" \
			|| die "extension install failed"
	fi
fi

if [ "$UNINSTALL" = 1 ]; then
	note "Done. Restart Blender to drop any already-loaded modules."
else
	[ "$REINSTALL" = 1 ] && note "Clean reinstall complete - relaunch Blender to load the fresh code."
	note "Done. Start Blender - the MCP bridge starts automatically"
	note "(Edit > Preferences > Add-ons > MCP to configure ports, agent, skills)."
fi
