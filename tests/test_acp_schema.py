# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Tests for the vendored ACP v2 draft schema and the generated models
(``agent/agentcore/acp/``).

ACP v2 is a DRAFT: variant order shifts between alphas, and the generated
model names are positional. These tests are the tripwire for that -- they
assert the readable aliases in ``wire.py`` still point at the variants their
names claim, and that what we serialize validates against the vendored schema
rather than merely against our own models.

    python -m unittest tests.test_acp_schema -v
"""

__all__ = ()

import importlib.util
import json
import os
import sys
import unittest
from typing import Any

_REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_AGENT_DIR = os.path.join(_REPO_DIR, "agent")
_SCHEMA_DIR = os.path.join(_AGENT_DIR, "agentcore", "acp", "schema")

_HAS_PYDANTIC = importlib.util.find_spec("pydantic") is not None
_HAS_JSONSCHEMA = importlib.util.find_spec("jsonschema") is not None


def _load_schema() -> "dict[str, Any]":
    with open(os.path.join(_SCHEMA_DIR, "v2.schema.json"), "r", encoding="utf-8") as fh:
        return json.load(fh)


def _import_acp() -> "tuple[Any, Any]":
    if _AGENT_DIR not in sys.path:
        sys.path.insert(0, _AGENT_DIR)
    from agentcore.acp import models_v2, wire
    return models_v2, wire


class TestVendoredSchema(unittest.TestCase):
    """The schema is a checked-in artifact; assert its shape and provenance."""

    def test_schema_present_and_pinned(self) -> None:
        schema = _load_schema()
        self.assertIn("$defs", schema)
        # The unstable superset: we implement session/fork and mcp/*.
        for name in ("ForkSessionRequest", "McpServerAcp", "ConnectMcpRequest"):
            self.assertIn(name, schema["$defs"], "{:s} missing from vendored schema".format(name))

    def test_pin_is_recorded(self) -> None:
        if _AGENT_DIR not in sys.path:
            sys.path.insert(0, _AGENT_DIR)
        from agentcore.acp.schema import regen
        self.assertRegex(regen.PINNED_SHA, r"^[0-9a-f]{40}$")

    def test_method_table_matches_what_we_target(self) -> None:
        with open(os.path.join(_SCHEMA_DIR, "v2.meta.json"), "r", encoding="utf-8") as fh:
            meta = json.load(fh)
        self.assertEqual(meta["version"], 2)
        agent_methods = meta["agentMethods"]
        # The stable surface plus the two unstable areas the plan commits to.
        for key in ("initialize", "session_new", "session_prompt", "session_cancel",
                    "session_list", "session_delete", "session_resume", "session_close",
                    "session_set_config_option", "auth_login", "auth_logout",
                    "session_fork", "mcp_message"):
            self.assertIn(key, agent_methods)
        self.assertIn("session_update", meta["clientMethods"])
        self.assertIn("elicitation_create", meta["clientMethods"])


@unittest.skipUnless(_HAS_PYDANTIC, "pydantic not installed")
class TestGeneratedModels(unittest.TestCase):
    """The generated models and the aliases layered over them."""

    def test_wire_aliases_verify(self) -> None:
        # wire._verify() runs at import; a drifted alias raises here.
        _models, wire = _import_acp()
        self.assertTrue(callable(wire.dump))

    def test_every_session_update_variant_is_reachable(self) -> None:
        """
        Every discriminated variant in the schema should either have an alias
        or be a deliberate omission. Catches upstream ADDING a variant.
        """
        schema = _load_schema()
        variants = schema["$defs"]["SessionUpdate"].get("anyOf") or []
        found = set()
        for alt in variants:
            disc = alt.get("properties", {}).get("sessionUpdate", {})
            const = disc.get("const")
            if const:
                found.add(const)
        _models, wire = _import_acp()
        aliased = {su for _name, su, _state in wire._BINDINGS}  # pylint: disable=protected-access
        missing = found - aliased
        self.assertEqual(
            missing, set(),
            "ACP v2 added session/update variant(s) {!r}; add an alias in wire.py "
            "or record the omission".format(sorted(missing)))

    def test_dump_uses_camel_case_and_omits_none(self) -> None:
        _models, wire = _import_acp()
        chunk = wire.AgentMessageChunk(
            sessionUpdate="agent_message_chunk", messageId="m1", content=wire.text("hi"))
        payload = wire.dump(chunk)
        self.assertEqual(payload["sessionUpdate"], "agent_message_chunk")
        self.assertEqual(payload["messageId"], "m1")
        self.assertEqual(payload["content"], {"type": "text", "text": "hi"})
        # v2 gives null the meaning "clear this value", so absent != null.
        self.assertNotIn("_meta", payload)

    def test_field_name_population_is_enabled(self) -> None:
        """
        Guard a silent-data-loss trap. The models declare snake_case fields with
        camelCase aliases; without ``populate_by_name`` a snake_case kwarg is
        the name mypy expects but NOT the name pydantic honors, so it
        type-checks and then discards the value. A capability advertised that
        way would simply never reach the wire.
        """
        models, _wire = _import_acp()
        caps = models.PromptCapabilities(
            embedded_context=models.PromptEmbeddedContextCapabilities())
        self.assertEqual(
            caps.model_dump(by_alias=True, exclude_none=True), {"embeddedContext": {}},
            "snake_case construction dropped the value -- regenerate with "
            "--allow-population-by-field-name")

    def test_unknown_fields_are_rejected(self) -> None:
        models, _wire = _import_acp()
        with self.assertRaises(Exception):
            models.PromptCapabilities(definitelyNotAField=1)

    def test_idle_carries_stop_reason(self) -> None:
        """
        v2 signals turn completion as an idle state update, not a turn boundary
        -- this is what lets a worker be steered mid-run.
        """
        _models, wire = _import_acp()
        payload = wire.dump(wire.SessionIdle(
            sessionUpdate="state_update", state="idle", stopReason="cancelled"))
        self.assertEqual(payload["state"], "idle")
        self.assertEqual(payload["stopReason"], "cancelled")


@unittest.skipUnless(_HAS_PYDANTIC and _HAS_JSONSCHEMA, "pydantic/jsonschema not installed")
class TestSchemaConformance(unittest.TestCase):
    """
    Validate serialized payloads against the vendored schema itself.

    Our models round-tripping is not evidence of wire correctness: the models
    are generated FROM the schema, so a generation bug would agree with itself.
    """

    def _validate(self, defn: str, payload: "dict[str, Any]") -> None:
        import jsonschema
        schema = _load_schema()
        jsonschema.validate(
            instance=payload,
            schema={"$ref": "#/$defs/{:s}".format(defn), "$defs": schema["$defs"]})

    def test_session_update_payload_validates(self) -> None:
        _models, wire = _import_acp()
        self._validate("SessionUpdate", wire.dump(wire.AgentMessageChunk(
            sessionUpdate="agent_message_chunk", messageId="m1", content=wire.text("hi"))))

    def test_tool_call_update_validates(self) -> None:
        _models, wire = _import_acp()
        self._validate("SessionUpdate", wire.dump(wire.ToolCallUpdate(
            sessionUpdate="tool_call_update", toolCallId="c1",
            status="in_progress", title="Run script")))

    def test_initialize_response_validates(self) -> None:
        models, wire = _import_acp()
        self._validate("InitializeResponse", wire.dump(models.InitializeResponse(
            protocolVersion=2,
            info=models.Implementation(name="blender-agent", version="0.1.0"))))


if __name__ == "__main__":
    unittest.main()
