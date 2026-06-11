# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
``blrig``: deterministic rigging skills for LLM agents driving Blender.

This package runs inside Blender's Python interpreter. The LLM selects and
parameterizes skills; the code here owns every coordinate-level decision.

Sub-packages:

- ``blrig.perception``: pure geometric queries (no scene mutation).
- ``blrig.standard``: rig conventions + ``validate_rig()``.
- ``blrig.skills``: skill modules following the diagnose/run/verify contract.
"""

__all__ = (
    "__version__",
)

__version__ = "0.1.0"
