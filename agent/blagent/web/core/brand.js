// SPDX-License-Identifier: GPL-3.0-or-later
//
// The agent's own mark: an isometric cube in the Blender brand palette
// (PMS 716 orange / PMS 647 blue / white), edge seams and front vertex
// picked out in white like an edit-mode selection. Deliberately NOT
// the Blender logo - the trademark policy reserves the orb for the
// Foundation, but the colors are fair game.
//
// The same geometry is inlined as the favicon in index.html; keep the
// two in sync when editing.

import { svg } from "lit";

export const brandMark = svg`
  <svg viewBox="0 0 24 24" width="100%" height="100%" role="img" aria-label="Blender Agent">
    <path fill="#f5a623" d="M12 3 20 7.5 12 12 4 7.5Z"/>
    <path fill="#e87d0d" d="M4 7.5 12 12 12 21 4 16.5Z"/>
    <path fill="#265787" d="M12 12 20 7.5 20 16.5 12 21Z"/>
    <path stroke="#fff" stroke-width="1.1" stroke-linecap="round" fill="none"
      d="M12 12 4 7.5 M12 12 20 7.5 M12 12 12 21"/>
    <circle cx="12" cy="12" r="1.8" fill="#fff"/>
  </svg>`;
