// SPDX-License-Identifier: GPL-3.0-or-later
//
// The Blender UI extension. Everything in this file is Blender-specific
// and would NOT ship with another agentcore build: the logo mark, the
// brand/welcome copy, and the `model/stl` 3D viewer. The generic shell
// (core/, components/) carries none of it — it asks the profile for
// branding and the media-viewer registry for how to render a file.
//
// index.html imports this module BEFORE app.js, so the profile and the
// viewer registry are populated before the first render. Swapping this
// one import (or having the server name a different extension) rebrands
// the whole app.

import { svg } from "lit";
import { html } from "lit";
import { applyProfile } from "/static/core/profile.js";
import { registerMediaViewer } from "/static/core/media-viewers.js";

// The Blender brand mark: an isometric cube in the Blender palette
// (PMS 716 orange / PMS 647 blue / white), edge seams picked out in
// white like an edit-mode selection. Deliberately NOT the Blender logo —
// the trademark policy reserves the orb for the Foundation, the colors
// are fair game. Kept in sync with the favicon in index.html.
const blenderMark = svg`
  <svg viewBox="0 0 24 24" width="100%" height="100%" role="img" aria-label="Blender Agent">
    <path fill="#f5a623" d="M12 3 20 7.5 12 12 4 7.5Z"/>
    <path fill="#e87d0d" d="M4 7.5 12 12 12 21 4 16.5Z"/>
    <path fill="#265787" d="M12 12 20 7.5 20 16.5 12 21Z"/>
    <path stroke="#fff" stroke-width="1.1" stroke-linecap="round" fill="none"
      d="M12 12 4 7.5 M12 12 20 7.5 M12 12 12 21"/>
    <circle cx="12" cy="12" r="1.8" fill="#fff"/>
  </svg>`;

// Same geometry as `blenderMark`, inlined for the tab icon.
const blenderFavicon =
  "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'>" +
  "<path fill='%23f5a623' d='M12 3 20 7.5 12 12 4 7.5Z'/>" +
  "<path fill='%23e87d0d' d='M4 7.5 12 12 12 21 4 16.5Z'/>" +
  "<path fill='%23265787' d='M12 12 20 7.5 20 16.5 12 21Z'/>" +
  "<path stroke='%23fff' stroke-width='1.1' stroke-linecap='round' fill='none' d='M12 12 4 7.5 M12 12 20 7.5 M12 12 12 21'/>" +
  "<circle cx='12' cy='12' r='1.8' fill='%23fff'/></svg>";

applyProfile({
  title: "Blender Agent",
  brand: { word: "Blender", rest: " Agent" },
  mark: blenderMark,
  favicon: blenderFavicon,
  welcome: {
    word: "Blender",
    rest: " Agent",
    body: "Connected to your Blender session through the MCP tool surface.",
    hint: 'Try: "what\'s in my scene?" or "make the selected mesh manifold".',
  },
  composerPlaceholder: "Ask the Blender agent…",
  swarmBlurb: "Parallel workers, each its own headless Blender, merged at the end.",
});

// `model/stl` exports get an interactive 3D thumbnail (and lightbox),
// backed by the vendored three.js viewer. Loading this registers the
// custom element too.
import "/static/components/stl-viewer.js";

const _isStl = (mime, name) => mime === "model/stl" || /\.stl$/i.test(name || "");

registerMediaViewer({
  id: "stl",
  match: _isStl,
  thumb: ({ src, label, onZoom }) => html`
    <ba-stl-viewer thumb .src=${src} .label=${label}
      @zoom=${(e) => onZoom(e.detail)}></ba-stl-viewer>`,
  full: ({ src, label }) => html`
    <div class="stage3d"><ba-stl-viewer .src=${src} .label=${label}></ba-stl-viewer></div>`,
});
