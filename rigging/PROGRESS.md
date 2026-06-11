# Rigging Skills Library — Progress

## Done
- **Phase 0** — headless harness, exit-code propagation verified, concurrent
  `--background` instances confirmed safe. `make test` runs all tiers.
- **Phase 1** — perception layer (`blrig/perception`): loose_parts,
  contact_graph (tri-tri contact points + PCA contact axis), part_obb,
  symmetry_plane (BVH surface-distance), cross_sections (Green's theorem),
  point_inside, mesh_health. 36 property tests.
- **Phase 2** — RIG_STANDARD.md + validate_rig()/validate_weights()
  (Rigify-compatible: unprefixed controls, parentless MCH floaters allowed).
- **Phase 3** — skill contract: diagnose/run/verify, structured failure
  reports with `suggest`, tracked rollback + scene-snapshot fallback,
  append-only failures.jsonl.
- **Phase 4** — mechanical skills: rig_hinge, rig_piston, rig_wheel,
  rig_turret, rig_rigid_assembly. Corpus: door/frame (+garbage), piston,
  wheel (+scaled), turret, desk lamp (objects + single-mesh), crates.
- **Phase 5** — character skills: rig_biped_rigify, rig_quadruped_rigify
  (proportional metarig fit, rigify_generate, bone-heat + explicit weight
  normalization, E_UNWEIGHTED as bone-heat failure signal, FK pose-extreme
  verification with volume thresholds). Skin-modifier character corpus.
- **Phase 6** — deformation tier (corpus×skill matrix, ±80° on all controls,
  explosion/reset bounds), golden-render tier (workbench, perceptual diff,
  BLRIG_UPDATE_GOLDEN), evals/ (14 selection scenarios + scorer).
- **Architecture v2 (Richard's mandate)** — blrig moved into the new
  `mcp_ext/` tools-extension package (`blender-mcp-extensions`, entry-point
  discovered, self-registers `rigging_*` MCP tools + bundles `rigging-*`
  SKILL.md collection). Core blmcp gained: skills subsystem (Anthropic
  layout; drop folder + git repos + config + extension sources;
  skills_list/search/read tools), shared tool registry (server + in-process
  agent), `welcome` tool + run-welcome-first nudges, addon prefs box
  (skills folder + repo URLs → ~/.config/blender-mcp/skills.json).

## Test status
- rigging suite: 99 green (property + deform + render tiers), `make test`.
- repo tests: test_skills_index (14), test_registry_extensions (4),
  test_mcp_server (42), test_tool_listing (regenerated snapshot),
  test_agent (11) — all green.

## Next / open
- End-to-end `rigging_run` through a live addon bridge (integration-suite
  style) — pieces are individually tested (payloads compile, blrig green
  headless, send_code is the existing transport), but one full pass through
  a real bridge would close the loop.
- Joint refinement for character metarig fit (perception-driven knee/elbow
  snapping from cross-section minima) — proportional fit is deliberate v1.
- Run the agent evals against the live agent and tune SKILL.md descriptions
  (selection failures fix descriptions, not code).
- Corpus growth toward 30–50 assets (crab/tentacle/backhoe + scanned junk).
- Addon prefs repo field is comma-separated; a UIList would be nicer UX.

## Coordination
- Second agent ("bug-fixer") works concurrently; notes via /tmp/coordination
  (move to read/ after reading). Commits use explicit paths only — never
  `git add -A`. Shared-lane edits so far: agent/blagent/blender_tools.py
  (registry switch), addon __init__ (Skills Library box) — both announced.
