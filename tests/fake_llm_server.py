# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
A scripted, content-aware, OpenAI-compatible chat-completions endpoint for
DETERMINISTIC full-stack integration tests — point the agent at it
(BLENDER_AGENT_ENDPOINT) instead of a real LLM and the entire stack
(runtime → engine → orchestrator → workers → tools → WS → UI) runs without a
model, fast and reproducibly.

It inspects each request and returns the right scripted reply for the call's
role in the orchestration:
  * draft        -> JSON {"objectives": [...]}        (also streams a reasoning trace)
  * planner      -> JSON {"tasks": [...]}
  * evaluator    -> JSON {"verdicts": [...]}  (all met -> the run completes)
  * worker turn  -> a tool call first, then a PROOF once a tool result is present
  * plain chat   -> a short answer

Streams real SSE (incl. reasoning_content + OpenAI delta tool_calls) so the
LlmChunk parser, the thinking codec, and the tool-call reassembly are all
exercised — only the *intelligence* is faked, not the transport.
"""

import json
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

MODEL = "fake/test-model"


def _sse(obj: dict[str, Any]) -> str:
    return "data: {}\n\n".format(json.dumps(obj))


def _chunk(delta: dict[str, Any], finish: str | None = None) -> dict[str, Any]:
    return {"id": "fake", "object": "chat.completion.chunk", "model": MODEL,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}


def _stream_text(reasoning: str, content: str):
    """SSE generator: a reasoning trace (reasoning_content) then content."""
    if reasoning:
        for word in reasoning.split(" "):
            yield _sse(_chunk({"reasoning_content": word + " "}))
    for word in content.split(" "):
        yield _sse(_chunk({"content": word + " "}))
    yield _sse(_chunk({}, finish="stop"))
    yield "data: [DONE]\n\n"


def _stream_tool_call(name: str, args: dict[str, Any]):
    yield _sse(_chunk({"reasoning_content": "I should call a tool. "}))
    yield _sse(_chunk({"tool_calls": [{"index": 0, "id": "call_fake_1",
                                       "type": "function",
                                       "function": {"name": name, "arguments": json.dumps(args)}}]}))
    yield _sse(_chunk({}, finish="tool_calls"))
    yield "data: [DONE]\n\n"


_DRAFT_OBJECTIVES = {
    "objectives": [
        {"text": "Clean up duplicate objects in the scene",
         "acceptance": "No objects with .001/.002 suffix remain"},
        {"text": "Assemble the robot arm with a square peg",
         "acceptance": "A Peg object bridges the upper and lower arm"},
    ]
}
_PLAN_TASKS = {
    "tasks": [{"objective_id": "obj-0", "instruction": "Delete duplicate objects"},
              {"objective_id": "obj-1", "instruction": "Create and place the square peg"}]
}
_VERDICTS = {
    "verdicts": [{"objective_id": "obj-0", "met": True, "evidence": "duplicates removed"},
                 {"objective_id": "obj-1", "met": True, "evidence": "peg present"}]
}


def _classify(messages: list[dict[str, Any]]) -> str:
    system = ""
    for m in messages:
        if m.get("role") == "system":
            system = str(m.get("content", "")).lower()
            break
    has_tool_result = any(m.get("role") == "tool" for m in messages)
    # Specific orchestration roles first (they also mention objectives/acceptance).
    if "planning half" in system:
        return "planner"
    if "independent" in system and "audit" in system:
        return "auditor"
    if "evaluator" in system:
        return "evaluator"
    # Dedicated per-worker QA reviewer (also mentions blender/acceptance, so it
    # must be classified before the worker/draft branches).
    if "qa reviewer" in system:
        return "qa"
    # The draft/intake prompt: turns a goal into OBJECTIVES with ACCEPTANCE.
    if "objectives" in system and "acceptance" in system:
        return "draft"
    # A worker turn: the Blender working instructions / autonomous-worker mission.
    if "autonomous worker" in system or "blender" in system:
        return "worker_proof" if has_tool_result else "worker_tool"
    return "chat"


async def completions(request: Request) -> StreamingResponse:
    body = await request.json()
    kind = _classify(body.get("messages", []))
    if kind == "draft":
        gen = _stream_text("Let me break the goal into objectives.", json.dumps(_DRAFT_OBJECTIVES))
    elif kind == "planner":
        gen = _stream_text("Decomposing the unmet objectives into worker tasks.",
                           json.dumps(_PLAN_TASKS))
    elif kind == "evaluator":
        gen = _stream_text("Checking the scene state.", json.dumps(_VERDICTS))
    elif kind == "auditor":
        gen = _stream_text("", json.dumps({"verdicts": _VERDICTS["verdicts"], "summary": "verified"}))
    elif kind == "qa":
        gen = _stream_text("Reviewing the worker's proof against the scene.",
                           json.dumps({"passed": True, "note": "Work matches the acceptance criteria."}))
    elif kind == "worker_tool":
        gen = _stream_tool_call("get_objects_summary", {})
    elif kind == "worker_proof":
        gen = _stream_text("The scene looks right.",
                           "PROOF OF WORK: inspected the scene via get_objects_summary; "
                           "the task is complete.")
    else:
        gen = _stream_text("", "Hello from the fake LLM.")
    return StreamingResponse(gen, media_type="text/event-stream")


async def models(_request: Request) -> JSONResponse:
    return JSONResponse({"object": "list", "data": [{"id": MODEL, "object": "model"}]})


def make_app() -> Starlette:
    return Starlette(routes=[
        Route("/v1/chat/completions", completions, methods=["POST"]),
        Route("/v1/models", models),
    ])


if __name__ == "__main__":
    import sys
    import uvicorn
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8900
    uvicorn.run(make_app(), host="127.0.0.1", port=port, log_level="warning")
