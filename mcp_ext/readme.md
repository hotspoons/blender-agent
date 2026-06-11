# blender-mcp-extensions

Optional tools extensions for the Blender MCP server: advanced workflow
toolsets that make complex Blender work accessible to agents without a
huge programming exercise. The core server works without this package;
installing it (`pip install -e mcp_ext`) makes the extensions appear
automatically.

## How extensions plug in

`blmcp.registry` discovers extensions from the `blender_mcp.extensions`
entry-point group (or the `BLENDER_MCP_EXTENSIONS` env var for raw
checkouts). Each extension is a module exposing:

- `register(mcp)` — registers its MCP tools (same hook as core tool modules)
- `skills_dir()` *(optional)* — a bundled skill collection (Anthropic
  SKILL.md layout) merged into the core skills index, served via the
  `skills_list` / `skills_search` / `skills_read` tools

A broken or missing extension never takes the core down — failures are
logged and skipped.

**Extensions vs skills:** an extension is Python pulled into the runtime
(deterministic tools the agent calls); a skill is knowledge the agent
reads and applies itself via `execute_blender_code`. Extensions bundle
skills that document when their tools apply.

## Extensions

### rigging

Deterministic rigging: the LLM selects and parameterizes skills, `blrig`
(running inside Blender) owns every coordinate-level decision.

| Tool | Purpose |
|---|---|
| `rigging_inspect` | health / loose parts / symmetry / contact graph — pick a skill from geometry |
| `rigging_diagnose` | dry-run precondition check, structured failure codes + suggestions |
| `rigging_run` | execute a rigging skill (rolls back cleanly on failure) |
| `rigging_verify` | pose-test postconditions through the depsgraph |
| `rigging_validate_rig` | validate any armature against the rig standard |

Skills: `rig_hinge`, `rig_piston`, `rig_wheel`, `rig_turret`,
`rig_rigid_assembly`, `rig_biped_rigify`, `rig_quadruped_rigify`.
Bundled docs: `rigging-overview`, `rigging-mechanical`,
`rigging-characters`, `rigging-standard`.

The extension is fully self-contained — library, tests, corpus and evals
all live under [`blmcp_ext/rigging/`](blmcp_ext/rigging/):
`cd mcp_ext/blmcp_ext/rigging && make test` runs all tiers headless
(tests/corpus are repo-only; wheels ship just the library and skills).
