// SPDX-License-Identifier: GPL-3.0-or-later
//
// Rendered (non-native) control library, in the spirit of Foyer
// Studio's ui-core widgets: every control is a Lit-rendered element
// styled by the shared tokens - no native checkbox/select/dialog
// chrome anywhere.

import { LitElement, html, css, nothing } from "lit";
import { icon } from "/static/core/icons.js";

const fieldStyles = css`
  :host { display: block; font-family: var(--font-sans); }
`;

/* ------------------------------------------------------------------ */
/* ba-switch: track + knob toggle. Emits `input` with {value}.        */

export class BaSwitch extends LitElement {
  static properties = {
    on: { type: Boolean, reflect: true },
    disabled: { type: Boolean },
  };

  static styles = css`
    *, *::before, *::after { box-sizing: border-box; }
    :host { display: inline-block; }
    button {
      width: 38px;
      height: 22px;
      border-radius: 999px;
      border: 1px solid var(--border);
      background: var(--surface-muted);
      position: relative;
      cursor: pointer;
      padding: 0;
      transition: background 0.15s ease, border-color 0.15s ease;
    }
    button:disabled { opacity: 0.5; cursor: default; }
    .knob {
      position: absolute;
      top: 2px;
      left: 2px;
      width: 16px;
      height: 16px;
      border-radius: 50%;
      background: var(--text-muted);
      transition: transform 0.15s ease, background 0.15s ease;
    }
    :host([on]) button {
      background: linear-gradient(135deg, var(--accent), var(--accent-2));
      border-color: transparent;
    }
    :host([on]) .knob {
      transform: translateX(16px);
      background: #fff;
    }
  `;

  constructor() {
    super();
    this.on = false;
    this.disabled = false;
  }

  render() {
    return html`
      <button role="switch" aria-checked=${this.on} ?disabled=${this.disabled}
        @click=${() => {
          this.dispatchEvent(new CustomEvent("input", {
            detail: { value: !this.on }, bubbles: true, composed: true,
          }));
        }}><span class="knob"></span></button>
    `;
  }
}
customElements.define("ba-switch", BaSwitch);

/* ------------------------------------------------------------------ */
/* ba-segmented: exclusive option strip. Emits `input` with {value}.  */

export class BaSegmented extends LitElement {
  static properties = {
    options: { type: Array },   // [{value, label, icon?}]
    value: { type: String },
  };

  static styles = css`
    *, *::before, *::after { box-sizing: border-box; }
    :host { display: inline-flex; }
    .strip {
      display: inline-flex;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      padding: 3px;
      gap: 3px;
    }
    button {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font: inherit;
      font-family: var(--font-sans);
      font-weight: 500;
      font-size: 13px;
      color: var(--text-muted);
      background: transparent;
      border: none;
      border-radius: var(--radius-sm);
      padding: 6px 14px;
      cursor: pointer;
      transition: all 0.15s ease;
    }
    button:hover { color: var(--text); }
    button.active {
      color: #fff;
      background: linear-gradient(135deg, var(--accent), var(--accent-2));
    }
  `;

  constructor() {
    super();
    this.options = [];
    this.value = "";
  }

  render() {
    return html`
      <div class="strip" role="radiogroup">
        ${this.options.map((option) => html`
          <button role="radio" aria-checked=${option.value === this.value}
            class=${option.value === this.value ? "active" : ""}
            @click=${() => {
              this.dispatchEvent(new CustomEvent("input", {
                detail: { value: option.value }, bubbles: true, composed: true,
              }));
            }}>
            ${option.icon ? icon(option.icon) : nothing}
            ${option.label}
          </button>`)}
      </div>
    `;
  }
}
customElements.define("ba-segmented", BaSegmented);

/* ------------------------------------------------------------------ */
/* ba-combo: editable combo box - text input + rendered option list.  */
/* `options` may update live (e.g. fetched models). Emits `input`     */
/* with {value} on typing and selection.                              */

export class BaCombo extends LitElement {
  static properties = {
    value: { type: String },
    options: { type: Array },     // [string]
    placeholder: { type: String },
    loading: { type: Boolean },
    editable: { type: Boolean },
    _open: { state: true },
  };

  static styles = css`
    *, *::before, *::after { box-sizing: border-box; }
    :host { display: block; position: relative; font-family: var(--font-sans); }
    .box {
      display: flex;
      align-items: center;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      transition: border-color 0.15s ease;
    }
    .box:focus-within { border-color: var(--accent); }
    input {
      flex: 1;
      min-width: 0;
      font: inherit;
      color: var(--text);
      background: transparent;
      border: none;
      outline: none;
      padding: 8px 10px;
    }
    input::placeholder { color: var(--text-muted); opacity: 0.7; }
    input[readonly] { cursor: pointer; }
    .chev {
      display: inline-flex;
      align-items: center;
      color: var(--text-muted);
      background: none;
      border: none;
      padding: 0 10px;
      cursor: pointer;
      transition: transform 0.15s ease;
    }
    .chev.open { transform: rotate(180deg); }
    .menu {
      position: absolute;
      z-index: 30;
      top: calc(100% + 4px);
      left: 0;
      right: 0;
      max-height: 220px;
      overflow-y: auto;
      background: var(--surface-elevated);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      box-shadow: var(--shadow-panel);
      padding: 4px;
    }
    .opt {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 7px 10px;
      border-radius: var(--radius-sm);
      cursor: pointer;
      font-size: 13.5px;
      color: var(--text);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .opt:hover { background: var(--accent-soft); }
    .opt .tick { color: var(--accent); visibility: hidden; }
    .opt.selected .tick { visibility: visible; }
    .note { padding: 8px 10px; color: var(--text-muted); font-size: 12.5px; }
  `;

  constructor() {
    super();
    this.value = "";
    this.options = [];
    this.placeholder = "";
    this.loading = false;
    this.editable = true;
    this._open = false;
    this._onDocClick = (e) => {
      if (!e.composedPath().includes(this)) this._open = false;
    };
  }

  connectedCallback() {
    super.connectedCallback();
    document.addEventListener("click", this._onDocClick);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    document.removeEventListener("click", this._onDocClick);
  }

  _emit(value) {
    this.value = value;
    this.dispatchEvent(new CustomEvent("input", {
      detail: { value }, bubbles: true, composed: true,
    }));
  }

  render() {
    const filtered = this.editable && this.value
      ? this.options.filter((o) => o.toLowerCase().includes(this.value.toLowerCase()))
      : this.options;
    const shown = filtered.length ? filtered : this.options;
    return html`
      <div class="box">
        <input .value=${this.value} placeholder=${this.placeholder}
          ?readonly=${!this.editable}
          @focus=${() => { if (this.options.length) this._open = true; }}
          @click=${() => { if (!this.editable) this._open = !this._open; }}
          @input=${(e) => { this._open = true; this._emit(e.target.value); }}
          @keydown=${(e) => { if (e.key === "Escape") this._open = false; }}>
        <button class="chev ${this._open ? "open" : ""}" tabindex="-1"
          @click=${() => { this._open = !this._open; }}>
          ${this.loading ? icon("arrow-path") : icon("chevron-down")}
        </button>
      </div>
      ${this._open ? html`
        <div class="menu" role="listbox">
          ${this.loading ? html`<div class="note">Loading models...</div>` : nothing}
          ${!this.loading && shown.length === 0 ? html`
            <div class="note">No options${this.editable ? " - free text is fine" : ""}.</div>` : nothing}
          ${shown.map((option) => html`
            <div class="opt ${option === this.value ? "selected" : ""}" role="option"
              @click=${() => { this._emit(option); this._open = false; }}>
              <span class="tick">${icon("check")}</span>${option}
            </div>`)}
        </div>` : nothing}
    `;
  }
}
customElements.define("ba-combo", BaCombo);

/* ------------------------------------------------------------------ */
/* ba-lightbox: fullscreen image preview. Esc/backdrop/X close.       */

export class BaLightbox extends LitElement {
  static properties = {
    src: { type: String },
    alt: { type: String },
    // "stl" swaps the <img> for an interactive 3D viewer.
    kind: { type: String },
  };

  static styles = css`
    *, *::before, *::after { box-sizing: border-box; }
    :host {
      position: fixed;
      inset: 0;
      z-index: 120;
      display: flex;
      align-items: center;
      justify-content: center;
      background: var(--overlay-tint);
      backdrop-filter: blur(var(--overlay-blur)) saturate(var(--overlay-saturate));
      cursor: zoom-out;
    }
    figure {
      margin: 0;
      max-width: 92vw;
      max-height: 90vh;
      display: flex;
      flex-direction: column;
      gap: 10px;
      cursor: default;
      /* Framed panel so light images separate from the frosted
         backdrop instead of bleeding into it. */
      background: var(--surface-elevated);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      padding: 10px;
      box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.35), var(--shadow-panel);
    }
    .stage3d {
      width: min(80vw, 900px);
      height: min(75vh, 700px);
      border-radius: var(--radius-sm);
      border: 1px solid var(--border);
      overflow: hidden;
    }
    .stage3d ba-stl-viewer { width: 100%; height: 100%; display: block; }
    img {
      max-width: calc(92vw - 20px);
      max-height: 80vh;
      object-fit: contain;
      border-radius: var(--radius-sm);
      border: 1px solid var(--border);
      background: var(--surface);
    }
    figcaption {
      display: flex;
      align-items: center;
      gap: 10px;
      color: var(--text-muted);
      font-family: var(--font-sans);
      font-size: 12.5px;
    }
    a, button.x {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      color: var(--text-muted);
      background: none;
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      padding: 4px 10px;
      cursor: pointer;
      font: inherit;
      text-decoration: none;
    }
    a:hover, button.x:hover { color: var(--text); border-color: var(--accent); }
    .spacer { flex: 1; }
  `;

  constructor() {
    super();
    this.src = "";
    this.alt = "";
    this._onKey = (e) => { if (e.key === "Escape") this._close(); };
  }

  connectedCallback() {
    super.connectedCallback();
    document.addEventListener("keydown", this._onKey);
    this.addEventListener("click", (e) => { if (e.target === this) this._close(); });
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    document.removeEventListener("keydown", this._onKey);
  }

  _close() {
    this.dispatchEvent(new CustomEvent("close", { bubbles: true, composed: true }));
  }

  render() {
    return html`
      <figure @click=${(e) => e.stopPropagation()}>
        ${this.kind === "stl"
            ? html`<div class="stage3d"><ba-stl-viewer .src=${this.src} .label=${this.alt}></ba-stl-viewer></div>`
            : html`<img src=${this.src} alt=${this.alt}>`}
        <figcaption>
          <span>${this.alt}</span>
          <span class="spacer"></span>
          <a href=${this.src} target="_blank" rel="noopener">${icon("arrow-top-right-on-square")} Open</a>
          <button class="x" @click=${() => this._close()}>${icon("x-mark")} Close</button>
        </figcaption>
      </figure>
    `;
  }
}
customElements.define("ba-lightbox", BaLightbox);

/* ------------------------------------------------------------------ */
/* ba-modal: overlay + panel shell. Slots: title, body (default),     */
/* footer. Emits `close` on backdrop click or Escape.                 */

export class BaModal extends LitElement {
  static styles = css`
    *, *::before, *::after { box-sizing: border-box; }
    :host {
      position: fixed;
      inset: 0;
      z-index: 100;
      display: flex;
      align-items: center;
      justify-content: center;
      background: var(--overlay-tint);
      backdrop-filter: blur(var(--overlay-blur)) saturate(var(--overlay-saturate));
    }
    .panel {
      width: min(560px, 94vw);
      max-height: 88vh;
      overflow-y: auto;
      background: var(--surface-elevated);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      box-shadow: var(--shadow-panel);
      font-family: var(--font-sans);
    }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 16px 20px 0;
    }
    header ::slotted(*) { margin: 0; font-size: 17px; font-weight: 600; }
    .x {
      display: inline-flex;
      color: var(--text-muted);
      background: none;
      border: none;
      cursor: pointer;
      padding: 4px;
      border-radius: var(--radius-sm);
    }
    .x:hover { color: var(--text); background: var(--surface-muted); }
    .body { padding: 14px 20px; }
    footer {
      display: flex;
      justify-content: flex-end;
      gap: 8px;
      padding: 0 20px 18px;
    }
  `;

  constructor() {
    super();
    this._onKey = (e) => { if (e.key === "Escape") this._close(); };
    // Close only on a click that BOTH started and ended on the
    // backdrop. A drag that begins inside the panel (e.g. selecting
    // text in a field) and releases outside still fires a `click` on
    // the host, but its press did not start on the backdrop - that
    // must not close. `composedPath()[0]` is the true innermost target
    // (events bubbling out of this element's own shadow root would
    // otherwise retarget to the host, hiding the distinction). Capture
    // phase so it runs before the panel's stopPropagation.
    this._pressOnBackdrop = false;
    this._onDown = (e) => { this._pressOnBackdrop = e.composedPath()[0] === this; };
    this._onClick = (e) => {
      if (e.composedPath()[0] === this && this._pressOnBackdrop) this._close();
      this._pressOnBackdrop = false;
    };
  }

  connectedCallback() {
    super.connectedCallback();
    document.addEventListener("keydown", this._onKey);
    this.addEventListener("pointerdown", this._onDown, true);
    this.addEventListener("click", this._onClick, true);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    document.removeEventListener("keydown", this._onKey);
    this.removeEventListener("pointerdown", this._onDown, true);
    this.removeEventListener("click", this._onClick, true);
  }

  _close() {
    this.dispatchEvent(new CustomEvent("close", { bubbles: true, composed: true }));
  }

  render() {
    return html`
      <div class="panel" @click=${(e) => e.stopPropagation()}>
        <header>
          <slot name="title"></slot>
          <button class="x" @click=${this._close}>${icon("x-mark")}</button>
        </header>
        <div class="body"><slot></slot></div>
        <footer><slot name="footer"></slot></footer>
      </div>
    `;
  }
}
customElements.define("ba-modal", BaModal);
