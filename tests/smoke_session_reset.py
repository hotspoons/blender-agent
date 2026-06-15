# SPDX-License-Identifier: GPL-3.0-or-later
"""
Headless store-logic test for two regressions:
  1. autonomy_accepted must adopt the run's session_id (so abort/stop targets
     the right session — otherwise stop does nothing and Blender must be killed).
  2. Switching sessions (session_loaded) must clear the live autonomy view, so a
     prior orchestrator run's objectives + worker cards don't bleed in ("jumble").

Run directly (needs Playwright + Chromium):
    python tests/smoke_session_reset.py
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
_PORT = 8734


def _app() -> Starlette:
    async def index(_req):
        return FileResponse(os.path.join(_WEB, "index.html"))
    return Starlette(routes=[
        Route("/", index),
        Mount("/static", app=StaticFiles(directory=_WEB), name="static"),
    ])


_SCRIPT = """async () => {
  const { store } = await import('/static/core/store.js');
  const out = {};

  // (1) a fresh orchestrator run announces its session id.
  store._handle({ type: 'autonomy_accepted', session_id: 'orch-sess-123' });
  out.sessionIdAdopted = store.state.sessionId === 'orch-sess-123';
  out.busyAfterAccept = store.state.busy === true;

  // populate a worker card under that run
  store._handle({ type: 'agent_spawned', session_id: 'orch-sess-123', agent_id: 'orch-sess-123:w:t1', role: 'worker', task: 'x' });
  out.hadWorker = store.state.autonomy.agentOrder.length === 1;

  // (2) switching to another session clears the autonomy view.
  store._handle({ type: 'session_loaded', session_id: 'other-sess', records: [], media: [] });
  out.sessionSwitched = store.state.sessionId === 'other-sess';
  out.autonomyCleared = store.state.autonomy.agentOrder.length === 0
      && Object.keys(store.state.autonomy.agents).length === 0
      && store.state.autonomy.objectives.length === 0;
  out.notBusyAfterSwitch = store.state.busy === false;
  return out;
}"""


def main() -> None:
    server = uvicorn.Server(uvicorn.Config(_app(), host="127.0.0.1", port=_PORT, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        pass
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto("http://127.0.0.1:{}/".format(_PORT), wait_until="networkidle")
            page.wait_for_timeout(400)
            res = page.evaluate(_SCRIPT)
            browser.close()

            checks = {
                "autonomy_accepted adopts session_id": res.get("sessionIdAdopted"),
                "busy set on accept": res.get("busyAfterAccept"),
                "worker card populated": res.get("hadWorker"),
                "session switch updates id": res.get("sessionSwitched"),
                "autonomy view cleared on switch": res.get("autonomyCleared"),
                "busy cleared on switch": res.get("notBusyAfterSwitch"),
                "no page errors": not errors,
            }
            for name, ok in checks.items():
                print(("PASS" if ok else "FAIL"), "-", name)
            if errors:
                print("page errors:", errors)
            ok = all(checks.values())
            print("\nRESULT:", "PASS" if ok else "FAIL")
            raise SystemExit(0 if ok else 1)
    finally:
        server.should_exit = True


if __name__ == "__main__":
    main()
