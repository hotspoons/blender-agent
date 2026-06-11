// SPDX-License-Identifier: GPL-3.0-or-later
//
// App shell: full-height left rail (brand / sessions / controls),
// center conversation column with a slim status bar, full-height
// right rail for artifacts. Composition follows Patapsco's
// platform-ui via Foyer Studio.

import { LitElement, html, css, nothing } from "lit";
import { store } from "/static/core/store.js";
import { icon } from "/static/core/icons.js";
import { brandMark } from "/static/core/brand.js";
import {
  getTheme, cycleTheme, THEME_META, onThemeChange,
  applyFrost, setFrost, resetFrost,
} from "/static/core/theme.js";

// Hidden design-tuning hooks (see theme.js): window.blenderAgent.frost(...).
applyFrost();
window.blenderAgent = Object.assign(window.blenderAgent || {}, {
  frost: setFrost,
  resetFrost,
});
import "/static/components/session-list.js";
import "/static/components/chat-stage.js";
import "/static/components/composer.js";
import "/static/components/artifact-panel.js";
import "/static/components/settings-modal.js";

const THEME_ICONS = { auto: "computer-desktop", light: "sun", dark: "moon", dim: "sparkles" };

export class BaApp extends LitElement {
  static properties = {
    _showLeft: { state: true },
    _showRight: { state: true },
    _showSettings: { state: true },
    _theme: { state: true },
    _connected: { state: true },
    _localLlm: { state: true },
    _config: { state: true },
  };

  constructor() {
    super();
    this._narrow = window.matchMedia("(max-width: 900px)");
    this._showLeft = !this._narrow.matches;
    this._showRight = window.innerWidth > 1200;
    this._showSettings = false;
    this._theme = getTheme();
    this._connected = false;
    this._localLlm = store.state.localLlm;
    this._config = store.state.config;
    this._unsubs = [];
    this._narrow.addEventListener?.("change", (e) => {
      // Leaving narrow mode restores the docked rail; entering narrow
      // mode hides it until explicitly opened (as an overlay drawer).
      this._showLeft = !e.matches;
      this.requestUpdate();
    });
  }

  connectedCallback() {
    super.connectedCallback();
    store.connect();
    this._unsubs.push(store.subscribe((keys) => {
      if (keys.has("connected")) this._connected = store.state.connected;
      if (keys.has("localLlm")) this._localLlm = { ...store.state.localLlm };
      if (keys.has("config")) this._config = { ...store.state.config };
      if (keys.has("instance")) {
        // Tab title follows the Blender instance (.blend file name) so
        // side-by-side agent tabs can be told apart; the bare port
        // disambiguates untitled instances.
        const { title, port } = store.state.instance;
        document.title = title
          ? `${title} - Blender Agent`
          : (port ? `Blender Agent :${port}` : "Blender Agent");
      }
    }));
    this._unsubs.push(onThemeChange(() => { this._theme = getTheme(); }));
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    for (const unsub of this._unsubs) unsub();
  }

  static styles = css`
    *, *::before, *::after { box-sizing: border-box; }
    :host {
      display: grid;
      grid-template-columns: auto 1fr auto;
      height: 100%;
      font-family: var(--font-sans);
    }
    aside {
      display: flex;
      flex-direction: column;
      min-height: 0;
      background: var(--surface-elevated);
    }
    aside.left { width: 248px; border-right: 1px solid var(--border); }
    aside.right { width: 320px; border-left: 1px solid var(--border); }

    /* Narrow viewports: the left rail becomes an overlay drawer that
       expands out over the content instead of squeezing it. */
    .backdrop {
      position: fixed;
      inset: 0;
      z-index: 59;
      background: var(--overlay-tint);
    }
    @media (max-width: 900px) {
      aside.left {
        position: fixed;
        z-index: 60;
        inset: 0 auto 0 0;
        box-shadow: var(--shadow-panel);
      }
      aside.right { width: min(320px, 86vw); }
    }

    .brand {
      display: flex;
      align-items: center;
      gap: 9px;
      padding: 16px 16px 12px;
      font-size: 16px;
      font-weight: 600;
      letter-spacing: 0.01em;
    }
    .brand .mark {
      width: 26px;
      height: 26px;
      display: inline-flex;
      flex: none;
    }
    .brand .word { color: var(--brand); }

    .rail-scroll { flex: 1; min-height: 0; overflow-y: auto; }

    .rail-foot {
      border-top: 1px solid var(--border);
      padding: 8px;
      display: flex;
      flex-direction: column;
      gap: 2px;
    }
    .foot-item {
      display: flex;
      align-items: center;
      gap: 9px;
      width: 100%;
      font: inherit;
      font-size: 13.5px;
      color: var(--text-muted);
      background: none;
      border: none;
      border-radius: var(--radius-sm);
      padding: 7px 10px;
      cursor: pointer;
      text-align: left;
    }
    .foot-item:hover { color: var(--text); background: var(--accent-soft); }
    .foot-item .dot {
      width: 7px; height: 7px; border-radius: 50%;
      background: var(--danger);
      margin-left: auto;
    }
    .foot-item .dot.on { background: var(--success); }

    .stage {
      display: grid;
      grid-template-rows: 46px 1fr auto;
      min-width: 0;
      min-height: 0;
      background: var(--surface);
    }
    /* Grid items default to min-height auto, which would let the
       transcript grow past the viewport and push the composer off
       screen - contain it so the transcript scrolls instead. */
    .stage ba-chat-stage { min-height: 0; min-width: 0; }
    .topbar { min-width: 0; overflow: hidden; }
    .topbar {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 0 12px;
      border-bottom: 1px solid var(--border);
    }
    .iconbtn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      color: var(--text-muted);
      background: none;
      border: none;
      border-radius: var(--radius-sm);
      padding: 6px;
      cursor: pointer;
    }
    .iconbtn:hover { color: var(--text); background: var(--accent-soft); }
    .chip {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 12px;
      color: var(--text-muted);
      border: 1px solid var(--border);
      border-radius: 999px;
      padding: 3px 10px;
      white-space: nowrap;
    }
    .chip .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--danger); }
    .chip .dot.on { background: var(--success); }
    .chip .dot.warm { background: var(--warning); }
    .spacer { flex: 1; }
  `;

  _modelChip() {
    const config = this._config || {};
    if (config.use_local_llm) {
      const state = this._localLlm.status === "ready" ? "on" : (this._localLlm.connected ? "warm" : "");
      return html`<span class="chip" title="Local in-browser model (Transformers.js)">
        ${icon("cpu-chip")} ${this._localLlm.model_id || "local model (none loaded)"}
        <span class="dot ${state}"></span></span>`;
    }
    if (config.endpoint) {
      return html`<span class="chip" title=${config.endpoint}>
        ${icon("arrow-top-right-on-square")} ${config.model || "remote model"}</span>`;
    }
    return html`<span class="chip">${icon("exclamation-triangle")} no model configured</span>`;
  }

  render() {
    return html`
      ${this._showLeft && this._narrow.matches ? html`
        <div class="backdrop" @click=${() => { this._showLeft = false; }}></div>` : nothing}
      ${this._showLeft ? html`
        <aside class="left">
          <div class="brand">
            <span class="mark">${brandMark}</span>
            <span><span class="word">Blender</span> Agent</span>
          </div>
          <div class="rail-scroll"><ba-session-list></ba-session-list></div>
          <div class="rail-foot">
            <button class="foot-item" @click=${() => { this._showSettings = true; }}>
              ${icon("cog-6-tooth")} Settings</button>
            <button class="foot-item" @click=${() => cycleTheme()}>
              ${icon(THEME_ICONS[this._theme])} Theme: ${THEME_META[this._theme].label}</button>
            <button class="foot-item" @click=${() => { this._showLeft = false; }}>
              ${icon("bars-3")} Collapse</button>
            <button class="foot-item" style="cursor: default;">
              ${icon("arrow-path")} ${this._connected ? "Connected" : "Reconnecting"}
              <span class="dot ${this._connected ? "on" : ""}"></span></button>
          </div>
        </aside>` : nothing}

      <div class="stage">
        <div class="topbar">
          ${!this._showLeft ? html`
            <button class="iconbtn" title="Show sessions" @click=${() => { this._showLeft = true; }}>
              ${icon("bars-3")}</button>` : nothing}
          ${this._modelChip()}
          <span class="spacer"></span>
          <button class="iconbtn" title="Artifacts panel"
            @click=${() => { this._showRight = !this._showRight; }}>${icon("photo")}</button>
        </div>
        <ba-chat-stage></ba-chat-stage>
        <ba-composer></ba-composer>
      </div>

      ${this._showRight ? html`
        <aside class="right"><ba-artifact-panel></ba-artifact-panel></aside>` : nothing}

      ${this._showSettings ? html`
        <ba-settings-modal @close=${() => { this._showSettings = false; }}></ba-settings-modal>` : nothing}
    `;
  }
}

customElements.define("ba-app", BaApp);
