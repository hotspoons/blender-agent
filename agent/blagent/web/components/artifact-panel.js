// SPDX-License-Identifier: GPL-3.0-or-later
//
// Right panel: session media / generated artifacts, plus the WebLLM
// loader card. Designed to grow into a richer artifact browser later.

import { LitElement, html, css } from "lit";
import { store } from "/static/core/store.js";
import "/static/components/webllm-panel.js";

export class BaArtifactPanel extends LitElement {
  static properties = {
    _media: { state: true },
    _sessionId: { state: true },
  };

  constructor() {
    super();
    this._media = store.state.media;
    this._sessionId = store.state.sessionId;
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
    :host { display: block; padding: 12px; }
    h3 {
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--text-dim);
      margin: 14px 0 8px;
    }
    .grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
    }
    .card {
      border: 1px solid var(--border);
      border-radius: 8px;
      overflow: hidden;
      background: var(--bg-raised);
      cursor: pointer;
    }
    .card img { width: 100%; display: block; }
    .card .cap {
      font-size: 11px;
      color: var(--text-dim);
      padding: 4px 6px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .empty { color: var(--text-dim); font-size: 12.5px; }
  `;

  render() {
    return html`
      <h3>Local model</h3>
      <ba-webllm-panel></ba-webllm-panel>
      <h3>Artifacts</h3>
      ${this._media.length === 0
        ? html`<div class="empty">Screenshots and renders produced by the agent appear here.</div>`
        : html`
          <div class="grid">
            ${this._media.map((m) => html`
              <div class="card" @click=${() => window.open(`/media/${this._sessionId}/${m.id}`, "_blank")}>
                <img src="/media/${this._sessionId}/${m.id}" alt=${m.id} loading="lazy">
                <div class="cap">${m.id} · ${m.label || m.mime}</div>
              </div>`)}
          </div>`}
    `;
  }
}

customElements.define("ba-artifact-panel", BaArtifactPanel);
