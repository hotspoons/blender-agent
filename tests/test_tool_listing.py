# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Checks that the MCP server exposes the expected tool listing.
"""

__all__ = ()

import asyncio
import os
import sys
import unittest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Root of the repository.
_REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Complete expected tool listing.
# When a tool is added, changed, or removed this must be updated.
# Run with `--update` to regenerate from a live server query.

# BEGIN: EXPECTED_TOOLS
EXPECTED_TOOLS = [
    {
        "name": "search_agent_tools",
        "description": "\n"
        "        Search the agent-authored tool library by intent. ALWAYS try this\n"
        "        before solving a task from scratch with execute_blender_code \u2014 a\n"
        "        tested tool may already exist. Returns ranked {name, description}.\n"
        "        ",
        "inputSchema": {
            "properties": {
                "query": {
                    "title": "Query",
                    "type": "string"
                },
                "max_results": {
                    "default": 8,
                    "title": "Max Results",
                    "type": "integer"
                }
            },
            "required": [
                "query"
            ],
            "title": "search_agent_toolsArguments",
            "type": "object"
        }
    },
    {
        "name": "list_agent_tools",
        "description": "List every agent-authored tool with a one-line summary.",
        "inputSchema": {
            "properties": {},
            "title": "list_agent_toolsArguments",
            "type": "object"
        }
    },
    {
        "name": "list_agent_skills",
        "description": "\n"
        "        List agent/user-authored skills (excludes shipped builtins and\n"
        "        tools-extension bundles). Read one with skills_read(name).\n"
        "        ",
        "inputSchema": {
            "properties": {},
            "title": "list_agent_skillsArguments",
            "type": "object"
        }
    },
    {
        "name": "agent_tool_details",
        "description": "\n"
        "        Full detail for one capability: an authored tool's input schema +\n"
        "        code + approval/imports, or \u2014 if *name* is a skill \u2014 its body.\n"
        "        ",
        "inputSchema": {
            "properties": {
                "name": {
                    "title": "Name",
                    "type": "string"
                }
            },
            "required": [
                "name"
            ],
            "title": "agent_tool_detailsArguments",
            "type": "object"
        }
    },
    {
        "name": "run_agent_tool",
        "description": "\n"
        "        Run an agent-authored tool by name with *args* (an object matching\n"
        "        its params_schema). Executes in Blender through the same path as\n"
        "        execute_blender_code, under the tool's approved import policy.\n"
        "        ",
        "inputSchema": {
            "properties": {
                "name": {
                    "title": "Name",
                    "type": "string"
                },
                "args": {
                    "anyOf": [
                        {
                            "additionalProperties": True,
                            "type": "object"
                        },
                        {
                            "type": "null"
                        }
                    ],
                    "default": None,
                    "title": "Args"
                }
            },
            "required": [
                "name"
            ],
            "title": "run_agent_toolArguments",
            "type": "object"
        }
    },
    {
        "name": "author_tool",
        "description": "\n"
        "        Create (or update) a reusable agent tool. *code* (the entry) receives\n"
        "        a dict ``params`` and must assign a dict ``result``; it runs in Blender\n"
        "        with bpy. For bigger tools, pass *modules* = {name: source} \u2014 extra\n"
        "        files importable by bare name from the entry and each other (a bundle).\n"
        "        You may also import curated framework SDKs (e.g. `blrig`) to compose\n"
        "        existing skills. Imports are jailed to a 3D-modeling allowlist; anything\n"
        "        outside it (network, subprocess, etc.) prompts you for approval before\n"
        "        the tool is saved. dry_run validates without saving.\n"
        "        ",
        "inputSchema": {
            "properties": {
                "name": {
                    "title": "Name",
                    "type": "string"
                },
                "description": {
                    "title": "Description",
                    "type": "string"
                },
                "code": {
                    "title": "Code",
                    "type": "string"
                },
                "params_schema": {
                    "anyOf": [
                        {
                            "additionalProperties": True,
                            "type": "object"
                        },
                        {
                            "type": "null"
                        }
                    ],
                    "default": None,
                    "title": "Params Schema"
                },
                "modules": {
                    "anyOf": [
                        {
                            "additionalProperties": {
                                "type": "string"
                            },
                            "type": "object"
                        },
                        {
                            "type": "null"
                        }
                    ],
                    "default": None,
                    "title": "Modules"
                },
                "dry_run": {
                    "default": False,
                    "title": "Dry Run",
                    "type": "boolean"
                }
            },
            "required": [
                "name",
                "description",
                "code"
            ],
            "title": "author_toolArguments",
            "type": "object"
        }
    },
    {
        "name": "author_skill",
        "description": "\n"
        "        Save a reusable skill (markdown recipe) so future agents can find\n"
        "        it via skills_search / list_agent_skills. Write one after a recipe\n"
        "        is confirmed to work. Skills are knowledge, not executed directly.\n"
        "        ",
        "inputSchema": {
            "properties": {
                "name": {
                    "title": "Name",
                    "type": "string"
                },
                "body": {
                    "title": "Body",
                    "type": "string"
                }
            },
            "required": [
                "name",
                "body"
            ],
            "title": "author_skillArguments",
            "type": "object"
        }
    },
    {
        "name": "blendfile",
        "description": "\n"
        "        Summarise a .blend file. The *verb* selects the aspect; pass\n"
        "        ``blend_file`` in args to inspect a file on disk in a background\n"
        "        Blender (``--background``) instead of the connected session.\n"
        "\n"
        "        Aspects (args = {} for the live session, or {blend_file}):\n"
        "        - blendfile(\"datablocks\", {...}) \u2014 data-block counts, active\n"
        "          workspace, render engine.\n"
        "        - blendfile(\"path\", {...}) \u2014 fast path/save-status/age/backups.\n"
        "        - blendfile(\"usage\", {...}) \u2014 guess primary use-cases\n"
        "          (animation, modeling, rendering, ...) scored 0-100.\n"
        "        - blendfile(\"missing\", {...}) \u2014 external references missing from\n"
        "          disk (images, libraries, fonts, sounds, clips, caches, sequences).\n"
        "        - blendfile(\"libraries\", {...}) \u2014 tree of directly and indirectly\n"
        "          linked library files.\n"
        "        ",
        "inputSchema": {
            "properties": {
                "verb": {
                    "title": "Verb",
                    "type": "string"
                },
                "args": {
                    "additionalProperties": True,
                    "title": "Args",
                    "type": "object"
                }
            },
            "required": [
                "verb",
                "args"
            ],
            "title": "blendfileArguments",
            "type": "object"
        }
    },
    {
        "name": "capture",
        "description": "\n"
        "        See the scene as pixels. One tool, verb-dispatched (args in {}):\n"
        "\n"
        "        - capture(\"screenshot\", {scope?: \"window\"|\"area\", area_ui_type?,\n"
        "          size_limit?}) \u2014 PNG of the Blender UI. scope defaults to\n"
        "          \"window\"; for \"area\" pass area_ui_type (the area's ui_type,\n"
        "          e.g. \"VIEW_3D\"). size_limit caps bytes (0 = MCP message limit).\n"
        "        - capture(\"render\", {path, quality?: \"full\"|\"thumbnail\"}) \u2014\n"
        "          render the scene to *path* and attach the image so vision\n"
        "          agents see it. quality \"full\" (default) uses current render\n"
        "          settings; \"thumbnail\" is a fast, low-quality preview.\n"
        "\n"
        "        For deliverable files the user can download, prefer media_io(...)\n"
        "        if the media extension is installed. Run `welcome` first if you\n"
        "        have not this session.\n"
        "        ",
        "inputSchema": {
            "properties": {
                "verb": {
                    "title": "Verb",
                    "type": "string"
                },
                "args": {
                    "additionalProperties": True,
                    "title": "Args",
                    "type": "object"
                }
            },
            "required": [
                "verb",
                "args"
            ],
            "title": "captureArguments",
            "type": "object"
        }
    },
    {
        "name": "docs",
        "description": "\n"
        "        Consult the bundled Blender docs before writing or debugging bpy\n"
        "        code. One tool, verb-dispatched (args in {}):\n"
        "\n"
        "        - docs(\"api\", {query, max_results?, context?, index?}) \u2014\n"
        "          full-text search of the Python API reference. Hits carry\n"
        "          path, text, breadcrumb, index, score. Tokens are matched\n"
        "          case-insensitively in any order; stop-words dropped. Use\n"
        "          context to widen surrounding paragraphs; re-call with index\n"
        "          (same query) to widen one hit to its enclosing section.\n"
        "        - docs(\"manual\", {query, max_results?, context?, index?}) \u2014\n"
        "          same, over the Blender user manual (concepts, workflows).\n"
        "        - docs(\"lookup\", {identifier}) \u2014 exact docs for a fully-qualified\n"
        "          name (e.g. \"bpy.types.Scene.frame_current\"). Trailing \"*\"\n"
        "          discovers a namespace: \"*\" lists top-level modules, \"bpy.*\"\n"
        "          lists direct children. Returns kind/found/identifier plus\n"
        "          content/examples/submodules/suggestions depending on the match.\n"
        "        ",
        "inputSchema": {
            "properties": {
                "verb": {
                    "title": "Verb",
                    "type": "string"
                },
                "args": {
                    "additionalProperties": True,
                    "title": "Args",
                    "type": "object"
                }
            },
            "required": [
                "verb",
                "args"
            ],
            "title": "docsArguments",
            "type": "object"
        }
    },
    {
        "name": "execute_blender_code",
        "description": "\n"
        "        Execute Python code in Blender. With full access to ``bpy``; to\n"
        "        return data, assign a JSON-serialisable dict to a variable named\n"
        "        ``result``.\n"
        "\n"
        "        Without *blend_file* the code runs in the connected interactive\n"
        "        Blender instance (deferred completion via ``check_is_finished``\n"
        "        is supported here). Pass *blend_file* to instead open that file\n"
        "        with ``blender --background`` and run the code in a one-shot\n"
        "        background process (no deferred completion).\n"
        "        \n"
        "\n"
        "FIRST ACTION this session: call the `welcome` tool before this one. It lists the skills installed right now (rigging, media, ...) and the conventions these tools assume - skipping it means you won't know those skills exist or how this toolset expects to be driven.",
        "inputSchema": {
            "properties": {
                "code": {
                    "title": "Code",
                    "type": "string"
                },
                "blend_file": {
                    "anyOf": [
                        {
                            "type": "string"
                        },
                        {
                            "type": "null"
                        }
                    ],
                    "default": None,
                    "title": "Blend File"
                }
            },
            "required": [
                "code"
            ],
            "title": "execute_blender_codeArguments",
            "type": "object"
        }
    },
    {
        "name": "scene",
        "description": "\n"
        "        Read the live scene \u2014 the inspect-before-acting entry point. One\n"
        "        tool, verb-dispatched (args in {}):\n"
        "\n"
        "        - scene(\"objects\", {}) \u2014 the scene's collection hierarchy and\n"
        "          their objects (name, type, parent, data name, selection,\n"
        "          visibility) plus nested child collections. START HERE.\n"
        "        - scene(\"object\", {name}) \u2014 structured detail for one object:\n"
        "          type, transforms, parent, children, modifiers, constraints,\n"
        "          materials, visibility, data-block name, collections.\n"
        "        - scene(\"mesh\", {name, evaluated?}) \u2014 topology / printability\n"
        "          report: vert/edge/face counts, holes vs non-manifold vs\n"
        "          degenerate triage, boundary loops, is_watertight, volume,\n"
        "          world dimensions/bbox, scale-applied and normals-consistent\n"
        "          flags. evaluated defaults true (modifiers applied); pass\n"
        "          false for the raw base mesh.\n"
        "        - scene(\"layout\", {}) \u2014 JSON of the window layout, areas, active\n"
        "          object, and selection (no pixels; use capture(...) for an image).\n"
        "\n"
        "        Run `welcome` first if you have not this session.\n"
        "        \n"
        "\n"
        "FIRST ACTION this session: call the `welcome` tool before this one. It lists the skills installed right now (rigging, media, ...) and the conventions these tools assume - skipping it means you won't know those skills exist or how this toolset expects to be driven.",
        "inputSchema": {
            "properties": {
                "verb": {
                    "title": "Verb",
                    "type": "string"
                },
                "args": {
                    "additionalProperties": True,
                    "title": "Args",
                    "type": "object"
                }
            },
            "required": [
                "verb",
                "args"
            ],
            "title": "sceneArguments",
            "type": "object"
        }
    },
    {
        "name": "skills_list",
        "description": "\n"
        "        List every available skill (name + one-line description) and the\n"
        "        sources they were indexed from.\n"
        "\n"
        "        Skills are proven recipes for complex Blender workflows (rigging,\n"
        "        modeling, repair, ...) with sample code YOU apply via\n"
        "        ``execute_blender_code`` \u2014 read one with ``skills_read`` before\n"
        "        attempting work it covers. Run the ``welcome`` tool first if you\n"
        "        have not yet this session.\n"
        "\n"
        "        Set ``refresh=True`` to re-scan folders and re-sync skill git repos.\n"
        "        ",
        "inputSchema": {
            "properties": {
                "refresh": {
                    "default": False,
                    "title": "Refresh",
                    "type": "boolean"
                }
            },
            "title": "skills_listArguments",
            "type": "object"
        }
    },
    {
        "name": "skills_search",
        "description": "\n"
        "        Rank skills against a natural-language *query* (task description,\n"
        "        keywords). Returns name + description; follow up with\n"
        "        ``skills_read`` on the best match.\n"
        "\n"
        "        ALWAYS search before non-trivial geometry, rigging, texturing or\n"
        "        repair work \u2014 skills encode deterministic recipes and their gotchas.\n"
        "        A miss returns the FULL catalog (it is small) \u2014 pick by\n"
        "        description instead of giving up.\n"
        "        ",
        "inputSchema": {
            "properties": {
                "query": {
                    "title": "Query",
                    "type": "string"
                },
                "max_results": {
                    "default": 8,
                    "title": "Max Results",
                    "type": "integer"
                }
            },
            "required": [
                "query"
            ],
            "title": "skills_searchArguments",
            "type": "object"
        }
    },
    {
        "name": "skills_read",
        "description": "\n"
        "        Read a skill's SKILL.md (default) or one of its ancillary files\n"
        "        (``file`` = relative path from ``skills_read(name)``'s file list).\n"
        "\n"
        "        The skill body contains instructions and sample code \u2014 execute the\n"
        "        code yourself via ``execute_blender_code``, adapting names/params\n"
        "        to the scene; nothing runs automatically.\n"
        "        ",
        "inputSchema": {
            "properties": {
                "name": {
                    "title": "Name",
                    "type": "string"
                },
                "file": {
                    "anyOf": [
                        {
                            "type": "string"
                        },
                        {
                            "type": "null"
                        }
                    ],
                    "default": None,
                    "title": "File"
                }
            },
            "required": [
                "name"
            ],
            "title": "skills_readArguments",
            "type": "object"
        }
    },
    {
        "name": "viewport",
        "description": "\n"
        "        Drive what the viewport shows. One tool, verb-dispatched\n"
        "        (args in {}):\n"
        "\n"
        "        - viewport(\"focus\", {name, target?: \"object\"|\"data\",\n"
        "          allow_edits?}) \u2014 move the 3D viewport onto an object.\n"
        "          target \"object\" (default) matches by object name; \"data\"\n"
        "          matches by data-block name. With allow_edits true the object\n"
        "          may be un-hidden and its collections enabled to reveal it.\n"
        "        - viewport(\"tab\", {name? | space_type?, allow_edits?}) \u2014 switch\n"
        "          the active workspace. Pass name for an exact tab, or\n"
        "          space_type to match the first workspace whose main area is\n"
        "          that type; with allow_edits and space_type, a new workspace is\n"
        "          created if none matches.\n"
        "        ",
        "inputSchema": {
            "properties": {
                "verb": {
                    "title": "Verb",
                    "type": "string"
                },
                "args": {
                    "additionalProperties": True,
                    "title": "Args",
                    "type": "object"
                }
            },
            "required": [
                "verb",
                "args"
            ],
            "title": "viewportArguments",
            "type": "object"
        }
    },
    {
        "name": "welcome",
        "description": "\n"
        "        Call FIRST, once per session, before any other tool.\n"
        "\n"
        "        This is the ONLY way to see what is actually installed in this\n"
        "        session: the live list of skills - reusable, tested recipes for\n"
        "        whole tasks (e.g. rigging any creature or mechanism, rendering\n"
        "        and encoding media) reached via `skills_search`/`skills_read` -\n"
        "        plus the conventions these tools assume (inspect before acting,\n"
        "        verify the API, code-execution rules). Skip it and you will not\n"
        "        know which skills exist or how this toolset expects to be driven.\n"
        "        Adopt the returned instructions for the rest of the session.\n"
        "        ",
        "inputSchema": {
            "properties": {},
            "title": "welcomeArguments",
            "type": "object"
        }
    },
    {
        "name": "media_io",
        "description": "\n"
        "        EVERY file between the user and the scene goes through this tool\n"
        "        and its media folder: user attachments land there, and anything\n"
        "        you put there the user can see and download. One tool,\n"
        "        verb-dispatched:\n"
        "\n"
        "        - media_io(\"list\", {}) \u2014 files available (user attachments of\n"
        "          any type: stl, obj, gltf/glb, fbx, usd, abc, svg, images,\n"
        "          audio \u2014 and your previous exports/renders).\n"
        "        - media_io(\"import\", {name}) \u2014 bring a listed file into the\n"
        "          scene: meshes via the native importers, svg as curves, images\n"
        "          as reference image-empties, audio as a speaker. Returns the\n"
        "          created object names.\n"
        "        - media_io(\"export\", {format, objects?, filename?}) \u2014 write the\n"
        "          scene (or just the named objects) as blend/stl/obj/ply/gltf/\n"
        "          glb/fbx/usd/abc (svg/pdf = grease-pencil strokes). An image\n"
        "          format (png/jpg/webp/exr) renders the scene instead \u2014 same as\n"
        "          \"render\".\n"
        "        - media_io(\"render\", {frame?, filename?, format?, camera?}) \u2014\n"
        "          render ONE frame straight to the media folder and return the\n"
        "          filename. The way to SHOW the user an image; works headless.\n"
        "          Uses the scene camera (or the only camera) and current render\n"
        "          settings.\n"
        "        - media_io(\"video\", {start?, end?, step?, fps?, format?,\n"
        "          filename?, camera?, quality?, ffmpeg?}) \u2014 render a frame range\n"
        "          and encode it to ONE video (mp4/mov/webm/gif) with ffmpeg.\n"
        "          The way to SHOW the user an animation (e.g. a looping walk\n"
        "          cycle); works headless. Defaults to the scene frame range and\n"
        "          24fps; quality is high/medium/low. ffmpeg is auto-located on\n"
        "          PATH and common OS paths \u2014 pass {ffmpeg: \"/path/to/ffmpeg\"}\n"
        "          only if it lives somewhere unusual.\n"
        "        - media_io(\"stage\", {path, filename?}) \u2014 copy a file that\n"
        "          already exists on disk (a render output, a baked cache) into\n"
        "          the media folder so the user gets it.\n"
        "        - media_io(\"info\", {name}) \u2014 size/kind of one file.\n"
        "\n"
        "        Filenames never overwrite \u2014 collisions get a -2/-3 suffix. When\n"
        "        the user attaches a file or asks for a deliverable (file OR\n"
        "        image), THIS is the tool \u2014 never read or write files via\n"
        "        execute_blender_code. Run `welcome` first if you have not.\n"
        "        ",
        "inputSchema": {
            "properties": {
                "verb": {
                    "title": "Verb",
                    "type": "string"
                },
                "args": {
                    "additionalProperties": True,
                    "title": "Args",
                    "type": "object"
                }
            },
            "required": [
                "verb",
                "args"
            ],
            "title": "media_ioArguments",
            "type": "object"
        }
    },
    {
        "name": "rig",
        "description": "\n"
        "        Rig ANYTHING \u2014 creatures with any number of legs, vehicles,\n"
        "        robots, props \u2014 WITHOUT writing armature code by hand. The\n"
        "        deterministic geometry code inside Blender computes every\n"
        "        coordinate (pivots, axes, rolls, weights), rolls back cleanly on\n"
        "        failure and pose-tests the result; hand-building armatures via\n"
        "        execute_blender_code forfeits all of that. ALWAYS try this tool\n"
        "        first for any rigging task.\n"
        "\n"
        "        FAST PATH \u2014 usually the only call you need:\n"
        "        - rig(\"auto\", {objects: [names]}) \u2014 inspects the parts, picks the\n"
        "          skill, diagnoses, builds AND verifies in one shot; returns a\n"
        "          staged transcript. Optional args: skill (override its routing),\n"
        "          params, contact_tolerance.\n"
        "\n"
        "        Step-by-step verbs (when auto fails, or for fine control):\n"
        "        - rig(\"inspect\", {objects}) \u2014 read-only COMPACT summary: ranked\n"
        "          `suggested` skills with ready-to-use params, a `next` call to\n"
        "          make, one line of health/size per object. Pass detail:true only\n"
        "          if you need raw OBBs and contact points.\n"
        "        - rig(\"diagnose\", {skill, objects, params?}) \u2014 dry-run; returns\n"
        "          the plan, or a failure code + `suggest` (act on it).\n"
        "        - rig(\"run\", {...same...}) \u2014 build the rig (armature, constraints,\n"
        "          skinning); rolls back cleanly on failure.\n"
        "        - rig(\"verify\", {skill, armature, objects?}) \u2014 pose-tests through\n"
        "          the depsgraph; REQUIRED before reporting success (auto already\n"
        "          includes it).\n"
        "        - rig(\"validate\", {armature}) \u2014 rig-standard report for ANY\n"
        "          armature, including imported/hand-built ones.\n"
        "\n"
        "        Skills: rig_chain (ORDERED parts -> ball/hinge joint chain;\n"
        "        bridges clearance gaps; `armature` param composes chains into an\n"
        "        existing rig \u2014 spider legs, robot arms, landing gear),\n"
        "        rig_rigid_assembly (any pile of parts; `contact_tolerance`,\n"
        "        `bridge_gaps`), rig_hinge, rig_piston, rig_wheel, rig_turret,\n"
        "        rig_biped_rigify (ONE clean symmetric humanoid mesh),\n"
        "        rig_biped_multipart (humanoid split across several meshes or\n"
        "        built from non-manifold shell piles \u2014 fused weight proxy +\n"
        "        weight transfer; originals untouched), rig_quadruped_rigify (ONE\n"
        "        clean four-legged mesh), rig_quadruped_multipart (four-legged\n"
        "        creature as several meshes / shell piles \u2014 same proxy path).\n"
        "\n"
        "        Param/failure-code reference: skills_read(\"rigging-overview\").\n"
        "        ",
        "inputSchema": {
            "properties": {
                "verb": {
                    "title": "Verb",
                    "type": "string"
                },
                "args": {
                    "additionalProperties": True,
                    "title": "Args",
                    "type": "object"
                }
            },
            "required": [
                "verb",
                "args"
            ],
            "title": "rigArguments",
            "type": "object"
        }
    },
    {
        "name": "weights",
        "description": "\n"
        "        Diagnose and FIX skinning/weight-paint problems in bulk \u2014 never\n"
        "        loop over vertices via execute_blender_code. Use when a mesh\n"
        "        deforms wrong (collapsing, dragging, not following its bone),\n"
        "        after importing a rigged model, or to skin meshes against an\n"
        "        existing armature. Mutating verbs snapshot the scene and roll\n"
        "        back on failure; retrying is always safe.\n"
        "\n"
        "        Verbs (args in {}):\n"
        "        - weights(\"inspect\", {object, armature?}) \u2014 START HERE. Coverage\n"
        "          report: per-group weighted-vert counts, empty groups, L/R\n"
        "          imbalance, unweighted verts, deform bones with no group.\n"
        "        - weights(\"transfer\", {source, targets: [names], armature?}) \u2014\n"
        "          copy all weights mesh->mesh by nearest-face interpolation\n"
        "          (clothes/props from a body; originals from a repaired proxy).\n"
        "        - weights(\"mirror\", {object, from_side: \"L\"|\"R\", armature?,\n"
        "          center_x?, tolerance?}) \u2014 copy one side's weights onto the\n"
        "          other across the detected symmetry midline, flipping .L/.R\n"
        "          group names. Fixes one-sided bone-heat failures.\n"
        "        - weights(\"clean\", {object, threshold?, limit?, armature?}) \u2014\n"
        "          prune weights below threshold, cap influences per vert\n"
        "          (default 4), drop empty groups, normalize.\n"
        "        - weights(\"smooth\", {object, groups?: [globs], factor?,\n"
        "          iterations?, armature?}) \u2014 blur weights along topology; fixes\n"
        "          hard seams after transfer and stair-step deformation.\n"
        "        - weights(\"bind\", {objects: [names], armature}) \u2014 armature\n"
        "          modifier + parent, transform preserved. Weights must already\n"
        "          exist (else it fails; pass allow_unweighted to bind first).\n"
        "        - weights(\"validate\", {objects: [names], armature}) \u2014 the QA\n"
        "          gate: unweighted/unnormalized verts, non-deform groups.\n"
        "\n"
        "        For rigging from scratch use rig(...); for full guidance\n"
        "        skills_read(\"weight-painting\").\n"
        "        ",
        "inputSchema": {
            "properties": {
                "verb": {
                    "title": "Verb",
                    "type": "string"
                },
                "args": {
                    "additionalProperties": True,
                    "title": "Args",
                    "type": "object"
                }
            },
            "required": [
                "verb",
                "args"
            ],
            "title": "weightsArguments",
            "type": "object"
        }
    },
    {
        "name": "pose",
        "description": "\n"
        "        Read and set armature poses in bulk \u2014 bone names take globs, so\n"
        "        one call poses a whole limb set. Handles the silent killers for\n"
        "        you: rotation_mode mismatches (values converted, never dropped),\n"
        "        armatures stuck in EDIT mode, depsgraph updates before reads,\n"
        "        Rigify IK_FK switch state. Failed calls restore the prior pose.\n"
        "\n"
        "        Verbs (args in {}):\n"
        "        - pose(\"get\", {armature, bones?: [globs]}) \u2014 read pose channels\n"
        "          (default: only bones posed away from rest) + IK/FK switch\n"
        "          state. START HERE on an unfamiliar rig.\n"
        "        - pose(\"set\", {armature, bones: {glob: {rotation_deg: [x,y,z],\n"
        "          location?, scale?}}, additive?}) \u2014 batch-set transforms; e.g.\n"
        "          one call raises both arms: {\"upper_arm_fk.*\": {...}}.\n"
        "        - pose(\"mirror\", {armature, from_side: \"L\"|\"R\", bones?}) \u2014 copy\n"
        "          a pose onto the other side, flipped (paste-flipped math).\n"
        "        - pose(\"reset\", {armature, bones?}) \u2014 back to rest pose.\n"
        "        - pose(\"ik_fk\", {armature, to: \"fk\"|\"ik\", limbs?: [globs],\n"
        "          snap?}) \u2014 switch Rigify limbs IK<->FK and snap the destination\n"
        "          controls so nothing jumps. Pose FK chains AFTER switching to\n"
        "          fk, IK targets after switching to ik \u2014 otherwise the controls\n"
        "          you move are silent no-ops.\n"
        "        - pose(\"save_named\"/\"apply_named\"/\"list_named\", {armature,\n"
        "          name}) \u2014 store and recall named poses on the armature.\n"
        "\n"
        "        Animate over time with anim(...); full guidance:\n"
        "        skills_read(\"posing\").\n"
        "        ",
        "inputSchema": {
            "properties": {
                "verb": {
                    "title": "Verb",
                    "type": "string"
                },
                "args": {
                    "additionalProperties": True,
                    "title": "Args",
                    "type": "object"
                }
            },
            "required": [
                "verb",
                "args"
            ],
            "title": "poseArguments",
            "type": "object"
        }
    },
    {
        "name": "anim",
        "description": "\n"
        "        Keyframe animation at scale on Blender 5.x layered Actions \u2014\n"
        "        bulk key insertion, PARAMETRIC motion cycles (walks, idles,\n"
        "        mechanical loops for ANY rig), seamless looping, visual-keying\n"
        "        bakes and NLA layering. Never hand-write keyframe loops or read\n"
        "        action.fcurves (it no longer exists) via execute_blender_code.\n"
        "        Failed mutations roll the scene back.\n"
        "\n"
        "        Verbs (args in {}):\n"
        "        - anim(\"inspect\", {armature}) \u2014 what's animated: action, keyed\n"
        "          bones/channels, key range, loop modifiers, NLA tracks.\n"
        "        - anim(\"keyframe\", {armature, keys: [{frame, bones: {glob:\n"
        "          {rotation_deg|location|scale}}}]}) \u2014 bulk insert across\n"
        "          bones x frames; rotation_mode handled per bone.\n"
        "        - anim(\"cycle\", {armature, frames?, channels: [{bones: [globs],\n"
        "          channel: \"rotation\"|\"location\", axis, amplitude, phase?,\n"
        "          phase_step?, frequency?, offset?}]}) \u2014 build a seamless\n"
        "          parametric cycle from phase-offset oscillators. Gaits are\n"
        "          phase relationships: opposite legs phase 0 and 0.5, tripod\n"
        "          groups via phase_step, root bob at frequency 2. Drive bones\n"
        "          the rig actually has (check pose(\"get\") / the rig's controls).\n"
        "        - anim(\"loop\", {armature}) \u2014 make the current action loop\n"
        "          cleanly: pin last key = first, CYCLES extrapolation, frame\n"
        "          range.\n"
        "        - anim(\"bake\", {armature, frame_start?, frame_end?, bones?,\n"
        "          step?}) \u2014 bake constraints/IK to plain keys (visual keying).\n"
        "        - anim(\"actions\", {armature, op: \"list\"|\"new\"|\"assign\"|\n"
        "          \"push_nla\"|\"rename\"|\"remove\", name?}) \u2014 layered-Action and\n"
        "          NLA management; push_nla stacks finished layers.\n"
        "        - anim(\"clear\", {armature, remove_action?, nla?}).\n"
        "\n"
        "        Static poses: pose(...). Guidance + gait patterns:\n"
        "        skills_read(\"animating-at-scale\") and the core\n"
        "        skills_read(\"animating-basics\").\n"
        "        ",
        "inputSchema": {
            "properties": {
                "verb": {
                    "title": "Verb",
                    "type": "string"
                },
                "args": {
                    "additionalProperties": True,
                    "title": "Args",
                    "type": "object"
                }
            },
            "required": [
                "verb",
                "args"
            ],
            "title": "animArguments",
            "type": "object"
        }
    }
]
# END: EXPECTED_TOOLS


def _list_tools() -> list[dict[str, object]]:
    """
    Starts the MCP server and returns the full tool listing.
    """

    # Async is required because the MCP client SDK is async-only.
    async def _run() -> list[dict[str, object]]:
        env = os.environ.copy()
        env["PYTHONPATH"] = os.path.join(_REPO_DIR, "mcp")
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "blmcp"],
            env=env,
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                return [
                    {
                        "name": t.name,
                        "description": t.description,
                        "inputSchema": t.inputSchema,
                    }
                    for t in result.tools
                ]

    return asyncio.run(_run())


class TestToolListing(unittest.TestCase):
    """
    Checks that the live tool listing matches the frozen snapshot.
    """

    _tools: list[dict[str, object]]

    @classmethod
    def setUpClass(cls) -> None:
        cls._tools = _list_tools()

    def test_tools_match_expected(self) -> None:
        """
        Checks that the live tool listing exactly matches ``EXPECTED_TOOLS``.
        """
        self.assertEqual(self._tools, EXPECTED_TOOLS)


def _update_expected_tools() -> None:
    """
    Re-generates the ``EXPECTED_TOOLS`` block from a live server query.
    """
    import json
    import subprocess

    filepath = os.path.abspath(__file__)
    with open(filepath, "r", encoding="utf-8") as fh:
        source = fh.read()
    begin = source.index("# BEGIN: EXPECTED_TOOLS\n") + len("# BEGIN: EXPECTED_TOOLS\n")
    end = source.index("# END: EXPECTED_TOOLS\n")
    formatted = json.dumps(_list_tools(), indent=4)
    formatted = (
        formatted.replace(": true", ": True")
        .replace(": false", ": False")
        .replace(": null", ": None")
    )
    formatted = formatted.replace("\\n", '\\n"\n"')
    # Also handles the `\n"` case (no trailing empty string).
    formatted = formatted.replace('\\n"\n""', '\\n"')
    formatted = "EXPECTED_TOOLS = " + formatted + "\n"
    with open(filepath, "w", encoding="utf-8") as fh:
        fh.write(source[:begin] + formatted + source[end:])
    subprocess.check_call(["autopep8", "--in-place", filepath])


if __name__ == "__main__":
    if "--update" in sys.argv:
        sys.argv.remove("--update")
        _update_expected_tools()
    else:
        unittest.main()
