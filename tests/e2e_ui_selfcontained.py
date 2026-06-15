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

import json
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

            # The frontend renders the backend-owned `autonomy_view` SNAPSHOT and
            # reduces no autonomy events itself. Build snapshots like the backend's
            # OrchestratorView.snapshot() and feed them via the autonomy_view event.
            def push_view(view):
                page.evaluate(
                    "async (v) => { const { store } = await import('/static/core/store.js'); "
                    "store._handle({type:'autonomy_view', session_id:'orch-1', view: v}); }",
                    view)

            def view(agents, order, objectives=None, done=None, prompts=None):
                return {"prompts": prompts or [], "objectives": objectives or [], "agents": agents,
                        "agentOrder": order, "rounds": [], "gathered": None, "done": done,
                        "audit": None, "planner": None, "currentRound": 0, "draft": None}

            # --- the original request is pinned at the top (Request card) ---
            push_view(view({}, [], prompts=["ORIGINAL_PROMPT_PEGS"]))
            page.wait_for_timeout(200)
            text = page.evaluate(_DOM_TEXT)
            _check("request card shows the original prompt at top", "ORIGINAL_PROMPT_PEGS" in text)

            # --- a mid-turn autonomy switch shows a pending hint (deferred) ---
            _drive(page, "store._set({busy:true}); store._handle({type:'config', config:{autonomy_level:'yolo', pending_autonomy:'orchestrator'}});")
            page.wait_for_timeout(120)
            pa = _drive(page, "return store.state.pendingAutonomy;")
            _check("pending autonomy tracked from config event", pa == "orchestrator", "pa=%s" % pa)
            page.evaluate("""() => { const find=(r)=>{const e=r.querySelector&&r.querySelector('ba-composer'); if(e)return e; let f=null; r.querySelectorAll&&r.querySelectorAll('*').forEach(el=>{if(el.shadowRoot){const g=find(el.shadowRoot); if(g)f=g;}}); return f;}; const c=find(document); if(c){c._autoOpen=true; c.requestUpdate&&c.requestUpdate();} }""")
            page.wait_for_timeout(200)
            text = page.evaluate(_DOM_TEXT)
            _check("pending autonomy hint rendered in composer",
                   "switching to" in text and "after this turn" in text)
            _drive(page, "store._set({busy:false});")

            # --- planner card: draft-phase "looking around" projects from the
            #     snapshot's planner field (feedback before objectives arrive) ---
            push_view({**view({}, []), "planner": {
                "phase": "draft", "round": 0, "active": True,
                "reasoning": "PLANNER_LOOKING_AROUND_77", "content": ""}})
            page.wait_for_timeout(250)
            text = page.evaluate(_DOM_TEXT)
            _check("planner: draft card shown before objectives", "Planning objectives" in text)
            _check("planner: reasoning trace streamed", "PLANNER_LOOKING_AROUND_77" in text)
            # plan-phase card carries the round label
            push_view({**view({}, []), "currentRound": 1, "planner": {
                "phase": "plan", "round": 1, "active": False,
                "reasoning": "DECOMPOSING_TRACE_88", "content": ""}})
            page.wait_for_timeout(250)
            text = page.evaluate(_DOM_TEXT)
            _check("planner: plan card labels the round", "Decomposing round 2" in text)
            _check("planner: plan reasoning shown", "DECOMPOSING_TRACE_88" in text)

            # --- autonomy_accepted adopts session id + sets busy + resets view ---
            push_view(view({"orch-1:w:t0": {"id": "orch-1:w:t0", "role": "worker", "task": "stale",
                                            "state": "running", "timeline": [], "calls": {}, "media": []}},
                           ["orch-1:w:t0"]))
            _drive(page, "store._handle({type:'autonomy_accepted', session_id:'orch-1'});")
            page.wait_for_timeout(120)
            st = _drive(page, "return {sid: store.state.sessionId, busy: store.state.busy, agents: store.state.autonomy.agentOrder.length};")
            _check("autonomy_accepted adopts session id", st["sid"] == "orch-1", str(st))
            _check("autonomy_accepted sets busy", st["busy"] is True)
            _check("autonomy_accepted resets prior agents", st["agents"] == 0)

            # --- worker card (from snapshot) collapses <think>, renders tool, no raw tags ---
            running_worker = {"orch-1:w:t1": {
                "id": "orch-1:w:t1", "role": "worker", "task": "do x", "state": "running",
                "timeline": [{"kind": "text", "content": "<think>SECRET_PLAN_42</think>VISIBLE_ANSWER_42\n\n```\nVERYLONGTOKEN_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n```"},
                             {"kind": "call", "call_id": "c1"}],
                "calls": {"c1": {"name": "execute_blender_code", "arguments": "{}", "state": "done"}},
                "media": [], "stream": "", "proof": "", "ok": None}}
            push_view(view(running_worker, ["orch-1:w:t1"]))
            page.wait_for_timeout(300)
            text = page.evaluate(_DOM_TEXT)
            _check("worker: visible answer shown", "VISIBLE_ANSWER_42" in text)
            _check("worker: no raw <think> tag", "<think>" not in text)
            _check("worker: reasoning collapsed (hidden)", "SECRET_PLAN_42" not in text)
            _check("worker: Thought disclosure present", "Thought for a moment" in text)
            _check("worker: tool call rendered", "execute_blender_code" in text)
            # A long code block in worker prose WRAPS (no horizontal scroll/truncation).
            pre_probe = page.evaluate("""() => { let pre=null; const w=(r)=>{const p=r.querySelector&&r.querySelector('.wtext pre'); if(p)pre=p; r.querySelectorAll&&r.querySelectorAll('*').forEach(e=>{if(e.shadowRoot)w(e.shadowRoot)})}; w(document); return pre ? {ws: getComputedStyle(pre).whiteSpace, overflowsX: pre.scrollWidth > pre.clientWidth + 2} : null; }""")
            _check("worker code block wraps (pre-wrap, no x-overflow)",
                   pre_probe and pre_probe["ws"] == "pre-wrap" and not pre_probe["overflowsX"], str(pre_probe))

            # --- done worker shows its proof (snapshot) ---
            done_worker = {"orch-1:w:t1": {**running_worker["orch-1:w:t1"], "state": "done",
                                           "ok": True,
                                           "proof": "## PROOF_DONE_42\n\npara one\n\npara two\n\n- item one\n- item two"}}
            push_view(view(done_worker, ["orch-1:w:t1"]))
            page.wait_for_timeout(300)
            text = page.evaluate(_DOM_TEXT)
            _check("worker: proof shown on done (Result tab default)", "PROOF_DONE_42" in text)
            # Proof is rendered markdown with TIGHT spacing (the double/triple-space
            # bug was pre-wrap + browser-default heading/paragraph margins).
            proof_probe = page.evaluate("""() => { let r=null; const w=(root)=>{const el=root.querySelector&&root.querySelector('.proof'); if(el)r=el; root.querySelectorAll&&root.querySelectorAll('*').forEach(e=>{if(e.shadowRoot)w(e.shadowRoot)})}; w(document); if(!r) return null; const h=r.querySelector('h1,h2,h3'); const p=r.querySelector('p'); const px=(el,prop)=>el?parseFloat(getComputedStyle(el)[prop]):0; return { ws: getComputedStyle(r).whiteSpace, lis: r.querySelectorAll('li').length, hTop: px(h,'marginTop'), pTop: px(p,'marginTop') }; }""")
            _check("worker proof: not pre-wrap (no double-spacing)",
                   proof_probe and proof_probe["ws"] != "pre-wrap", str(proof_probe))
            _check("worker proof: markdown list rendered as <li>",
                   proof_probe and proof_probe["lis"] == 2, str(proof_probe))
            _check("worker proof: heading + paragraph margins are tight",
                   proof_probe and proof_probe["hTop"] <= 12 and proof_probe["pTop"] <= 8, str(proof_probe))
            _check("done worker: Result tab hides the work timeline", "execute_blender_code" not in text)
            # switch to the Work tab -> timeline (tool calls) appears
            page.evaluate("""() => { const find=(r)=>{for(const b of r.querySelectorAll('button')){if((b.textContent||'').trim()==='Work')return b; const s=b.shadowRoot&&find(b.shadowRoot); } for(const e of r.querySelectorAll('*')){if(e.shadowRoot){const f=find(e.shadowRoot); if(f)return f;}} return null;}; const b=find(document); if(b)b.click(); }""")
            page.wait_for_timeout(300)
            text = page.evaluate(_DOM_TEXT)
            _check("done worker: Work tab shows the activity timeline", "execute_blender_code" in text)
            # Work timeline scrolls INSIDE the card (doesn't push the session down),
            # and worker cards have a clear shadow for separation.
            wprobe = page.evaluate("""() => { let act=null, card=null; const w=(r)=>{const a=r.querySelector&&r.querySelector('.agent-activity'); if(a)act=a; const c=r.querySelector&&r.querySelector('.agent'); if(c)card=c; r.querySelectorAll&&r.querySelectorAll('*').forEach(e=>{if(e.shadowRoot)w(e.shadowRoot)})}; w(document); return {actMax: act&&getComputedStyle(act).maxHeight, actOv: act&&getComputedStyle(act).overflowY, shadow: card&&getComputedStyle(card).boxShadow}; }""")
            _check("work timeline scrolls internally (capped max-height)",
                   wprobe and wprobe["actMax"] not in (None, "none", "") and wprobe["actOv"] in ("auto", "scroll"),
                   str(wprobe))
            _check("worker card has a separation shadow",
                   wprobe and wprobe["shadow"] not in (None, "none", ""), str(wprobe))

            # --- review loop: orchestrator verdict on the worker + a bounded
            #     QA inspector agent card ---
            qa_view = view({
                "orch-1:w:t1": {
                    "id": "orch-1:w:t1", "role": "worker", "task": "build torso",
                    "state": "done", "ok": True, "proof": "PROOF_QA_42",
                    "timeline": [], "calls": {}, "media": [],
                    "review": {"passed": False, "note": "GUIDANCE_FIX_SEAM", "qa": "",
                               "attempt": 1, "stopped": False}},
                "orch-1:qa:t1:0": {
                    "id": "orch-1:qa:t1:0", "role": "qa", "task": "QA inspect — build torso",
                    "state": "done", "ok": False, "proof": "QA_FINDINGS_TEXT",
                    "reviews": "orch-1:w:t1", "timeline": [], "calls": {}, "media": []}},
                ["orch-1:w:t1", "orch-1:qa:t1:0"])
            push_view(qa_view)
            page.wait_for_timeout(300)
            text = page.evaluate(_DOM_TEXT)
            _check("qa: bounded QA inspector card rendered", "QA inspect — build torso" in text)
            _check("qa: QA inspector findings shown", "QA_FINDINGS_TEXT" in text)
            _check("review: orchestrator guidance shown on worker", "GUIDANCE_FIX_SEAM" in text)
            _check("review: needs-work verdict shown", "needs work" in text)
            _check("review: cycle count shown", "pass 2" in text)
            qa_class = page.evaluate("""() => { let f=false; const w=(r)=>{if(r.querySelector&&r.querySelector('.agent.qa'))f=true; r.querySelectorAll&&r.querySelectorAll('*').forEach(e=>{if(e.shadowRoot)w(e.shadowRoot)})}; w(document); return f; }""")
            _check("qa: QA agent card has dedicated role class", qa_class)

            # --- a tall streaming work timeline latches to the bottom (follows
            #     live output) without scrolling the whole page ---
            many = {"c%d" % i: {"name": "get_objects_summary", "state": "done"} for i in range(28)}
            latch_worker = {"orch-1:w:t1": {
                "id": "orch-1:w:t1", "role": "worker", "task": "x", "state": "running",
                "timeline": [{"kind": "call", "call_id": "c%d" % i} for i in range(28)],
                "calls": many, "media": [], "stream": "", "proof": "", "ok": None}}
            push_view(view(latch_worker, ["orch-1:w:t1"]))
            page.wait_for_timeout(400)
            latch = page.evaluate("""() => { let a=null; const w=(r)=>{const el=r.querySelector&&r.querySelector('.agent-activity.latch'); if(el)a=el; r.querySelectorAll&&r.querySelectorAll('*').forEach(e=>{if(e.shadowRoot)w(e.shadowRoot)})}; w(document); return a ? {overflows: a.scrollHeight > a.clientHeight + 10, atBottom: (a.scrollHeight - a.scrollTop - a.clientHeight) < 80} : null; }""")
            _check("work timeline latches to bottom (overflows + pinned)",
                   latch and latch["overflows"] and latch["atBottom"], str(latch))
            # User scrolls up -> unlatches; further output must NOT yank to bottom.
            page.evaluate("""() => { const f=(r)=>{const el=r.querySelector&&r.querySelector('.agent-activity.latch'); if(el){el.scrollTop=0; el.dispatchEvent(new Event('scroll'));} r.querySelectorAll&&r.querySelectorAll('*').forEach(e=>{if(e.shadowRoot)f(e.shadowRoot)})}; f(document); }""")
            many["c28"] = {"name": "get_objects_summary", "state": "done"}
            latch_worker["orch-1:w:t1"]["timeline"].append({"kind": "call", "call_id": "c28"})
            push_view(view(latch_worker, ["orch-1:w:t1"]))
            page.wait_for_timeout(300)
            top = page.evaluate("""() => { let a=null; const w=(r)=>{const el=r.querySelector&&r.querySelector('.agent-activity.latch'); if(el)a=el; r.querySelectorAll&&r.querySelectorAll('*').forEach(e=>{if(e.shadowRoot)w(e.shadowRoot)})}; w(document); return a ? a.scrollTop : null; }""")
            _check("scrolling up unlatches (new output doesn't yank to bottom)",
                   top is not None and top < 80, "scrollTop=%s" % top)

            # --- worker→orchestrator Q&A renders on the work timeline ---
            qna_worker = {"orch-1:w:t1": {
                "id": "orch-1:w:t1", "role": "worker", "task": "do x", "state": "running",
                "timeline": [{"kind": "question", "content": "WHICH_AXIS_Q", "options": ["X", "Z"]},
                             {"kind": "answer", "content": "USE_Z_ANSWER", "source": "orchestrator"}],
                "calls": {}, "media": [], "stream": "", "proof": "", "ok": None}}
            push_view(view(qna_worker, ["orch-1:w:t1"]))
            page.wait_for_timeout(250)
            text = page.evaluate(_DOM_TEXT)
            _check("worker question rendered on timeline", "WHICH_AXIS_Q" in text)
            _check("orchestrator answer rendered on timeline", "USE_Z_ANSWER" in text)

            # --- worker-produced media surfaces in the Artifacts panel (live) ---
            media_worker = {"orch-1:w:t1": {
                "id": "orch-1:w:t1", "role": "worker", "task": "render", "state": "running",
                "timeline": [{"kind": "call", "call_id": "c9"}],
                "calls": {"c9": {"name": "media_io", "state": "done", "media_ids": ["i7"]}},
                "media": [], "stream": "", "proof": "", "ok": None}}
            push_view(view(media_worker, ["orch-1:w:t1"]))
            page.wait_for_timeout(300)
            html_all = page.evaluate("""() => { const o=[]; const w=(r)=>{r.querySelectorAll('*').forEach(e=>{o.push(e.outerHTML||''); if(e.shadowRoot)w(e.shadowRoot)})}; w(document); return o.join(''); }""")
            _check("worker media appears in Artifacts panel", "/worker-media/orch-1:w:t1/i7" in html_all)

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

            # Reasoning is rendered markdown (tight spacing), not pre-wrapped raw
            # text (which double-spaced on the model's blank lines). Expand and check.
            _drive(page, "store._handle({type:'session_loaded', session_id:'plain-2', records:[{role:'assistant', content:'<think>para A\\n\\npara B</think>REPLY', tool_calls:[]}], media:[]});")
            page.wait_for_timeout(200)
            page.evaluate("""() => { const find=(r)=>{for(const e of r.querySelectorAll('.think-head'))return e; for(const e of r.querySelectorAll('*')){if(e.shadowRoot){const f=find(e.shadowRoot); if(f)return f;}} return null;}; const h=find(document); if(h)h.click(); }""")
            page.wait_for_timeout(200)
            tb = page.evaluate("""() => { let b=null; const w=(r)=>{const el=r.querySelector&&r.querySelector('.think-body'); if(el)b=el; r.querySelectorAll&&r.querySelectorAll('*').forEach(e=>{if(e.shadowRoot)w(e.shadowRoot)})}; w(document); return b ? {ws: getComputedStyle(b).whiteSpace, ps: b.querySelectorAll('p').length} : null; }""")
            _check("thinking trace: not pre-wrap, markdown paragraphs",
                   tb and tb["ws"] != "pre-wrap" and tb["ps"] >= 2, str(tb))

            # --- objectives draft renders read-only (no editable cells) ---
            _drive(page, "store.setAutonomyLevel('orchestrator'); store._handle({type:'objectives_draft', goal:'g', objectives:[{text:'Goal one full text here', acceptance:'done when X happens fully'},{text:'Goal two', acceptance:'done when Y'}]});")
            page.wait_for_timeout(400)
            n_items = page.locator(".ol-items li").count()
            _check("objectives: read-only list rendered", n_items == 2, "%d items" % n_items)
            editable = page.evaluate("""() => { let f=0; const w=(r)=>{r.querySelectorAll('.obj-list input,.obj-list textarea,.oe-row').forEach(()=>f++); r.querySelectorAll('*').forEach(e=>{if(e.shadowRoot)w(e.shadowRoot)})}; w(document); return f; }""")
            _check("objectives: no editable cells", editable == 0, "editable=%d" % editable)
            text = page.evaluate(_DOM_TEXT)
            _check("objectives: full goal text (not truncated)", "Goal one full text here" in text)

            # --- backend-authoritative: a reload PROJECTS the orchestrator view
            #     from the backend snapshot (frontend holds no autonomy state) ---
            snap = {
                "objectives": [{"id": "obj-0", "text": "RECON_OBJECTIVE_ABC", "acceptance": "done when X", "status": "met"}],
                "agents": {"reload-1:w:t1": {
                    "id": "reload-1:w:t1", "role": "worker", "task": "RECON_WORKER_TASK_XYZ",
                    "state": "done", "ok": True, "proof": "RECON_PROOF_123",
                    "timeline": [{"kind": "text", "content": "<think>reasoning</think>worker did it"}],
                    "calls": {}, "media": []}},
                "agentOrder": ["reload-1:w:t1"], "rounds": [], "gathered": None,
                "done": {"paused": False, "allMet": True, "rounds": 1}, "audit": None, "currentRound": 0,
            }
            page.evaluate("async (snap) => { const { store } = await import('/static/core/store.js'); "
                          "store._handle({type:'session_loaded', session_id:'reload-1', records:[], media:[], autonomy_view: snap}); }",
                          snap)
            page.wait_for_timeout(400)
            st = _drive(page, "return {agents: store.state.autonomy.agentOrder.length, objs: store.state.autonomy.objectives.length};")
            _check("reload projects autonomy snapshot", st["agents"] == 1 and st["objs"] == 1, str(st))
            text = page.evaluate(_DOM_TEXT)
            _check("reload projects objective text", "RECON_OBJECTIVE_ABC" in text)
            _check("reload projects worker proof", "RECON_PROOF_123" in text)
            _check("reload projection: no raw <think>", "<think>" not in text)

            # Benign in a static-only harness: the /ws socket 403s and media
            # <img> URLs (/media, /worker-media) 404 (no backend serving them).
            fatal = [e for e in errs if "websocket" not in e.lower()
                     and "failed to load resource" not in e.lower()]
            _check("no fatal console errors", not fatal, "; ".join(fatal[:3]))
            browser.close()
    finally:
        server.should_exit = True

    n_fail = sum(1 for _, ok, _ in _results if not ok)
    print("\n=== %d checks, %d failed ===" % (len(_results), n_fail))
    raise SystemExit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
