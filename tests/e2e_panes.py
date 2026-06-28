# SPDX-License-Identifier: GPL-3.0-or-later
"""Real-browser checks for the resizable side panes + scrollable sessions /
artifacts (app.js). Boots the actual frontend (no Blender/LLM), drags each
divider with the real mouse, and asserts widths change + persist and the
panes scroll when content overflows."""
import os
import sys
import threading

import uvicorn
from playwright.sync_api import sync_playwright
from starlette.applications import Starlette
from starlette.responses import FileResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

_WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent", "agentcore", "web")
_PORT = 8821
_results = []


def _check(name, ok, detail=""):
    _results.append((name, bool(ok), detail))
    print(("PASS" if ok else "FAIL"), "-", name, (":: " + detail) if detail else "", flush=True)


def _app():
    async def index(_req):
        return FileResponse(os.path.join(_WEB, "index.html"))
    return Starlette(routes=[
        Route("/", index),
        Mount("/static", app=StaticFiles(directory=_WEB, check_dir=False)),
    ])


_APP = "document.querySelector('ba-app').shadowRoot"


def main():
    server = uvicorn.Server(uvicorn.Config(_app(), host="127.0.0.1", port=_PORT, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        import time
        time.sleep(0.05)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            errs = []
            page.on("pageerror", lambda e: errs.append(str(e)))
            page.goto("http://127.0.0.1:{}/".format(_PORT), wait_until="networkidle")
            page.wait_for_timeout(500)
            # Orchestrator config + open the right (artifacts) pane.
            page.evaluate("async () => { const { store } = await import('/static/core/store.js'); "
                          "store._handle({type:'hello', config:{autonomy_level:'orchestrator', endpoint:'x', "
                          "model:'m', use_local_llm:false}, sessions:[], local_llm:{}, instance:{}}); }")
            page.wait_for_timeout(200)

            def rect(sel):
                return page.evaluate("(s)=>{const e=%s.querySelector(s); if(!e) return null; "
                                     "const r=e.getBoundingClientRect(); return {x:r.x,y:r.y,w:r.width,h:r.height};}" % _APP, sel)

            def drag(sel, dx):
                r = rect(sel)
                page.mouse.move(r["x"] + r["w"] / 2, r["y"] + r["h"] / 2)
                page.mouse.down()
                page.mouse.move(r["x"] + r["w"] / 2 + dx, r["y"] + r["h"] / 2 + 0, steps=8)
                page.mouse.up()
                page.wait_for_timeout(150)

            # --- LEFT pane resize ---
            lw0 = rect("aside.left")["w"]
            _check("left resizer present", rect("aside.left .resizer") is not None)
            drag("aside.left .resizer", 120)
            lw1 = rect("aside.left")["w"]
            _check("left pane widened by drag", lw1 > lw0 + 60, "%.0f -> %.0f" % (lw0, lw1))
            persisted_l = page.evaluate("() => localStorage.getItem('blender-agent.left-w')")
            _check("left width persisted", persisted_l and abs(int(persisted_l) - lw1) <= 2, "stored=%s" % persisted_l)
            drag("aside.left .resizer", -200)
            lw2 = rect("aside.left")["w"]
            _check("left pane narrowed by drag (and clamps)", lw2 < lw1 - 60 and lw2 >= 180, "-> %.0f" % lw2)

            # --- RIGHT pane resize (right divider grows pane as you drag LEFT) ---
            rw0 = rect("aside.right")["w"]
            _check("right resizer present", rect("aside.right .resizer") is not None)
            drag("aside.right .resizer", -120)
            rw1 = rect("aside.right")["w"]
            _check("right pane widened by drag-left", rw1 > rw0 + 60, "%.0f -> %.0f" % (rw0, rw1))
            persisted_r = page.evaluate("() => localStorage.getItem('blender-agent.right-w')")
            _check("right width persisted", persisted_r and abs(int(persisted_r) - rw1) <= 2, "stored=%s" % persisted_r)

            # --- width persists across reload ---
            page.reload(wait_until="networkidle")
            page.wait_for_timeout(400)
            lw_reload = rect("aside.left")["w"]
            _check("left width survives reload", abs(lw_reload - lw2) <= 3, "%.0f" % lw_reload)

            # --- SCROLL: sessions rail + artifacts inner are overflow:auto and actually scroll ---
            def overflow(sel):
                return page.evaluate("(s)=>{const e=%s.querySelector(s); return e?getComputedStyle(e).overflowY:null;}" % _APP, sel)
            _check("sessions rail is overflow auto", overflow(".rail-scroll") == "auto", str(overflow(".rail-scroll")))
            _check("artifacts inner is overflow auto", overflow(".right-inner") == "auto", str(overflow(".right-inner")))

            def scrolls(sel):
                # Inject a very tall probe child and confirm the container scrolls.
                # min-height (not height) so a flex child can't be shrunk to fit —
                # mirrors real content (artifact cards / session rows have an
                # intrinsic min height).
                return page.evaluate("(s)=>{const e=%s.querySelector(s); if(!e) return false; "
                                     "const d=document.createElement('div'); d.style.minHeight='4000px'; "
                                     "e.appendChild(d); const ok=e.scrollHeight > e.clientHeight + 100; "
                                     "e.removeChild(d); return ok;}" % _APP, sel)
            _check("sessions rail scrolls when content overflows", scrolls(".rail-scroll"))
            _check("artifacts inner scrolls when content overflows", scrolls(".right-inner"))

            _check("no fatal console errors", not errs, "; ".join(errs[:3]))
            browser.close()
    finally:
        server.should_exit = True

    n_fail = sum(1 for _, ok, _ in _results if not ok)
    print("\n=== %d checks, %d failed ===" % (len(_results), n_fail))
    raise SystemExit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
