// SPDX-FileCopyrightText: 2026 Blender Authors
//
// SPDX-License-Identifier: GPL-3.0-or-later

// ba-stl-viewer: STL preview backed by three.js (vendored, MIT).
//
// Two modes: `thumb` renders one static frame to a small canvas (media
// strips — click bubbles a `zoom` event so the host can open a
// lightbox), the default mode runs an interactive orbit viewer.
// three.js (~600 KB) loads lazily on the first viewer instance, so
// sessions without 3D media never pay for it. Files above the size cap
// (default 20 MB) render as a download chip instead of a preview.

import { LitElement, html, css, nothing } from "/static/vendor/lit.js";

const SIZE_CAP_BYTES = 20 * 1024 * 1024;

let threePromise = null;

function loadThree() {
  if (!threePromise) {
    threePromise = Promise.all([
      import("/static/vendor/three.module.js"),
      import("/static/vendor/three-stl-loader.js"),
      import("/static/vendor/three-orbit-controls.js"),
    ]).then(([THREE, stl, orbit]) => ({
      THREE,
      STLLoader: stl.STLLoader,
      OrbitControls: orbit.OrbitControls,
    }));
  }
  return threePromise;
}

export class BaStlViewer extends LitElement {
  static properties = {
    src: { type: String },
    label: { type: String },
    thumb: { type: Boolean },
    _state: { state: true }, // "loading" | "ready" | "toobig" | "error"
  };

  static styles = css`
    *, *::before, *::after { box-sizing: border-box; }
    :host { display: block; }
    .stage {
      position: relative;
      width: 100%;
      height: 100%;
      min-height: 64px;
      border-radius: var(--radius-sm);
      overflow: hidden;
      background:
        radial-gradient(ellipse at 30% 20%, rgba(125, 130, 180, 0.18), transparent 60%),
        var(--surface);
    }
    :host([thumb]) .stage { cursor: zoom-in; }
    canvas { display: block; width: 100%; height: 100%; }
    .note {
      position: absolute;
      inset: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 11px;
      color: var(--text-muted);
      padding: 6px;
      text-align: center;
    }
    .badge {
      position: absolute;
      left: 6px;
      bottom: 6px;
      font-size: 10px;
      font-family: var(--font-mono);
      color: var(--text-muted);
      background: color-mix(in srgb, var(--surface) 75%, transparent);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      padding: 1px 6px;
      pointer-events: none;
    }
  `;

  constructor() {
    super();
    this.src = "";
    this.label = "";
    this.thumb = false;
    this._state = "loading";
    this._disposers = [];
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    for (const dispose of this._disposers.splice(0)) {
      try { dispose(); } catch {}
    }
  }

  firstUpdated() {
    this._build();
  }

  async _build() {
    try {
      const head = await fetch(this.src, { method: "HEAD" });
      const size = Number(head.headers.get("content-length") || 0);
      if (size > SIZE_CAP_BYTES) {
        this._state = "toobig";
        return;
      }
      const { THREE, STLLoader, OrbitControls } = await loadThree();
      const buffer = await (await fetch(this.src)).arrayBuffer();
      const geometry = new STLLoader().parse(buffer);
      geometry.computeVertexNormals();
      geometry.computeBoundingSphere();
      const { center, radius } = geometry.boundingSphere;

      const scene = new THREE.Scene();
      const material = new THREE.MeshStandardMaterial({
        color: 0x8d93b8, roughness: 0.55, metalness: 0.1,
      });
      const mesh = new THREE.Mesh(geometry, material);
      mesh.position.sub(center);
      scene.add(mesh);
      scene.add(new THREE.HemisphereLight(0xf4f5ff, 0x33343d, 1.6));
      const key = new THREE.DirectionalLight(0xffffff, 1.4);
      key.position.set(1, 1, 1.2);
      scene.add(key);

      const stage = this.renderRoot.querySelector(".stage");
      const width = Math.max(stage.clientWidth, 64);
      const height = Math.max(stage.clientHeight, 64);
      const camera = new THREE.PerspectiveCamera(40, width / height, radius / 100, radius * 20);
      // Three-quarter framing, slightly above.
      camera.position.set(radius * 1.9, -radius * 1.9, radius * 1.4);
      camera.up.set(0, 0, 1); // Blender convention: Z-up
      camera.lookAt(0, 0, 0);

      const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      renderer.setSize(width, height);
      stage.appendChild(renderer.domElement);
      this._disposers.push(() => {
        renderer.dispose();
        geometry.dispose();
        material.dispose();
        renderer.domElement.remove();
      });

      if (this.thumb) {
        renderer.render(scene, camera); // one static frame
      } else {
        const controls = new OrbitControls(camera, renderer.domElement);
        controls.enableDamping = true;
        let alive = true;
        this._disposers.push(() => { alive = false; controls.dispose(); });
        const animate = () => {
          if (!alive) return;
          controls.update();
          renderer.render(scene, camera);
          requestAnimationFrame(animate);
        };
        animate();
        // Track host resizes (lightbox open/resize).
        const observer = new ResizeObserver(() => {
          const w = Math.max(stage.clientWidth, 64);
          const h = Math.max(stage.clientHeight, 64);
          camera.aspect = w / h;
          camera.updateProjectionMatrix();
          renderer.setSize(w, h);
        });
        observer.observe(stage);
        this._disposers.push(() => observer.disconnect());
      }
      this._state = "ready";
    } catch (err) {
      console.error("ba-stl-viewer:", err);
      this._state = "error";
    }
  }

  _onClick() {
    if (!this.thumb) return;
    this.dispatchEvent(new CustomEvent("zoom", {
      detail: { src: this.src, alt: this.label || "STL model", kind: "stl" },
      bubbles: true,
      composed: true,
    }));
  }

  render() {
    return html`
      <div class="stage" @click=${() => this._onClick()}>
        ${this._state === "loading" ? html`<div class="note">loading…</div>` : nothing}
        ${this._state === "toobig" ? html`
          <div class="note">STL too large to preview (&gt;20 MB)<br>
            <a href=${this.src} download>download</a></div>` : nothing}
        ${this._state === "error" ? html`<div class="note">preview failed</div>` : nothing}
        <span class="badge">STL</span>
      </div>
    `;
  }
}

customElements.define("ba-stl-viewer", BaStlViewer);
