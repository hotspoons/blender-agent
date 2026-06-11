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
import { localLlm } from "/static/core/local-llm-controller.js";
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
    _railCollapsed: { state: true },
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
    // Wide viewports collapse the rail to an icon strip (it never
    // fully disappears - same semantics as the right panel toggle);
    // narrow viewports use the overlay drawer instead.
    this._railCollapsed = localStorage.getItem("blender-agent.rail-collapsed") === "true";
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
    const onLlm = () => this.requestUpdate();
    localLlm.addEventListener("change", onLlm);
    this._unsubs.push(() => localLlm.removeEventListener("change", onLlm));
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
    /* Both side panels animate their width; inner wrappers keep a
       fixed width so content clips cleanly instead of reflowing
       mid-transition. */
    aside.left {
      width: 248px;
      border-right: 1px solid var(--border);
      transition: width 0.22s ease;
      overflow: hidden;
    }
    aside.right {
      width: 320px;
      border-left: 1px solid var(--border);
      transition: width 0.22s ease;
      overflow: hidden;
    }
    aside.right.closed { width: 0; border-left-width: 0; }
    .left-inner, .rail-inner, .right-inner {
      display: flex;
      flex-direction: column;
      min-height: 0;
      height: 100%;
      flex: none;
    }
    .left-inner { width: 248px; }
    .right-inner { width: 320px; }
    .rail-inner { width: 56px; align-items: center; }

    /* Collapsed rail: a slim icon strip - the sidebar never fully
       disappears on wide viewports (mirrors the right panel, which
       also keeps its toggle visible). */
    aside.left.collapsed { width: 56px; }
    .rail-inner .rail-foot { border-top: 1px solid var(--border); width: 100%; align-items: center; }
    .railbtn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 38px;
      height: 38px;
      font: inherit;
      color: var(--text-muted);
      background: none;
      border: none;
      border-radius: var(--radius-sm);
      cursor: pointer;
    }
    .railbtn:hover { color: var(--text); background: var(--accent-soft); }
    .railbtn .mark { width: 26px; height: 26px; display: inline-flex; }
    /* One icon size everywhere: the icon helper sizes itself in em,
       and .foot-item (13.5px) vs .railbtn (inherited) bases would
       otherwise render slightly different glyphs. */
    .railbtn svg, .foot-item svg, .iconbtn svg { font-size: 14.4px; }
    .rail-top {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 6px;
      padding: 12px 0 8px;
    }
    .rail-spring { flex: 1; }
    .conn-dot {
      width: 7px; height: 7px; border-radius: 50%;
      background: var(--danger);
      margin: 8px 0 10px;
    }
    .conn-dot.on { background: var(--success); }

    /* Narrow viewports: the left rail becomes an overlay drawer that
       slides out over the content instead of squeezing it. */
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
        transition: transform 0.22s ease;
      }
      aside.left.off { transform: translateX(-100%); box-shadow: none; }
      aside.right { width: min(320px, 86vw); }
      aside.right.closed { width: 0; }
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
      font: inherit;
      font-size: 12px;
      color: var(--text-muted);
      background: none;
      border: 1px solid var(--border);
      border-radius: 999px;
      padding: 3px 10px;
      white-space: nowrap;
      cursor: pointer;
    }
    .chip:hover { color: var(--text); border-color: var(--accent); background: var(--accent-soft); }
    .chip .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--danger); }
    .chip .dot.on { background: var(--success); }
    .chip .dot.warm { background: var(--warning); }
    /* Nothing usable configured: read as a link, not a status. */
    .chip.cta { color: var(--accent-2); border-color: var(--accent); text-decoration: underline; text-underline-offset: 3px; }
    .spacer { flex: 1; }
  `;

  _modelChip() {
    // The chip is the model affordance, not just a status readout. A
    // selected-but-unloaded local model loads on click (a model id is
    // always selected - the panel persists the choice); while loading
    // it shows live progress; otherwise it opens settings.
    const open = () => { this._showSettings = true; };
    const config = this._config || {};
    if (config.use_local_llm) {
      if (localLlm.status === "loading") {
        const pct = localLlm.progress?.progress
          ? ` ${Math.round(localLlm.progress.progress * 100)}%` : "";
        return html`<button class="chip" @click=${open}
          title=${localLlm.progress?.text || "Loading model..."}>
          ${icon("cpu-chip")} loading ${localLlm.modelLabel}...${pct}
          <span class="dot warm"></span></button>`;
      }
      if (localLlm.status === "error") {
        return html`<button class="chip cta" @click=${open}
          title=${localLlm.error || "Load failed - open settings"}>
          ${icon("exclamation-triangle")} model load failed - open settings
          <span class="dot"></span></button>`;
      }
      if (localLlm.status !== "ready" && !this._localLlm.model_id) {
        return html`<button class="chip cta" @click=${() => localLlm.load()}
          title="Load ${localLlm.modelLabel} in this browser (downloads once, then cached)">
          ${icon("cpu-chip")} load ${localLlm.modelLabel}
          <span class="dot"></span></button>`;
      }
      const state = this._localLlm.status === "ready" ? "on" : (this._localLlm.connected ? "warm" : "");
      return html`<button class="chip" @click=${open} title="Local in-browser model - open settings">
        ${icon("cpu-chip")} ${this._localLlm.model_id || localLlm.modelLabel}
        <span class="dot ${state}"></span></button>`;
    }
    if (config.endpoint) {
      return html`<button class="chip" @click=${open} title=${config.endpoint}>
        ${icon("arrow-top-right-on-square")} ${config.model || "remote model"}</button>`;
    }
    return html`<button class="chip cta" @click=${open}
      title="Open settings to configure a model">
      ${icon("exclamation-triangle")} no model configured - click to set up</button>`;
  }

  _setRailCollapsed(collapsed) {
    this._railCollapsed = collapsed;
    localStorage.setItem("blender-agent.rail-collapsed", String(collapsed));
  }

  /** Slim icon-strip content shown when the rail is collapsed. */
  _renderRailContent() {
    return html`
      <div class="rail-inner">
        <div class="rail-top">
          <button class="railbtn" title="Expand sidebar" @click=${() => this._setRailCollapsed(false)}>
            <span class="mark">${brandMark}</span></button>
          <button class="railbtn" title="New session" @click=${() => store.newSession()}>
            ${icon("plus")}</button>
        </div>
        <div class="rail-spring"></div>
        <div class="rail-foot">
          <button class="railbtn" title="Settings" @click=${() => { this._showSettings = true; }}>
            ${icon("cog-6-tooth")}</button>
          <button class="railbtn" title="Theme: ${THEME_META[this._theme].label}" @click=${() => cycleTheme()}>
            ${icon(THEME_ICONS[this._theme])}</button>
          <button class="railbtn" title="Expand sidebar" @click=${() => this._setRailCollapsed(false)}>
            ${icon("chevron-double-right")}</button>
          <span class="conn-dot ${this._connected ? "on" : ""}"
            title=${this._connected ? "Connected" : "Reconnecting"}></span>
        </div>
      </div>`;
  }

  _renderFullRailContent(narrow) {
    return html`
      <div class="left-inner">
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
          <button class="foot-item" @click=${() => {
            if (narrow) this._showLeft = false;
            else this._setRailCollapsed(true);
          }}>
            ${icon("chevron-double-left")} Collapse</button>
          <button class="foot-item" style="cursor: default;">
            ${icon("arrow-path")} ${this._connected ? "Connected" : "Reconnecting"}
            <span class="dot ${this._connected ? "on" : ""}"></span></button>
        </div>
      </div>`;
  }

  render() {
    const narrow = this._narrow.matches;
    const collapsed = !narrow && this._railCollapsed;
    // Both asides stay mounted so width/transform changes animate;
    // the inner wrappers keep fixed widths so content clips instead
    // of reflowing mid-transition.
    const leftClass = narrow
      ? `left ${this._showLeft ? "" : "off"}`
      : `left ${collapsed ? "collapsed" : ""}`;
    return html`
      ${narrow && this._showLeft ? html`
        <div class="backdrop" @click=${() => { this._showLeft = false; }}></div>` : nothing}
      <aside class=${leftClass}>
        ${collapsed ? this._renderRailContent() : this._renderFullRailContent(narrow)}
      </aside>

      <div class="stage">
        <div class="topbar">
          ${narrow && !this._showLeft ? html`
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

      <aside class="right ${this._showRight ? "" : "closed"}">
        <div class="right-inner"><ba-artifact-panel></ba-artifact-panel></div>
      </aside>

      ${this._showSettings ? html`
        <ba-settings-modal @close=${() => { this._showSettings = false; }}></ba-settings-modal>` : nothing}
    `;
  }
}

customElements.define("ba-app", BaApp);
