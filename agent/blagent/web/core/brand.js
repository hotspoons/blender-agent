// SPDX-License-Identifier: GPL-3.0-or-later
//
// The NEUTRAL core mark for an unbranded `agentcore` build: a simple
// rounded glyph in the accent color. Domain builds replace it with their
// own logo via `applyProfile({ mark })` (see core/profile.js); the
// Blender cube lives in extensions/blender.js, not here, so core ships
// no domain-specific artwork.

import { svg } from "lit";

export const coreMark = svg`
  <svg viewBox="0 0 24 24" width="100%" height="100%" role="img" aria-label="Agent">
    <rect x="3" y="3" width="18" height="18" rx="5" fill="var(--brand, #5b8def)"/>
    <circle cx="12" cy="12" r="3.4" fill="#fff"/>
  </svg>`;
