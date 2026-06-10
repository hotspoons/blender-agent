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
      webllm: { status: "disconnected", model_id: "", connected: false },
      sessions: [],
      sessionId: "",
      records: [],       // persisted transcript records for the open session
      media: [],         // media items for the open session
      streaming: "",     // assistant text being streamed right now
      busy: false,       // a turn is running
      toolCalls: {},     // call_id -> {name, arguments, state, summary, media_ids}
      toolOrder: [],     // call ids in arrival order (current turn)
      pendingConfirm: null, // {call_id, name, arguments}
      error: "",
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
        this._set({ config: msg.config, sessions: msg.sessions, webllm: msg.webllm });
        if (!this.state.sessionId && msg.sessions.length) {
          this.loadSession(msg.sessions[0].id);
        }
        break;
      case "sessions":
        this._set({ sessions: msg.sessions });
        break;
      case "session_loaded":
        this._set({
          sessionId: msg.session_id,
          records: msg.records || [],
          media: msg.media || [],
          streaming: "",
          toolCalls: {},
          toolOrder: [],
          pendingConfirm: null,
          error: "",
        });
        break;
      case "chat_accepted":
        this._set({ sessionId: msg.session_id, busy: true, error: "" });
        this.send({ type: "list_sessions" });
        break;
      case "user_record":
        if (forThisSession) {
          this.state.records.push({ role: "user", content: msg.content });
          this._set({ records: this.state.records });
        }
        break;
      case "token":
        if (forThisSession) this._set({ streaming: this.state.streaming + msg.text, busy: true });
        break;
      case "assistant_done":
        if (forThisSession) {
          this.state.records.push({
            role: "assistant",
            content: msg.content,
            tool_calls: msg.tool_calls || [],
          });
          this._set({ records: this.state.records, streaming: "" });
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
          this._set({ busy: false, streaming: "" });
          this.send({ type: "list_sessions" });
          this._refreshMedia();
        }
        break;
      case "config":
        this._set({ config: msg.config });
        break;
      case "webllm_status":
        this._set({ webllm: { status: msg.status, model_id: msg.model_id, connected: msg.connected } });
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

  chat(content) {
    this._set({ streaming: "", toolCalls: {}, toolOrder: [], error: "" });
    this.send({ type: "chat", session_id: this.state.sessionId, content });
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

  confirm(callId, approve) {
    this.send({ type: "confirm", session_id: this.state.sessionId, call_id: callId, approve });
  }

  abort() {
    this.send({ type: "abort", session_id: this.state.sessionId });
  }
}

export const store = new Store();
