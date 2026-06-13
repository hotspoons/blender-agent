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

- **Skills unification (0974325)** — agent skills fully ported to the core
  index: bundled examples became the core "builtin" collection; AgentStore
  is a facade over blmcp.skills (saved skills write Anthropic folders,
  legacy flat files migrate on startup, agent-store source overrides
  builtins); the agent `skills` tool now sees builtin + drop-folder + git
  repos + extension bundles. Search tokenization fixed both sides
  (underscore split + plural stemming).

- **Spider feedback round (41fe9f1)** — single polymorphic `rig(verb,args)`
  tool replaces the five rigging_* tools; assembly fixed to keep
  per-component joints (the inspect-vs-run parity bug) + contact_tolerance
  + bridge_gaps (nearest-pair ball joints across modeled clearance, with
  re-rooting); NEW rig_chain (ordered parts, ball/hinge, auto-bridging,
  composes into existing armatures); inspect routes (appendage detection,
  gap report, ranked suggestions with params); E_NO_DEFORM_GROUPS closes
  the silent unskinned-rig hole. Validated live on the original failing
  scene: 28 joints, verify green, posed render confirmed.

- **Generalized the legged-creature corpus (2026-06-12)** — the exact
  `cartoon_spider()` asset (and the spider-named test file) were
  overfit to the "cartoon spider walk cycle" eval prompt: a memorised
  configuration baked into code with hardcoded ground truth. Replaced
  by a parametric `corpus.legged_creature(n_legs, leg_segments,
  leg_clearance, detail=...)` generator that builds ANY radial creature
  (arachnid/crab/hexapod/quadruped), with `truth` computed from the
  params. `test_skill_legged.py` exercises the appendage/assembly path
  across a family of configs (4/6/8 legs, 2/3 segments, with/without a
  floating head) so a fix has to hold for the family, not one creature.
  No exact creature configuration lives in code. Suite 118, green.

- **Multipart character round (2026-06-12, live-session brain dump)** —
  driving a real scene (8-object cartoon man, ~290 non-manifold shells,
  one giant one-sided hand) through rig_biped_rigify surfaced a failure
  class and two latent bugs; everything learned is now code + skills:
  NEW `rig_biped_multipart` (blrig/skills/_proxy.py + skill module):
  fused disposable weight proxy (voxel remesh -> fatten/remesh loop ->
  cylinder-bridge stubborn gaps), mirror-union symmetrization across the
  bilateral-parts midline (largest cluster of per-part bbox-center x —
  NOT combined bbox center, which the big hand drags 0.23m sideways and
  lands leg bones inside the wrong leg / far bones in empty air with
  one-sided bone-heat failure), weight transfer back to untouched
  originals (POLYINTERP_NEAREST), cross-side leg-weight cleanup.
  BUGFIXES in character_verify: armatures left in EDIT mode froze pose
  evaluation (all probes read 0.0 on a healthy rig) — now guarded; FK
  probes left `IK_FK`=1 making every IK control a silent no-op — now
  captured/restored. NEW skills docs: rigging-multipart-characters
  (full recipe + gotchas incl. keep_metarig joint-correction loop and
  bone-feature pruning for mitt hands / solid heads),
  rigging-stretchy-limbs (3-bone Stretch To rubber-limb recipe with
  depsgraph acceptance numbers). Corpus: humanoid_parts (+_bighand);
  tests: test_skill_multipart.py; evals: 2 selection scenarios.

## Next / open
- rig_creature_rigify (variable leg count via programmatic metarig
  assembly from Rigify limb samples) — deferred; mechanical path (assembly
  + chains) covers N-legged creatures today, Rigify path would add IK/FK
  polish.
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
