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

// Highlight colors must reach shadow DOM, where document <link>
// stylesheets do not apply. A single constructable stylesheet is
// shared with every component that calls `adoptHighlightStyles`, and
// its contents swap with the theme.
const _hljsSheet = typeof CSSStyleSheet !== "undefined" ? new CSSStyleSheet() : null;

async function applyHighlightCss() {
  const url = HLJS_CSS[effectiveTheme()] || HLJS_CSS.dark;
  if (!_hljsSheet) return;
  try {
    const response = await fetch(url);
    _hljsSheet.replaceSync(await response.text());
  } catch {
    // Highlighting becomes plain; not fatal.
  }
}

// Styling for rendered markdown bodies (everything `renderMarkdown`
// wraps in `.md-content`). Tables especially: marked emits bare GFM
// tables and browser defaults look broken next to the styled chat.
// Theme custom properties inherit through shadow boundaries, so one
// static sheet follows all three themes for free.
const _MD_CSS = `
  .md-content > :first-child { margin-top: 0; }
  .md-content > :last-child { margin-bottom: 0; }
  .md-content table {
    display: block;
    width: max-content;
    max-width: 100%;
    overflow-x: auto;
    overflow-y: hidden;
    border-spacing: 0;
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    margin: 12px 0;
    font-size: 0.93em;
    line-height: 1.45;
  }
  .md-content th, .md-content td {
    padding: 7px 14px;
    text-align: left;
    vertical-align: top;
  }
  .md-content thead th {
    background: var(--surface-elevated);
    font-weight: 600;
    white-space: nowrap;
  }
  .md-content tbody td { border-top: 1px solid var(--border); }
  .md-content tbody tr:nth-child(even) { background: rgba(128, 128, 128, 0.05); }
  .md-content blockquote {
    margin: 10px 0;
    padding: 4px 14px;
    border-left: 3px solid var(--accent);
    border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
    background: var(--surface-elevated);
    color: var(--text-muted);
  }
  .md-content hr { border: none; border-top: 1px solid var(--border); margin: 14px 0; }
`;
const _mdSheet = typeof CSSStyleSheet !== "undefined" ? new CSSStyleSheet() : null;
if (_mdSheet) _mdSheet.replaceSync(_MD_CSS);

/**
 * Adopt the shared markdown stylesheets (theme-following highlight
 * colors + `.md-content` body styles) into a shadow root. Call from
 * any component that renders `renderMarkdown` output.
 */
export function adoptHighlightStyles(root) {
  if (!root) return;
  for (const sheet of [_hljsSheet, _mdSheet]) {
    if (sheet && !root.adoptedStyleSheets.includes(sheet)) {
      root.adoptedStyleSheets = [...root.adoptedStyleSheets, sheet];
    }
  }
}

onThemeChange(() => { applyHighlightCss(); });

/**
 * Kick off lazy load (idempotent). Resolves when `window.marked` (and,
 * best-effort, `window.hljs`) are ready.
 */
export function ensureMarkdownReady() {
  if (_ready) return _ready;
  _ready = (async () => {
    await loadScript(MARKED_URL);
    try {
      await applyHighlightCss();
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
    return `<div class="md-content"><pre>${escapeHtml(input)}</pre></div>`;
  }
  configureMarked();
  try {
    return `<div class="md-content">${window.marked.parse(input)}</div>`;
  } catch (err) {
    console.warn("[markdown] parse failed:", err);
    return `<div class="md-content">${escapeHtml(input)}</div>`;
  }
}
