# SPDX-License-Identifier: GPL-3.0-or-later
"""Real-browser checks for the interactive DAG pipeline viewer (dag-viewer.js
+ dag-layout.js, mounted in chat-stage). Boots the actual frontend (no
Blender/LLM), injects a recorded orchestrator `autonomy_view` snapshot with
dependency edges + mixed live states, and asserts the graph renders (nodes +
edges + live status), and that clicking a node isolates that agent's card
(focus/dim) while a background click restores the full view."""
import os
import sys
import threading
import time

import uvicorn
from playwright.sync_api import sync_playwright
from starlette.applications import Starlette
from starlette.responses import FileResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

_WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent", "agentcore", "web")
_PORT = 8823
_results = []

# A village-shaped run: two parts (one done, one running) -> assemble -> gather.
_VIEW = {
    "prompts": ["Build a tiny village"],
    "objectives": [{"id": "obj-0", "text": "Make the parts", "status": "met"}],
    "agentOrder": ["s:w:a", "s:w:b", "s:w:assemble", "s:w:gather"],
    "agents": {
        "s:w:a": {"id": "s:w:a", "role": "worker", "state": "done", "ok": True,
                  "task": "build House", "dependsOn": [], "round": 0, "timeline": [], "calls": {}},
        "s:w:b": {"id": "s:w:b", "role": "worker", "state": "running", "ok": None,
                  "task": "build Tower", "dependsOn": [], "round": 0, "timeline": [], "calls": {}},
        "s:w:assemble": {"id": "s:w:assemble", "role": "worker", "state": "idle", "ok": None,
                         "task": "assemble village", "dependsOn": ["s:w:a", "s:w:b"], "round": 0,
                         "timeline": [], "calls": {}},
        "s:w:gather": {"id": "s:w:gather", "role": "gather", "state": "idle", "ok": None,
                       "task": "merge components", "dependsOn": [], "round": None,
                       "timeline": [], "calls": {}},
    },
}


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


# Pierce: ba-app -> chat-stage -> dag-viewer shadow roots.
_STAGE = "document.querySelector('ba-app').shadowRoot.querySelector('ba-chat-stage').shadowRoot"
_DAG = _STAGE + ".querySelector('ba-dag-viewer').shadowRoot"


def main():
    server = uvicorn.Server(uvicorn.Config(_app(), host="127.0.0.1", port=_PORT, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            errs = []
            page.on("pageerror", lambda e: errs.append(str(e)))
            page.goto("http://127.0.0.1:{}/".format(_PORT), wait_until="networkidle")
            page.wait_for_timeout(400)
            # Orchestrator config, then inject the recorded view as the live scratch run.
            page.evaluate("async () => { const { store } = await import('/static/core/store.js'); "
                          "store._handle({type:'hello', config:{autonomy_level:'orchestrator', endpoint:'x', "
                          "model:'m', use_local_llm:false}, sessions:[], local_llm:{}, instance:{}}); }")
            page.evaluate("(v) => import('/static/core/store.js').then(({store}) => "
                          "store._handle({type:'autonomy_view', view:v}))", _VIEW)
            page.wait_for_timeout(400)

            def q(root, sel, prop="length"):
                return page.evaluate("([r,s])=>{const x=eval(r).querySelectorAll(s); return x.%s;}" % prop, [root, sel])

            # --- the viewer mounts and renders the graph ---
            _check("dag-viewer present", page.evaluate("() => !!%s" % _DAG))
            nodes = q(_DAG, ".node")
            _check("renders all 4 nodes", nodes == 4, "got %s" % nodes)
            edges = q(_DAG, "path.edge")
            # a->assemble, b->assemble, assemble->gather (gather hangs off the sink)
            _check("renders 3 dependency edges", edges == 3, "got %s" % edges)
            _check("running node is lit (pulse)", q(_DAG, ".node.running .pulse") >= 1)
            _check("done node marked ok", q(_DAG, ".node.done") >= 1)
            _check("gather node styled", q(_DAG, ".node.gather") == 1)

            # --- click a node -> isolate that agent card in the transcript ---
            page.evaluate("() => { const g=[...%s.querySelectorAll('.node')]"
                          ".find(n => n.textContent.includes('a')); "
                          "g.dispatchEvent(new MouseEvent('click', {bubbles:true})); }" % _DAG)
            page.wait_for_timeout(300)
            focused = q(_STAGE, ".agent.focused")
            dimmed = q(_STAGE, ".agent.dimmed")
            _check("clicked node focuses its agent card", focused == 1, "focused=%s" % focused)
            _check("other agent cards are dimmed", dimmed >= 1, "dimmed=%s" % dimmed)

            # --- background click clears focus ---
            page.evaluate("() => { const c=%s.querySelector('.canvas'); "
                          "c.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true})); "
                          "c.dispatchEvent(new PointerEvent('pointerup',{bubbles:true})); }" % _DAG)
            page.wait_for_timeout(250)
            _check("background click clears focus", q(_STAGE, ".agent.dimmed") == 0)

            # --- collapse toggle hides the canvas ---
            page.evaluate("() => %s.querySelector('.hdr .toggle').click()" % _DAG)
            page.wait_for_timeout(200)
            _check("collapse hides the canvas", q(_DAG, ".canvas") == 0)
            page.evaluate("() => %s.querySelector('.hdr .toggle').click()" % _DAG)  # reopen
            page.wait_for_timeout(150)

            # --- theme: the viewer follows light/dark via inherited tokens ---
            def host_bg():
                return page.evaluate("() => getComputedStyle(%s.host).backgroundColor" % _DAG)
            page.evaluate("() => document.documentElement.setAttribute('data-theme','dark')")
            page.wait_for_timeout(120); dark_bg = host_bg()
            page.evaluate("() => document.documentElement.setAttribute('data-theme','light')")
            page.wait_for_timeout(120); light_bg = host_bg()
            _check("viewer recolors for light theme", dark_bg != light_bg,
                   "dark=%s light=%s" % (dark_bg, light_bg))
            # light surface-elevated (#f8fafc) is near-white -> high RGB sum
            import re as _re
            nums = [int(x) for x in _re.findall(r"\d+", light_bg)[:3]]
            _check("light theme uses a light surface", sum(nums) > 600, "rgb sum=%s" % sum(nums))
            page.evaluate("() => document.documentElement.setAttribute('data-theme','dark')")

            _check("no fatal console errors", not errs, "; ".join(errs[:3]))
            browser.close()
    finally:
        server.should_exit = True

    n_fail = sum(1 for _, ok, _ in _results if not ok)
    print("\n=== %d checks, %d failed ===" % (len(_results), n_fail))
    raise SystemExit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
