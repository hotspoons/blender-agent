#!/bin/sh
# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Print the path to Blender's bundled Python interpreter on stdout, or
# exit non-zero with guidance on stderr. Pure POSIX shell - needs NO
# host Python, since the whole point is to find Blender's own redist
# before anything is run. Used by `make install-dev` / `uninstall-dev`.
#
# Resolution order:
#   1. $BLENDER_PYTHON               - explicit interpreter path.
#   2. $BLENDER_BIN / $BLENDER_PATH  - a Blender binary, queried for its
#                                      sys.prefix (exact, version-agnostic).
#   3. Standard install locations    - per-OS glob, newest version first.
#   4. `blender` on PATH / the macOS .app binary, queried as in (2).

set -u

# --- 1. Explicit interpreter ------------------------------------------------
if [ -n "${BLENDER_PYTHON:-}" ]; then
	if [ -f "$BLENDER_PYTHON" ]; then
		echo "$BLENDER_PYTHON"
		exit 0
	fi
	echo "find_blender_python: BLENDER_PYTHON set but not a file: $BLENDER_PYTHON" >&2
	exit 1
fi

# Ask a Blender binary where its bundled python lives.
query_binary() {
	# $1 = blender binary. Echoes the python path on success.
	_expr='import sys,glob,os
b=os.path.join(sys.prefix,"bin")
c=sorted(glob.glob(os.path.join(b,"python3.*")))+sorted(glob.glob(os.path.join(b,"python.exe")))+sorted(glob.glob(os.path.join(b,"python3")))
c=[x for x in c if "-config" not in os.path.basename(x)]
print("BLPY="+(c[-1] if c else ""))'
	_out=$("$1" --background --factory-startup --python-expr "$_expr" 2>/dev/null \
		| sed -n 's/^BLPY=//p' | head -1)
	if [ -n "$_out" ] && [ -f "$_out" ]; then
		echo "$_out"
		return 0
	fi
	return 1
}

# --- 2. Explicitly-pointed Blender binary -----------------------------------
_bl="${BLENDER_BIN:-${BLENDER_PATH:-}}"
if [ -n "$_bl" ]; then
	if query_binary "$_bl"; then exit 0; fi
	echo "find_blender_python: could not query bundled python from '$_bl'" >&2
	exit 1
fi

# --- 3. Standard install-location globs (newest first) ----------------------
_os=$(uname -s 2>/dev/null || echo unknown)
case "$_os" in
	Darwin)
		set -- \
			"/Applications/Blender.app/Contents/Resources"/*/python/bin/python3* \
			"$HOME/Applications/Blender.app/Contents/Resources"/*/python/bin/python3* ;;
	Linux)
		set -- \
			/usr/share/blender/*/python/bin/python3* \
			/opt/blender*/*/python/bin/python3* \
			/snap/blender/current/*/python/bin/python3* \
			"$HOME/.local/share/blender"/*/python/bin/python3* \
			"$HOME"/blender*/*/python/bin/python3* ;;
	*)
		# Windows under git-bash / MSYS (MINGW*, MSYS*) and anything else.
		set -- \
			"/c/Program Files/Blender Foundation"/*/*/python/bin/python.exe \
			"$HOME/AppData/Roaming/Blender Foundation/Blender"/*/python/bin/python.exe ;;
esac
# Keep only real files (unmatched globs stay literal), drop -config
# wrappers, pick the newest by reverse sort.
_match=$(
	for _p in "$@"; do
		[ -f "$_p" ] && echo "$_p"
	done | grep -v -- '-config' | sort -r | head -1
)
if [ -n "$_match" ]; then
	echo "$_match"
	exit 0
fi

# --- 4. `blender` on PATH, or the macOS app bundle binary -------------------
if command -v blender >/dev/null 2>&1; then
	if query_binary blender; then exit 0; fi
fi
if [ -x "/Applications/Blender.app/Contents/MacOS/Blender" ]; then
	if query_binary "/Applications/Blender.app/Contents/MacOS/Blender"; then exit 0; fi
fi

echo "find_blender_python: could not locate Blender's bundled Python." >&2
echo "  Set BLENDER_PYTHON to its path, e.g." >&2
echo "  /Applications/Blender.app/Contents/Resources/5.1/python/bin/python3.11" >&2
echo "  or set BLENDER_BIN to the Blender binary so it can be queried." >&2
exit 1
