# Blender Agent

## Overview

**Blender Agent** builds on Blender's official MCP (Model Context
Protocol) server, adding an autonomous web agent, an in-core skills
library, optional tool extensions for advanced workflows (rigging,
animation), and container/Helm deployment - while keeping the original
MCP tool surface intact and usable on its own.

It is a fork of the upstream
[Blender MCP server](https://www.blender.org/lab/mcp-server/)
([projects.blender.org/lab/blender_mcp](https://projects.blender.org/lab/blender_mcp));
the core MCP server and add-on below are upstream's, documented at
[blender.org/lab/mcp-server](https://www.blender.org/lab/mcp-server/).

### What this adds over upstream Blender MCP

- **Web Agent** (`agent/`, package `blender-mcp-agent`) - a
  conversational agent that drives Blender through the same tools:
  sessions with transcripts, a confirmation gate for destructive
  actions, media artifacts, context compaction, and a choice of LLM
  backend - any OpenAI-compatible endpoint **or** an in-browser model
  (Transformers.js / WebLLM on WebGPU, no server-side GPU needed). It
  also exposes an OpenAI-compatible `/v1/chat/completions` API for
  headless clients, and can run **standalone**: with no Blender in
  front of it, it spawns its own headless Blender as the compute
  surface (with a process-tree recursion guard). See [agent/readme.md](agent/readme.md).
- **Skills in the core MCP tools** - a searchable playbook library
  exposed as `skills_list` / `skills_search` / `skills_read` plus a
  `welcome` tool that primes a client with working instructions.
  Skills use the Anthropic `SKILL.md` layout and are sourced from
  built-ins, a drop folder, configured git repos, and tool extensions.
- **Tools extensions** (`mcp_ext/`, package `blender-mcp-extensions`) -
  an optional add-on collection that self-registers extra MCP tools and
  bundles matching skills. The first extension is a deterministic
  **rigging/animation** toolset (perception queries, rig standards,
  validation, Rigify wrappers).
- **Deployment** - a `Dockerfile` that bundles a headless Blender, a
  Helm chart at [charts/blender-agent](charts/blender-agent/), and a
  `make install-dev` that installs all three packages into Blender's
  bundled Python (Linux/macOS/Windows).

----

At its core it has two components that communicate over a TCP socket:

- A **Blender add-on** that runs inside Blender and executes requests.
- An **MCP server** that runs as a separate process, launched by the
  MCP client (e.g. [Llama.cpp](https://projects.blender.org/lab/blender_mcp/wiki/Llama.cpp)).

The data flow is:
```
MCP Client  ⇐ MCP/stdio ⇒  blender-mcp  ⇐ TCP socket ⇒  Blender Add-on
```


## Blender Add-on

Located in ``addon/blender_mcp_addon/``.

A Blender extension that allows the MCP server to communicate with a
running Blender instance. It must be installed and enabled for any of
the MCP tools to work.

The add-on provides a preferences panel for configuring the host, port,
and an optional auto-start setting.

### Functionality Overview

Note that this is intended to be a fairly minimal add-on.

Connectivity
   - Auto-start (optional), is non-blocking any issues can be viewed from the preferences.
   - Configurable polling intervals (active and idle rates) from preferences to avoid excessive overhead.
   - Client timeout protection - stalled connections are evicted.
   - Start/stop operators accessible from the preferences panel.
   - Deferred responses are supported only by the interactive add-on server;
     background mode requires requests to complete synchronously and rejects deferred results.




## MCP Server

Located in ``mcp/blmcp/``, installed as a Python package with the
entry point ``blender-mcp``.

An MCP client launches this process and communicates with it over
stdio. The server connects to the add-on's TCP socket to relay
requests to Blender.

### Transports

By default the server uses **stdio**: the MCP client launches one
``blender-mcp`` process per session and talks to it over its
standard input/output. No further configuration is needed.

The server can also run as a long-lived **HTTP** service
(MCP streamable-HTTP), shared by any number of MCP clients:

```
blender-mcp --transport http --port 10101
```

The data flow then becomes:
```
MCP Client  ⇐ MCP/http ⇒  blender-mcp (127.0.0.1:10101)  ⇐ TCP socket ⇒  Blender Add-on
```

Local MCP clients (e.g. Claude Code, Claude Desktop) connect with a
``.mcp.json`` pointing at the **MCP port** (here ``10101``):

```json
{
  "mcpServers": {
    "blender": {
      "type": "http",
      "url": "http://127.0.0.1:10101"
    }
  }
}
```

or, with the Claude Code CLI:

```
claude mcp add --transport http blender http://127.0.0.1:10101
```

Notes:

- **Mind which port.** When you run the Web Agent (below) it serves
  two distinct ports: its browser UI (default ``10102``, for you) and
  the MCP-over-HTTP endpoint (default ``10101``, for MCP clients). The
  ``.mcp.json`` must point at the **MCP port**, not the UI port. The
  TCP bridge port (``9876``) is internal plumbing between the server
  and the add-on - never an MCP client target.
- **Local only.** This endpoint binds to the loop-back interface, so
  it is reachable from MCP clients on the same machine. Cloud/web
  connectors (e.g. claude.ai custom connectors) run on Anthropic's
  servers and cannot reach your ``127.0.0.1`` - they need a public
  HTTPS URL (an ngrok/cloudflared tunnel in front of the port).
  Running inside a container? Publish/forward the port to the host
  (the dev container forwards ``9876``/``10101``/``10102``).
- The HTTP endpoint is stateless, so clients may connect, disconnect
  and reconnect freely.
- Browser-based clients (e.g. the llama.cpp web UI) are allowed by
  CORS only when served from this machine (``localhost`` origins).
- Anything that can reach the port can execute Python code in
  Blender. Only change ``--host`` from the default on a trusted
  network.


## Web Agent (Optional)

Located in ``agent/``, installed as the optional ``blender-mcp-agent``
package. A web-based agent UI that drives Blender through the same
tool surface, with conversation sessions, a searchable skills library,
media artifacts, an in-browser LLM option (Transformers.js), and any
OpenAI-compatible endpoint. It can be launched from the add-on
preferences (Web Agent section) or standalone via ``blender-agent``.
See [agent/readme.md](agent/readme.md).

``mcp/blmcp/data/``
   Data files bundled with the package.

   - ``prompts.yml`` provides instructions sent to the LLM at
     connection time.
   - ``api/`` contains Blender Python API reference in RST format.
   - ``manual/`` contains Blender user manual excerpts in RST format.

``mcp/blmcp/tools/``
   Each tool is a single module, auto-discovered at startup.
   Modules ending in ``_toolcode`` contain code that runs inside
   Blender (sent to the addon for execution) and are skipped during
   discovery.

``mcp/blmcp/tools_helpers/``
   Shared utilities used by tools. Tools should not import from each
   other; shared logic lives here instead.


### Tools
- ``execute_blender_code``
   - Execute Python code in the connected Blender instance.
- ``execute_blender_code_for_cli``
   - Execute Python code in a background Blender process.
- ``get_blendfile_summary_datablocks``
   - Return a summary of the blend file: data-block counts, active workspace,
   and render engine.
- ``get_blendfile_summary_datablocks_for_cli``
   - Return a data-block summary by opening *blend_file* in background
   Blender.
- ``get_blendfile_summary_missing_files``
   - Report external file references that are missing from disk (images,
   libraries, fonts, sounds, movie clips, caches, sequences).
- ``get_blendfile_summary_missing_files_for_cli``
   - Report missing file references by opening *blend_file* in background
   Blender.
- ``get_blendfile_summary_of_linked_libraries``
   - Return a tree of directly and indirectly linked library files.
- ``get_blendfile_summary_of_linked_libraries_for_cli``
   - Return linked-library info by opening *blend_file* in background
   Blender.
- ``get_blendfile_summary_path_info``
   - Simple/fast access to the blend file's path, save status, age, and
   backups.
- ``get_blendfile_summary_path_info_for_cli``
   - Return path info by opening *blend_file* in background Blender.
- ``get_blendfile_summary_usage_guess``
   - Guess the primary use-cases of the current blend file (scored 0-100 with
   certainty).
- ``get_blendfile_summary_usage_guess_for_cli``
   - Guess use-cases by opening *blend_file* in background Blender.
- ``get_object_detail_summary``
   - Return a structured summary of the object identified by *name*.
- ``get_objects_summary``
   - Return the scene's collection hierarchy and their objects.
- ``get_python_api_docs``
   - Return the Blender Python API docs for *identifier*, or list modules
   matching a trailing-``*`` discovery pattern.
- ``get_screenshot_of_area_as_image``
   - Take a screenshot of a single Blender area and return it as a PNG image.
- ``get_screenshot_of_window_as_image``
   - Take a screenshot of the entire Blender window and return it as a PNG
   image.
- ``get_screenshot_of_window_as_json``
   - Return a JSON description of the Blender window layout, areas, active
   object, and selection.
- ``jump_to_tab_by_name``
   - Switch the active workspace tab to *name*.
- ``jump_to_tab_by_space_type``
   - Switch to a workspace whose main area matches *space_type*.
- ``jump_to_view3d_object_by_name``
   - Move the 3D viewport to focus on an object by *name*.
- ``jump_to_view3d_object_data_by_name``
   - Move the 3D viewport to the object whose data block matches *name*.
- ``render_thumbnail_to_path``
   - Render a small, low-quality thumbnail to *output_path* (temporarily
   overrides settings).
- ``render_viewport_to_path``
   - Render the current scene to *output_path* using current render settings.