---
name: authoring-agent-tools
description: Author reusable agent tools and skills at runtime (recursive self-improvement) — the tool contract, the import jail, and composing the framework SDK in one shot.
keywords: author, authoring, tool, tools, skill, skills, recursive, self-improvement, rsi, registry, publish, reusable, run_agent_tool, author_tool, author_skill, sandbox, sdk
---

# Authoring agent tools & skills

When you solve a task that will recur, **publish it** so future agents reuse it
instead of rebuilding it. First always `search_agent_tools(query)` — a tested
tool may already exist. If not, author one.

## Two things you can publish

- **Skill** (`author_skill(name, body)`): a markdown recipe — knowledge, not
  executed. Write one after a recipe is confirmed to work. Found later via
  `skills_search` / `list_agent_skills`.
- **Tool** (`author_tool(name, description, code, params_schema)`): executable
  Python that runs in Blender and is invoked by `run_agent_tool(name, args)`.

## The tool contract

`code` receives a dict named **`params`** and must assign a dict named
**`result`**. It runs in Blender with `bpy`, through the same transport as
`execute_blender_code`:

```python
author_tool(
  name="taper_to_point",
  description="Taper the active mesh's top verts toward a point over N steps.",
  params_schema={"properties": {"object": {"type": "string"},
                                "steps": {"type": "integer"}},
                 "required": ["object"]},
  code='''
import bpy, bmesh
from mathutils import Vector
obj = bpy.data.objects[params["object"]]
steps = int(params.get("steps", 4))
# ... bmesh edits ...
result = {"object": obj.name, "steps": steps}
''')
```

## The import jail (what you may import)

Imports are gated. **Allowed without approval**: `bpy`, `bpy_extras`, `bmesh`,
`mathutils`, `numpy`, `math`, `random`, `json`, `re`, `itertools`,
`dataclasses`, `typing`, and other benign stdlib — everything normal 3D
tooling needs. Anything else (network, `subprocess`, `os`, `importlib`,
dynamic `eval`/`exec`) pauses for **human approval**; the tool is saved INERT
until a person approves it. So: stick to the allowlist and your tool
auto-registers and runs immediately. Only the tool's OWN imports are gated —
libraries you import may use whatever they need internally.

## Compose the framework — don't reinvent it (the one-shot path)

Curated **framework SDKs are on the allowlist**, so a single tool can stand on
an existing Tier-A framework. Rigging exposes `blrig` (see `blrig.api`): inspect
a scene, run and compose existing rig skills, and verify — all in one tool:

```python
author_tool(
  name="rig_dragon_with_tail",
  description="Rig a multi-part dragon body, then compose a bendy tail chain onto it.",
  params_schema={"properties": {"body": {"type": "array"},
                                "tail": {"type": "array"}},
                 "required": ["body", "tail"]},
  code='''
from blrig import api
body = api.run("rig_rigid_assembly", params["body"], {"bridge_gaps": True})
arm = body["armature"]
api.run("rig_chain", params["tail"], {"armature": arm})
v = api.verify("rig_rigid_assembly", arm)
result = {"armature": arm, "verified": v["ok"]}
''')
```

Because `blrig` is a vetted SDK, this needs no approval — it auto-registers and
is immediately runnable. That is how a large capability ships as one authored
tool: compose the framework, don't rebuild it.

## After authoring

A tool you've proven across several real uses is a promotion candidate to a
curated core tool (a human runs `promote`). Until then it lives in the dynamic
registry, discovered by `search_agent_tools`.
