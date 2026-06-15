// SPDX-FileCopyrightText: 2026 agentcore contributors
//
// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Media-viewer registry: the generic core renders images and a
// download chip; domain UI extensions register richer viewers (e.g.
// the Blender build's `ba-stl-viewer` for `model/stl`) WITHOUT core
// hardcoding any domain mime type. Components ask the registry to
// render a thumbnail / full view by (mime, name); the registry picks
// the most-specific registered viewer.
//
// A viewer is:
//   {
//     id,                                  // unique key
//     match(mime, name) -> bool,           // claim this media?
//     thumb({ src, label, onZoom }) -> TemplateResult,   // strip thumbnail
//     full({ src, label }) -> TemplateResult,            // lightbox body
//   }
// `onZoom(detail)` opens the lightbox; `detail` is `{ src, alt, kind }`.

import { html } from "lit";
import { icon } from "/static/core/icons.js";

// Newest registration wins (unshift + find-first), so a domain extension
// loaded after core overrides the core defaults for an overlapping mime.
const _viewers = [];

export function registerMediaViewer(viewer) {
  _viewers.unshift(viewer);
}

export function pickMediaViewer(mime, name) {
  return _viewers.find((v) => {
    try { return v.match(mime || "", name || ""); } catch { return false; }
  }) || null;
}

/** Render a strip thumbnail for a media id (no mime known) or a
 *  {mime, name} pair. `onZoom` receives the lightbox detail. */
export function renderMediaThumb({ mime, name, src, onZoom }) {
  const v = pickMediaViewer(mime, name) || _fileChip;
  return v.thumb({ src, label: name, onZoom: onZoom || (() => {}) });
}

/** Render the full (lightbox) view. `kind` (the viewer id stamped onto
 *  the zoom detail) selects the viewer directly; otherwise fall back to
 *  matching by {mime, name}. */
export function renderMediaFull({ mime, name, src, kind }) {
  let v = kind ? _viewers.find((x) => x.id === kind) : null;
  if (!v) v = pickMediaViewer(mime, name) || _fileChip;
  return v.full({ src, label: name });
}

// --- core defaults ---------------------------------------------------------
// Short ids (i<N>) are always tool-rendered images; named files match by
// extension or mime. This heuristic is domain-neutral.
const _isImage = (mime, name) =>
  (mime && mime.startsWith("image/")) ||
  /^i\d+$/.test(name || "") ||
  /\.(png|jpe?g|webp|gif|bmp|svg)$/i.test(name || "");

const _imageViewer = {
  id: "image",
  match: _isImage,
  thumb: ({ src, label, onZoom }) => html`
    <img src=${src} alt=${label || ""} title=${label || ""} loading="lazy"
      @click=${() => onZoom({ src, alt: label, kind: "image" })}>`,
  full: ({ src, label }) => html`<img src=${src} alt=${label || ""}>`,
};

const _fileChip = {
  id: "file",
  match: () => true,
  thumb: ({ src, label }) => html`
    <a class="file-chip" href=${src} download=${label || ""} title=${label || ""}>
      ${icon("arrow-down-tray")} ${label || "download"}</a>`,
  full: ({ src, label }) => html`
    <a class="file-chip" href=${src} download=${label || ""} target="_blank" rel="noopener">
      ${icon("arrow-down-tray")} ${label || "download"}</a>`,
};

// Register the catch-all first so it sits at the bottom of the stack,
// then the image viewer on top of it.
registerMediaViewer(_fileChip);
registerMediaViewer(_imageViewer);
