# SPDX-License-Identifier: GPL-3.0-or-later
"""
Self-contained UI regression suite — NO LLM, NO Blender, NO agent backend.

Serves only the static web bundle and drives the real store + Lit components
with synthetic WS events (store._handle), then asserts rendered DOM / store
state. This is the fast, deterministic harness that catches the class of UI
bugs that kept slipping through (raw <think> tags, session jumble, stop not
adopting the session id, autonomy reset on reload, editable objectives, …).

Runs in a couple of seconds. Needs Playwright + Chromium:
    python tests/e2e_ui_selfcontained.py
"""

import os
import threading

import uvicorn
from playwright.sync_api import sync_playwright
from starlette.applications import Starlette
from starlette.responses import FileResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

_WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "agent", "blagent", "web")
_PORT = 8736
_results = []


def _check(name, ok, detail=""):
    _results.append((name, bool(ok), detail))
    print(("PASS" if ok else "FAIL"), "-", name, (":: " + detail) if detail else "")


def _app():
    async def index(_req):
        return FileResponse(os.path.join(_WEB, "index.html"))
    return Starlette(routes=[
        Route("/", index),
        Mount("/static", app=StaticFiles(directory=_WEB), name="static"),
    ])


# Helper run in the page: drive store._handle and return state/DOM probes.
_DOM_TEXT = """() => { const o=[]; const w=(r)=>{r.querySelectorAll('*').forEach(e=>{if(e.shadowRoot)w(e.shadowRoot)});o.push(r.textContent||'')}; w(document); return o.join('\\n'); }"""


def _drive(page, js):
    return page.evaluate("async () => { const { store } = await import('/static/core/store.js'); " + js + " }")


def main():
    server = uvicorn.Server(uvicorn.Config(_app(), host="127.0.0.1", port=_PORT, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        pass
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page()
            errs = []
            page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: errs.append("pageerror: " + str(e)))
            page.goto("http://127.0.0.1:{}/".format(_PORT), wait_until="networkidle")
            page.wait_for_timeout(500)

            # --- branding from the web extension ---
            text = page.evaluate(_DOM_TEXT)
            _check("brand: Blender extension applied", "Blender" in text)
            _check("title set by extension", page.title() == "Blender Agent", page.title())

            # --- autonomy level restored from hello.config (no reset to yolo) ---
            _drive(page, "store._handle({type:'hello', config:{autonomy_level:'orchestrator', endpoint:'x', model:'m', use_local_llm:false}, sessions:[], local_llm:{}, instance:{}});")
            page.wait_for_timeout(150)
            lvl = _drive(page, "return store.state.autonomyLevel;")
            _check("autonomy level adopted from hello (not yolo)", lvl == "orchestrator", "level=%s" % lvl)

            # --- autonomy_accepted adopts session id + sets busy + resets view ---
            _drive(page, "store._handle({type:'agent_spawned', session_id:'s0', agent_id:'s0:w:t0', role:'worker', task:'stale'});")
            _drive(page, "store._handle({type:'autonomy_accepted', session_id:'orch-1'});")
            page.wait_for_timeout(120)
            st = _drive(page, "return {sid: store.state.sessionId, busy: store.state.busy, agents: store.state.autonomy.agentOrder.length};")
            _check("autonomy_accepted adopts session id", st["sid"] == "orch-1", str(st))
            _check("autonomy_accepted sets busy", st["busy"] is True)
            _check("autonomy_accepted resets prior agents", st["agents"] == 0)

            # --- worker card collapses <think>, shows answer, no raw tags ---
            _drive(page, "store._handle({type:'agent_spawned', session_id:'orch-1', agent_id:'orch-1:w:t1', role:'worker', task:'do x'});")
            _drive(page, "store._handle({type:'assistant_done', session_id:'orch-1:w:t1', parent_session_id:'orch-1', role:'worker', tool_calls:[], content:'<think>SECRET_PLAN_42</think>VISIBLE_ANSWER_42'});")
            page.wait_for_timeout(400)
            text = page.evaluate(_DOM_TEXT)
            _check("worker: visible answer shown", "VISIBLE_ANSWER_42" in text)
            _check("worker: no raw <think> tag", "<think>" not in text)
            _check("worker: reasoning collapsed (hidden)", "SECRET_PLAN_42" not in text)
            _check("worker: Thought disclosure present", "Thought for a moment" in text)

            # --- worker tool call renders ---
            _drive(page, "store._handle({type:'tool_status', session_id:'orch-1:w:t1', parent_session_id:'orch-1', call_id:'c1', name:'execute_blender_code', arguments:'{}', state:'running'});")
            page.wait_for_timeout(300)
            text = page.evaluate(_DOM_TEXT)
            _check("worker: tool call rendered", "execute_blender_code" in text)

            # --- agent_done shows proof ---
            _drive(page, "store._handle({type:'agent_done', session_id:'orch-1', agent_id:'orch-1:w:t1', role:'worker', ok:true, proof:'PROOF_DONE_42', objective_id:'o1'});")
            page.wait_for_timeout(300)
            text = page.evaluate(_DOM_TEXT)
            _check("worker: proof shown on done", "PROOF_DONE_42" in text)

            # --- session switch clears the autonomy view (no jumble) + busy ---
            _drive(page, "store._handle({type:'session_loaded', session_id:'plain-1', records:[], media:[]});")
            page.wait_for_timeout(200)
            st = _drive(page, "return {agents: store.state.autonomy.agentOrder.length, objs: store.state.autonomy.objectives.length, busy: store.state.busy};")
            _check("session switch clears worker cards", st["agents"] == 0, str(st))
            _check("session switch clears objectives", st["objs"] == 0)
            _check("session switch clears busy", st["busy"] is False)

            # --- main transcript collapses <think> in a persisted assistant record ---
            _drive(page, "store._handle({type:'session_loaded', session_id:'plain-1', records:[{role:'assistant', content:'<think>INNER_THOUGHT_9</think>OUTER_REPLY_9', tool_calls:[]}], media:[]});")
            page.wait_for_timeout(300)
            text = page.evaluate(_DOM_TEXT)
            _check("transcript: assistant answer shown", "OUTER_REPLY_9" in text)
            _check("transcript: no raw <think>", "<think>" not in text)
            _check("transcript: reasoning collapsed", "INNER_THOUGHT_9" not in text)

            # --- objectives draft renders read-only (no editable cells) ---
            _drive(page, "store.setAutonomyLevel('orchestrator'); store._handle({type:'objectives_draft', goal:'g', objectives:[{text:'Goal one full text here', acceptance:'done when X happens fully'},{text:'Goal two', acceptance:'done when Y'}]});")
            page.wait_for_timeout(400)
            n_items = page.locator(".ol-items li").count()
            _check("objectives: read-only list rendered", n_items == 2, "%d items" % n_items)
            editable = page.evaluate("""() => { let f=0; const w=(r)=>{r.querySelectorAll('.obj-list input,.obj-list textarea,.oe-row').forEach(()=>f++); r.querySelectorAll('*').forEach(e=>{if(e.shadowRoot)w(e.shadowRoot)})}; w(document); return f; }""")
            _check("objectives: no editable cells", editable == 0, "editable=%d" % editable)
            text = page.evaluate(_DOM_TEXT)
            _check("objectives: full goal text (not truncated)", "Goal one full text here" in text)

            _check("no fatal console errors", not [e for e in errs if "websocket" not in e.lower() and "/ws" not in e.lower()],
                   "; ".join(errs[:3]))
            browser.close()
    finally:
        server.should_exit = True

    n_fail = sum(1 for _, ok, _ in _results if not ok)
    print("\n=== %d checks, %d failed ===" % (len(_results), n_fail))
    raise SystemExit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
