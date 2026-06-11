# Rigging Skills Library — Progress

## Done
- **Phase 0** — headless smoke test green; `blender --background` exits cleanly,
  exit codes propagate (`--python-exit-code 1` verified with a negative test).
  Concurrent headless instances confirmed working (3 simultaneous on 10 cores).
  Repo layout stood up under `rigging/`; `make test` runs all tiers headless.

## Next
- Phase 1: perception layer (`blrig/perception`) + exhaustive unit tests against
  primitive fixtures.

## Blockers
- None.

## Open questions
- Golden-render baselines: store under `rigging/tests/golden/` as small PNGs
  (workbench engine, fixed resolution) — revisit size policy when we get there.

## Coordination
- A second agent ("bug-fixer") works in this repo concurrently. Notes are
  exchanged via /tmp/coordination (moved to read/ after reading). Commits here
  use explicit paths only — never `git add -A` — because the tree carries the
  other agent's uncommitted work.
