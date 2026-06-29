// SPDX-FileCopyrightText: 2026 agentcore contributors
//
// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Interactive pipeline viewer: renders the orchestrator/swarm run as a
// zoomable node-edge DAG (SVG). Nodes are colored by role and lit by live
// status; edges are the dependency graph the scheduler runs. Clicking a node
// asks the chat to focus that agent (node-select event); clicking empty space
// clears it (node-clear). A pure projection of the autonomy snapshot — no
// state of its own beyond the camera (zoom/pan).

import { LitElement, html, css, svg, nothing } from "lit";
import { icon } from "/static/core/icons.js";
import { layoutDAG } from "/static/lib/dag-layout.js";

const ROLE_CLASS = { gather: "gather", evaluator: "eval", qa: "qa", worker: "worker" };

export class BaDagViewer extends LitElement {
  static properties = {
    view: { attribute: false },
    focused: { attribute: false },
    collapsed: { state: true },
    _scale: { state: true },
    _tx: { state: true },
    _ty: { state: true },
  };

  constructor() {
    super();
    this.view = null;
    this.focused = "";
    this.collapsed = false;
    this._scale = 1; this._tx = 0; this._ty = 0;
    this._fitKey = "";          // refit only when the node set changes, not on every token
    this._drag = null;
  }

  // --- derive the graph from the snapshot --------------------------------
  _graph() {
    const v = this.view || {};
    const order = v.agentOrder || [];
    const agents = v.agents || {};
    const present = new Set(order.filter((id) => agents[id]));
    const raw = order.map((id) => agents[id]).filter(Boolean);
    if (!raw.length) return { nodes: [], edges: [], width: 0, height: 0 };

    // Which non-gather nodes are sinks (nothing depends on them)? A gather node
    // with no explicit deps is the terminal merge — hang it off the sinks so it
    // lands in the final generation instead of floating at the source.
    const depended = new Set();
    raw.forEach((a) => (a.dependsOn || []).forEach((d) => depended.add(d)));
    const sinks = raw.filter((a) => a.role !== "gather" && !depended.has(a.id)).map((a) => a.id);

    const nodes = raw.map((a) => {
      let needs = (a.dependsOn || []).filter((d) => present.has(d));
      if (a.role === "gather" && !needs.length) needs = sinks.filter((s) => s !== a.id);
      return { id: a.id, needs, role: a.role || "worker", state: a.state,
               ok: a.ok, task: a.task || "", round: a.round };
    });
    return layoutDAG(nodes);
  }

  updated() {
    const g = this._lastGraph;
    if (!g) return;
    const key = g.nodes.map((n) => n.id).join("|");
    if (key && key !== this._fitKey) { this._fitKey = key; this._fit(g); }
  }

  _fit(g) {
    const host = this.renderRoot?.querySelector(".canvas");
    if (!host || !g.width) return;
    const vw = host.clientWidth || 600, vh = host.clientHeight || 200;
    const s = Math.min(vw / g.width, vh / g.height, 1.4) || 1;
    this._scale = s;
    this._tx = Math.max(0, (vw - g.width * s) / 2);
    this._ty = Math.max(0, (vh - g.height * s) / 2);
  }

  // --- camera ------------------------------------------------------------
  _onWheel(e) {
    e.preventDefault();
    const f = e.deltaY < 0 ? 1.1 : 1 / 1.1;
    const ns = Math.min(10, Math.max(0.2, this._scale * f));
    const r = this.renderRoot.querySelector(".canvas").getBoundingClientRect();
    const mx = e.clientX - r.left, my = e.clientY - r.top;
    // zoom toward the cursor
    this._tx = mx - (mx - this._tx) * (ns / this._scale);
    this._ty = my - (my - this._ty) * (ns / this._scale);
    this._scale = ns;
  }

  _onPointerDown(e) {
    if (e.target.closest(".node")) return;   // node handles its own click
    this._drag = { x: e.clientX, y: e.clientY, tx: this._tx, ty: this._ty, moved: false };
    try { this.renderRoot.querySelector(".canvas").setPointerCapture(e.pointerId); } catch { /* no active pointer */ }
  }
  _onPointerMove(e) {
    if (!this._drag) return;
    const dx = e.clientX - this._drag.x, dy = e.clientY - this._drag.y;
    if (Math.abs(dx) + Math.abs(dy) > 3) this._drag.moved = true;
    this._tx = this._drag.tx + dx; this._ty = this._drag.ty + dy;
  }
  _onPointerUp(e) {
    const wasDrag = this._drag && this._drag.moved;
    this._drag = null;
    if (!wasDrag && !e.target.closest(".node")) {
      this.dispatchEvent(new CustomEvent("node-clear", { bubbles: true, composed: true }));
    }
  }

  _selectNode(id, e) {
    e.stopPropagation();
    this.dispatchEvent(new CustomEvent("node-select", { detail: { id }, bubbles: true, composed: true }));
  }

  render() {
    const g = this._graph();
    this._lastGraph = g;
    if (!g.nodes.length) return nothing;
    const n = g.nodes.length;
    return html`
      <div class="hdr">
        <button class="toggle" @click=${() => { this.collapsed = !this.collapsed; }}
          title=${this.collapsed ? "Show pipeline" : "Hide pipeline"}>
          ${icon(this.collapsed ? "chevron-right" : "chevron-down")}
        </button>
        <span class="title">Pipeline</span>
        <span class="count">${n} node${n === 1 ? "" : "s"}</span>
        <span class="spacer"></span>
        ${this.collapsed ? nothing : html`
          <button class="fit" @click=${() => this._fit(g)} title="Fit to view">${icon("arrows-pointing-out")}</button>`}
      </div>
      ${this.collapsed ? nothing : html`
        <div class="canvas" @wheel=${this._onWheel}
          @pointerdown=${this._onPointerDown} @pointermove=${this._onPointerMove}
          @pointerup=${this._onPointerUp} @pointercancel=${this._onPointerUp}>
          <svg width="100%" height="100%">
            <g transform="translate(${this._tx} ${this._ty}) scale(${this._scale})">
              ${g.edges.map((ed) => svg`<path class="edge" d=${ed.path}></path>`)}
              ${g.nodes.map((node) => this._node(node))}
            </g>
          </svg>
        </div>`}
    `;
  }

  _node(node) {
    const roleC = ROLE_CLASS[node.role] || "worker";
    const stateC = node.state === "running" ? "running"
      : node.ok === false ? "fail" : node.state === "done" ? "done" : "idle";
    const focused = this.focused === node.id ? "focused" : "";
    const label = (node.task || node.id).slice(0, 42);
    const short = node.id.split(":").pop();
    return svg`
      <g class="node ${roleC} ${stateC} ${focused}" transform="translate(${node.x} ${node.y})"
         @click=${(e) => this._selectNode(node.id, e)}>
        <rect width=${node.w} height=${node.h} rx="8"></rect>
        <text class="role" x="10" y="19">${node.role}</text>
        <text class="name" x="10" y="38">${short}</text>
        <title>${label}</title>
        ${node.state === "running"
          ? svg`<circle class="pulse" cx=${node.w - 14} cy="16" r="4"></circle>`
          : node.ok === false
          ? svg`<text class="mark fail" x=${node.w - 18} y="20">✗</text>`
          : node.state === "done"
          ? svg`<text class="mark ok" x=${node.w - 18} y="20">✓</text>` : nothing}
      </g>`;
  }

  static styles = css`
    :host { display: block; border: 1px solid var(--border, #2c3542);
      border-radius: var(--radius-md, 10px); background: var(--surface-2, var(--surface, #1b212b));
      overflow: hidden; margin-bottom: 12px; }
    .hdr { display: flex; align-items: center; gap: 8px; padding: 6px 10px;
      border-bottom: 1px solid var(--border, #2c3542); font-size: 12.5px; }
    .hdr .title { font-weight: 600; letter-spacing: .02em; }
    .hdr .count { color: var(--muted, #8893a5); font-size: 11.5px; }
    .hdr .spacer { flex: 1; }
    .hdr button { display: inline-flex; align-items: center; background: none; border: none;
      color: var(--muted, #8893a5); cursor: pointer; padding: 2px; border-radius: 5px; }
    .hdr button:hover { color: var(--text, #e4e9f0); background: var(--surface-3, rgba(255,255,255,.05)); }
    .hdr button svg, .hdr button :first-child { width: 15px; height: 15px; }
    .canvas { height: 210px; cursor: grab; touch-action: none;
      background: repeating-linear-gradient(0deg, transparent, transparent 23px, rgba(255,255,255,.018) 24px),
                  repeating-linear-gradient(90deg, transparent, transparent 23px, rgba(255,255,255,.018) 24px); }
    .canvas:active { cursor: grabbing; }
    svg { display: block; }
    .edge { fill: none; stroke: var(--muted, #8893a5); stroke-width: 1.5; opacity: .5; }
    .node { cursor: pointer; }
    .node rect { fill: var(--surface-3, #222a36); stroke: var(--border, #3a4555); stroke-width: 1.5;
      transition: stroke .15s, fill .15s; }
    .node text { fill: var(--text, #e4e9f0); font-size: 11px; pointer-events: none;
      font-family: ui-monospace, "SF Mono", Menlo, monospace; }
    .node text.role { fill: var(--muted, #8893a5); font-size: 9px; letter-spacing: .12em;
      text-transform: uppercase; }
    .node text.name { font-weight: 600; font-size: 11.5px; }
    .node text.mark.ok { fill: var(--success, #7fb88b); font-size: 13px; }
    .node text.mark.fail { fill: var(--danger, #d98b7e); font-size: 13px; }
    /* role accents on the left edge via stroke color */
    .node.worker rect { stroke-left: var(--accent); }
    .node.worker.idle rect { stroke: var(--border, #3a4555); }
    .node.running rect { stroke: var(--accent, #e8a06b); stroke-width: 2; }
    .node.done rect { stroke: var(--success, #7fb88b); }
    .node.fail rect { stroke: var(--danger, #d98b7e); }
    .node.gather rect { fill: color-mix(in srgb, var(--accent-2, #6fa8c7) 14%, var(--surface-3, #222a36)); }
    .node.qa rect { fill: color-mix(in srgb, var(--success, #7fb88b) 12%, var(--surface-3, #222a36)); }
    .node.focused rect { stroke: var(--accent-2, #6fa8c7); stroke-width: 3; }
    .pulse { fill: var(--accent, #e8a06b); animation: pulse 1.1s ease-in-out infinite; }
    @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: .25; } }
    @media (prefers-reduced-motion: reduce) { .pulse { animation: none; } }
  `;
}

customElements.define("ba-dag-viewer", BaDagViewer);
