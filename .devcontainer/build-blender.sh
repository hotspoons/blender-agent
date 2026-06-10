#!/usr/bin/env bash
# Install the pinned Blender version (see blender.env) for in-container
# testing.
#
# Two paths:
#
#   1. x86_64: the official binary from download.blender.org (fast).
#   2. Anything else (e.g. Linux ARM64, which blender.org does not
#      ship): clone the pinned tag and build from source against
#      Blender's official precompiled libraries
#      (projects.blender.org/blender/lib-linux_arm64). Takes a while
#      on first run; later runs are incremental.
#
# Idempotent: exits immediately when the installed `blender` already
# reports the pinned version.
#
# Environment overrides:
#   BLENDER_FORCE_SOURCE_BUILD=1  build from source even on x86_64.
#   BLENDER_SOURCE_DIR=...        where to clone/build (default ~/.cache/blender-source).
#   BLENDER_BUILD_JOBS=N          parallel build jobs (default: nproc).
#   BLENDER_SKIP_INSTALL=1        do nothing (opt out entirely).
set -euo pipefail

if [ "${BLENDER_SKIP_INSTALL:-0}" = "1" ]; then
    echo "BLENDER_SKIP_INSTALL is set; skipping Blender install."
    exit 0
fi

# Single-instance guard: post-create forks this script, and a user may
# also run it by hand - never let two builds race in the same tree.
LOCK_FILE="$HOME/.cache/blender-build.lock"
mkdir -p "$(dirname "$LOCK_FILE")"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "Another build-blender.sh is already running; exiting."
    exit 0
fi

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=blender.env
source "$SCRIPT_DIR/blender.env"

PREFIX="$HOME/.local"
BIN_DIR="$PREFIX/bin"
SOURCE_DIR="${BLENDER_SOURCE_DIR:-$HOME/.cache/blender-source}"
JOBS="${BLENDER_BUILD_JOBS:-$(nproc)}"

installed_version() {
    command -v blender >/dev/null 2>&1 &&
        blender --version 2>/dev/null | head -n1 | awk '{print $2}' || true
}

if [ "$(installed_version)" = "${BLENDER_VERSION}" ]; then
    echo "Blender ${BLENDER_VERSION} already installed: $(command -v blender)"
    exit 0
fi

mkdir -p "$BIN_DIR"

# ---------------------------------------------------------------------------
# Fast path: official binary (x86_64 only - blender.org ships no other
# Linux architecture).

if [ "$(uname -m)" = "x86_64" ] && [ "${BLENDER_FORCE_SOURCE_BUILD:-0}" != "1" ]; then
    echo "Installing official Blender ${BLENDER_VERSION} (linux-x64)..."
    sudo apt-get update -qq
    sudo apt-get install -y -qq --no-install-recommends \
        libx11-6 libxi6 libxxf86vm1 libxfixes3 libxrender1 \
        libgl1 libegl1 libsm6 libxkbcommon0 xz-utils
    url="https://download.blender.org/release/${BLENDER_RELEASE_DIR}/blender-${BLENDER_VERSION}-linux-x64.tar.xz"
    curl -sL "$url" | tar -xJ -C "$PREFIX"
    ln -sf "$PREFIX/blender-${BLENDER_VERSION}-linux-x64/blender" "$BIN_DIR/blender"
    blender --version | head -n1
    exit 0
fi

# ---------------------------------------------------------------------------
# Source build, pinned to ${BLENDER_GIT_TAG}. Blender publishes
# precompiled dependency libraries for this platform
# (lib-linux_arm64 et al), fetched by `make update`, so only the
# toolchain and windowing headers come from apt.

echo "Building Blender ${BLENDER_GIT_TAG} from source for $(uname -m)..."

sudo apt-get update -qq
sudo apt-get install -y -qq --no-install-recommends \
    build-essential cmake ninja-build git git-lfs python3 \
    libx11-dev libxxf86vm-dev libxcursor-dev libxi-dev libxrandr-dev \
    libxinerama-dev libegl-dev libwayland-dev wayland-protocols \
    libxkbcommon-dev libdbus-1-dev linux-libc-dev libsm-dev libvulkan-dev

mkdir -p "$SOURCE_DIR"
SRC="$SOURCE_DIR/blender"

if [ -d "$SRC/.git" ]; then
    git -C "$SRC" fetch --depth 1 origin tag "${BLENDER_GIT_TAG}"
    git -C "$SRC" checkout "${BLENDER_GIT_TAG}"
else
    git clone --branch "${BLENDER_GIT_TAG}" --depth 1 \
        https://projects.blender.org/blender/blender.git "$SRC"
fi

cd "$SRC"
# Fetch the matching precompiled libraries + asset submodules for the
# checked-out tag. On platforms without a configured lib submodule
# (linux_arm64 at the 5.1 tag) make_update exits non-zero after the
# submodules are already updated - tolerate that; the libs are fetched
# explicitly below.
python3 ./build_files/utils/make_update.py --no-blender ||
    echo "make_update reported issues (continuing; platform libs handled below)"

# Blender 5.1's CMake supports precompiled libs for this platform
# (`lib/linux_arm64` in platform_unix.cmake) and upstream publishes
# them, but the 5.1 tag's .gitmodules has no entry for them yet - so
# `make update` skips the fetch. Clone the matching release branch of
# the lib repo directly when the platform's lib dir is missing.
LIB_PLATFORM="linux_$(uname -m | sed -e 's/x86_64/x64/' -e 's/aarch64/arm64/')"
LIB_BRANCH="blender-v${BLENDER_VERSION%.*}-release"
if [ ! -d "lib/${LIB_PLATFORM}/.git" ] && ! grep -q "lib/${LIB_PLATFORM}" .gitmodules; then
    echo "Fetching precompiled libraries lib-${LIB_PLATFORM} @ ${LIB_BRANCH} (not in .gitmodules at this tag)..."
    git clone --branch "${LIB_BRANCH}" --depth 1 \
        "https://projects.blender.org/blender/lib-${LIB_PLATFORM}.git" "lib/${LIB_PLATFORM}"
fi

# Build + install into the build tree's bin/ (Blender's default `make`
# target already runs the install step into <build>/bin).
make -j"$JOBS"

BUILD_BIN=$(ls -d "$SOURCE_DIR"/build_linux*/bin/blender 2>/dev/null | head -n1)
if [ -z "$BUILD_BIN" ]; then
    echo "ERROR: build completed but no blender binary found under $SOURCE_DIR/build_linux*/bin" >&2
    exit 1
fi

ln -sf "$BUILD_BIN" "$BIN_DIR/blender"
blender --version | head -n1
echo "Blender ${BLENDER_VERSION} built and installed (symlink: $BIN_DIR/blender)"
