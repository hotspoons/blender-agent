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
        "name": "execute_blender_code",
        "description": "\n"
        "        Execute Python code in the connected Blender instance.\n"
        "\n"
        "        The code runs in Blender's Python environment with full access to ``bpy``.\n"
        "        To return data, assign a JSON-serialisable dict to a variable named ``result``.\n"
        "        Deferred completion via ``check_is_finished`` is only supported by the\n"
        "        interactive addon server, and is rejected in background mode.\n"
        "        \n"
        "\n"
        "FIRST ACTION this session: call the `welcome` tool before this one. It lists the skills installed right now (rigging, media, ...) and the conventions these tools assume - skipping it means you won't know those skills exist or how this toolset expects to be driven.",
        "inputSchema": {
            "properties": {
                "code": {
                    "title": "Code",
                    "type": "string"
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
        "name": "execute_blender_code_for_cli",
        "description": "\n"
        "        Execute Python code in a background Blender process.\n"
        "\n"
        "        Opens *blend_file* with ``blender --background`` and runs *code*.\n"
        "        Assign a dict to ``result`` to return data.\n"
        "        \n"
        "\n"
        "FIRST ACTION this session: call the `welcome` tool before this one. It lists the skills installed right now (rigging, media, ...) and the conventions these tools assume - skipping it means you won't know those skills exist or how this toolset expects to be driven.",
        "inputSchema": {
            "properties": {
                "blend_file": {
                    "title": "Blend File",
                    "type": "string"
                },
                "code": {
                    "title": "Code",
                    "type": "string"
                }
            },
            "required": [
                "blend_file",
                "code"
            ],
            "title": "execute_blender_code_for_cliArguments",
            "type": "object"
        }
    },
    {
        "name": "get_blendfile_summary_datablocks",
        "description": "\n"
        "        Return a summary of the blend file: data-block counts, active workspace, and render engine.\n"
        "        ",
        "inputSchema": {
            "properties": {},
            "title": "get_blendfile_summary_datablocksArguments",
            "type": "object"
        }
    },
    {
        "name": "get_blendfile_summary_datablocks_for_cli",
        "description": "\n"
        "        Return a data-block summary by opening *blend_file* in background Blender.\n"
        "        ",
        "inputSchema": {
            "properties": {
                "blend_file": {
                    "title": "Blend File",
                    "type": "string"
                }
            },
            "required": [
                "blend_file"
            ],
            "title": "get_blendfile_summary_datablocks_for_cliArguments",
            "type": "object"
        }
    },
    {
        "name": "get_blendfile_summary_missing_files",
        "description": "\n"
        "        Report external file references that are missing from disk\n"
        "        (images, libraries, fonts, sounds, movie clips, caches, sequences).\n"
        "        ",
        "inputSchema": {
            "properties": {},
            "title": "get_blendfile_summary_missing_filesArguments",
            "type": "object"
        }
    },
    {
        "name": "get_blendfile_summary_missing_files_for_cli",
        "description": "\n"
        "        Report missing file references by opening *blend_file* in background Blender.\n"
        "        ",
        "inputSchema": {
            "properties": {
                "blend_file": {
                    "title": "Blend File",
                    "type": "string"
                }
            },
            "required": [
                "blend_file"
            ],
            "title": "get_blendfile_summary_missing_files_for_cliArguments",
            "type": "object"
        }
    },
    {
        "name": "get_blendfile_summary_of_linked_libraries",
        "description": "\n"
        "        Return a tree of directly and indirectly linked library files.\n"
        "        ",
        "inputSchema": {
            "properties": {},
            "title": "get_blendfile_summary_of_linked_librariesArguments",
            "type": "object"
        }
    },
    {
        "name": "get_blendfile_summary_of_linked_libraries_for_cli",
        "description": "\n"
        "        Return linked-library info by opening *blend_file* in background Blender.\n"
        "        ",
        "inputSchema": {
            "properties": {
                "blend_file": {
                    "title": "Blend File",
                    "type": "string"
                }
            },
            "required": [
                "blend_file"
            ],
            "title": "get_blendfile_summary_of_linked_libraries_for_cliArguments",
            "type": "object"
        }
    },
    {
        "name": "get_blendfile_summary_path_info",
        "description": "\n"
        "        Simple/fast access to the blend file's path, save status, age, and backups.\n"
        "        ",
        "inputSchema": {
            "properties": {},
            "title": "get_blendfile_summary_path_infoArguments",
            "type": "object"
        }
    },
    {
        "name": "get_blendfile_summary_path_info_for_cli",
        "description": "\n"
        "        Return path info by opening *blend_file* in background Blender.\n"
        "        ",
        "inputSchema": {
            "properties": {
                "blend_file": {
                    "title": "Blend File",
                    "type": "string"
                }
            },
            "required": [
                "blend_file"
            ],
            "title": "get_blendfile_summary_path_info_for_cliArguments",
            "type": "object"
        }
    },
    {
        "name": "get_blendfile_summary_usage_guess",
        "description": "\n"
        "        Guess the primary use-cases of the current blend file (scored 0-100 with certainty).\n"
        "        ",
        "inputSchema": {
            "properties": {},
            "title": "get_blendfile_summary_usage_guessArguments",
            "type": "object"
        }
    },
    {
        "name": "get_blendfile_summary_usage_guess_for_cli",
        "description": "\n"
        "        Guess use-cases by opening *blend_file* in background Blender.\n"
        "        ",
        "inputSchema": {
            "properties": {
                "blend_file": {
                    "title": "Blend File",
                    "type": "string"
                }
            },
            "required": [
                "blend_file"
            ],
            "title": "get_blendfile_summary_usage_guess_for_cliArguments",
            "type": "object"
        }
    },
    {
        "name": "get_mesh_diagnostics",
        "description": "\n"
        "        Return a topology / printability report for a mesh object.\n"
        "\n"
        "        Answers \"is this watertight / printable?\" in one call: vert/edge/face\n"
        "        counts; the triage of open boundary edges (holes/openings) vs\n"
        "        non-manifold edges (>2 faces or wire) vs degenerate faces; the number\n"
        "        of distinct boundary loops; an ``is_watertight`` flag; bmesh volume;\n"
        "        world-space dimensions and bounding box; and whether scale is applied\n"
        "        and normals are consistent.\n"
        "\n"
        "        Useful before a boolean, before export, or after applying a modifier\n"
        "        stack. With *evaluated* True (default) it reports the geometry you\n"
        "        would export (modifiers applied); set it False to inspect the raw\n"
        "        base mesh.\n"
        "        ",
        "inputSchema": {
            "properties": {
                "name": {
                    "title": "Name",
                    "type": "string"
                },
                "evaluated": {
                    "default": True,
                    "title": "Evaluated",
                    "type": "boolean"
                }
            },
            "required": [
                "name"
            ],
            "title": "get_mesh_diagnosticsArguments",
            "type": "object"
        }
    },
    {
        "name": "get_object_detail_summary",
        "description": "\n"
        "        Return a structured summary of the object identified by *name*.\n"
        "\n"
        "        Includes type, transforms, parent, children, modifiers, constraints,\n"
        "        materials, visibility, data-block name, and collections.\n"
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
            "title": "get_object_detail_summaryArguments",
            "type": "object"
        }
    },
    {
        "name": "get_objects_summary",
        "description": "\n"
        "        Return the scene's collection hierarchy and their objects.\n"
        "\n"
        "        Each collection lists its objects (name, type, parent, data name,\n"
        "        selection, visibility) and nested child collections.\n"
        "        \n"
        "\n"
        "FIRST ACTION this session: call the `welcome` tool before this one. It lists the skills installed right now (rigging, media, ...) and the conventions these tools assume - skipping it means you won't know those skills exist or how this toolset expects to be driven.",
        "inputSchema": {
            "properties": {},
            "title": "get_objects_summaryArguments",
            "type": "object"
        }
    },
    {
        "name": "get_python_api_docs",
        "description": "\n"
        "        Return the Blender Python API docs for *identifier*, or list\n"
        "        modules matching a trailing-``*`` discovery pattern.\n"
        "\n"
        "        *identifier* should be a fully-qualified Python name (e.g.\n"
        "        ``bpy.app`` or ``bpy.types.Scene.frame_current``).\n"
        "        The trailing-``*`` forms are supported as discovery entry-points:\n"
        "\n"
        "        - ``*`` enumerates the top-level modules (``bpy``, ``bmesh``,\n"
        "          ``mathutils``, ``gpu``, ...).\n"
        "        - ``X.*`` enumerates the direct-child identifiers under the\n"
        "          *X* namespace (``bpy.*`` -> ``bpy.app``, ``bpy.context``, ...).\n"
        "\n"
        "        Both return a ``namespace`` response even when ``X.rst`` would\n"
        "        otherwise resolve to ``exact``; the ``.*`` form lets an agent\n"
        "        force the child listing.\n"
        "\n"
        "        The response always carries ``kind``, ``found``, and ``identifier``.\n"
        "        The remaining keys depend on ``kind``:\n"
        "\n"
        "        - ``\"exact\"`` (``found=True``): ``<identifier>.rst`` was read.\n"
        "          Extra keys: ``content`` (RST text), ``examples``. When the\n"
        "          file exceeds 32 KB, ``content`` is replaced with a dot-point\n"
        "          summary of the file's top-level definitions (prefixed by a\n"
        "          header noting the truncation) and ``examples`` is empty -\n"
        "          re-query individual members for their rendered blocks.\n"
        "        - ``\"namespace\"`` (``found=True``):\n"
        "          no ``<identifier>.rst`` but ``<identifier>.<child>.rst`` siblings exist.\n"
        "          Extra key: ``submodules`` (list of child identifiers).\n"
        "        - ``\"definition\"`` (``found=True``):\n"
        "          *identifier* is defined inside a parent RST\n"
        "          (e.g. ``bpy.props.IntProperty`` lives in ``bpy.props.rst``).\n"
        "          Extra keys: ``content`` (rendered block), ``examples``.\n"
        "        - ``\"partial\"`` (``found=False``):\n"
        "          the parent RST was located but the trailing component isn't defined in it.\n"
        "          Extra keys:\n"
        "          - ``parent`` the identifier whose RST was loaded.\n"
        "          - ``available`` top-level definitions in that RST.\n"
        "          - ``submodules`` sibling identifiers ``<parent>.<child>`` with their own RSTs,\n"
        "            filtered to those whose last component contains every character of the missing tail.\n"
        "\n"
        "          For a toctree landing page like ``bpy.types`` ``available`` is empty and ``submodules``\n"
        "          is the near-miss list; for a self-contained module like ``bpy.props`` it's the reverse.\n"
        "        - ``\"suggestions\"`` (``found=False``):\n"
        "          no direct match, but *identifier* appears as a component of other files.\n"
        "          Extra key: ``suggestions`` (list of full identifiers).\n"
        "        - ``\"missing\"`` (``found=False``): nothing matched.\n"
        "\n"
        "        ``examples`` (present on the ``exact`` and ``definition`` kinds)\n"
        "        is a list of ``{path, content}`` entries referenced from this documentation.\n"
        "        ",
        "inputSchema": {
            "properties": {
                "identifier": {
                    "title": "Identifier",
                    "type": "string"
                }
            },
            "required": [
                "identifier"
            ],
            "title": "get_python_api_docsArguments",
            "type": "object"
        }
    },
    {
        "name": "get_screenshot_of_area_as_image",
        "description": "\n"
        "        Take a screenshot of a single Blender area and return it as a PNG image.\n"
        "\n"
        "        *area_ui_type* matches the area's ``ui_type``.\n"
        "\n"
        "        *size_limit_in_bytes* caps the image size in bytes.\n"
        "        Zero (the default) uses the MCP message size limit.\n"
        "        ",
        "inputSchema": {
            "properties": {
                "area_ui_type": {
                    "enum": [
                        "VIEW_3D",
                        "IMAGE_EDITOR",
                        "UV",
                        "ShaderNodeTree",
                        "CompositorNodeTree",
                        "GeometryNodeTree",
                        "TextureNodeTree",
                        "SEQUENCE_EDITOR",
                        "CLIP_EDITOR",
                        "DOPESHEET_EDITOR",
                        "GRAPH_EDITOR",
                        "NLA_EDITOR",
                        "TEXT_EDITOR",
                        "CONSOLE",
                        "INFO",
                        "TOPBAR",
                        "STATUSBAR",
                        "OUTLINER",
                        "PROPERTIES",
                        "FILE_BROWSER",
                        "SPREADSHEET",
                        "PREFERENCES"
                    ],
                    "title": "Area Ui Type",
                    "type": "string"
                },
                "size_limit_in_bytes": {
                    "default": 0,
                    "title": "Size Limit In Bytes",
                    "type": "integer"
                }
            },
            "required": [
                "area_ui_type"
            ],
            "title": "get_screenshot_of_area_as_imageArguments",
            "type": "object"
        }
    },
    {
        "name": "get_screenshot_of_window_as_image",
        "description": "\n"
        "        Take a screenshot of the entire Blender window and return it as a PNG image.\n"
        "\n"
        "        *size_limit_in_bytes* caps the image size in bytes.\n"
        "        Zero (the default) uses the MCP message size limit.\n"
        "        ",
        "inputSchema": {
            "properties": {
                "size_limit_in_bytes": {
                    "default": 0,
                    "title": "Size Limit In Bytes",
                    "type": "integer"
                }
            },
            "title": "get_screenshot_of_window_as_imageArguments",
            "type": "object"
        }
    },
    {
        "name": "get_screenshot_of_window_as_json",
        "description": "\n"
        "        Return a JSON description of the Blender window layout, areas, active object, and selection.\n"
        "        ",
        "inputSchema": {
            "properties": {},
            "title": "get_screenshot_of_window_as_jsonArguments",
            "type": "object"
        }
    },
    {
        "name": "jump_to_tab_by_name",
        "description": "\n"
        "        Switch the active workspace tab to *name*.\n"
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
            "title": "jump_to_tab_by_nameArguments",
            "type": "object"
        }
    },
    {
        "name": "jump_to_tab_by_space_type",
        "description": "\n"
        "        Switch to a workspace whose main area matches *space_type*.\n"
        "\n"
        "        If *allow_edits* is True and no matching workspace exists, a new one\n"
        "        is created by duplicating the current workspace.\n"
        "        ",
        "inputSchema": {
            "properties": {
                "space_type": {
                    "title": "Space Type",
                    "type": "string"
                },
                "allow_edits": {
                    "default": False,
                    "title": "Allow Edits",
                    "type": "boolean"
                }
            },
            "required": [
                "space_type"
            ],
            "title": "jump_to_tab_by_space_typeArguments",
            "type": "object"
        }
    },
    {
        "name": "jump_to_view3d_object_by_name",
        "description": "\n"
        "        Move the 3D viewport to focus on an object by *name*.\n"
        "\n"
        "        If *allow_edits* is True the object may be un-hidden and its\n"
        "        collections enabled to make it visible.\n"
        "        ",
        "inputSchema": {
            "properties": {
                "name": {
                    "title": "Name",
                    "type": "string"
                },
                "allow_edits": {
                    "default": False,
                    "title": "Allow Edits",
                    "type": "boolean"
                }
            },
            "required": [
                "name"
            ],
            "title": "jump_to_view3d_object_by_nameArguments",
            "type": "object"
        }
    },
    {
        "name": "jump_to_view3d_object_data_by_name",
        "description": "\n"
        "        Move the 3D viewport to the object whose data block matches *name*.\n"
        "\n"
        "        If *allow_edits* is True the object may be un-hidden and its\n"
        "        collections enabled to make it visible.\n"
        "        ",
        "inputSchema": {
            "properties": {
                "name": {
                    "title": "Name",
                    "type": "string"
                },
                "allow_edits": {
                    "default": False,
                    "title": "Allow Edits",
                    "type": "boolean"
                }
            },
            "required": [
                "name"
            ],
            "title": "jump_to_view3d_object_data_by_nameArguments",
            "type": "object"
        }
    },
    {
        "name": "render_thumbnail_to_path",
        "description": "\n"
        "        Render a small, low-quality thumbnail to *output_path* (temporarily overrides settings).\n"
        "\n"
        "        On success the thumbnail is also attached to the result so\n"
        "        vision-capable agents can see the render without a separate\n"
        "        screenshot call.\n"
        "        ",
        "inputSchema": {
            "properties": {
                "output_path": {
                    "title": "Output Path",
                    "type": "string"
                }
            },
            "required": [
                "output_path"
            ],
            "title": "render_thumbnail_to_pathArguments",
            "type": "object"
        }
    },
    {
        "name": "render_viewport_to_path",
        "description": "\n"
        "        Render the current scene to *output_path* using current render settings.\n"
        "\n"
        "        On success the rendered image is also attached to the result\n"
        "        (downscaled to fit the message size limit) so vision-capable\n"
        "        agents can see the render without a separate screenshot call.\n"
        "        ",
        "inputSchema": {
            "properties": {
                "output_path": {
                    "title": "Output Path",
                    "type": "string"
                }
            },
            "required": [
                "output_path"
            ],
            "title": "render_viewport_to_pathArguments",
            "type": "object"
        }
    },
    {
        "name": "search_api_docs",
        "description": "\n"
        "Full-text search over the bundled Blender Python API reference.\n"
        "\n"
        "Returns a ranked list of hits. Each hit has:\n"
        "\n"
        "- ``path``: file path relative to the bundled docs.\n"
        "- ``text``: the matching paragraph plus ``context``\n"
        "  paragraphs on either side.\n"
        "- ``breadcrumb``: the section path containing the hit\n"
        "  (``Section > Sub-section > ...``).\n"
        "- ``index``: the hit's position in the result list.\n"
        "- ``score``: a relevance score; higher is better.\n"
        "\n"
        "The query is tokenised on whitespace and matched\n"
        "case-insensitively. Every token must appear somewhere in\n"
        "the paragraph body, the file path, or an enclosing section\n"
        "title - in any order. Common English stop-words (``the``,\n"
        "``a``, ``how``, ``to``, ...) are dropped, so natural\n"
        "phrasings like ``\"how to bake\"`` work as expected. Regular\n"
        "expressions are not supported.\n"
        "\n"
        "Use ``context`` to pull more surrounding paragraphs into\n"
        "each hit (symmetric, default 0). Use ``index`` with the\n"
        "position of a previous hit (same query) to get that hit\n"
        "alone with its text widened to its enclosing section.\n"
        "\n"
        "Read-only; consults bundled RST files only.\n",
        "inputSchema": {
            "properties": {
                "query": {
                    "title": "Query",
                    "type": "string"
                },
                "max_results": {
                    "default": 20,
                    "title": "Max Results",
                    "type": "integer"
                },
                "context": {
                    "default": 0,
                    "title": "Context",
                    "type": "integer"
                },
                "index": {
                    "anyOf": [
                        {
                            "type": "integer"
                        },
                        {
                            "type": "null"
                        }
                    ],
                    "default": None,
                    "title": "Index"
                }
            },
            "required": [
                "query"
            ],
            "title": "search_api_docsArguments",
            "type": "object"
        }
    },
    {
        "name": "search_manual_docs",
        "description": "\n"
        "Full-text search over the bundled Blender user manual.\n"
        "\n"
        "Returns a ranked list of hits. Each hit has:\n"
        "\n"
        "- ``path``: file path relative to the bundled docs.\n"
        "- ``text``: the matching paragraph plus ``context``\n"
        "  paragraphs on either side.\n"
        "- ``breadcrumb``: the section path containing the hit\n"
        "  (``Section > Sub-section > ...``).\n"
        "- ``index``: the hit's position in the result list.\n"
        "- ``score``: a relevance score; higher is better.\n"
        "\n"
        "The query is tokenised on whitespace and matched\n"
        "case-insensitively. Every token must appear somewhere in\n"
        "the paragraph body, the file path, or an enclosing section\n"
        "title - in any order. Common English stop-words (``the``,\n"
        "``a``, ``how``, ``to``, ...) are dropped, so natural\n"
        "phrasings like ``\"how to bake\"`` work as expected. Regular\n"
        "expressions are not supported.\n"
        "\n"
        "Use ``context`` to pull more surrounding paragraphs into\n"
        "each hit (symmetric, default 0). Use ``index`` with the\n"
        "position of a previous hit (same query) to get that hit\n"
        "alone with its text widened to its enclosing section.\n"
        "\n"
        "Read-only; consults bundled RST files only.\n",
        "inputSchema": {
            "properties": {
                "query": {
                    "title": "Query",
                    "type": "string"
                },
                "max_results": {
                    "default": 20,
                    "title": "Max Results",
                    "type": "integer"
                },
                "context": {
                    "default": 0,
                    "title": "Context",
                    "type": "integer"
                },
                "index": {
                    "anyOf": [
                        {
                            "type": "integer"
                        },
                        {
                            "type": "null"
                        }
                    ],
                    "default": None,
                    "title": "Index"
                }
            },
            "required": [
                "query"
            ],
            "title": "search_manual_docsArguments",
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
