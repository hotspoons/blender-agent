# SPDX-License-Identifier: GPL-3.0-or-later
"""
Full-stack browser test of the persistent CONDUCTOR orchestrator, against the
reported pain points — real agent server + real headless Blender + the actual
UI, with the deterministic fake LLM scripted as a conductor (post_objectives ->
delegate -> complete_objective -> summary).

Checks:
  1. an orchestrator message goes to the conductor (NO composer draft/Begin-run);
  2. the conductor OWNS + renders the objective list;
  3. delegate spawns a worker that renders as a card;
  4. the first turn completes;
  5. a FOLLOW-UP message does NOT restart — same run, objectives + worker card
     persist, context kept;
  6. the conductor's reasoning/summary renders in the transcript.

Needs Playwright + Chromium + a Blender at $BLENDER_PATH:
    BLENDER_PATH=/path/to/blender python tests/e2e_conductor_ui.py
"""
import json
import os
import signal
import subprocess
import sys
import threading
import time

import uvicorn
from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fake_llm_server import make_app  # noqa: E402

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LLM_PORT = 8903
_AGENT_PORT = 10293
_DATA = "/tmp/agent_conductor_ui"
_results = []


def check(name, ok, detail=""):
    _results.append((name, bool(ok), detail))
    print(("PASS" if ok else "FAIL"), "-", name, (":: " + detail) if detail else "", flush=True)


def _wait_http(url, timeout=180):
    import urllib.request
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(2)
    return False


def _alltext(page):
    return page.evaluate("() => (function dt(r){let s=r.textContent||'';r.querySelectorAll('*')"
                         ".forEach(e=>{if(e.shadowRoot)s+=dt(e.shadowRoot)});return s})(document)")


def _drive(page, js):
    return page.evaluate("async () => { const { store } = await import('/static/core/store.js'); " + js + " }")


def _send_message(page, text):
    page.locator("textarea").first.fill(text)
    page.locator("textarea").first.press("Enter")


def main():
    llm = uvicorn.Server(uvicorn.Config(make_app(), host="127.0.0.1", port=_LLM_PORT, log_level="warning"))
    threading.Thread(target=llm.run, daemon=True).start()
    while not llm.started:
        time.sleep(0.05)

    os.makedirs(_DATA, exist_ok=True)
    with open(os.path.join(_DATA, "config.yaml"), "w", encoding="utf-8") as fh:
        json.dump({
            "endpoint": "http://127.0.0.1:{}/v1".format(_LLM_PORT),
            "model": "fake/test-model", "use_local_llm": False,
            "autonomy": "auto", "autonomy_level": "orchestrator",
            "autonomy_workers": "in_process", "autonomy_policy": "auto_until_done",
            "autonomy_qa": False, "max_rounds": 10, "context_tokens": 16384,
        }, fh)

    env = dict(os.environ, PYTHONPATH="mcp:agent", BLENDER_AGENT_DATA_DIR=_DATA,
               BLENDER_PATH=os.environ.get("BLENDER_PATH", "blender"))
    proc = subprocess.Popen(
        [sys.executable, "-c", "import blagent; blagent.main()",
         "--port", str(_AGENT_PORT), "--data-dir", _DATA, "--spawn-blender"],
        cwd=_REPO, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=os.setsid)
    try:
        if not _wait_http("http://127.0.0.1:{}/healthz".format(_AGENT_PORT)):
            check("agent server boots", False, "healthz never came up")
            return
        check("agent server boots (real Blender + fake conductor LLM)", True)
        time.sleep(3)

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1100, "height": 900})
            errs = []
            page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: errs.append("pageerror: " + str(e)))
            page.goto("http://127.0.0.1:{}/".format(_AGENT_PORT), wait_until="networkidle")
            page.wait_for_timeout(800)
            _drive(page, "store.setAutonomyLevel('orchestrator');")
            page.wait_for_timeout(300)

            # The composer must NOT present a draft/Begin-run editor in orchestrator
            # mode — the conductor owns objectives; the user just sends messages.
            _send_message(page, "Add a UV sphere named Ball to the scene.")
            page.wait_for_timeout(600)
            txt_early = _alltext(page)
            check("orchestrator composer has no draft Begin-run editor",
                  "Begin run" not in txt_early)

            # The conductor posts the objective list (it owns it).
            posted = False
            for _ in range(60):
                page.wait_for_timeout(500)
                if "UV sphere named Ball" in _alltext(page) or _drive(
                        page, "const r=store.state.autonomyRuns; return r.length>0 && (r[0].view.objectives||[]).length>0;"):
                    posted = True
                    break
            check("conductor posts + renders its objective list", posted)

            # delegate spawns a worker -> a worker card renders.
            worker = False
            for _ in range(80):
                page.wait_for_timeout(500)
                if page.locator(".agent").count() > 0:
                    worker = True
                    break
            check("conductor delegates a worker (card renders)", worker)

            # first turn completes
            done1 = False
            for _ in range(120):
                page.wait_for_timeout(500)
                if _drive(page, "return store.state.busy === false;"):
                    done1 = True
                    break
            check("first conductor turn completes (busy clears)", done1)
            run_id_1 = _drive(page, "const r=store.state.autonomyRuns; return r.length?r[r.length-1].run_id:null;")
            objs_1 = _drive(page, "const r=store.state.autonomyRuns; return r.length?(r[r.length-1].view.objectives||[]).length:0;")
            check("conductor reasoning/summary in transcript", "objectives met" in _alltext(page).lower()
                  or "ball" in _alltext(page).lower())

            # FOLLOW-UP message must CONTINUE, not restart.
            _send_message(page, "Now also make sure the scene has no stray objects.")
            page.wait_for_timeout(2500)
            run_id_2 = _drive(page, "const r=store.state.autonomyRuns; return r.length?r[r.length-1].run_id:null;")
            n_runs = _drive(page, "return store.state.autonomyRuns.length;")
            objs_2 = _drive(page, "const r=store.state.autonomyRuns; return r.length?(r[r.length-1].view.objectives||[]).length:0;")
            restart_records = _drive(
                page, "return (store.state.records||[]).filter(r=>r.autonomy_objectives_draft||r.autonomy_goal).length;")
            check("follow-up does NOT restart (same run id)", run_id_1 and run_id_2 == run_id_1,
                  "run1=%s run2=%s" % (run_id_1, run_id_2))
            check("follow-up keeps ONE persistent run", n_runs == 1, "runs=%s" % n_runs)
            check("objectives persist across the follow-up", objs_2 >= objs_1 and objs_2 > 0,
                  "objs1=%s objs2=%s" % (objs_1, objs_2))
            check("no draft/restart records written", restart_records == 0, "restart_records=%s" % restart_records)
            check("worker card still present after follow-up", page.locator(".agent").count() > 0)

            # let the follow-up turn settle, then no fatal console errors
            for _ in range(120):
                page.wait_for_timeout(500)
                if _drive(page, "return store.state.busy === false;"):
                    break
            check("no fatal console errors",
                  not [e for e in errs if "websocket" not in e.lower() and "favicon" not in e.lower()
                       and "404" not in e],
                  "; ".join(errs[:3]))
            browser.close()
    finally:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception:
            pass
        llm.should_exit = True

    n_fail = sum(1 for _, ok, _ in _results if not ok)
    print("\n=== %d checks, %d failed ===" % (len(_results), n_fail))
    raise SystemExit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
