# SPDX-License-Identifier: GPL-3.0-or-later
"""
FULL-STACK integration test driven THROUGH THE UI with a faked-out LLM.

The whole real stack runs — agent server (runtime → engine → orchestrator →
ChildSessionRunner workers → blmcp tools → real headless Blender) → WebSocket →
the actual browser UI — but the LLM is the deterministic scripted endpoint in
tests/fake_llm_server.py. So the orchestration pipeline is exercised end to end,
fast and reproducibly, with NO real model. This is the integration test the
orchestration design originally lacked.

Needs Playwright + Chromium + a Blender at $BLENDER_PATH. Run directly:
    BLENDER_PATH=/path/to/blender python tests/e2e_integration_orchestration.py
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
_LLM_PORT = 8901
_AGENT_PORT = 10288
_DATA = "/tmp/agentint"
_results = []


def check(name, ok, detail=""):
    _results.append((name, bool(ok), detail))
    print(("PASS" if ok else "FAIL"), "-", name, (":: " + detail) if detail else "")


def _wait_http(url, code=200, timeout=120):
    import urllib.request
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == code:
                    return True
        except Exception:
            pass
        time.sleep(2)
    return False


def main():
    # 1) fake LLM (thread)
    llm = uvicorn.Server(uvicorn.Config(make_app(), host="127.0.0.1", port=_LLM_PORT, log_level="warning"))
    threading.Thread(target=llm.run, daemon=True).start()
    while not llm.started:
        time.sleep(0.05)

    # 2) test data dir + config pointing at the fake LLM, orchestrator mode,
    #    minimal rounds for a quick deterministic run.
    os.makedirs(_DATA, exist_ok=True)
    with open(os.path.join(_DATA, "config.yaml"), "w", encoding="utf-8") as fh:
        json.dump({  # JSON is valid YAML
            "endpoint": "http://127.0.0.1:{}/v1".format(_LLM_PORT),
            "model": "fake/test-model", "use_local_llm": False,
            "autonomy": "auto", "autonomy_level": "orchestrator",
            "autonomy_workers": "in_process", "autonomy_policy": "auto_until_done",
            "autonomy_qa": True,  # dedicated per-worker QA reviewer
            "max_rounds": 3, "max_autonomy_rounds": 1, "budget_review": False,
            "context_tokens": 16384,
        }, fh)

    # 3) boot the real agent server (real Blender, fake LLM) as a subprocess.
    env = dict(os.environ, PYTHONPATH="mcp:agent", BLENDER_AGENT_DATA_DIR=_DATA,
               BLENDER_PATH=os.environ.get("BLENDER_PATH", "blender"))
    proc = subprocess.Popen(
        [sys.executable, "-c", "import blagent; blagent.main()",
         "--port", str(_AGENT_PORT), "--data-dir", _DATA, "--spawn-blender"],
        cwd=_REPO, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        preexec_fn=os.setsid)
    try:
        if not _wait_http("http://127.0.0.1:{}/healthz".format(_AGENT_PORT)):
            check("agent server boots", False, "healthz never came up")
            return
        check("agent server boots (real Blender + fake LLM)", True)
        time.sleep(3)  # let the Blender bridge attach

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page()
            errs = []
            page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: errs.append("pageerror: " + str(e)))
            page.goto("http://127.0.0.1:{}/".format(_AGENT_PORT), wait_until="networkidle")
            page.wait_for_timeout(800)

            # orchestrator mode + a goal -> draft (real draft_objectives via fake LLM)
            page.evaluate("async()=>{const{store}=await import('/static/core/store.js');store.setAutonomyLevel('orchestrator');}")
            page.wait_for_timeout(400)
            page.locator("textarea").first.fill("Clean up duplicates and assemble the robot arm.")
            page.locator("button.circle.act.draft").first.click()

            # a planning card appears DURING the draft (feedback before objectives)
            planning = False
            for _ in range(40):
                page.wait_for_timeout(200)
                if _drive(page, "return store.state.autonomy.planner != null;"):
                    planning = True
                    break
            check("draft shows a planning card before objectives arrive", planning)

            # objectives decomposed by the (real) draft path
            drafted = False
            for _ in range(40):
                page.wait_for_timeout(500)
                if page.locator(".ol-items li").count() > 0:
                    drafted = True
                    break
            check("draft path decomposes goal into objectives (read-only)",
                  drafted, "%d items" % page.locator(".ol-items li").count())
            if not drafted:
                return

            # Begin run -> real orchestrator: plan -> worker -> tool -> proof -> evaluate -> done
            page.get_by_text("Begin run", exact=False).first.click()
            worker = False
            for _ in range(60):
                page.wait_for_timeout(500)
                if page.locator(".agent").count() > 0:
                    worker = True
                    break
            check("orchestrator spawns a worker", worker)

            # worker really dispatched a tool through the stack
            tool_seen = False
            for _ in range(60):
                page.wait_for_timeout(500)
                if 'scene("objects")' in page.evaluate("() => document.body && (function dt(r){let s=r.textContent||'';r.querySelectorAll('*').forEach(e=>{if(e.shadowRoot)s+=dt(e.shadowRoot)});return s})(document)"):
                    tool_seen = True
                    break
            check("worker dispatches a real tool call through the stack", tool_seen)

            # run reaches completion (autonomy_done) -> busy clears. The run's
            # `done` lives in its durable per-run view (autonomyRuns), not scratch.
            done = False
            for _ in range(80):
                page.wait_for_timeout(500)
                if _drive(page, "const r=store.state.autonomyRuns; const v=r[r.length-1] && r[r.length-1].view; "
                                "return store.state.busy === false && !!(v && v.done);"):
                    done = True
                    break
            check("orchestrator run completes (done, busy cleared)", done)

            txt = page.evaluate("() => (function dt(r){let s=r.textContent||'';r.querySelectorAll('*').forEach(e=>{if(e.shadowRoot)s+=dt(e.shadowRoot)});return s})(document)")
            check("worker proof rendered (no raw <think>)",
                  ("PROOF OF WORK" in txt) and ("<think>" not in txt))

            # dedicated QA reviewer ran per worker and annotated the work (agents
            # live in the run's durable view now).
            qa_seen = _drive(page, "const r=store.state.autonomyRuns; const v=(r[r.length-1]||{}).view||{}; "
                                   "const ags=Object.values(v.agents||{}); "
                                   "return ags.some(a => a.role === 'qa') && ags.some(a => a.review);")
            check("bounded QA inspector spawned + worker reviewed", qa_seen)
            check("QA inspector rendered in the UI", "QA inspect" in txt)

            # persistence: reload the session, history survives
            sid = _drive(page, "return store.state.sessionId;")
            page.reload(wait_until="networkidle")
            page.wait_for_timeout(1500)
            recs = _drive(page, "return (store.state.records||[]).length;")
            check("orchestrator history persists across reload", recs and recs > 0, "records=%s" % recs)

            check("no console errors", not [e for e in errs if "websocket" not in e.lower()],
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


def _drive(page, js):
    return page.evaluate("async () => { const { store } = await import('/static/core/store.js'); " + js + " }")


if __name__ == "__main__":
    main()
