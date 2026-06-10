// SPDX-License-Identifier: GPL-3.0-or-later
//
// App shell: header + three panes (sessions | conversation | artifacts),
// the standard chat layout with a hidable left panel and a right panel
// for media and generated artifacts.

import { LitElement, html, css, nothing } from "lit";
import { store } from "/static/core/store.js";
import { getTheme, cycleTheme, THEME_META, onThemeChange } from "/static/core/theme.js";
import "/static/components/session-list.js";
import "/static/components/chat-stage.js";
import "/static/components/composer.js";
import "/static/components/artifact-panel.js";
import "/static/components/settings-modal.js";

export class BaApp extends LitElement {
  static properties = {
    _showLeft: { state: true },
    _showRight: { state: true },
    _showSettings: { state: true },
    _theme: { state: true },
    _connected: { state: true },
    _webllm: { state: true },
  };

  constructor() {
    super();
    this._showLeft = window.innerWidth > 900;
    this._showRight = window.innerWidth > 1200;
    this._showSettings = false;
    this._theme = getTheme();
    this._connected = false;
    this._webllm = store.state.webllm;
    this._unsubs = [];
  }

  connectedCallback() {
    super.connectedCallback();
    store.connect();
    this._unsubs.push(store.subscribe((keys) => {
      if (keys.has("connected")) this._connected = store.state.connected;
      if (keys.has("webllm")) this._webllm = store.state.webllm;
    }));
    this._unsubs.push(onThemeChange(() => { this._theme = getTheme(); }));
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    for (const unsub of this._unsubs) unsub();
  }

  static styles = css`
    :host {
      display: grid;
      grid-template-rows: 44px 1fr;
      height: 100%;
    }
    header {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 0 12px;
      background: var(--bg-panel);
      border-bottom: 1px solid var(--border);
    }
    header .title {
      font-weight: 650;
      letter-spacing: 0.02em;
    }
    header .title .accent { color: var(--accent); }
    .spacer { flex: 1; }
    .chip {
      font-size: 12px;
      color: var(--text-dim);
      border: 1px solid var(--border);
      border-radius: 999px;
      padding: 2px 10px;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      white-space: nowrap;
    }
    .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--err); }
    .dot.on { background: var(--ok); }
    button.icon {
      background: none;
      border: 1px solid var(--border);
      border-radius: 6px;
      color: var(--text);
      padding: 4px 9px;
      cursor: pointer;
      font-size: 13px;
    }
    button.icon:hover { background: var(--bg-raised); }
    main {
      display: grid;
      grid-template-columns: auto 1fr auto;
      min-height: 0;
    }
    aside {
      background: var(--bg-panel);
      min-height: 0;
      overflow-y: auto;
    }
    aside.left { width: 250px; border-right: 1px solid var(--border); }
    aside.right { width: 320px; border-left: 1px solid var(--border); }
    .stage {
      display: grid;
      grid-template-rows: 1fr auto;
      min-width: 0;
      min-height: 0;
    }
  `;

  render() {
    const themeMeta = THEME_META[this._theme];
    return html`
      <header>
        <button class="icon" title="Toggle sessions panel"
          @click=${() => { this._showLeft = !this._showLeft; }}>☰</button>
        <span class="title"><span class="accent">Blender</span> Agent</span>
        <span class="chip"><span class="dot ${this._connected ? "on" : ""}"></span>
          ${this._connected ? "connected" : "reconnecting"}</span>
        ${this._webllm.connected ? html`
          <span class="chip" title="In-browser LLM bridge">
            <span class="dot ${this._webllm.status === "ready" ? "on" : ""}"></span>
            WebLLM ${this._webllm.model_id || this._webllm.status}
          </span>` : nothing}
        <span class="spacer"></span>
        <button class="icon" title="Theme: ${themeMeta.label}"
          @click=${() => { cycleTheme(); }}>${themeMeta.icon} ${themeMeta.label}</button>
        <button class="icon" title="Artifacts panel"
          @click=${() => { this._showRight = !this._showRight; }}>🗀</button>
        <button class="icon" title="Settings"
          @click=${() => { this._showSettings = true; }}>⚙</button>
      </header>
      <main>
        ${this._showLeft ? html`<aside class="left"><ba-session-list></ba-session-list></aside>` : nothing}
        <div class="stage">
          <ba-chat-stage></ba-chat-stage>
          <ba-composer></ba-composer>
        </div>
        ${this._showRight ? html`<aside class="right"><ba-artifact-panel></ba-artifact-panel></aside>` : nothing}
      </main>
      ${this._showSettings ? html`
        <ba-settings-modal @close=${() => { this._showSettings = false; }}></ba-settings-modal>` : nothing}
    `;
  }
}

customElements.define("ba-app", BaApp);
