# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Golden corpus: procedural asset generators (deterministic — no binary
.blend files in git). Every production failure should add an asset here.
"""

__all__ = (
    "CORPUS",
    "build",
)

from .assets import CORPUS as _MECHANICAL
from .characters import CHARACTERS as _CHARACTERS

CORPUS = {**_MECHANICAL, **_CHARACTERS}


def build(name: str) -> dict:
    """
    Build corpus asset *name* into the current scene; returns its manifest
    (object names + ground-truth annotations the tests assert against).
    """
    return CORPUS[name]()
