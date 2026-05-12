from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, List


LOCAL_MESSAGES_URL = "http://127.0.0.1:8082/v1/messages"
MODELS = ("glm-chat", "deepseek-chat", "qwen-instruct")


TOOLS: List[Dict[str, Any]] = [
    {
        "name": "Bash",
        "description": "Run a shell command",
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    },
    {
        "name": "Read",
        "description": "Read a local file",
        "input_schema": {
            "type": "object",
            "properties": {"file_path": {"type": "string"}},
            "required": ["file_path"],
        },
    },
]


def post_message(payload: Dict[str, Any], timeout: int = 180) -> Dict[str, Any]:
    request = urllib.request.Request(
        LOCAL_MESSAGES_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"content-type": "application/json", "x-api-key": "local-proxy", "anthropic-version": "2023-06-01"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def tool_uses(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    content = payload.get("content")
    if not isinstance(content, list):
        return []
    return [item for item in content if isinstance(item, dict) and item.get("type") == "tool_use"]


def texts(payload: Dict[str, Any]) -> str:
    content = payload.get("content")
    if not isinstance(content, list):
        return ""
    return "\n".join(str(item.get("text") or "") for item in content if isinstance(item, dict) and item.get("type") == "text")


def assert_ok(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run_model(model: str) -> None:
    first_payload = post_message({
        "model": model,
        "max_tokens": 2048,
        "stream": False,
        "tools": TOOLS,
        "tool_choice": {"type": "auto"},
        "messages": [{"role": "user", "content": "D:/litellm/eval_cases.json 这个文件里面说了啥？"}],
    })
    uses = tool_uses(first_payload)
    text = texts(first_payload)
    print(f"## {model}")
    print("first_stop_reason", first_payload.get("stop_reason"))
    print("tool_uses", [{"name": item.get("name"), "input": item.get("input")} for item in uses])
    if text:
        print("text", text[:500].replace("\n", "\\n"))
    assert_ok(uses, f"{model} returned no Anthropic tool_use; text={text[:500]}")
    assert_ok(first_payload.get("stop_reason") == "tool_use", f"{model} stop_reason should be tool_use")

    first_tool = uses[0]
    follow_payload = post_message({
        "model": model,
        "max_tokens": 2048,
        "stream": False,
        "tools": TOOLS,
        "tool_choice": {"type": "auto"},
        "messages": [
            {"role": "user", "content": "D:/litellm/eval_cases.json 这个文件里面说了啥？"},
            {"role": "assistant", "content": [first_tool]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": first_tool.get("id"), "content": "[{\"id\":\"case_a\",\"expect\":\"multi-turn context works\"}]"}]},
            {"role": "user", "content": "先总结刚才工具结果；然后切换工具，用 Bash 列出 D:/litellm 目录。"},
        ],
    })
    follow_uses = tool_uses(follow_payload)
    follow_text = texts(follow_payload)
    print("follow_stop_reason", follow_payload.get("stop_reason"))
    print("follow_tool_uses", [{"name": item.get("name"), "input": item.get("input")} for item in follow_uses])
    assert_ok(follow_uses, f"{model} follow-up did not request a second tool; text={follow_text[:500]}")
    assert_ok(any(item.get("name") == "Bash" for item in follow_uses), f"{model} follow-up did not switch to Bash: {follow_uses}")

    bash_tool = next(item for item in follow_uses if item.get("name") == "Bash")
    final_payload = post_message({
        "model": model,
        "max_tokens": 2048,
        "stream": False,
        "tools": TOOLS,
        "tool_choice": {"type": "auto"},
        "messages": [
            {"role": "user", "content": "D:/litellm/eval_cases.json 这个文件里面说了啥？"},
            {"role": "assistant", "content": [first_tool]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": first_tool.get("id"), "content": "[{\"id\":\"case_a\",\"expect\":\"multi-turn context works\"}]"}]},
            {"role": "user", "content": "先总结刚才工具结果；然后切换工具，用 Bash 列出 D:/litellm 目录。"},
            {"role": "assistant", "content": [bash_tool]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": bash_tool.get("id"), "content": "api.txt\neval_cases.json"}]},
            {"role": "user", "content": "现在不要再调用工具，综合两次工具结果用一句中文回答。"},
        ],
    })
    final_text = texts(final_payload)
    print("final_stop_reason", final_payload.get("stop_reason"))
    assert_ok(final_text.strip(), f"{model} final answer was empty")
    assert_ok("eval_cases" in final_text or "multi-turn" in final_text or "多轮" in final_text, f"{model} final answer did not use multi-turn context: {final_text[:500]}")


def main() -> int:
    failures: List[str] = []
    for model in MODELS:
        try:
            run_model(model)
        except (AssertionError, urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            failures.append(f"{model}: {type(exc).__name__}: {exc}")
            print("FAILED", failures[-1])
    if failures:
        print("\nFailures:")
        for failure in failures:
            print("-", failure)
        return 1
    print("\nClaude Messages path probe passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
