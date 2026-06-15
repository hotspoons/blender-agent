# SPDX-License-Identifier: GPL-3.0-or-later
"""
Headless DOM test: a worker card whose assistant text contains <think> tags
must COLLAPSE them (a "Thought for a moment" disclosure), not render the raw
tags as literal text. This is the regression the unit/smoke tests missed.

Run directly (needs Playwright + Chromium):
    python tests/smoke_worker_think.py
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
_PORT = 8733


def _app() -> Starlette:
    async def index(_req):
        return FileResponse(os.path.join(_WEB, "index.html"))
    return Starlette(routes=[
        Route("/", index),
        Mount("/static", app=StaticFiles(directory=_WEB), name="static"),
    ])


# Drive the real store message path: spawn a worker, then deliver an
# assistant_done whose content mixes reasoning (<think>) with a visible answer.
_DRIVE = """async () => {
  const { store } = await import('/static/core/store.js');
  store._handle({ type: 'agent_spawned', session_id: 's', agent_id: 's:w:t1',
                  role: 'worker', task: 'do the thing', objective_id: 'o1' });
  store._handle({ type: 'assistant_done', session_id: 's:w:t1', parent_session_id: 's',
                  role: 'worker', tool_calls: [],
                  content: '<think>SECRET_REASONING_XYZ</think>VISIBLE_ANSWER_ABC' });
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
            page.wait_for_timeout(500)
            page.evaluate(_DRIVE)
            page.wait_for_timeout(600)

            # Collect all rendered text across open shadow roots.
            text = page.evaluate("""() => {
                const out = [];
                const walk = (root) => {
                    root.querySelectorAll('*').forEach((el) => {
                        if (el.shadowRoot) walk(el.shadowRoot);
                    });
                    out.push(root.textContent || '');
                };
                walk(document);
                return out.join('\\n');
            }""")
            browser.close()

            checks = {
                "visible answer shown": "VISIBLE_ANSWER_ABC" in text,
                "no literal <think> tag": "<think>" not in text,
                "reasoning collapsed (hidden)": "SECRET_REASONING_XYZ" not in text,
                "think disclosure present": "Thought for a moment" in text,
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
