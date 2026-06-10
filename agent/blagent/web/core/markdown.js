// SPDX-License-Identifier: GPL-3.0-or-later
//
// Markdown + syntax highlight for chat bodies, ported from Foyer
// Studio's `core/markdown.js`.
//
// marked + hljs ship as UMD globals (vendored browser builds), loaded
// lazily via <script> tags on first render and adopted from
// `window.marked` / `window.hljs`. The highlight stylesheet swaps
// between light and dark variants with the active theme.

import { effectiveTheme, onThemeChange } from "/static/core/theme.js";

const MARKED_URL = "/static/vendor/marked.min.js";
const HLJS_URL = "/static/vendor/highlight.min.js";
const HLJS_EXTRA_URLS = [
  "/static/vendor/hljs-yaml.min.js",
  "/static/vendor/hljs-glsl.min.js",
];
const HLJS_CSS = {
  light: "/static/vendor/highlight-light.css",
  dark: "/static/vendor/highlight-dark.css",
};

let _ready = null;
let _configured = false;

function loadScript(url) {
  return new Promise((resolve, reject) => {
    const existing = document.querySelector(`script[data-ba-md="${url}"]`);
    if (existing) {
      if (existing.dataset.loaded === "true") resolve();
      else {
        existing.addEventListener("load", () => resolve(), { once: true });
        existing.addEventListener("error", () => reject(new Error(`failed to load ${url}`)), { once: true });
      }
      return;
    }
    const s = document.createElement("script");
    s.src = url;
    s.async = false;
    s.dataset.baMd = url;
    s.addEventListener("load", () => { s.dataset.loaded = "true"; resolve(); }, { once: true });
    s.addEventListener("error", () => reject(new Error(`failed to load ${url}`)), { once: true });
    document.head.appendChild(s);
  });
}

function applyHighlightCss() {
  const url = HLJS_CSS[effectiveTheme()] || HLJS_CSS.dark;
  let link = document.querySelector("link[data-ba-hljs]");
  if (!link) {
    link = document.createElement("link");
    link.rel = "stylesheet";
    link.dataset.baHljs = "true";
    document.head.appendChild(link);
  }
  if (link.getAttribute("href") !== url) link.setAttribute("href", url);
}

onThemeChange(() => applyHighlightCss());

/**
 * Kick off lazy load (idempotent). Resolves when `window.marked` (and,
 * best-effort, `window.hljs`) are ready.
 */
export function ensureMarkdownReady() {
  if (_ready) return _ready;
  _ready = (async () => {
    await loadScript(MARKED_URL);
    try {
      applyHighlightCss();
      await loadScript(HLJS_URL);
      for (const url of HLJS_EXTRA_URLS) await loadScript(url);
    } catch {
      // hljs/grammar not present - fenced code renders plain.
    }
    configureMarked();
  })();
  return _ready;
}

function configureMarked() {
  if (_configured) return;
  if (typeof window.marked === "undefined") return;
  window.marked.setOptions({ breaks: false, gfm: true });
  if (typeof window.hljs !== "undefined") {
    const renderer = {
      code(token) {
        const lang = (token.lang || "").toLowerCase();
        const code = token.text || "";
        if (lang && window.hljs.getLanguage(lang)) {
          try {
            const hl = window.hljs.highlight(code, { language: lang }).value;
            return `<pre><code class="hljs language-${lang}">${hl}</code></pre>`;
          } catch {}
        }
        return `<pre><code>${escapeHtml(code)}</code></pre>`;
      },
    };
    window.marked.use({ renderer });
  }
  _configured = true;
}

export function escapeHtml(s) {
  const table = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  return (s || "").replace(/[&<>"']/g, (c) => table[c]);
}

/**
 * Render markdown to an HTML string. Falls back to escaped plain text
 * until the libraries are loaded; await `ensureMarkdownReady()` first
 * for the richest output.
 */
export function renderMarkdown(md) {
  const input = md || "";
  if (typeof window.marked === "undefined") {
    return `<pre>${escapeHtml(input)}</pre>`;
  }
  configureMarked();
  try {
    return window.marked.parse(input);
  } catch (err) {
    console.warn("[markdown] parse failed:", err);
    return escapeHtml(input);
  }
}
