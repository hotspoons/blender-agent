// SPDX-License-Identifier: GPL-3.0-or-later
//
// Left panel: conversation sessions (new / switch / delete).

import { LitElement, html, css } from "lit";
import { store } from "/static/core/store.js";

export class BaSessionList extends LitElement {
  static properties = {
    _sessions: { state: true },
    _current: { state: true },
  };

  constructor() {
    super();
    this._sessions = store.state.sessions;
    this._current = store.state.sessionId;
  }

  connectedCallback() {
    super.connectedCallback();
    this._unsub = store.subscribe((keys) => {
      if (keys.has("sessions")) this._sessions = [...store.state.sessions];
      if (keys.has("sessionId")) this._current = store.state.sessionId;
    });
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this._unsub?.();
  }

  static styles = css`
    :host { display: block; padding: 10px; }
    button.new {
      width: 100%;
      padding: 8px;
      border-radius: 8px;
      border: 1px solid var(--border);
      background: var(--accent-soft);
      color: var(--text);
      cursor: pointer;
      font-weight: 600;
      margin-bottom: 10px;
    }
    button.new:hover { border-color: var(--accent); }
    .item {
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 8px 10px;
      border-radius: 8px;
      cursor: pointer;
      color: var(--text-dim);
      margin-bottom: 2px;
    }
    .item:hover { background: var(--bg-raised); }
    .item.active { background: var(--bg-raised); color: var(--text); }
    .item .label {
      flex: 1;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-size: 13px;
    }
    .item .del {
      visibility: hidden;
      border: none;
      background: none;
      color: var(--text-dim);
      cursor: pointer;
      font-size: 13px;
    }
    .item:hover .del { visibility: visible; }
    .item .del:hover { color: var(--err); }
    .empty { color: var(--text-dim); font-size: 12px; padding: 8px; }
  `;

  render() {
    return html`
      <button class="new" @click=${() => store.newSession()}>+ New session</button>
      ${this._sessions.length === 0 ? html`<div class="empty">No sessions yet.</div>` : ""}
      ${this._sessions.map((s) => html`
        <div class="item ${s.id === this._current ? "active" : ""}"
             @click=${() => store.loadSession(s.id)}>
          <span class="label" title=${s.title}>${s.title}</span>
          <button class="del" title="Delete session"
            @click=${(e) => { e.stopPropagation(); store.deleteSession(s.id); }}>✕</button>
        </div>
      `)}
    `;
  }
}

customElements.define("ba-session-list", BaSessionList);
