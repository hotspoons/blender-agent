# SPDX-FileCopyrightText: 2026 agentcore contributors
#
# SPDX-License-Identifier: MIT OR Apache-2.0

"""
agentcore — a domain-agnostic agent harness (engine, tools, transports,
orchestration, UI shell). A domain (e.g. the Blender build ``blagent``) binds
to it through the ``ToolBackend`` boundary; agentcore never imports domain code.

Dual-licensed MIT OR Apache-2.0 so it can be reused freely and spun out to its
own repository; the Blender build that depends on it stays GPL-3.0-or-later.
"""
