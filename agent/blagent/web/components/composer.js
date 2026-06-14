// SPDX-License-Identifier: GPL-3.0-or-later
//
// Message composer: Enter sends, Shift+Enter newlines, abort while
// busy. Image attachments arrive by paste, drag-and-drop, or the
// attach button; they upload immediately and ride along as media ids.
// The textarea auto-grows and is also manually resizable.

import { LitElement, html, css, nothing } from "lit";
import { store } from "/static/core/store.js";
import { icon } from "/static/core/icons.js";
import { localLlm } from "/static/core/local-llm-controller.js";
import { getProfile } from "/static/core/profile.js";

const HEIGHT_KEY = "blender-agent.composer-height";

// One comfortable text line (line-height 24 + breathing room): the
// floor for both the drag-resize and the restored height, so the box
// can never be crushed into showing a scrollbar around one line.
const MIN_TA_HEIGHT = 40;

export class BaComposer extends LitElement {
  static properties = {
    _busy: { state: true },
    _connected: { state: true },
    _attachments: { state: true },   // [{id, sessionId, uploading}]
    _dragOver: { state: true },
    _autoload: { state: true },      // loading a local model before send
    _level: { state: true },         // autonomy level: ask|yolo|orchestrator|swarm
    _autoOpen: { state: true },      // is the autonomy slider expanded?
    _objRows: { state: true },       // guided-intake objective editor rows
    _swarmPreflight: { state: true },// {ready, report} — swarm requirements
    _draftPending: { state: true },  // guided-intake draft request in flight
    _objCollapsed: { state: true },  // objectives editor collapsed into an expando
    _queued: { state: true },        // {text, ready} queued to send when not busy
  };

  constructor() {
    super();
    this._busy = store.state.busy;
    this._connected = store.state.connected;
    this._attachments = [];
    this._dragOver = false;
    this._autoload = false;
    this._level = store.state.autonomyLevel;
    this._autoOpen = false;
    this._objRows = [];
    this._swarmPreflight = store.state.swarmPreflight;
    this._draftPending = store.state.draftPending;
    this._objCollapsed = false;
    this._queued = null;
    this._lastDraftGoal = null;
    this._onLlmChange = () => this._onLocalLlmState();
  }

  connectedCallback() {
    super.connectedCallback();
    this._unsub = store.subscribe((keys) => {
      if (keys.has("busy")) {
        const wasBusy = this._busy;
        this._busy = store.state.busy;
        // Flush a queued message once the running turn finishes.
        if (wasBusy && !this._busy && this._queued) {
          const q = this._queued;
          this._queued = null;
          store.chat(q.text || "(see attached media)", q.ready || []);
        }
      }
      if (keys.has("connected")) this._connected = store.state.connected;
      // Switching sessions drops staged attachments (they belong to
      // the session they were uploaded into).
      if (keys.has("sessionId")) {
        this._attachments = this._attachments.filter(
          (a) => a.sessionId === store.state.sessionId);
      }
      if (keys.has("autonomyLevel")) this._level = store.state.autonomyLevel;
      if (keys.has("swarmPreflight")) this._swarmPreflight = store.state.swarmPreflight;
      if (keys.has("draftPending")) this._draftPending = store.state.draftPending;
      if (keys.has("autonomy")) {
        const d = store.state.autonomy?.draft;
        if (d && d.objectives?.length && d.goal !== this._lastDraftGoal) {
          this._lastDraftGoal = d.goal;
          this._objRows = d.objectives.map((o) => ({ text: o.text || "", acceptance: o.acceptance || "" }));
          this._objCollapsed = false; // surface the fresh draft for editing
        }
      }
    });
    localLlm.addEventListener("change", this._onLlmChange);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this._unsub?.();
    localLlm.removeEventListener("change", this._onLlmChange);
  }

  firstUpdated() {
    // Restore the last manually-chosen composer height (floored so a
    // single line never overflows into a scrollbar).
    const saved = parseInt(localStorage.getItem(HEIGHT_KEY) || "", 10);
    if (saved > MIN_TA_HEIGHT) {
      const ta = this.renderRoot.querySelector("textarea");
      ta.style.height = Math.min(window.innerHeight * 0.5, saved) + "px";
      this._manualHeight = true;
    }
  }

  /** True when the configured model is in-browser and not yet ready. */
  _localNotReady() {
    return !!store.state.config?.use_local_llm && localLlm.status !== "ready";
  }

  /** Drive the deferred send once an auto-load finishes (or fails). */
  _onLocalLlmState() {
    if (!this._autoload) return;
    if (localLlm.status === "ready") {
      this._autoload = false;
      // The bridge needs a beat to register over the tunnel; the turn
      // itself tolerates a not-quite-ready bridge by erroring, so a
      // short settle keeps the common path clean.
      setTimeout(() => this._send(), 150);
    } else if (localLlm.status === "error" || localLlm.status === "idle") {
      this._autoload = false;
    }
    this.requestUpdate();
  }

  async _addFiles(files) {
    for (const file of files) {
      if (file.size > 64 * 1024 * 1024) continue; // server cap
      const staged = { id: "", sessionId: "", uploading: true, name: file.name || "pasted file" };
      this._attachments = [...this._attachments, staged];
      try {
        const uploaded = await store.uploadAttachment(file);
        staged.id = uploaded.id;
        staged.sessionId = uploaded.session_id;
        staged.uploading = false;
      } catch (err) {
        console.error("attachment upload failed:", err);
        this._attachments = this._attachments.filter((a) => a !== staged);
        continue;
      }
      this._attachments = [...this._attachments];
    }
  }

  _onPaste(e) {
    const files = [...(e.clipboardData?.items || [])]
      .filter((item) => item.kind === "file")
      .map((item) => item.getAsFile())
      .filter(Boolean);
    if (files.length) {
      e.preventDefault();
      this._addFiles(files);
    }
  }

  _onDrop(e) {
    e.preventDefault();
    this._dragOver = false;
    this._addFiles([...(e.dataTransfer?.files || [])]);
  }

  /** Top-edge drag: pulling up grows the box (it expands upward). */
  _onGripDown(e) {
    const ta = this.renderRoot.querySelector("textarea");
    const grip = e.currentTarget;
    const startY = e.clientY;
    const startHeight = ta.getBoundingClientRect().height;
    try { grip.setPointerCapture(e.pointerId); } catch {}
    grip.classList.add("active");
    const maxHeight = window.innerHeight * 0.5;
    let height = startHeight;
    const onMove = (ev) => {
      height = Math.min(maxHeight, Math.max(MIN_TA_HEIGHT, startHeight + (startY - ev.clientY)));
      ta.style.height = height + "px";
      this._manualHeight = true;
    };
    const onUp = (ev) => {
      try { grip.releasePointerCapture(ev.pointerId); } catch {}
      grip.classList.remove("active");
      grip.removeEventListener("pointermove", onMove);
      grip.removeEventListener("pointerup", onUp);
      // Remember the chosen size across reloads.
      localStorage.setItem(HEIGHT_KEY, String(Math.round(height)));
    };
    grip.addEventListener("pointermove", onMove);
    grip.addEventListener("pointerup", onUp);
  }

  static styles = css`
    *, *::before, *::after { box-sizing: border-box; }
    :host {
      display: block;
      padding: 10px 16px 16px;
      font-family: var(--font-sans);
    }
    .box {
      max-width: 820px;
      margin: 0 auto;
      display: flex;
      flex-direction: column;
      background: var(--surface-elevated);
      border: 1px solid var(--border);
      border-radius: 22px;
      padding: 8px 12px 10px;
      transition: border-color 0.15s ease, box-shadow 0.15s ease;
    }
    .box:focus-within {
      border-color: var(--accent);
      box-shadow: 0 0 0 3px var(--accent-soft);
    }
    .box.drag { border-color: var(--accent); background: var(--accent-soft); }
    .grip {
      height: 10px;
      margin: -8px -12px 0;   /* span the box's full width */
      cursor: ns-resize;
      display: flex;
      align-items: center;
      justify-content: center;
      touch-action: none;
    }
    .grip::after {
      content: "";
      width: 44px;
      height: 3px;
      border-radius: 2px;
      background: var(--border);
      opacity: 0;
      transition: opacity 0.15s ease;
    }
    .grip:hover::after, .grip.active::after { opacity: 1; background: var(--accent); }
    /* Autonomy slider: a real detented slider (track + knob), not buttons. */
    .autonomy {
      display: flex; align-items: flex-start; gap: 8px; margin-bottom: 8px;
      background: var(--surface-muted); border: 1px solid var(--border);
      border-radius: var(--radius-md); padding: 10px 14px 6px;
    }
    .auto-slider { flex: 1; }
    .auto-slider .track {
      position: relative; height: 6px; margin: 4px 11px 0; border-radius: 999px;
      background: var(--border); cursor: pointer; touch-action: none;
    }
    .auto-slider .track:focus-visible { outline: 2px solid var(--accent); outline-offset: 6px; }
    .auto-slider .fill {
      position: absolute; left: 0; top: 0; height: 100%; border-radius: 999px;
      background: linear-gradient(90deg, var(--accent-2), var(--accent));
    }
    .auto-slider .detent {
      position: absolute; top: 50%; width: 9px; height: 9px; border-radius: 50%;
      transform: translate(-50%, -50%); background: var(--surface);
      border: 2px solid var(--border);
    }
    .auto-slider .detent.on { border-color: var(--accent); background: var(--accent); }
    .auto-slider .knob {
      position: absolute; top: 50%; width: 18px; height: 18px; border-radius: 50%;
      transform: translate(-50%, -50%); background: #fff; border: 2px solid var(--accent);
      box-shadow: 0 1px 4px rgba(0,0,0,0.35); pointer-events: none;
    }
    .auto-slider .ticks { position: relative; height: 18px; margin: 8px 0 0; }
    .auto-slider .tick {
      position: absolute; top: 0; transform: translateX(-50%); white-space: nowrap;
      border: none; background: transparent; color: var(--text-muted);
      font: inherit; font-size: 11px; font-weight: 600; letter-spacing: 0.02em;
      padding: 0 2px; cursor: pointer;
    }
    .auto-slider .tick:first-of-type { transform: translateX(0); }
    .auto-slider .tick:last-of-type { transform: translateX(-100%); }
    .auto-slider .tick:hover:not(:disabled) { color: var(--text); }
    .auto-slider .tick.on { color: var(--accent); }
    .auto-slider .tick:disabled { cursor: default; opacity: 0.6; }
    .autonomy .auto-dismiss { border: none; background: transparent; color: var(--text-muted);
      cursor: pointer; padding: 0; display: inline-flex; align-items: center; }
    .autonomy .auto-dismiss:hover { color: var(--text); }
    .autonomy .auto-dismiss svg { width: 14px; height: 14px; }
    /* Collapsed autonomy control: a quiet chip that expands the slider. */
    .auto-chip {
      align-self: flex-start; display: inline-flex; align-items: center; gap: 5px;
      margin-bottom: 8px; padding: 3px 10px;
      background: var(--surface-muted); border: 1px solid var(--border);
      border-radius: 999px; color: var(--text-muted); font: inherit; font-size: 12px; cursor: pointer;
    }
    .auto-chip:hover { color: var(--text); border-color: var(--accent); }
    .auto-chip strong { color: var(--accent); font-weight: 700; }
    .auto-chip svg { width: 13px; height: 13px; }
    /* Swarm requirements panel (per-OS readiness), shown while on swarm. */
    .swarm-pf { margin-bottom: 8px; border: 1px solid var(--border);
      border-radius: var(--radius-md); background: var(--surface-muted); padding: 8px 10px; }
    .swarm-pf.warn { border-color: var(--warning); }
    .swarm-pf .pf-head { display: flex; align-items: center; gap: 6px;
      font-size: 12px; font-weight: 600; color: var(--text-muted); margin-bottom: 4px; }
    .swarm-pf.warn .pf-head { color: var(--warning); }
    .swarm-pf .pf-head svg { width: 14px; height: 14px; }
    .swarm-pf pre { margin: 0; font-family: var(--font-mono); font-size: 11px;
      color: var(--text-muted); white-space: pre-wrap; overflow-wrap: anywhere; }
    /* Guided-intake objectives editor. */
    .obj-editor {
      border: 1px solid var(--border); border-radius: var(--radius-md);
      background: var(--surface-muted); padding: 8px; margin-bottom: 8px;
      display: flex; flex-direction: column; gap: 6px;
    }
    .oe-head { display: flex; align-items: center; gap: 5px; cursor: pointer;
      font-size: 11px; font-weight: 700; text-transform: uppercase;
      letter-spacing: 0.04em; color: var(--text-muted); }
    .oe-head svg { width: 13px; height: 13px; }
    .oe-head .hint { font-weight: 500; text-transform: none; letter-spacing: 0; opacity: 0.8; }
    .oe-cols { display: flex; gap: 6px; padding: 0 2px; font-size: 10px; font-weight: 700;
      text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-muted); opacity: 0.7; }
    .oe-cols span:first-child { flex: 2; }
    .oe-cols span:last-child { flex: 3; }
    /* Collapsed objectives expando (after a run is launched). */
    .obj-expando { display: flex; align-items: center; gap: 6px; margin-bottom: 8px;
      width: 100%; text-align: left; padding: 7px 10px; cursor: pointer;
      background: var(--surface-muted); border: 1px solid var(--border); border-radius: var(--radius-md);
      color: var(--text-muted); font: inherit; font-size: 11px; font-weight: 700;
      text-transform: uppercase; letter-spacing: 0.04em; }
    .obj-expando:hover { color: var(--text); border-color: var(--accent); }
    .obj-expando svg { width: 13px; height: 13px; }
    .obj-expando .count { background: var(--accent); color: #0d0d0d; border-radius: 999px;
      padding: 0 7px; font-size: 11px; }
    .obj-expando .hint { font-weight: 500; text-transform: none; letter-spacing: 0; opacity: 0.7; }
    /* Queued-to-send indicator (shown while a turn runs). */
    .queued-chip { display: flex; align-items: center; gap: 6px; margin-bottom: 8px;
      padding: 5px 10px; font-size: 12px; color: var(--text-muted);
      background: var(--surface-muted); border: 1px dashed var(--border); border-radius: var(--radius-md); }
    .queued-chip svg { width: 13px; height: 13px; animation: spin 1.4s linear infinite; }
    .queued-chip span { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .queued-chip button { background: transparent; border: none; color: var(--text-muted);
      cursor: pointer; display: inline-flex; padding: 0; }
    .queued-chip button:hover { color: var(--text); }
    .queue-btn { display: inline-flex; align-items: center; gap: 4px; padding: 5px 12px;
      background: var(--surface-muted); color: var(--text); border: 1px solid var(--border);
      border-radius: 999px; font: inherit; font-size: 12px; font-weight: 600; cursor: pointer; }
    .queue-btn:hover:not(:disabled) { border-color: var(--accent); color: var(--accent); }
    .queue-btn:disabled { opacity: 0.5; cursor: default; }
    .queue-btn svg { width: 13px; height: 13px; }
    .oe-row { display: flex; gap: 6px; align-items: center; }
    .oe-row input { background: var(--surface); color: var(--text);
      border: 1px solid var(--border); border-radius: var(--radius-sm);
      padding: 5px 8px; font: inherit; font-size: 12.5px; }
    .oe-row .oe-text { flex: 2; }
    .oe-row .oe-acc { flex: 3; color: var(--text-muted); }
    .oe-row .oe-x { background: transparent; border: none; color: var(--text-muted);
      cursor: pointer; display: inline-flex; padding: 2px; }
    .oe-row .oe-x:hover { color: var(--danger); }
    .oe-actions { display: flex; align-items: center; gap: 6px; }
    .oe-actions .spacer { flex: 1; }
    .oe-add, .oe-discard, .oe-begin { font: inherit; font-size: 12px; cursor: pointer;
      border-radius: var(--radius-sm); padding: 4px 10px; border: 1px solid var(--border); }
    .oe-add, .oe-discard { background: transparent; color: var(--text-muted); }
    .oe-add:hover, .oe-discard:hover { color: var(--text); }
    .oe-begin { background: var(--accent); color: #0d0d0d; border-color: transparent; font-weight: 600; }
    .oe-begin:disabled { opacity: 0.5; cursor: default; }
    .draft-btn { background: var(--accent-soft); color: var(--accent); border: 1px solid transparent;
      border-radius: var(--radius-md); padding: 6px 10px; font: inherit; font-size: 12.5px;
      font-weight: 600; cursor: pointer; }
    .draft-btn:hover:not(:disabled) { filter: brightness(1.15); }
    .draft-btn:disabled { opacity: 0.5; cursor: default; }
    .draft-btn.pending { opacity: 1; cursor: progress; }
    .draft-btn .spin { display: inline-flex; vertical-align: -2px; animation: spin 1.4s linear infinite; }
    .draft-btn .spin svg { width: 13px; height: 13px; }
    .chips { display: flex; gap: 6px; flex-wrap: wrap; padding-bottom: 6px; }
    .chip {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      padding: 3px;
      background: var(--surface);
    }
    .chip img { height: 38px; border-radius: 4px; display: block; }
    .chip .up { font-size: 11px; color: var(--text-muted); padding: 0 6px; }
    .chip button {
      display: inline-flex;
      border: none;
      background: none;
      color: var(--text-muted);
      cursor: pointer;
      padding: 2px;
    }
    .chip button:hover { color: var(--danger); }
    textarea {
      width: 100%;
      resize: none;              /* the top-edge handle resizes instead */
      border: none;
      outline: none;
      background: transparent;
      color: var(--text);
      font: inherit;
      line-height: 24px;
      max-height: 50vh;
      min-height: 24px;
      /* Spacing via margin, NOT vertical padding: padding makes even an
         EMPTY one-line box overflow its own height (border-box) and
         grow a scrollbar. */
      padding: 0 4px;
      margin-top: 6px;
      overflow-y: auto;
      scrollbar-width: thin;
      scrollbar-color: var(--border) transparent;
    }
    textarea::placeholder { color: var(--text-muted); opacity: 0.7; }
    /* Controls live UNDER the text like the current crop of chat
       composers: attach on the left, send/stop circle on the right. */
    .controls { display: flex; align-items: center; gap: 6px; padding-top: 6px; }
    .controls .spacer { flex: 1; }
    .circle {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 36px;
      height: 36px;
      border-radius: 50%;
      border: none;
      cursor: pointer;
      font: inherit;
      transition: background 0.15s ease, color 0.15s ease, transform 0.1s ease;
    }
    .circle:active { transform: scale(0.94); }
    .circle svg { width: 20px; height: 20px; }
    button.attach {
      background: none;
      color: var(--text-muted);
      border: 1px solid var(--border);
    }
    button.attach:hover { color: var(--text); background: var(--accent-soft); border-color: transparent; }
    button.act {
      color: #fff;
      background: linear-gradient(135deg, var(--accent), var(--accent-2));
    }
    button.act:hover { filter: brightness(1.1); }
    button.act:disabled { opacity: 0.45; cursor: default; filter: none; }
    button.act.abort { background: var(--danger); }
    button.act .spin { display: inline-flex; animation: spin 1.4s linear infinite; }
    @keyframes spin { to { transform: rotate(360deg); } }
    input[type="file"] { display: none; }
  `;

  _send() {
    const ta = this.renderRoot.querySelector("textarea");
    const text = ta.value.trim();
    const ready = this._attachments.filter((a) => !a.uploading).map((a) => a.id);
    const hasRows = this._autonomyMode() && this._objRows.length > 0;
    if ((!text && !ready.length && !hasRows) || this._busy || !this._connected) return;
    if (this._attachments.some((a) => a.uploading)) return;
    // Local model not loaded yet: kick off the load and defer the send
    // until it is ready (the Send button shows a spinner meanwhile).
    // The message text stays in the box until then.
    if (this._localNotReady()) {
      if (localLlm.status !== "loading") localLlm.load();
      this._autoload = true;
      this.requestUpdate();
      return;
    }
    this._autoload = false;
    if (this._autonomyMode()) {
      // Autonomy modes: an open objectives editor wins; otherwise the line
      // is a single quick objective (the explicit shortcut).
      if (this._objRows.length) this._beginRun();
      else store.objectives([{ text: text, acceptance: "" }]);
    } else {
      store.chat(text || "(see attached image)", ready);
    }
    this._attachments = [];
    ta.value = "";
    // A manually-chosen height is the user's preference - keep it after
    // sending instead of snapping back to one row; otherwise auto-fit.
    const saved = parseInt(localStorage.getItem(HEIGHT_KEY) || "", 10);
    if (this._manualHeight && saved > 24) {
      ta.style.height = Math.min(window.innerHeight * 0.5, saved) + "px";
    } else {
      ta.style.height = "auto";
      this._manualHeight = false;
    }
  }

  _autonomyMode() {
    return this._level === "orchestrator" || this._level === "swarm";
  }

  static _LEVELS = [
    ["ask", "Ask", "Act directly; confirm every mutating tool call"],
    ["yolo", "YOLO", "Act directly; run tool calls without confirmation"],
    ["orchestrator", "Orchestrator", "Pursue objectives via in-process worker agents"],
    ["swarm", "Swarm", getProfile().swarmBlurb],
  ];

  _levelLabel() {
    const found = BaComposer._LEVELS.find(([v]) => v === this._level);
    return found ? found[1] : this._level;
  }

  _levelIndex() {
    const i = BaComposer._LEVELS.findIndex(([v]) => v === this._level);
    return i < 0 ? 1 : i;
  }

  _commitLevel(val) {
    this._level = val;                       // immediate visual
    if (val !== store.state.autonomyLevel) store.setAutonomyLevel(val);
  }

  _idxFromClientX(clientX, track) {
    const r = track.getBoundingClientRect();
    const frac = Math.max(0, Math.min(1, (clientX - r.left) / r.width));
    return Math.round(frac * (BaComposer._LEVELS.length - 1));
  }

  // Drag the knob: preview live (no backend churn), commit once on release.
  _onTrackDown(e) {
    if (this._busy) return;
    e.preventDefault();
    const track = e.currentTarget;
    try { track.setPointerCapture(e.pointerId); } catch (_e) { /* ignore */ }
    this._dragging = true;
    this._level = BaComposer._LEVELS[this._idxFromClientX(e.clientX, track)][0];
  }

  _onTrackMove(e) {
    if (!this._dragging) return;
    this._level = BaComposer._LEVELS[this._idxFromClientX(e.clientX, e.currentTarget)][0];
  }

  _onTrackUp(e) {
    if (!this._dragging) return;
    this._dragging = false;
    try { e.currentTarget.releasePointerCapture(e.pointerId); } catch (_e) { /* ignore */ }
    this._commitLevel(this._level);
  }

  _onTrackKey(e) {
    let idx = this._levelIndex();
    if (e.key === "ArrowRight" || e.key === "ArrowUp") idx = Math.min(BaComposer._LEVELS.length - 1, idx + 1);
    else if (e.key === "ArrowLeft" || e.key === "ArrowDown") idx = Math.max(0, idx - 1);
    else return;
    e.preventDefault();
    this._commitLevel(BaComposer._LEVELS[idx][0]);
  }

  /**
   * Collapsed: a small "autonomy: <Level>" chip. Click to expand the
   * segmented slider; pick a level (or click the chip again) to dismiss.
   */
  _renderSwarmPreflight() {
    // Only while on swarm, and only if there's something worth flagging.
    if (this._level !== "swarm" || !this._swarmPreflight?.report) return nothing;
    const pf = this._swarmPreflight;
    return html`
      <div class="swarm-pf ${pf.ready ? "ok" : "warn"}">
        <div class="pf-head">${icon(pf.ready ? "check" : "exclamation-triangle")}
          ${pf.ready ? "Swarm ready — requirements" : "Swarm may not run — check requirements"}</div>
        <pre>${pf.report}</pre>
      </div>`;
  }

  _renderAutonomyControl() {
    if (!this._autoOpen) {
      return html`
        <button class="auto-chip" title="Change autonomy level"
          @click=${() => { this._autoOpen = true; }}>
          autonomy: <strong>${this._levelLabel()}</strong> ${icon("chevron-down")}
        </button>
        ${this._renderSwarmPreflight()}`;
    }
    const idx = this._levelIndex();
    const last = BaComposer._LEVELS.length - 1;
    const pct = (i) => (i / last) * 100;
    return html`
      <div class="autonomy">
        <div class="auto-slider">
          <div class="track" role="slider" tabindex="0"
            aria-label="Autonomy level" aria-valuemin="0" aria-valuemax=${last}
            aria-valuenow=${idx} aria-valuetext=${this._levelLabel()}
            @pointerdown=${this._onTrackDown} @pointermove=${this._onTrackMove}
            @pointerup=${this._onTrackUp} @pointercancel=${this._onTrackUp}
            @keydown=${this._onTrackKey}>
            <div class="fill" style="width:${pct(idx)}%"></div>
            ${BaComposer._LEVELS.map((_l, i) => html`
              <span class="detent ${i <= idx ? "on" : ""}" style="left:${pct(i)}%"></span>`)}
            <span class="knob" style="left:${pct(idx)}%"></span>
          </div>
          <div class="ticks">
            ${BaComposer._LEVELS.map(([val, label, desc], i) => html`
              <button class="tick ${this._level === val ? "on" : ""}"
                style="left:${pct(i)}%" title=${desc} ?disabled=${this._busy}
                @click=${() => this._commitLevel(val)}>${label}</button>`)}
          </div>
        </div>
        <button class="auto-dismiss" title="Dismiss"
          @click=${() => { this._autoOpen = false; }}>${icon("x-mark")}</button>
      </div>
      ${this._renderSwarmPreflight()}`;
  }

  _draftObjectives() {
    const ta = this.renderRoot.querySelector("textarea");
    store.draftObjectives((ta?.value || "").trim());
  }

  _setRow(i, field, value) {
    const rows = [...this._objRows];
    rows[i] = { ...rows[i], [field]: value };
    this._objRows = rows;
  }

  _beginRun() {
    const rows = this._objRows
      .map((r) => ({ text: (r.text || "").trim(), acceptance: (r.acceptance || "").trim() }))
      .filter((r) => r.text);
    if (!rows.length) return;
    store.objectives(rows);
    // Keep the objectives, collapsed into an expando, so they can be tweaked
    // and re-run without re-drafting.
    this._objCollapsed = true;
  }

  /**
   * Mid-run: push edited objectives to the running orchestrator, which
   * updates its goals and interjects the new instructions to its workers.
   */
  _updateObjectives() {
    const rows = this._objRows
      .map((r) => ({ text: (r.text || "").trim(), acceptance: (r.acceptance || "").trim() }))
      .filter((r) => r.text);
    if (!rows.length) return;
    store.updateObjectives(rows);
    this._objCollapsed = true;
  }

  /** Queue the current input to auto-send when the running turn finishes. */
  _queueSend() {
    const ta = this.renderRoot.querySelector("textarea");
    const text = (ta?.value || "").trim();
    const ready = this._attachments.filter((a) => !a.uploading).map((a) => a.id);
    if (!text && !ready.length) return;
    this._queued = { text, ready };
    if (ta) { ta.value = ""; ta.style.height = "auto"; }
    this._attachments = [];
  }

  render() {
    return html`
      <div class="box ${this._dragOver ? "drag" : ""}"
        @dragover=${(e) => { e.preventDefault(); this._dragOver = true; }}
        @dragleave=${() => { this._dragOver = false; }}
        @drop=${this._onDrop}>
        <div class="grip" title="Drag to resize" @pointerdown=${this._onGripDown}></div>
        ${this._renderAutonomyControl()}
        ${this._autonomyMode() && this._objRows.length ? (
          this._objCollapsed
            ? html`
              <button class="obj-expando" @click=${() => { this._objCollapsed = false; }}
                title="Show / edit objectives">
                ${icon("chevron-right")} Objectives <span class="count">${this._objRows.length}</span>
                <span class="hint">tap to edit / re-run</span>
              </button>`
            : html`
              <div class="obj-editor">
                <div class="oe-head" @click=${() => { this._objCollapsed = true; }} title="Collapse">
                  ${icon("chevron-down")} Objectives
                  <span class="hint">${this._busy ? "edit, then update the running orchestrator" : "edit, then begin the run"}</span></div>
                <div class="oe-cols"><span>Goal</span><span>Acceptance criteria</span></div>
                ${this._objRows.map((r, i) => html`
                  <div class="oe-row">
                    <input class="oe-text" .value=${r.text} placeholder="what to build"
                      @input=${(e) => this._setRow(i, "text", e.target.value)}>
                    <input class="oe-acc" .value=${r.acceptance} placeholder="done when…"
                      @input=${(e) => this._setRow(i, "acceptance", e.target.value)}>
                    <button class="oe-x" title="Remove"
                      @click=${() => { this._objRows = this._objRows.filter((_, j) => j !== i); }}>
                      ${icon("x-mark")}</button>
                  </div>`)}
                <div class="oe-actions">
                  <button class="oe-add"
                    @click=${() => { this._objRows = [...this._objRows, { text: "", acceptance: "" }]; }}>+ objective</button>
                  <span class="spacer"></span>
                  <button class="oe-discard"
                    @click=${() => { this._objRows = []; this._lastDraftGoal = null; this._objCollapsed = false; }}>discard</button>
                  ${this._busy
                    ? html`<button class="oe-begin" ?disabled=${!this._connected}
                        title="Send the edited objectives to the running orchestrator, which interjects updated instructions to its workers"
                        @click=${() => this._updateObjectives()}>Update objectives</button>`
                    : html`<button class="oe-begin" ?disabled=${!this._connected}
                        @click=${() => this._beginRun()}>Begin run</button>`}
                </div>
              </div>`
        ) : nothing}
        ${this._queued ? html`
          <div class="queued-chip">
            ${icon("arrow-path")} <span title=${this._queued.text}>queued: ${this._queued.text || "(attachment)"}</span>
            <button title="Cancel queued message" @click=${() => { this._queued = null; }}>${icon("x-mark")}</button>
          </div>` : nothing}
        ${this._attachments.length ? html`
          <div class="chips">
            ${this._attachments.map((a) => html`
              <span class="chip">
                ${a.uploading
                  ? html`<span class="up">uploading...</span>`
                  : html`<img src="/media/${a.sessionId}/${a.id}" alt=${a.name} title=${a.name}>`}
                <button title="Remove" @click=${() => {
                  this._attachments = this._attachments.filter((x) => x !== a);
                }}>${icon("x-mark")}</button>
              </span>`)}
          </div>` : nothing}
        <textarea rows="1" placeholder=${
          this._level === "orchestrator" || this._level === "swarm"
            ? "Describe an objective for the orchestrator to pursue..."
            : getProfile().composerPlaceholder}
          @paste=${this._onPaste}
          @input=${(e) => {
            if (!this._manualHeight) {
              e.target.style.height = "auto";
              e.target.style.height = e.target.scrollHeight + "px";
            }
          }}
          @keydown=${(e) => {
            if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); this._send(); }
          }}></textarea>
        <div class="controls">
          <button class="circle attach" title="Attach files (or paste / drop)"
            @click=${() => this.renderRoot.querySelector("input[type=file]").click()}>
            ${icon("plus")}</button>
          <input type="file" multiple
            @change=${(e) => { this._addFiles([...e.target.files]); e.target.value = ""; }}>
          ${this._autonomyMode() ? html`
            <button class="draft-btn ${this._draftPending ? "pending" : ""}"
              title="Draft objectives from your goal (guided intake)"
              ?disabled=${this._busy || !this._connected || this._draftPending}
              @click=${() => this._draftObjectives()}>
              ${this._draftPending
                ? html`<span class="spin">${icon("arrow-path")}</span> Drafting…`
                : html`✦ Draft`}</button>`
            : nothing}
          <span class="spacer"></span>
          ${this._busy
            ? html`
                <button class="queue-btn" title="Queue this message to send when the current turn finishes"
                  ?disabled=${!!this._queued} @click=${() => this._queueSend()}>
                  ${icon("arrow-up")} Queue</button>
                <button class="circle act abort" title="Stop"
                  @click=${() => store.abort()}>${icon("stop")}</button>`
            : this._autoload
              ? html`<button class="circle act" disabled title=${localLlm.progress?.text || "Loading model..."}>
                  <span class="spin">${icon("arrow-path")}</span></button>`
              : html`<button class="circle act" title="Send (Enter)"
                  ?disabled=${!this._connected} @click=${() => this._send()}>
                  ${icon("arrow-up")}</button>`}
        </div>
      </div>
    `;
  }
}

customElements.define("ba-composer", BaComposer);
