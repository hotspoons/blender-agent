// SPDX-License-Identifier: GPL-3.0-or-later
//
// The UI profile: all the brand/copy that makes the generic agentcore
// shell look like a *specific* agent. Core ships neutral defaults so an
// unbranded build is presentable; a domain UI extension overrides them
// with `applyProfile(...)` at boot, before any component renders (see
// extensions/blender.js). The server can also push a profile over the
// control socket so branding is YAML-configurable end to end.
//
// Visual assets that can't cross JSON (the logo mark, registered media
// viewers) are supplied by the extension module; plain text (brand
// words, welcome copy, placeholders) can come from either the extension
// or the server profile.

import { coreMark } from "/static/core/brand.js";

// The header / welcome render a colored `word` followed by plain `rest`.
const DEFAULT_PROFILE = {
  title: "Agent",                       // base for document.title
  brand: { word: "Agent", rest: "" },   // left-rail + empty-state heading
  mark: coreMark,                        // logo (lit svg template)
  welcome: {
    word: "Agent",
    rest: "",
    body: "Connected. Ask for anything and I'll get to work.",
    hint: "",
  },
  composerPlaceholder: "Ask the agent…",
  swarmBlurb: "Parallel workers, each running its own instance, merged at the end.",
  favicon: "",                           // data: URL; empty keeps index.html's
};

let _profile = DEFAULT_PROFILE;

/** Shallow-per-section merge: callers pass only what they override. */
export function applyProfile(partial) {
  if (!partial) return;
  _profile = {
    ..._profile,
    ...partial,
    brand: { ..._profile.brand, ...(partial.brand || {}) },
    welcome: { ..._profile.welcome, ...(partial.welcome || {}) },
  };
  if (partial.title) {
    try { document.title = partial.title; } catch {}
  }
  if (partial.favicon) {
    try {
      let link = document.querySelector('link[rel="icon"]');
      if (!link) {
        link = document.createElement("link");
        link.rel = "icon";
        document.head.appendChild(link);
      }
      link.href = partial.favicon;
    } catch {}
  }
}

export function getProfile() {
  return _profile;
}
