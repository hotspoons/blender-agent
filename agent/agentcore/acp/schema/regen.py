# SPDX-FileCopyrightText: 2026 agentcore contributors
#
# SPDX-License-Identifier: MIT OR Apache-2.0

"""
Vendor the ACP v2 draft schema at a pinned commit and regenerate
``agentcore/acp/models_v2.py`` from it.

The official Python SDK (``agent-client-protocol``) ships v1 models only
(``acp.meta.PROTOCOL_VERSION == 1``), so the v2 models are ours to generate.
v2 is a DRAFT: types get renamed between alphas, so the schema is pinned by
sha and the generated models are checked in. Bumping the pin is a deliberate
act -- regenerate, then read the diff.

Usage (needs ``pip install datamodel-code-generator``)::

    python -m agentcore.acp.schema.regen --fetch   # re-download at PINNED_SHA
    python -m agentcore.acp.schema.regen           # regenerate from vendored
"""

__all__ = (
    "PINNED_SHA",
    "fetch",
    "generate",
    "main",
)

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request

# schema-v2.0.0-alpha.2 era. Bump deliberately; see the module docstring.
PINNED_SHA = "7b160aeda86d123f37f7a9d201e642cd7ee12ef5"

# The UNSTABLE schema is the superset: it carries session/fork and the mcp/*
# ACP transport, which we implement. Stable-only types are a subset of it.
_UPSTREAM = (
    "https://raw.githubusercontent.com/agentclientprotocol/agent-client-protocol/"
    "{sha:s}/schema/v2/{name:s}"
)
_FILES = (("schema.unstable.json", "v2.schema.json"), ("meta.unstable.json", "v2.meta.json"))

_HERE = os.path.dirname(os.path.abspath(__file__))
_MODELS = os.path.join(os.path.dirname(_HERE), "models_v2.py")

_HEADER = """# SPDX-FileCopyrightText: 2026 agentcore contributors
#
# SPDX-License-Identifier: MIT OR Apache-2.0
#
# GENERATED FILE -- DO NOT EDIT.
# Regenerate with: python -m agentcore.acp.schema.regen
# Source: ACP v2 draft schema (Apache-2.0), pinned at
#   {sha:s}
\"\"\"
Pydantic models for the ACP v2 draft, generated from the vendored schema.

Field names are snake_case with camelCase wire aliases, so every model must be
serialized with ``by_alias=True`` (see ``agentcore.acp.wire``).
\"\"\"

"""


def fetch(sha: str) -> None:
    """Download the pinned schema + method table into this directory."""
    for remote, local in _FILES:
        url = _UPSTREAM.format(sha=sha, name=remote)
        with urllib.request.urlopen(url) as response:  # noqa: S310 - fixed https host
            body = response.read()
        with open(os.path.join(_HERE, local), "wb") as fh:
            fh.write(body)
        print("fetched {:s} -> {:s} ({:d} bytes)".format(remote, local, len(body)))


def _codegen_input(schema_path: str, out_path: str) -> None:
    """
    Write a codegen-only copy of the schema with the top-level union dropped.

    The root ``anyOf`` is the JSON-RPC envelope (request/response/notification
    wrappers). ``acp.connection.Connection`` already owns framing, so
    generating envelope models would only add junk names like
    ``AgentClientProtocol23`` beside the types we actually use.
    """
    with open(schema_path, "r", encoding="utf-8") as fh:
        schema = json.load(fh)
    schema.pop("anyOf", None)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(schema, fh)


def generate() -> int:
    """Regenerate the models from the vendored schema. Returns an exit code."""
    schema_path = os.path.join(_HERE, "v2.schema.json")
    if not os.path.isfile(schema_path):
        print("no vendored schema; run with --fetch first", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        stripped = os.path.join(tmp, "codegen.schema.json")
        body = os.path.join(tmp, "models.py")
        _codegen_input(schema_path, stripped)
        try:
            subprocess.run(
                [
                    sys.executable, "-m", "datamodel_code_generator",
                    "--input", stripped,
                    "--input-file-type", "jsonschema",
                    "--output-model-type", "pydantic_v2.BaseModel",
                    "--target-python-version", "3.10",
                    "--snake-case-field",
                    # Without this, a model accepts ONLY the camelCase alias --
                    # so `PromptCapabilities(embedded_context=...)` type-checks
                    # (it is the declared field name) yet silently drops the
                    # value. Population by field name closes that gap: the
                    # name mypy sees is the name pydantic honors.
                    "--allow-population-by-field-name",
                    # Reject unknown keys on OUR side rather than absorbing
                    # them; v2's forward-compat story is the `_`-prefixed
                    # variant escape and `_meta`, not silent extras.
                    "--extra-fields", "forbid",
                    "--use-annotated",
                    "--use-default",
                    "--disable-timestamp",
                    "--output", body,
                ],
                check=True,
            )
        except FileNotFoundError:
            print("datamodel-code-generator is not installed", file=sys.stderr)
            return 1
        except subprocess.CalledProcessError as ex:
            print("codegen failed: {!s}".format(ex), file=sys.stderr)
            return 1
        with open(body, "r", encoding="utf-8") as fh:
            generated = fh.read()

    # Drop the generator's own banner; ours carries the provenance that matters.
    lines = generated.splitlines(keepends=True)
    while lines and (lines[0].startswith("#") or not lines[0].strip()):
        lines.pop(0)
    with open(_MODELS, "w", encoding="utf-8") as fh:
        fh.write(_HEADER.format(sha=PINNED_SHA))
        fh.write(_with_namespace(lines))
    print("wrote {:s}".format(_MODELS))
    return 0


def _with_namespace(lines: "list[str]") -> str:
    """
    Splice an ``__all__`` covering the generated classes into the body.

    The repo requires every module to declare its namespace
    (``_misc/check_namespace.py``), and a generated file is no exception. It
    goes immediately before the first class -- after the imports, because
    ``from __future__`` must be the first statement in the file.
    """
    body = "".join(lines)
    names = sorted(set(re.findall(r"^class ([A-Za-z_][A-Za-z0-9_]*)", body, re.MULTILINE)))
    entries = "".join('    "{:s}",\n'.format(name) for name in names)
    namespace = "__all__ = (\n{:s})\n\n\n".format(entries)

    for index, line in enumerate(lines):
        if line.startswith("class "):
            return "".join(lines[:index]) + namespace + "".join(lines[index:])
    # No classes at all: nothing to export, but still declare the namespace.
    return body + "\n__all__ = ()\n"


def main() -> int:
    """Entry point for the ACP schema vendor/regen script."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fetch", action="store_true",
        help="re-download the schema at PINNED_SHA before generating")
    parser.add_argument(
        "--sha", default=PINNED_SHA,
        help="override the pinned sha (updates nothing; edit PINNED_SHA to make it stick)")
    args = parser.parse_args()

    if args.fetch:
        fetch(args.sha)
    return generate()


if __name__ == "__main__":
    sys.exit(main())
