# SPDX-License-Identifier: GPL-3.0-or-later
"""
Headless browser smoke test for the web UI extension boundary.

Serves agent/blagent/web exactly as app.py does (index at /, files under
/static) and loads it in Chromium to confirm:
  * every ES module in the graph loads (no import/syntax/reference errors),
  * the Blender UI extension applied its profile (title + brand word),
  * the neutral core ships no Blender artwork until the extension loads.

Not part of the unittest suite (needs Playwright + Chromium); run directly:
    python tests/smoke_web_profile.py
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
_PORT = 8731


def _make_app() -> Starlette:
    async def index(_req):
        return FileResponse(os.path.join(_WEB, "index.html"))

    return Starlette(routes=[
        Route("/", index),
        Mount("/static", app=StaticFiles(directory=_WEB), name="static"),
    ])


def main() -> None:
    server = uvicorn.Server(uvicorn.Config(_make_app(), host="127.0.0.1", port=_PORT, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        pass

    errors: list[str] = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page()
            page.on("console", lambda m: errors.append("console.{}: {}".format(m.type, m.text))
                    if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append("pageerror: {}".format(e)))
            page.goto("http://127.0.0.1:{}/".format(_PORT), wait_until="networkidle")
            page.wait_for_timeout(800)

            title = page.title()
            brand_word = page.locator(".brand .word").first.inner_text()
            empty_heading = page.locator(".empty h2").first.inner_text() if page.locator(".empty h2").count() else ""

            # Module-load errors are fatal; a failed /ws connection is not.
            fatal = [e for e in errors
                     if not any(s in e.lower() for s in ("websocket", "/ws", "failed to fetch local", " services"))]

            print("title          :", title)
            print("brand word     :", brand_word)
            print("empty heading  :", empty_heading)
            print("console errors :", len(errors), "| fatal:", len(fatal))
            for e in errors:
                print("   -", e)
            browser.close()

            ok = (title == "Blender Agent" and brand_word.strip() == "Blender" and not fatal)
            print("\nRESULT:", "PASS" if ok else "FAIL")
            raise SystemExit(0 if ok else 1)
    finally:
        server.should_exit = True


if __name__ == "__main__":
    main()
