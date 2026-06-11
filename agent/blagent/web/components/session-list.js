// SPDX-License-Identifier: GPL-3.0-or-later
//
// Left rail: conversation sessions as platform-style nav items.

import { LitElement, html, css } from "lit";
import { store } from "/static/core/store.js";
import { icon } from "/static/core/icons.js";

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
    *, *::before, *::after { box-sizing: border-box; }
    :host { display: block; padding: 4px 8px 10px; font-family: var(--font-sans); }
    .new {
      display: flex;
      align-items: center;
      gap: 8px;
      width: 100%;
      font: inherit;
      font-size: 13.5px;
      font-weight: 500;
      color: var(--text);
      background: var(--accent-soft);
      border: 1px solid transparent;
      border-radius: var(--radius-md);
      padding: 8px 12px;
      cursor: pointer;
      margin-bottom: 10px;
      transition: border-color 0.15s ease;
    }
    .new:hover { border-color: var(--accent); }
    h3 {
      font-size: 11px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--text-muted);
      margin: 6px 10px 6px;
    }
    .item {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 7px 10px;
      border-radius: var(--radius-sm);
      cursor: pointer;
      color: var(--text-muted);
      margin-bottom: 1px;
      font-size: 13.5px;
    }
    .item:hover { background: var(--accent-soft); color: var(--text); }
    .item.active {
      background: var(--accent-soft);
      color: var(--text);
      box-shadow: inset 2px 0 0 var(--accent);
    }
    .item .label {
      flex: 1;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .item .del {
      display: inline-flex;
      visibility: hidden;
      border: none;
      background: none;
      color: var(--text-muted);
      cursor: pointer;
      padding: 2px;
      border-radius: var(--radius-sm);
    }
    .item:hover .del { visibility: visible; }
    .item .del:hover { color: var(--danger); }
    .empty { color: var(--text-muted); font-size: 12.5px; padding: 4px 10px; }
  `;

  render() {
    return html`
      <button class="new" @click=${() => store.newSession()}>${icon("plus")} New session</button>
      <h3>Sessions</h3>
      ${this._sessions.length === 0 ? html`<div class="empty">No sessions yet.</div>` : ""}
      ${this._sessions.map((s) => html`
        <div class="item ${s.id === this._current ? "active" : ""}"
             @click=${() => store.loadSession(s.id)}>
          <span class="label" title=${s.title}>${s.title}</span>
          <button class="del" title="Delete session"
            @click=${(e) => { e.stopPropagation(); store.deleteSession(s.id); }}>${icon("trash")}</button>
        </div>
      `)}
    `;
  }
}

customElements.define("ba-session-list", BaSessionList);
