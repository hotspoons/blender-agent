// SPDX-FileCopyrightText: 2026 agentcore contributors
//
// SPDX-License-Identifier: MIT OR Apache-2.0
//
// DAG layout for the pipeline viewer: topological-generation ordering
// (Kahn's algorithm) → a left-to-right grid, with cubic-bezier edge paths.
// Ported from the zip-ties cadre-graph layout, flattened for this domain
// (no nested cells yet — fan-out instances are just sibling nodes). The
// generation math mirrors the backend DAG.topological_generations the
// pipeline is actually scheduled by.

export const NODE_W = 170;
export const NODE_H = 56;
const COL_GAP = 90;
const ROW_GAP = 22;
const PAD = 28;

/**
 * @param {Array<{id:string, needs?:string[]}>} nodes
 * @returns {{nodes:Array, edges:Array, width:number, height:number}}
 *   positioned nodes get {x,y,w,h,generation,row}; edges get {from,to,path}.
 */
export function layoutDAG(nodes, opts = {}) {
  if (!nodes || !nodes.length) return { nodes: [], edges: [], width: 0, height: 0 };
  const nodeW = opts.nodeW || NODE_W;
  const nodeH = opts.nodeH || NODE_H;
  const colGap = opts.colGap || COL_GAP;
  const rowGap = opts.rowGap || ROW_GAP;
  const pad = opts.pad == null ? PAD : opts.pad;

  const ids = new Set(nodes.map((n) => n.id));
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const needs = (n) => (n.needs || []).filter((d) => ids.has(d) && d !== n.id);

  // Kahn: in-degree from needs, peel off generation by generation.
  const inDeg = new Map();
  const fwd = new Map();
  for (const n of nodes) { inDeg.set(n.id, 0); fwd.set(n.id, []); }
  for (const n of nodes) {
    const deps = needs(n);
    inDeg.set(n.id, deps.length);
    for (const d of deps) fwd.get(d).push(n.id);
  }
  const gens = [];
  let cur = nodes.filter((n) => inDeg.get(n.id) === 0).map((n) => n.id);
  const placed = new Set();
  while (cur.length) {
    cur.sort();
    gens.push(cur);
    cur.forEach((id) => placed.add(id));
    const next = [];
    for (const id of gens[gens.length - 1]) {
      for (const dep of fwd.get(id) || []) {
        inDeg.set(dep, inDeg.get(dep) - 1);
        if (inDeg.get(dep) === 0) next.push(dep);
      }
    }
    cur = next;
  }
  // A cycle would leave nodes unplaced — drop them into a final generation so
  // the viewer still draws everything rather than silently losing nodes.
  const orphans = nodes.filter((n) => !placed.has(n.id)).map((n) => n.id);
  if (orphans.length) gens.push(orphans.sort());

  const pos = new Map();
  const out = [];
  for (let gi = 0; gi < gens.length; gi++) {
    for (let ri = 0; ri < gens[gi].length; ri++) {
      const id = gens[gi][ri];
      const node = {
        ...byId.get(id),
        x: pad + gi * (nodeW + colGap),
        y: pad + ri * (nodeH + rowGap),
        w: nodeW, h: nodeH, generation: gi, row: ri,
      };
      pos.set(id, node);
      out.push(node);
    }
  }

  const edges = [];
  for (const n of nodes) {
    const tgt = pos.get(n.id);
    if (!tgt) continue;
    for (const dep of needs(n)) {
      const src = pos.get(dep);
      if (!src) continue;
      const sx = src.x + src.w, sy = src.y + src.h / 2;
      const tx = tgt.x, ty = tgt.y + tgt.h / 2;
      const dx = Math.max(28, (tx - sx) * 0.5);
      edges.push({
        from: dep, to: n.id,
        path: `M ${sx} ${sy} C ${sx + dx} ${sy} ${tx - dx} ${ty} ${tx} ${ty}`,
      });
    }
  }

  let width = 0, height = 0;
  for (const n of out) { width = Math.max(width, n.x + n.w); height = Math.max(height, n.y + n.h); }
  return { nodes: out, edges, width: width + pad, height: height + pad };
}
