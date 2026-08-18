# SPDX-FileCopyrightText: 2026 agentcore contributors
#
# SPDX-License-Identifier: MIT OR Apache-2.0

"""
The vendored ACP schema, pinned by commit sha.

``v2.schema.json`` / ``v2.meta.json`` are copies of the upstream v2 UNSTABLE
schema (Apache-2.0), taken at ``regen.PINNED_SHA``. They are checked in on
purpose: v2 is a draft whose types are renamed between alphas, so the version
we generate against has to be a deliberate, auditable choice rather than
whatever upstream happens to be serving today.

See ``regen.py`` to re-vendor or regenerate.
"""

__all__ = ()
