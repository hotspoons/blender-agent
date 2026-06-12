# syntax=docker/dockerfile:1.7
#
# Container image for the Blender Agent (blender-mcp-agent).
#
# The agent's OpenAI-compatible chat-completions API is the primary
# entry point. The image bundles Blender itself so the agent can spawn
# its own headless compute surface (no external Blender bridge needed):
# on amd64 the official blender.org binary is used, on arm64 Blender is
# built from source at the pinned tag - exactly as the devcontainer
# does, reusing .devcontainer/build-blender.sh as the single source of
# truth for the version (.devcontainer/blender.env) and build recipe.
#
# Multi-arch: built once per architecture by the GitLab docker-build
# component and stitched into a manifest. Nothing here is arch-specific
# beyond what build-blender.sh already branches on (uname -m).

ARG PYTHON_VERSION=3.12

# ---------------------------------------------------------------------------
# Stage 1 - Blender. Reuses the devcontainer build script verbatim, then
# normalises whatever it produced (official portable tree on amd64, a
# from-source install tree on arm64) into a single relocatable /opt/blender.
# ---------------------------------------------------------------------------
# Trixie, not bookworm: Blender 5.1's CMake requires GCC >= 14 for the
# arm64 source build (bookworm ships 12.2; trixie 14.2 — same base the
# devcontainer builds with). The runtime stage must track the SAME
# Debian release: the built binary links the builder's glibc.
FROM python:${PYTHON_VERSION}-trixie AS blender-build

# build-blender.sh shells out to `sudo apt-get`; as root in the builder a
# trivial passthrough satisfies that without pulling in real sudo.
RUN printf '#!/bin/sh\nexec "$@"\n' > /usr/local/bin/sudo \
    && chmod +x /usr/local/bin/sudo \
    && apt-get update \
    && apt-get install -y --no-install-recommends curl xz-utils git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Force a from-source build even on amd64 by passing --build-arg
# BLENDER_FORCE_SOURCE_BUILD=1. BLENDER_BUILD_JOBS caps the source build
# parallelism (defaults to nproc inside the script).
ARG BLENDER_FORCE_SOURCE_BUILD=0
ARG BLENDER_BUILD_JOBS=
ENV HOME=/opt/blenderhome \
    BLENDER_SOURCE_DIR=/opt/blender-source \
    BLENDER_FORCE_SOURCE_BUILD=${BLENDER_FORCE_SOURCE_BUILD} \
    BLENDER_BUILD_JOBS=${BLENDER_BUILD_JOBS}

# Only the pieces the build needs - keeps this layer independent of app source.
COPY .devcontainer/blender.env .devcontainer/build-blender.sh /opt/devcontainer/

RUN bash /opt/devcontainer/build-blender.sh \
    # build-blender.sh leaves $HOME/.local/bin/blender symlinked at the real
    # binary; its parent dir is a complete, relocatable install on both paths.
    && install_dir="$(dirname "$(readlink -f "$HOME/.local/bin/blender")")" \
    && cp -a "$install_dir" /opt/blender \
    && /opt/blender/blender --version

# ---------------------------------------------------------------------------
# Stage 2 - runtime. Slim Python + Blender's shared-library dependencies,
# the agent packages, and the blender-mcp extension pre-installed into the
# runtime user's Blender config so `--command blender_mcp` resolves.
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim-trixie AS runtime

# Shared libraries Blender links against (superset of build-blender.sh's
# amd64 runtime set, plus the windowing libs a from-source arm64 build wants).
# The agent only ever launches Blender in --background, so no display server,
# Vulkan/GL stack, or Weston is required.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libx11-6 libxi6 libxxf86vm1 libxfixes3 libxrender1 \
        libxrandr2 libxinerama1 libxcursor1 \
        libgl1 libegl1 libsm6 libxkbcommon0 libgomp1 \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=blender-build /opt/blender /opt/blender
RUN ln -sf /opt/blender/blender /usr/local/bin/blender

# Non-root runtime user. HOME must match at build time (extension install)
# and run time (agent spawns Blender, which reads this user's config).
ARG APP_USER=app
ARG APP_UID=10001
RUN useradd --create-home --uid ${APP_UID} ${APP_USER}
ENV HOME=/home/${APP_USER}

WORKDIR /app
# Only what the runtime needs: the two installable packages and the add-on
# source (built into an extension below). Tests, ext/, chat_client are omitted.
COPY mcp/ /app/mcp/
COPY agent/ /app/agent/
COPY mcp_ext/ /app/mcp_ext/
COPY addon/ /app/addon/

RUN python -m pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir ./mcp ./agent ./mcp_ext \
    && chown -R ${APP_USER}:${APP_USER} /app

# Build and install the blender-mcp extension into the runtime user's
# Blender config (HOME), mirroring the test harness. With the extension
# enabled in user prefs, a later `blender --background --command blender_mcp`
# (which the agent spawns) loads it without --factory-startup.
USER ${APP_USER}
# NOTE: `extension build` does NOT create --output-dir (it writes the
# archive as a dotfile inside it first, failing with a confusing
# ".mcp-*.zip: No such file or directory" when the dir is missing).
RUN mkdir -p /tmp/ext \
    && blender --command extension build \
        --source-dir=/app/addon/blender_mcp_addon \
        --output-dir=/tmp/ext \
    && blender --online-mode --background --factory-startup \
        --command extension install-file \
        "$(ls /tmp/ext/mcp-*.zip | head -n1)" \
        --repo user_default --enable \
    && rm -rf /tmp/ext

# Persisted agent state (transcripts, skills, media) lives here; mount a
# volume at /data in production for durability.
USER root
RUN mkdir -p /data && chown ${APP_USER}:${APP_USER} /data
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENV BLENDER_PATH=/usr/local/bin/blender \
    XDG_DATA_HOME=/data \
    BLENDER_AGENT_HOST=0.0.0.0 \
    BLENDER_AGENT_PORT=10102 \
    BLENDER_AGENT_NO_PORT_AUTO=1 \
    PYTHONUNBUFFERED=1

USER ${APP_USER}
# Web UI / chat-completions API; MCP-over-HTTP (10101) is opt-in via env.
EXPOSE 10102 10101
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
