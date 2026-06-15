"""Comprehensive UI-driven test of the orchestration stack (live browser)."""
import sys, time
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:10277/"
results = []
def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("PASS" if ok else "FAIL"), "-", name, (":: " + detail) if detail else "")

def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        console_errs = []
        page.on("console", lambda m: console_errs.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: console_errs.append("pageerror: " + str(e)))
        page.goto(BASE, wait_until="networkidle")
        page.wait_for_timeout(800)

        # ---- Phase A: plain chat (yolo) ----
        print("\n== Phase A: plain chat ==")
        page.evaluate("async () => { const {store}=await import('/static/core/store.js'); store.setAutonomyLevel('yolo'); }")
        page.wait_for_timeout(500)
        ta = page.locator("textarea").first
        ta.fill("Say the single word PONG and nothing else.")
        # send button (non-autonomy): the plain circle act (not draft/abort)
        page.locator("button.circle.act:not(.draft):not(.abort)").first.click()
        got = False
        for _ in range(40):
            page.wait_for_timeout(1000)
            body = page.evaluate("() => { const o=[]; const w=(r)=>{r.querySelectorAll('*').forEach(e=>{if(e.shadowRoot)w(e.shadowRoot)});o.push(r.textContent||'')}; w(document); return o.join('\\n'); }")
            if "PONG" in body:
                got = True
                break
        check("plain chat streams a response", got)
        body = page.evaluate("() => { const o=[]; const w=(r)=>{r.querySelectorAll('*').forEach(e=>{if(e.shadowRoot)w(e.shadowRoot)});o.push(r.textContent||'')}; w(document); return o.join('\\n'); }")
        check("plain chat: no raw <think> tag", "<think>" not in body)

        # ---- Phase B: orchestrator ----
        print("\n== Phase B: orchestrator ==")
        page.evaluate("async () => { const {store}=await import('/static/core/store.js'); store.newSession(); }")
        page.wait_for_timeout(1500)
        page.evaluate("async () => { const {store}=await import('/static/core/store.js'); store.setAutonomyLevel('orchestrator'); }")
        page.wait_for_timeout(800)
        ta = page.locator("textarea").first
        goal = ("Clean up duplicate objects in the scene, and assemble the robot arm with a "
                "square peg joining the upper and lower arm.")
        ta.fill(goal)
        # draft button (orchestrator, no objectives yet)
        draft = page.locator("button.circle.act.draft").first
        check("orchestrator: draft button present (clipboard, not sparkle)", draft.count() > 0)
        draft.click()
        # wait for objectives to be drafted (decomposition via Kimi)
        objs = False
        for _ in range(80):
            page.wait_for_timeout(1500)
            if page.locator(".oe-row").count() > 0:
                objs = True
                break
        n_obj = page.locator(".oe-row").count()
        check("orchestrator: goal decomposed into objectives", objs, "%d rows" % n_obj)

        if objs:
            # Begin run
            page.get_by_text("Begin run", exact=False).first.click()
            # wait for a worker card to appear + show activity
            worker = False
            for _ in range(120):
                page.wait_for_timeout(1500)
                if page.locator(".agent").count() > 0:
                    worker = True
                    break
            check("orchestrator: worker card spawned", worker)
            page.wait_for_timeout(8000)  # let it stream some
            body = page.evaluate("() => { const o=[]; const w=(r)=>{r.querySelectorAll('*').forEach(e=>{if(e.shadowRoot)w(e.shadowRoot)});o.push(r.textContent||'')}; w(document); return o.join('\\n'); }")
            check("orchestrator: worker card has no raw <think>", "<think>" not in body)
            check("orchestrator: worker shows a Thinking/Thought disclosure",
                  ("Thought for a moment" in body) or ("Thinking" in body))
            # STOP
            stop = page.locator("button.circle.act.abort").first
            check("orchestrator: Stop button present while running", stop.count() > 0)
            if stop.count() > 0:
                n_before = page.locator(".agent").count()
                stop.click()
                page.wait_for_timeout(12000)  # allow current tool to finish + cancel to propagate
                busy = page.evaluate("async () => { const {store}=await import('/static/core/store.js'); return store.state.busy; }")
                n_after = page.locator(".agent").count()
                check("orchestrator: Stop halts the run (busy cleared)", busy is False, "busy=%s" % busy)
                check("orchestrator: Stop prevents new workers spawning",
                      n_after <= n_before + 1, "before=%d after=%d" % (n_before, n_after))

        # ---- Phase C: session switch (no jumble) ----
        print("\n== Phase C: session switch ==")
        page.evaluate("async () => { const {store}=await import('/static/core/store.js'); store.newSession(); }")
        page.wait_for_timeout(2000)
        agents_after_switch = page.evaluate("async () => { const {store}=await import('/static/core/store.js'); return store.state.autonomy.agentOrder.length; }")
        check("session switch clears worker cards (no jumble)", agents_after_switch == 0, "agents=%s" % agents_after_switch)

        # ---- Phase D: swarm preflight ----
        print("\n== Phase D: swarm preflight ==")
        page.evaluate("async () => { const {store}=await import('/static/core/store.js'); store.setAutonomyLevel('swarm'); }")
        page.wait_for_timeout(2500)
        pf = page.evaluate("async () => { const {store}=await import('/static/core/store.js'); return store.state.swarmPreflight || null; }")
        check("swarm: preflight reported", pf is not None, str(pf)[:160] if pf else "none")

        check("no console errors during UI run", not console_errs,
              "; ".join(console_errs[:3]) if console_errs else "")
        browser.close()

    print("\n=== RESULTS ===")
    n_fail = sum(1 for _, ok, _ in results if not ok)
    for name, ok, detail in results:
        print(("PASS" if ok else "FAIL"), "-", name, (":: " + detail) if detail else "")
    print("\n%d checks, %d failed" % (len(results), n_fail))
    sys.exit(1 if n_fail else 0)

main()
