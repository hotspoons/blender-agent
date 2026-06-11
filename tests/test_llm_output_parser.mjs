// SPDX-License-Identifier: GPL-3.0-or-later
//
// Unit tests for the streaming local-model output parser. Run with:
//   node --test tests/test_llm_output_parser.mjs
// (also wrapped by tests/test_agent.py::TestLlmOutputParser when node
// is on PATH).

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  LlmStreamParser,
  createParser,
  inferFamily,
  toolParamTypes,
} from "../agent/blagent/web/core/llm-output-parser.js";

const TOOLS = [{
  type: "function",
  function: {
    name: "execute_blender_code",
    parameters: {
      type: "object",
      properties: { code: { type: "string" }, timeout: { type: "integer" } },
      required: ["code"],
    },
  },
}];

/** Feed text in awkward chunk sizes to exercise marker splitting. */
function run(family, text, { tools = TOOLS, chunk = 3, opts } = {}) {
  const parser = createParser(family, tools, opts);
  let out = "";
  for (let i = 0; i < text.length; i += chunk) out += parser.push(text.slice(i, i + chunk));
  const fin = parser.finish();
  return { content: out + fin.delta, toolCalls: fin.toolCalls };
}

test("family inference", () => {
  assert.equal(inferFamily("onnx-community/Qwen3.5-4B-ONNX"), "qwen");
  assert.equal(inferFamily("onnx-community/gemma-4-E4B-it-ONNX"), "gemma");
  assert.equal(inferFamily("google/gemma-3-4b-it"), "generic");
  assert.equal(inferFamily("Hermes-3-Llama-3.1-8B-q4f16_1-MLC"), "generic");
});

test("qwen: implicit think is closed and wrapped", () => {
  const { content } = run("qwen", "I should add a cube.\n</think>\n\nAdding a cube now.<|im_end|>");
  assert.equal(content, "<think>I should add a cube.\n</think>\n\nAdding a cube now.");
});

test("qwen: empty think emits nothing", () => {
  const { content } = run("qwen", "\n</think>\n\nHello!<|im_end|>");
  assert.equal(content, "\n\nHello!");
});

test("qwen: XML tool call with string coercion", () => {
  const text = "</think>Let me run it.\n<tool_call>\n<function=execute_blender_code>\n"
    + "<parameter=code>\nimport bpy\nprint({\"x\": 1})\n</parameter>\n"
    + "<parameter=timeout>\n30\n</parameter>\n</function>\n</tool_call><|im_end|>";
  const { content, toolCalls } = run("qwen", text);
  assert.equal(content.includes("tool_call"), false);
  assert.equal(content.includes("Let me run it."), true);
  assert.equal(toolCalls.length, 1);
  assert.equal(toolCalls[0].name, "execute_blender_code");
  // String param stays verbatim even though it contains JSON-ish text.
  assert.equal(toolCalls[0].arguments.code, 'import bpy\nprint({"x": 1})');
  assert.equal(toolCalls[0].arguments.timeout, 30);
});

test("qwen: legacy hermes JSON body still parses", () => {
  const text = '</think><tool_call>\n{"name": "execute_blender_code", "arguments": {"code": "import bpy"}}\n</tool_call>';
  const { toolCalls } = run("qwen", text);
  assert.equal(toolCalls.length, 1);
  assert.equal(toolCalls[0].arguments.code, "import bpy");
});

test("qwen: unclosed tool call at eos is recovered", () => {
  const text = "</think><tool_call>\n<function=execute_blender_code>\n"
    + "<parameter=code>\nbpy.ops.mesh.primitive_cube_add()\n</parameter>\n</function>\n";
  const { toolCalls } = run("qwen", text);
  assert.equal(toolCalls.length, 1);
  assert.equal(toolCalls[0].arguments.code, "bpy.ops.mesh.primitive_cube_add()");
});

test("gemma: native call grammar with quoted strings", () => {
  const text = 'Sure.<|tool_call>call:execute_blender_code{code:<|"|>import bpy\n'
    + 'bpy.ops.object.select_all(action="SELECT")<|"|>,timeout:30}<tool_call|><turn|>';
  const { content, toolCalls } = run("gemma", text);
  assert.equal(content, "Sure.");
  assert.equal(toolCalls.length, 1);
  assert.equal(toolCalls[0].name, "execute_blender_code");
  assert.equal(toolCalls[0].arguments.code.includes('action="SELECT"'), true);
  assert.equal(toolCalls[0].arguments.timeout, 30);
});

test("gemma: nested values and booleans", () => {
  const text = '<|tool_call>call:demo{opts:{deep:<|"|>x<|"|>,n:1.5},flags:[true,false],bare:hello}<tool_call|>';
  const { toolCalls } = run("gemma", text, { tools: [] });
  assert.deepEqual(toolCalls[0].arguments, {
    opts: { deep: "x", n: 1.5 },
    flags: [true, false],
    bare: "hello",
  });
});

test("gemma: thought channel becomes think block", () => {
  const text = "<|channel>thought\nThe user wants a sphere.\n<channel|>Here you go.<turn|>";
  const { content } = run("gemma", text);
  // Whitespace before the first thinking text is dropped by the lazy
  // <think> open - the body is trimmed for display anyway.
  assert.equal(content, "<think>The user wants a sphere.\n</think>Here you go.");
});

test("generic: hermes JSON and thinking passthrough", () => {
  const text = '<thinking>plan it</thinking>Done. <tool_call>{"name": "execute_blender_code", "arguments": {"code": "x"}}</tool_call>';
  const { content, toolCalls } = run("generic", text);
  assert.equal(content, "<think>plan it</think>Done. ");
  assert.equal(toolCalls[0].name, "execute_blender_code");
});

test("generic: unparseable tool block stays visible", () => {
  const text = "<tool_call>not json at all</tool_call>";
  const { content, toolCalls } = run("generic", text);
  assert.equal(toolCalls.length, 0);
  assert.equal(content, "<tool_call>not json at all</tool_call>");
});

test("markers split across single-character pushes", () => {
  const text = "</think>ok<tool_call>\n<function=execute_blender_code>\n"
    + "<parameter=code>\na\n</parameter>\n</function>\n</tool_call>";
  const { content, toolCalls } = run("qwen", text, { chunk: 1 });
  assert.equal(content, "ok");
  assert.equal(toolCalls.length, 1);
});

test("multiple tool calls in one stream", () => {
  const text = '</think><tool_call>{"name": "a", "arguments": {}}</tool_call>'
    + 'between<tool_call>{"name": "b", "arguments": {"k": 2}}</tool_call>';
  const { content, toolCalls } = run("qwen", text, { tools: [] });
  assert.equal(content, "between");
  assert.deepEqual(toolCalls.map((c) => c.name), ["a", "b"]);
});

test("qwen on WebLLM: implicitThink off keeps content as content", () => {
  // MLC's plain qwen2 template does not pre-open <think>; the model
  // emits its own tags (or none at all).
  const { content } = run("qwen", "Just a plain answer.", { opts: { implicitThink: false } });
  assert.equal(content, "Just a plain answer.");
  const withTags = run("qwen", "<think>hm</think>ok", { opts: { implicitThink: false } });
  assert.equal(withTags.content, "<think>hm</think>ok");
});

test("inferFamily: gpt-oss maps to harmony", () => {
  assert.equal(inferFamily("onnx-community/gpt-oss-20b-ONNX"), "harmony");
});

test("harmony: analysis becomes think, final becomes content", () => {
  const text = "<|channel|>analysis<|message|>The user wants a cube.<|end|>"
    + "<|start|>assistant<|channel|>final<|message|>Here is your cube!<|return|>";
  const { content, toolCalls } = run("harmony", text);
  assert.equal(content, "<think>The user wants a cube.</think>Here is your cube!");
  assert.equal(toolCalls.length, 0);
});

test("harmony: commentary tool call with constrain json", () => {
  const text = "<|channel|>analysis<|message|>Need to run code.<|end|>"
    + "<|start|>assistant<|channel|>commentary to=functions.execute_blender_code "
    + '<|constrain|>json<|message|>{"code": "import bpy"}<|call|>';
  const { content, toolCalls } = run("harmony", text);
  assert.equal(content, "<think>Need to run code.</think>");
  assert.equal(toolCalls.length, 1);
  assert.equal(toolCalls[0].name, "execute_blender_code");
  assert.deepEqual(toolCalls[0].arguments, { code: "import bpy" });
});

test("harmony: swallowed <|call|> eos still closes the tool call", () => {
  const text = "<|channel|>commentary to=functions.demo <|constrain|>json"
    + '<|message|>{"x": 1}';
  const { toolCalls } = run("harmony", text, { tools: [] });
  assert.equal(toolCalls.length, 1);
  assert.deepEqual(toolCalls[0].arguments, { x: 1 });
});

test("harmony: commentary preamble without recipient reads as thinking", () => {
  const text = "<|channel|>commentary<|message|>Plan: two steps.<|end|>"
    + "<|start|>assistant<|channel|>final<|message|>Done.<|return|>";
  const { content } = run("harmony", text);
  assert.equal(content, "<think>Plan: two steps.</think>Done.");
});

test("harmony: markers split across tiny pushes", () => {
  const text = "<|channel|>analysis<|message|>t<|end|>"
    + "<|start|>assistant<|channel|>final<|message|>ok<|return|>";
  const { content } = run("harmony", text, { chunk: 1 });
  assert.equal(content, "<think>t</think>ok");
});

test("toolParamTypes shape", () => {
  const types = toolParamTypes(TOOLS);
  assert.equal(types.execute_blender_code.code, "string");
  assert.equal(types.execute_blender_code.timeout, "integer");
});
