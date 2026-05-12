from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, List, Tuple


LOCAL_RESPONSES_URL = "http://127.0.0.1:8082/v1/responses"
MODELS = ("glm-chat", "deepseek-chat", "qwen-instruct")


def post_json(payload: Dict[str, Any], timeout: int = 180) -> Dict[str, Any]:
    request = urllib.request.Request(
        LOCAL_RESPONSES_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"accept": "application/json", "authorization": "Bearer local-proxy", "content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        text = response.read().decode("utf-8", errors="replace")
    return json.loads(text)


def post_sse(payload: Dict[str, Any], timeout: int = 180) -> List[Tuple[str, Any]]:
    request = urllib.request.Request(
        LOCAL_RESPONSES_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"accept": "text/event-stream", "authorization": "Bearer local-proxy", "content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        text = response.read().decode("utf-8", errors="replace")
    events: List[Tuple[str, Any]] = []
    for block in text.split("\n\n"):
        event = "message"
        data_lines: List[str] = []
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].strip())
        if not data_lines:
            continue
        data = "\n".join(data_lines)
        if data == "[DONE]":
            events.append(("[DONE]", None))
            continue
        events.append((event, json.loads(data)))
    return events


def tool(name: str, description: str, properties: Dict[str, Any], required: List[str]) -> Dict[str, Any]:
    return {"type": "function", "name": name, "description": description, "parameters": {"type": "object", "properties": properties, "required": required}}


TOOLS = [
    tool("read_file", "Read a local file and return its text", {"path": {"type": "string"}}, ["path"]),
    tool("list_dir", "List files in a local directory", {"path": {"type": "string"}}, ["path"]),
    tool("web_search", "Search the web", {"query": {"type": "string"}}, ["query"]),
]


def outputs(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    output = payload.get("output")
    return output if isinstance(output, list) else []


def function_calls(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [item for item in outputs(payload) if isinstance(item, dict) and item.get("type") == "function_call"]


def output_text(payload: Dict[str, Any]) -> str:
    parts: List[str] = []
    for item in outputs(payload):
        if isinstance(item, dict) and item.get("type") == "message":
            for part in item.get("content", []):
                if isinstance(part, dict) and part.get("type") == "output_text":
                    parts.append(str(part.get("text") or ""))
    return "".join(parts)


def assert_ok(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run_plain_chat(model: str) -> None:
    payload = post_json({"model": model, "stream": False, "input": [{"role": "user", "content": "Reply with one short sentence saying you are ready."}], "temperature": 0})
    assert_ok(not payload.get("error"), f"{model} plain chat returned error: {payload.get('error')}")
    assert_ok(bool(output_text(payload).strip()), f"{model} plain chat returned no text")


def run_single_tool(model: str) -> Dict[str, Any]:
    payload = post_json({
        "model": model,
        "stream": False,
        "input": [{"role": "user", "content": "Use the read_file tool to read exactly D:/litellm/eval_cases.json. Do not answer from memory."}],
        "tools": TOOLS,
        "tool_choice": "auto",
        "temperature": 0,
    })
    calls = function_calls(payload)
    assert_ok(calls, f"{model} single-tool scenario returned no function_call: {payload}")
    assert_ok(any(call.get("name") == "read_file" for call in calls), f"{model} did not choose read_file: {calls}")
    return calls[0]


def run_implicit_tool_need(model: str) -> None:
    payload = post_json({
        "model": model,
        "stream": False,
        "input": [{"role": "user", "content": "D:/litellm/eval_cases.json 这个文件里面说了啥？"}],
        "tools": TOOLS,
        "tool_choice": "auto",
        "temperature": 0,
    })
    calls = function_calls(payload)
    assert_ok(calls, f"{model} implicit file question did not trigger a tool call: {payload}")
    assert_ok(any(call.get("name") == "read_file" for call in calls), f"{model} implicit file question did not choose read_file: {calls}")


def run_tool_result_followup(model: str, call: Dict[str, Any]) -> None:
    call_id = call.get("call_id") or call.get("id") or "call_probe"
    payload = post_json({
        "model": model,
        "stream": False,
        "input": [
            {"role": "user", "content": "Use the read_file tool to read exactly D:/litellm/eval_cases.json. Do not answer from memory."},
            {"type": "function_call", "call_id": call_id, "name": call.get("name") or "read_file", "arguments": call.get("arguments") or '{"path":"D:/litellm/eval_cases.json"}'},
            {"type": "function_call_output", "call_id": call_id, "output": "[{\"case\":\"tool-followup\",\"expected\":\"multi-round context survived\"}]"},
            {"role": "user", "content": "Summarize the tool output in Chinese in one sentence and mention the expected value."},
        ],
        "tools": TOOLS,
        "temperature": 0,
        "stream": False,
    })
    text = output_text(payload)
    assert_ok(text.strip(), f"{model} follow-up returned no text: {payload}")
    assert_ok("multi-round" in text or "多轮" in text or "上下文" in text, f"{model} follow-up did not use tool output: {text}")


def run_multi_tool(model: str) -> None:
    payload = post_json({
        "model": model,
        "stream": False,
        "input": [{"role": "user", "content": "Use tools only. Call read_file for D:/litellm/eval_cases.json and call list_dir for D:/litellm. Return both tool calls if possible."}],
        "tools": TOOLS,
        "tool_choice": "auto",
        "temperature": 0,
    })
    calls = function_calls(payload)
    names = {call.get("name") for call in calls}
    assert_ok(calls, f"{model} multi-tool scenario returned no function_call: {payload}")
    assert_ok(names & {"read_file", "list_dir"}, f"{model} multi-tool scenario chose unexpected tools: {calls}")


def run_tool_switch_followup(model: str) -> None:
    first = post_json({
        "model": model,
        "stream": False,
        "input": [{"role": "user", "content": "D:/litellm/eval_cases.json 这个文件里面说了啥？"}],
        "tools": TOOLS,
        "tool_choice": "auto",
        "temperature": 0,
    })
    first_calls = function_calls(first)
    assert_ok(first_calls, f"{model} switch first turn returned no tool call")
    first_call = first_calls[0]
    second = post_json({
        "model": model,
        "stream": False,
        "input": [
            {"role": "user", "content": "D:/litellm/eval_cases.json 这个文件里面说了啥？"},
            {"type": "function_call", "call_id": first_call.get("call_id") or first_call.get("id"), "name": first_call.get("name"), "arguments": first_call.get("arguments")},
            {"type": "function_call_output", "call_id": first_call.get("call_id") or first_call.get("id"), "output": "[{\"id\":\"case_a\",\"expect\":\"multi-turn context works\"}]"},
            {"role": "user", "content": "现在切换工具，列出 D:/litellm 目录。"},
        ],
        "tools": TOOLS,
        "tool_choice": "auto",
        "temperature": 0,
    })
    second_calls = function_calls(second)
    assert_ok(second_calls, f"{model} switch second turn returned no tool call: {second}")
    assert_ok(any(call.get("name") == "list_dir" for call in second_calls), f"{model} did not switch to list_dir: {second_calls}")
    second_call = next(call for call in second_calls if call.get("name") == "list_dir")
    final = post_json({
        "model": model,
        "stream": False,
        "input": [
            {"role": "user", "content": "D:/litellm/eval_cases.json 这个文件里面说了啥？"},
            {"type": "function_call", "call_id": first_call.get("call_id") or first_call.get("id"), "name": first_call.get("name"), "arguments": first_call.get("arguments")},
            {"type": "function_call_output", "call_id": first_call.get("call_id") or first_call.get("id"), "output": "[{\"id\":\"case_a\",\"expect\":\"multi-turn context works\"}]"},
            {"role": "user", "content": "现在切换工具，列出 D:/litellm 目录。"},
            {"type": "function_call", "call_id": second_call.get("call_id") or second_call.get("id"), "name": second_call.get("name"), "arguments": second_call.get("arguments")},
            {"type": "function_call_output", "call_id": second_call.get("call_id") or second_call.get("id"), "output": "api.txt\neval_cases.json"},
            {"role": "user", "content": "不要再调用工具，用一句中文总结两次工具结果。"},
        ],
        "tools": TOOLS,
        "temperature": 0,
        "stream": False,
    })
    text = output_text(final)
    assert_ok(text.strip(), f"{model} switch final answer empty: {final}")
    assert_ok("eval_cases" in text or "multi-turn" in text or "多轮" in text, f"{model} switch final answer missed context: {text}")


def run_stream_tool(model: str) -> None:
    events = post_sse({
        "model": model,
        "stream": True,
        "input": [{"role": "user", "content": "Use the web_search tool for query ShanghaiTech library. Do not answer directly."}],
        "tools": TOOLS,
        "tool_choice": "auto",
        "temperature": 0,
    })
    event_names = [event for event, _ in events]
    assert_ok("response.completed" in event_names, f"{model} stream missing response.completed: {event_names}")
    assert_ok("response.output_item.done" in event_names, f"{model} stream missing output item: {event_names}")
    calls = []
    for event, data in events:
        if event == "response.output_item.done" and isinstance(data, dict):
            item = data.get("item") if isinstance(data.get("item"), dict) else {}
            if item.get("type") == "function_call":
                calls.append(item)
    assert_ok(any(call.get("name") == "web_search" for call in calls), f"{model} stream did not produce web_search function_call: {calls}")


def run_model(model: str) -> None:
    print(f"## {model}")
    run_plain_chat(model)
    print("plain_chat ok")
    run_implicit_tool_need(model)
    print("implicit_tool_need ok")
    call = run_single_tool(model)
    print("single_tool ok", {"name": call.get("name"), "arguments": call.get("arguments")})
    run_tool_result_followup(model, call)
    print("tool_result_followup ok")
    run_multi_tool(model)
    print("multi_tool ok")
    run_tool_switch_followup(model)
    print("tool_switch_followup ok")
    run_stream_tool(model)
    print("stream_tool ok")


def main() -> int:
    failures: List[str] = []
    for model in MODELS:
        try:
            run_model(model)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:1000]
            failures.append(f"{model}: HTTPError {exc.code}: {body}")
            print("FAILED", failures[-1])
        except (AssertionError, urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            failures.append(f"{model}: {type(exc).__name__}: {exc}")
            print("FAILED", failures[-1])
    if failures:
        print("\nFailures:")
        for failure in failures:
            print("-", failure)
        return 1
    print("\nDeep API probe passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
