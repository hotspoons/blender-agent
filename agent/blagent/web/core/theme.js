// SPDX-License-Identifier: GPL-3.0-or-later
//
// Theme system, ported from Foyer Studio's `ui-core/theme.js`:
// `[data-theme="..."]` scopes on <html>, localStorage persistence, and
// an "auto" mode that follows the system preference (the default).

export const THEMES = ["auto", "light", "dark", "dim"];

export const THEME_META = {
  auto: { icon: "◑", label: "Auto" },
  light: { icon: "☀", label: "Light" },
  dark: { icon: "☾", label: "Dark" },
  dim: { icon: "✦", label: "Dim" },
};

const STORAGE_KEY = "blender-agent.theme";
const EVT = "ba:theme-change";

export function getTheme() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw && THEMES.includes(raw)) return raw;
  } catch {}
  return "auto";
}

/** Resolve "auto" to a concrete theme using prefers-color-scheme. */
export function effectiveTheme(raw) {
  const t = raw || getTheme();
  if (t === "auto") {
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  return t;
}

export function setTheme(name) {
  if (!THEMES.includes(name)) return;
  try { localStorage.setItem(STORAGE_KEY, name); } catch {}
  applyTheme();
  window.dispatchEvent(new CustomEvent(EVT, { detail: { theme: name } }));
}

export function cycleTheme() {
  const cur = getTheme();
  const next = THEMES[(THEMES.indexOf(cur) + 1) % THEMES.length];
  setTheme(next);
  return next;
}

export function applyTheme() {
  document.documentElement.setAttribute("data-theme", effectiveTheme());
}

export function onThemeChange(fn) {
  window.addEventListener(EVT, fn);
  return () => window.removeEventListener(EVT, fn);
}

// ------------------------------------------------------------------
// Frost (overlay backdrop) tuning - a hidden console API for design
// experiments. Not surfaced in the UI; from devtools:
//
//   blenderAgent.frost({ tint: "rgba(20,0,40,0.5)", blur: "6px", saturate: "140%" })
//   blenderAgent.frost()        // show current values
//   blenderAgent.resetFrost()   // back to theme defaults
//
// Overrides persist in localStorage and re-apply on boot.

const FROST_KEY = "blender-agent.frost";
const FROST_PROPS = { tint: "--overlay-tint", blur: "--overlay-blur", saturate: "--overlay-saturate" };

export function applyFrost() {
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(FROST_KEY) || "null"); } catch {}
  for (const [key, prop] of Object.entries(FROST_PROPS)) {
    if (saved && saved[key]) document.documentElement.style.setProperty(prop, saved[key]);
    else document.documentElement.style.removeProperty(prop);
  }
}

export function setFrost(options) {
  if (!options) {
    const style = getComputedStyle(document.documentElement);
    const current = {};
    for (const [key, prop] of Object.entries(FROST_PROPS)) current[key] = style.getPropertyValue(prop).trim();
    return current;
  }
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(FROST_KEY) || "{}") || {}; } catch {}
  for (const key of Object.keys(FROST_PROPS)) {
    if (options[key] !== undefined) saved[key] = options[key];
  }
  try { localStorage.setItem(FROST_KEY, JSON.stringify(saved)); } catch {}
  applyFrost();
  return saved;
}

export function resetFrost() {
  try { localStorage.removeItem(FROST_KEY); } catch {}
  applyFrost();
}

// Auto-respond to system preference changes when the theme is 'auto'.
if (typeof window !== "undefined" && window.matchMedia) {
  const mq = window.matchMedia("(prefers-color-scheme: dark)");
  mq.addEventListener?.("change", () => {
    if (getTheme() === "auto") {
      applyTheme();
      window.dispatchEvent(new CustomEvent(EVT, { detail: { theme: "auto" } }));
    }
  });
}
