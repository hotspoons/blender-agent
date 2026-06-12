// SPDX-License-Identifier: GPL-3.0-or-later
//
// Client-side state + control-plane WebSocket, modeled on Foyer
// Studio's `core/store.js`/`core/ws.js` pair but speaking the lean
// blagent protocol (see blagent/app.py).
//
// A single store instance is shared by every component; `subscribe()`
// notifies on each state change with the mutated-keys set.

class Store extends EventTarget {
  constructor() {
    super();
    this.state = {
      connected: false,
      config: {},
      localLlm: { status: "disconnected", model_id: "", connected: false },
      instance: { title: "", port: 0 },   // which Blender this agent belongs to
      sessions: [],
      sessionId: "",
      records: [],       // persisted transcript records for the open session
      media: [],         // media items for the open session
      streaming: "",     // assistant text being streamed right now
      drafting: null,    // {name, chars} while the model writes a long tool call
      quiet: 0,          // seconds of LLM-stream silence (backend buffering)
      busy: false,       // a turn is running
      toolCalls: {},     // call_id -> {name, arguments, state, summary, media_ids}
      toolOrder: [],     // call ids in arrival order (current turn)
      pendingConfirm: null, // {call_id, name, arguments}
      error: "",
      models: { endpoint: "", list: [], error: "", loading: false },
    };
    this._ws = null;
    this._backoff = 500;
  }

  subscribe(fn) {
    const handler = (e) => fn(e.detail);
    this.addEventListener("change", handler);
    return () => this.removeEventListener("change", handler);
  }

  _set(patch) {
    Object.assign(this.state, patch);
    this.dispatchEvent(new CustomEvent("change", { detail: new Set(Object.keys(patch)) }));
  }

  // ----------------------------------------------------------------
  // WebSocket lifecycle.

  connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws`);
    this._ws = ws;
    ws.onopen = () => {
      this._backoff = 500;
      this._set({ connected: true, error: "" });
    };
    ws.onclose = () => {
      this._set({ connected: false });
      setTimeout(() => this.connect(), this._backoff);
      this._backoff = Math.min(this._backoff * 2, 10_000);
    };
    ws.onmessage = (e) => {
      let msg;
      try { msg = JSON.parse(e.data); } catch { return; }
      this._handle(msg);
    };
  }

  send(msg) {
    if (this._ws && this._ws.readyState === WebSocket.OPEN) {
      this._ws.send(JSON.stringify(msg));
    }
  }

  // ----------------------------------------------------------------
  // Server event handling.

  _handle(msg) {
    const forThisSession = !msg.session_id || msg.session_id === this.state.sessionId;
    switch (msg.type) {
      case "hello":
        this._set({
          config: msg.config,
          sessions: msg.sessions,
          localLlm: msg.local_llm,
          instance: msg.instance || this.state.instance,
        });
        if (!this.state.sessionId && msg.sessions.length) {
          this.loadSession(msg.sessions[0].id);
        }
        break;
      case "sessions":
        this._set({ sessions: msg.sessions });
        break;
      case "session_loaded": {
        // Mid-turn refreshes (media updates) for the CURRENT session
        // must not wipe live turn state - doing so destroyed the
        // pending-confirm card, the engine timed out, and the model
        // saw phantom "user declined" results.
        const sameSessionBusy = msg.session_id === this.state.sessionId && this.state.busy;
        const patch = {
          sessionId: msg.session_id,
          records: msg.records || [],
          media: msg.media || [],
        };
        if (!sameSessionBusy) {
          Object.assign(patch, {
            streaming: "",
            toolCalls: {},
            toolOrder: [],
            pendingConfirm: null,
            error: "",
          });
        }
        this._set(patch);
        break;
      }
      case "chat_accepted":
        this._set({ sessionId: msg.session_id, busy: true, error: "" });
        this.send({ type: "list_sessions" });
        break;
      case "user_record":
        if (forThisSession) {
          this.state.records.push({
            role: "user",
            content: msg.content,
            media_ids: msg.media_ids || [],
          });
          this._set({ records: this.state.records });
        }
        break;
      case "tool_drafting":
        if (forThisSession) this._set({ drafting: { name: msg.name, chars: msg.chars, n_calls: msg.n_calls }, quiet: 0, busy: true });
        break;
      case "llm_quiet":
        // The stream is alive but the backend is buffering (e.g. vLLM
        // parsing a long tool call) — nothing else will repaint.
        if (forThisSession) this._set({ quiet: msg.seconds, busy: true });
        break;
      case "orchestrator_review":
        // Budget checkpoint: the reviewer's verdict becomes a record so
        // it persists in the conversation like compaction summaries do.
        if (forThisSession) {
          this.state.records.push({
            role: "review",
            content: msg.summary,
            verdict: msg.verdict,
            granted_rounds: msg.granted_rounds,
            detail: msg.detail,
          });
          this._set({ records: this.state.records });
        }
        break;
      case "token":
        if (forThisSession) this._set({ streaming: this.state.streaming + msg.text, busy: true, drafting: null, quiet: 0 });
        break;
      case "assistant_done":
        if (forThisSession) {
          this.state.records.push({
            role: "assistant",
            content: msg.content,
            tool_calls: msg.tool_calls || [],
          });
          this._set({ records: this.state.records, streaming: "", drafting: null, quiet: 0 });
        }
        break;
      case "tool_status": {
        if (!forThisSession) break;
        const calls = { ...this.state.toolCalls };
        const existing = calls[msg.call_id] || {};
        calls[msg.call_id] = {
          ...existing,
          name: msg.name,
          arguments: msg.arguments,
          state: msg.state,
          summary: msg.summary || existing.summary || "",
          media_ids: msg.media_ids || existing.media_ids || [],
          data: msg.data !== undefined ? msg.data : existing.data,
        };
        const order = this.state.toolOrder.includes(msg.call_id)
          ? this.state.toolOrder
          : [...this.state.toolOrder, msg.call_id];
        const patch = { toolCalls: calls, toolOrder: order };
        if (msg.state === "pending_confirm") {
          patch.pendingConfirm = { call_id: msg.call_id, name: msg.name, arguments: msg.arguments };
        } else if (this.state.pendingConfirm?.call_id === msg.call_id) {
          patch.pendingConfirm = null;
        }
        if (msg.media_ids?.length) this._refreshMedia();
        this._set(patch);
        break;
      }
      case "turn_done":
        if (forThisSession) {
          this._set({ busy: false, streaming: "", drafting: null, quiet: 0 });
          this.send({ type: "list_sessions" });
          this._refreshMedia();
        }
        break;
      case "config":
        this._set({ config: msg.config });
        break;
      case "local_llm_status":
        this._set({ localLlm: { status: msg.status, model_id: msg.model_id, connected: msg.connected } });
        break;
      case "instance":
        this._set({ instance: { title: msg.title || "", port: msg.port || 0 } });
        break;
      case "models":
        this._set({
          models: {
            endpoint: msg.endpoint,
            list: msg.models || [],
            error: msg.error || "",
            loading: false,
          },
        });
        break;
      case "error":
        if (forThisSession) this._set({ error: msg.message, busy: false });
        break;
      default:
        break;
    }
  }

  _refreshMedia() {
    // Reload the session to pick up new media metadata (cheap: records
    // come from memory server-side).
    if (this.state.sessionId) {
      this.send({ type: "load_session", id: this.state.sessionId });
    }
  }

  // ----------------------------------------------------------------
  // Actions.

  chat(content, attachments = []) {
    this._set({ streaming: "", drafting: null, quiet: 0, toolCalls: {}, toolOrder: [], error: "" });
    this.send({ type: "chat", session_id: this.state.sessionId, content, attachments });
  }

  /**
   * Upload an image attachment to the current session (creating one
   * when none is open). Resolves to {session_id, id}.
   */
  async uploadAttachment(file) {
    const sessionId = this.state.sessionId || "new";
    const response = await fetch(`/upload/${sessionId}`, {
      method: "POST",
      headers: {
        "Content-Type": file.type || "application/octet-stream",
        // Original name: non-image attachments keep it (sanitized) in
        // the session media folder so the agent can import by name.
        "X-File-Name": encodeURIComponent(file.name || ""),
      },
      body: file,
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.error || `upload failed (${response.status})`);
    }
    const result = await response.json();
    if (!this.state.sessionId) {
      this._set({ sessionId: result.session_id });
      this.send({ type: "list_sessions" });
    }
    return result;
  }

  newSession() {
    this.send({ type: "new_session" });
  }

  loadSession(id) {
    this.send({ type: "load_session", id });
  }

  deleteSession(id) {
    if (id === this.state.sessionId) {
      this._set({ sessionId: "", records: [], media: [] });
    }
    this.send({ type: "delete_session", id });
  }

  setConfig(updates) {
    this.send({ type: "set_config", ...updates });
  }

  /** Fetch the model list for an endpoint (debounced by callers). */
  requestModels(endpoint, apiKey) {
    this._set({ models: { ...this.state.models, loading: true, error: "" } });
    this.send({ type: "list_models", endpoint, api_key: apiKey || "" });
  }

  confirm(callId, approve) {
    this.send({ type: "confirm", session_id: this.state.sessionId, call_id: callId, approve });
  }

  abort() {
    this.send({ type: "abort", session_id: this.state.sessionId });
  }
}

export const store = new Store();
