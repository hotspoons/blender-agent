// SPDX-License-Identifier: GPL-3.0-or-later
//
// Right rail: session media / generated artifacts. (The local-model
// controls live in the settings dialog; the header chip shows status.)

import { LitElement, html, css, nothing } from "lit";
import { store } from "/static/core/store.js";
import { icon } from "/static/core/icons.js";
import "/static/core/widgets.js";
import "/static/components/stl-viewer.js";

export class BaArtifactPanel extends LitElement {
  static properties = {
    _media: { state: true },
    _sessionId: { state: true },
    _lightbox: { state: true },
  };

  constructor() {
    super();
    this._media = store.state.media;
    this._sessionId = store.state.sessionId;
    this._lightbox = null;
  }

  connectedCallback() {
    super.connectedCallback();
    this._unsub = store.subscribe((keys) => {
      if (keys.has("media")) this._media = [...store.state.media];
      if (keys.has("sessionId")) this._sessionId = store.state.sessionId;
    });
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this._unsub?.();
  }

  static styles = css`
    *, *::before, *::after { box-sizing: border-box; }
    :host { display: block; padding: 14px; font-family: var(--font-sans); }
    h3 {
      display: flex;
      align-items: center;
      gap: 7px;
      font-size: 11px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--text-muted);
      margin: 4px 0 10px;
    }
    .grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
    }
    .card {
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      overflow: hidden;
      background: var(--surface);
      cursor: pointer;
      transition: border-color 0.15s ease;
    }
    .card:hover { border-color: var(--accent); }
    .card img { width: 100%; display: block; }
    .card ba-stl-viewer { width: 100%; height: 110px; display: block; }
    .card .filelink {
      display: block;
      padding: 14px 10px;
      text-align: center;
      font-size: 12px;
      color: var(--accent);
      text-decoration: none;
    }
    .card .cap {
      font-size: 11px;
      color: var(--text-muted);
      padding: 4px 7px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .empty { color: var(--text-muted); font-size: 12.5px; }
  `;

  render() {
    return html`
      <h3>${icon("photo")} Artifacts</h3>
      ${this._media.length === 0
        ? html`<div class="empty">Screenshots and renders produced by the agent appear here.</div>`
        : html`
          <div class="grid">
            ${this._media.map((m) => html`
              <div class="card" @click=${() => {
                if (!(m.mime || "").startsWith("image/")) return;
                this._lightbox = { src: `/media/${this._sessionId}/${m.id}`, alt: `${m.id} · ${m.label || m.mime}` };
              }}>
                ${(m.mime || "").startsWith("image/")
                  ? html`<img src="/media/${this._sessionId}/${m.id}" alt=${m.id} loading="lazy">`
                  : m.mime === "model/stl"
                    ? html`<ba-stl-viewer thumb .src=${`/media/${this._sessionId}/${m.id}`} .label=${m.id}
                        @zoom=${(e) => { this._lightbox = e.detail; }}></ba-stl-viewer>`
                    : html`<a class="filelink" href="/media/${this._sessionId}/${m.id}" download=${m.id}>download</a>`}
                <div class="cap">${m.id} · ${m.label || m.mime}</div>
              </div>`)}
          </div>`}
      ${this._lightbox ? html`
        <ba-lightbox .src=${this._lightbox.src} .alt=${this._lightbox.alt}
          .kind=${this._lightbox.kind || ""}
          @close=${() => { this._lightbox = null; }}></ba-lightbox>` : nothing}
    `;
  }
}

customElements.define("ba-artifact-panel", BaArtifactPanel);
