# Bundled Tier-B agent tools (shipped library)

Tools dropped here **ship with the package** and are discovered the same way
as user-authored Tier-B tools — via `search_agent_tools` / `list_agent_tools`
/ `run_agent_tool` — **without** being core MCP tools (they are NOT in the
always-on tool surface and NOT in the `test_tool_listing` golden).

This is the "ship a library that isn't part of core MCP tools" seed. The
registry scans this dir **in addition to** the user dir
(`~/.config/blender-mcp/agent_tools/`); a user-local tool of the same name
**shadows** the bundled one (so users can patch a shipped tool). Bundled
tools are read-only — `run_agent_tool` runs them; the store never overwrites
or deletes them.

## On-disk layout (one directory per tool)

    <tool_name>/
      tool.json        # metadata (below)
      tool.py          # entry: reads dict `params`, assigns dict `result`
      <helper>.py ...  # OPTIONAL bundle siblings, imported by bare name

`<tool_name>` must be a lowercase slug `[a-z0-9][a-z0-9_-]{1,63}`.

### tool.json

```json
{
  "name": "measure_joints",
  "description": "Detect joint/port frames on the selected parts (read-only).",
  "params_schema": {
    "properties": {"objects": {"type": "array"}},
    "required": ["objects"]
  },
  "granted_imports": [],
  "approved": true,
  "author": "blender-agent",
  "version": 1,
  "created": "2026-06-14",
  "pending_imports": []
}
```

- **`approved` MUST be `true`** — bundled tools ship vetted; `run_agent_tool`
  refuses unapproved tools.
- **`granted_imports`**: any imports OUTSIDE the default 3D-modeling allowlist
  that `tool.py` (or its siblings) needs. Stick to the allowlist
  (`bpy, bpy_extras, bmesh, mathutils, numpy, math, json, re, ...`) and leave
  this `[]`. To compose a framework, import its SDK (e.g. `blrig` → `blrig.api`)
  — SDK modules are allowed automatically, no grant needed.
- **`pending_imports`**: leave `[]` (only used for the runtime-author approval
  flow, never for shipped tools).

### tool.py contract

`tool.py` receives a dict named **`params`** and must assign a dict named
**`result`**. It runs inside Blender with `bpy`, under the import guard
(`granted_imports` ∪ allowlist ∪ SDK). Multi-file: add sibling `*.py` files and
`import <helper>` by bare name.

## Bundled skills

Tier-B *skills* (markdown recipes) do NOT go here — drop them in
`blmcp/data/skills/<name>/SKILL.md` (the builtin skill collection). They are
already shipped and discovered via `skills_search` / `skills_read`.
