// SPDX-License-Identifier: GPL-3.0-or-later
//
// Theme system, ported from Foyer Studio's `ui-core/theme.js`:
// `[data-theme="..."]` scopes on <html>, localStorage persistence, and
// an "auto" mode that follows the system preference (the default).

export const THEMES = ["auto", "light", "dark"];

export const THEME_META = {
  auto: { icon: "◑", label: "Auto" },
  light: { icon: "☀", label: "Light" },
  dark: { icon: "☾", label: "Dark" },
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
