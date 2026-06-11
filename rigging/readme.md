# Rigging Skills Library (`blrig`)

A programmatic, deterministic rigging library for LLM agents driving Blender.

**Thesis:** the LLM selects and parameterizes skills; deterministic `bpy` code owns
every coordinate-level decision. Nothing load-bearing is generated — only selected
and parameterized. Classical geometry plus Blender's built-in machinery (Rigify,
bone-heat weights, symmetrize) — no ML rigging models.

## Layout

```
blrig/                  Python package, runs inside Blender's Python.
  perception/           Pure geometric queries (no scene mutation). The keystone.
  standard/             RIG_STANDARD.md + validate_rig() — conventions, enforced.
  skills/               One module per skill: diagnose(ctx) / run(ctx, params) / verify(ctx).
corpus/                 Procedural golden-asset generators (deterministic, no .blend blobs).
tests/                  Tiers: property tests, deformation smoke, golden-render regression.
evals/                  Agent skill-selection scenarios (natural language -> expected chain).
logs/                   Structured failure logs (append-only JSONL).
```

## Running

Everything runs headless inside Blender:

```sh
cd rigging
make test          # all tiers
make test-fast     # property tests only
```

Or directly:

```sh
blender --background --factory-startup --python tests/bl_run_all.py -- -v
```

`BLENDER_BIN` overrides the Blender binary (defaults to `blender` on `PATH`).

## Using from the agent

The agent-facing skill descriptions live in `agent/blagent/data/skills/rig-*.md`.
They instruct the agent to run, via `execute_blender_code`:

```python
import sys
sys.path.insert(0, "/workspaces/blender_mcp/rigging")
from blrig.skills import rig_hinge
report = rig_hinge.diagnose(ctx)        # machine-readable preconditions
result = rig_hinge.run(ctx, params)     # semantic params only
report = rig_hinge.verify(ctx)          # postconditions incl. validate_rig()
```

Every skill is idempotent or rolls back cleanly; failures return structured
diagnostics (`{"fail": "...", "suggest": "..."}`) the agent can act on.
