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

- **Weights / pose / anim tool families (2026-06-13)** — three new
  polymorphic MCP tools beside `rig`, same verb-router shape, registered
  in tools.py; ops live in blrig/skills/{weight,pose,anim}_ops.py, each
  exposing `dispatch(verb, args)`:
  * `weights`: inspect (coverage + L/R balance + bones-without-group),
    transfer (wraps _proxy.transfer_weights), mirror (NEW directional
    kdtree mirror across perception.symmetry_plane / explicit center_x,
    flips .L/.R group names, keeps the midline-margin blend), clean
    (prune/limit-total/normalize/drop-empty via vgroup ops, keep_single
    guard), smooth (vertex_group_smooth w/ WEIGHT_PAINT fallback), bind
    (wraps _proxy.bind_to_rig; REFUSES unweighted meshes by default —
    E_NO_DEFORM_GROUPS hole stays closed), validate. Mutators:
    scene-snapshot rollback, failures.jsonl.
  * `pose`: get/set (globs; rotation_deg CONVERTED to the bone's real
    rotation_mode, never dropped), mirror (paste-flipped channel math),
    reset (subset), ik_fk (Rigify switch + matrix snap via the ORG
    chain, geometric pole placement, snap_drift reported), named poses
    (JSON id-prop). Cheap pose-state capture/restore instead of scene
    snapshots. The EDIT-mode freeze + IK_FK capture bugs are now
    guarded in the shared path (`_bones.ensure_object_mode`, promoted
    from _character).
  * `anim`: inspect (layered channelbag API encoded once —
    action_fcurves()), keyframe (bulk bones x frames), cycle
    (PARAMETRIC phase-offset oscillators: bones/axis/amplitude/phase/
    phase_step/frequency/offset; seamless wrap by construction; NO
    named-gait library anywhere), loop (pin end keys + CYCLES mods),
    bake (anim_utils.bake_action visual keying; PoseBone.select — 5.x
    removed Bone.select), actions (new/assign/push_nla/...), clear.
    Probe-at-quarter-period lesson: every sin channel is ZERO at the
    half period — probing start vs start+frames/2 reads a healthy
    cycle as static.
  Skills: weight-painting, posing, animating-at-scale (cross-links
  animating-basics, doesn't fork it); rigging-overview routes the
  families. Tests: test_{weight,pose,anim}_ops.py (37 new; suite 163
  green all tiers); repo tests green, tool-listing snapshot
  regenerated (103). Evals: 10 new tool-family scenarios (chain =
  tool name, verb in param_checks); blind selection run on all 10
  (fresh sonnet agents, routing surface only): 10/10. Param lessons
  folded back into code, not descriptions: axis now accepts
  "X"/0|1|2, non-integer frequency rounds (can't wrap seamlessly).

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
- Agent-eval pass (2026-06-13) — ran all 16 selection scenarios blind
  (routing surface + request only, no inspect signal, no expected answer).
  Blind selection 14/16; both misses explained, realistic 15/16:
  * multipart-bighand: blind miss (request never says "multiple meshes" —
    that's an inspect fact). Re-run WITH the inspect report -> correctly
    routes rig_biped_multipart. Methodology artifact, not a description bug.
  * lamp-articulate: picks rig_chain over the expected rig_rigid_assembly
    EVEN with assembly ranked #1 in suggested — and the asset's own truth
    is {"chain": True}. Genuine routing ambiguity (a desk lamp IS an
    ordered segment chain). OPEN DECISION: accept rig_chain for the lamp,
    or tighten the table so standalone base+arm objects route to assembly.
  Param note: turret-limits real param is `pitch_limits_deg` (agent guessed
  `min_elevation_deg`); surfaced by inspect/diagnose at runtime, low pri.
- Deform coverage gap closed (2026-06-13) — `humanoid_parts ->
  rig_biped_multipart` added to deform_corpus._MATRIX; the multipart rig now
  gets the same pose-extremes (+-80deg) deformation smoke every other skill
  has. Full suite 126 green across all tiers. (Multipart end-to-end tests
  stay in the property tier — consistent with TestBipedEndToEnd, which is
  equally slow and also property; deform tier is the deformation matrix.)
- Corpus growth toward 30–50 assets (crab/tentacle/backhoe + scanned junk).
- Addon prefs repo field is comma-separated; a UIList would be nicer UX.

## Coordination
- Second agent ("bug-fixer") works concurrently; notes via /tmp/coordination
  (move to read/ after reading). Commits use explicit paths only — never
  `git add -A`. Shared-lane edits so far: agent/blagent/blender_tools.py
  (registry switch), addon __init__ (Skills Library box) — both announced.
