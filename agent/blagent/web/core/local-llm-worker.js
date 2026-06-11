// SPDX-License-Identifier: GPL-3.0-or-later
//
// Worker shim around the host-agnostic inference engine: keeps WASM
// generation off the main thread. See core/local-llm-engine.js for the
// protocol and the main-thread variant (used when a browser exposes
// WebGPU to pages but not to workers).

import { LocalLlmEngine } from "/static/core/local-llm-engine.js";

const engine = new LocalLlmEngine((msg) => self.postMessage(msg));
self.onmessage = (e) => engine.handle(e.data);
