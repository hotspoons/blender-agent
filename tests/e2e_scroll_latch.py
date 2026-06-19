# SPDX-License-Identifier: GPL-3.0-or-later
"""
REAL scroll-latch test for worker cards — drives the actual web bundle in
Chromium and uses REAL mouse-wheel scrolling (not synthetic scrollTop writes),
because the bug only shows with genuine wheel events + Lit re-render timing.

Asserts the behavior the user asked for, on the worker card's activity area:
  1. while streaming, it STAYS pinned to the bottom (follows new output);
  2. a real wheel scroll UP breaks the latch (no snap-back on new output);
  3. wheeling back to the bottom RE-LATCHES (new output sticks again).

    python tests/e2e_scroll_latch.py        # needs Playwright + Chromium
"""
import json
import os
import threading
import time

import uvicorn
from playwright.sync_api import sync_playwright
from starlette.applications import Starlette
from starlette.responses import FileResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

_AGENT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent")
_WEB = os.path.join(_AGENT, "blagent", "web")          # Blender overlay (index.html)
_CORE_WEB = os.path.join(_AGENT, "agentcore", "web")   # generic shell behind it
_PORT = 8741
_results = []


def _check(name, ok, detail=""):
    _results.append((name, bool(ok), detail))
    print(("PASS" if ok else "FAIL"), "-", name, (":: " + detail) if detail else "")


def _layered_static():
    static = StaticFiles(directory=_WEB, check_dir=False)
    static.all_directories = [_WEB, _CORE_WEB]
    return static


def _app():
    async def index(_req):
        return FileResponse(os.path.join(_WEB, "index.html"))
    return Starlette(routes=[
        Route("/", index),
        Mount("/static", app=_layered_static(), name="static"),
    ])


# A worker view (OrchestratorView.snapshot shape) with N timeline text blocks,
# each tall enough that the 360px-capped .agent-activity overflows well.
def _worker_view(n, state="running"):
    timeline = [{"kind": "text",
                 "content": "Step %02d — reasoning about the mesh: checking manifold edges, "
                            "boundary loops, and normals before the next boolean.\n\nMore detail "
                            "on step %02d so the block has real height in the scroll area." % (i, i)}
                for i in range(n)]
    agent = {"id": "orch-1:w:t1", "role": "worker", "task": "build the legs",
             "state": state, "ok": None if state == "running" else True,
             "proof": "", "timeline": timeline, "calls": {}, "media": [], "stream": ""}
    return {"prompts": ["build a robot"], "objectives": [], "agents": {"orch-1:w:t1": agent},
            "agentOrder": ["orch-1:w:t1"], "rounds": [], "gathered": None, "done": None,
            "audit": None, "planner": None, "currentRound": 0, "draft": None}


def _push(page, view):
    page.evaluate(
        "async ([v, rid]) => { const { store } = await import('/static/core/store.js'); "
        "store._handle({type:'autonomy_view', session_id:'orch-1', run_id: rid, view: v}); }",
        [view, "orch-1:run"])


# Walk shadow DOM to the worker activity scroller; return its scroll metrics + page rect.
_ACT = """() => {
  let a=null; const w=(r)=>{const el=r.querySelector&&r.querySelector('.agent-activity.latch');
    if(el)a=el; r.querySelectorAll&&r.querySelectorAll('*').forEach(e=>{if(e.shadowRoot)w(e.shadowRoot)})};
  w(document); if(!a) return null; const r=a.getBoundingClientRect();
  return {scrollTop:a.scrollTop, scrollHeight:a.scrollHeight, clientHeight:a.clientHeight,
          x:r.x, y:r.y, width:r.width, height:r.height,
          dist: a.scrollHeight - a.scrollTop - a.clientHeight}; }"""


def main():
    server = uvicorn.Server(uvicorn.Config(_app(), host="127.0.0.1", port=_PORT, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1100, "height": 900})
            errs = []
            page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
            page.goto("http://127.0.0.1:%d/" % _PORT, wait_until="networkidle")
            page.evaluate("async()=>{const{store}=await import('/static/core/store.js');"
                          "store._handle({type:'hello',config:{autonomy_level:'orchestrator'},sessions:[],local_llm:{},instance:{}});}")
            page.wait_for_timeout(200)

            # Streaming worker, overflowing the card.
            _push(page, _worker_view(20))
            page.wait_for_timeout(300)
            m = page.evaluate(_ACT)
            _check("worker activity overflows (scrollable)", m and m["scrollHeight"] > m["clientHeight"] + 20, str(m))
            _check("auto-pinned to bottom on first render", m and m["dist"] < 40, "dist=%s" % (m and m["dist"]))

            # Stream more -> must STAY pinned to the bottom.
            for n in (24, 28, 32):
                _push(page, _worker_view(n))
                page.wait_for_timeout(150)
            m = page.evaluate(_ACT)
            _check("stays pinned while streaming", m and m["dist"] < 40, "dist=%s" % (m and m["dist"]))

            # REAL wheel scroll UP over the card -> breaks the latch.
            page.mouse.move(m["x"] + m["width"] / 2, m["y"] + m["height"] / 2)
            page.mouse.wheel(0, -600)
            page.wait_for_timeout(200)
            m_up = page.evaluate(_ACT)
            _check("wheel up scrolls the card away from the bottom", m_up and m_up["dist"] > 60, "dist=%s" % (m_up and m_up["dist"]))

            # Stream more -> must NOT snap back to the bottom (latch torn).
            for n in (36, 40, 44):
                _push(page, _worker_view(n))
                page.wait_for_timeout(150)
            m_held = page.evaluate(_ACT)
            _check("tear-off HOLDS across streaming (no snap-back)", m_held and m_held["dist"] > 60,
                   "dist=%s scrollTop=%s" % (m_held and m_held["dist"], m_held and m_held["scrollTop"]))

            # Wheel back DOWN to the bottom -> re-latches.
            page.mouse.move(m_held["x"] + m_held["width"] / 2, m_held["y"] + m_held["height"] / 2)
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(200)
            for n in (48, 52):
                _push(page, _worker_view(n))
                page.wait_for_timeout(150)
            m_re = page.evaluate(_ACT)
            _check("wheel back to bottom RE-LATCHES (sticks again)", m_re and m_re["dist"] < 40,
                   "dist=%s" % (m_re and m_re["dist"]))

            _check("no fatal console errors",
                   not [e for e in errs if "websocket" not in e.lower() and "favicon" not in e.lower()],
                   "; ".join(errs[:3]))
            browser.close()
    finally:
        server.should_exit = True

    n_fail = sum(1 for _, ok, _ in _results if not ok)
    print("\n=== %d checks, %d failed ===" % (len(_results), n_fail))
    raise SystemExit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
