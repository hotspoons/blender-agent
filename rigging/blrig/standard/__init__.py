# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
The rig standard: conventions (see ``RIG_STANDARD.md``) and their enforcement.
"""

__all__ = (
    "bone_class",
    "validate_rig",
    "validate_weights",
)

from .validate import bone_class, validate_rig, validate_weights
