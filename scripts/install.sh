#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Install the Blender MCP plugin without needing `make` (or a host
# Python): works on Linux, macOS and WSL2 under bash or zsh.
#
#   ./scripts/install.sh                 full install
#   ./scripts/install.sh --uninstall    remove everything again
#   ./scripts/install.sh --packages-only    pip packages, skip the add-on
#   ./scripts/install.sh --extension-only   add-on, skip the pip packages
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

REPO_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd)"
ADDON_DIR="$REPO_DIR/addon/blender_mcp_addon"
DIST_DIR="$REPO_DIR/dist"

DO_PACKAGES=1
DO_EXTENSION=1
UNINSTALL=0
for arg in "$@"; do
	case "$arg" in
		--packages-only) DO_EXTENSION=0 ;;
		--extension-only) DO_PACKAGES=0 ;;
		--uninstall) UNINSTALL=1 ;;
		-h|--help)
			sed -n '6,21p' "$0" | sed 's/^# \{0,1\}//'
			exit 0 ;;
		*)
			echo "install.sh: unknown argument '$arg' (try --help)" >&2
			exit 1 ;;
	esac
done

note() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

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
	if [ "$UNINSTALL" = 1 ]; then
		note "Removing python packages"
		"$BLPY" -m pip uninstall -y blender-mcp-extensions blender-mcp-agent blender-mcp || true
	else
		note "Installing python packages (mcp, agent, mcp_ext)"
		"$BLPY" -m ensurepip --upgrade >/dev/null 2>&1 || true
		"$BLPY" -m pip install --upgrade \
			"$REPO_DIR/mcp" "$REPO_DIR/agent" "$REPO_DIR/mcp_ext"
	fi
fi

# --- 2. The add-on, as a Blender extension ----------------------------------
if [ "$DO_EXTENSION" = 1 ]; then
	if [ "$UNINSTALL" = 1 ]; then
		note "Removing the add-on extension"
		"$BLENDER" --command extension remove user_default.mcp \
			|| die "extension removal failed (was it installed?)"
	else
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
	note "Done. Start Blender - the MCP bridge starts automatically"
	note "(Edit > Preferences > Add-ons > MCP to configure ports, agent, skills)."
fi
