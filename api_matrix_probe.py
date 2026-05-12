from __future__ import annotations

import json
import pathlib
import re
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, Tuple


API_NOTES = pathlib.Path(r"D:\litellm\api.txt")
LOCAL_RESPONSES_URL = "http://127.0.0.1:8082/v1/responses"


def load_tokens() -> Dict[str, str]:
    text = API_NOTES.read_text(encoding="utf-8-sig")
    tokens: Dict[str, str] = {}
    for label, model in (("GLM 5.1", "glm-chat"), ("deepv4", "deepseek-chat"), ("qwen3.5", "qwen-instruct")):
        marker = re.search(rf"{re.escape(label)}:(.*?)(?:\n\s*\n\s*\n|\Z)", text, re.S)
        section = marker.group(1) if marker else text
        match = re.search(r"Authorization:\s*Bearer\s+([A-Za-z0-9._-]+)", section)
        if match:
            tokens[model] = match.group(1)
    return tokens


def post_json(url: str, token: str, payload: Dict[str, Any], timeout: int = 120) -> Tuple[int, str]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "accept": "application/json",
            "authorization": f"Bearer {token}",
            "content-type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return int(response.status), response.read().decode("utf-8", errors="replace")


def post_sse(url: str, token: str, payload: Dict[str, Any], timeout: int = 120) -> Tuple[int, str]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "accept": "text/event-stream",
            "authorization": f"Bearer {token}",
            "content-type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return int(response.status), response.read().decode("utf-8", errors="replace")


def summarize(label: str, status: int, text: str) -> None:
    print(f"\n## {label} status={status}")
    try:
        payload = json.loads(text)
    except Exception:
        print("non_json", text[:400].replace("\n", "\\n"))
        return

    if isinstance(payload.get("error"), dict):
        error = payload["error"]
        print("error", {"type": error.get("type"), "code": error.get("code"), "message": str(error.get("message"))[:240]})
        return

    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        choice = choices[0] if isinstance(choices[0], dict) else {}
        message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
        print("choice", {"finish_reason": choice.get("finish_reason"), "message_keys": sorted(message.keys())})
        if message.get("tool_calls"):
            print("tool_calls", message.get("tool_calls"))
        else:
            print("content", str(message.get("content"))[:240])
        return

    output = payload.get("output")
    if isinstance(output, list):
        print("output_types", [item.get("type") for item in output if isinstance(item, dict)])
        for item in output:
            if isinstance(item, dict) and item.get("type") == "function_call":
                print("function_call", {"name": item.get("name"), "arguments": item.get("arguments")})
            elif isinstance(item, dict) and item.get("type") == "message":
                print("message", str(item.get("content"))[:240])
        return

    print("keys", sorted(payload.keys()))
    print(json.dumps(payload, ensure_ascii=False)[:600])


def summarize_sse(label: str, status: int, text: str) -> None:
    print(f"\n## {label} status={status}")
    events = []
    for block in text.split("\n\n"):
        event = "message"
        data_lines = []
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
        try:
            events.append((event, json.loads(data)))
        except Exception:
            events.append((event, data[:120]))
    print("events", [event for event, _ in events])
    for event, data in events:
        if event == "response.output_item.done" and isinstance(data, dict):
            item = data.get("item") if isinstance(data.get("item"), dict) else {}
            if item.get("type") == "function_call":
                print("function_call", {"name": item.get("name"), "arguments": item.get("arguments")})
        if event == "response.failed" and isinstance(data, dict):
            print("failed", data.get("response", {}).get("error"))


def run_case(label: str, url: str, token: str, payload: Dict[str, Any]) -> None:
    try:
        summarize(label, *post_json(url, token, payload))
    except urllib.error.HTTPError as exc:
        summarize(label, exc.code, exc.read().decode("utf-8", errors="replace"))
    except Exception as exc:
        print(f"\n## {label} exception={type(exc).__name__}: {exc}")


def run_sse_case(label: str, url: str, token: str, payload: Dict[str, Any]) -> None:
    try:
        summarize_sse(label, *post_sse(url, token, payload))
    except urllib.error.HTTPError as exc:
        summarize(label, exc.code, exc.read().decode("utf-8", errors="replace"))
    except Exception as exc:
        print(f"\n## {label} exception={type(exc).__name__}: {exc}")


def chat_tool(name: str = "get_current_weather") -> Dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": "获取指定城市的天气情况" if name == "get_current_weather" else "Run a command and return output",
            "parameters": {
                "type": "object",
                "properties": {
                    "location" if name == "get_current_weather" else "command": {"type": "string"},
                    "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
                },
                "required": ["location" if name == "get_current_weather" else "command"],
            },
        },
    }


def responses_tool(name: str = "get_current_weather") -> Dict[str, Any]:
    tool = chat_tool(name)["function"]
    return {"type": "function", "name": tool["name"], "description": tool["description"], "parameters": tool["parameters"]}


def main() -> int:
    tokens = load_tokens()
    missing = [model for model in ("glm-chat", "deepseek-chat", "qwen-instruct") if model not in tokens]
    if missing:
        print("missing_tokens", missing)
        return 2

    direct_urls = {
        "glm-chat": "https://genaiapi.shanghaitech.edu.cn/api/v1/start",
        "deepseek-chat": "https://genaiapi.shanghaitech.edu.cn/api/v1/start/chat/completions",
        "qwen-instruct": "https://genaiapi.shanghaitech.edu.cn/api/v1/start/chat/completions",
    }

    for model, url in direct_urls.items():
        tool_name = "get_current_weather" if model == "qwen-instruct" else "shell"
        prompt = "北京今天天气怎么样？" if tool_name == "get_current_weather" else "Use the shell tool to output exactly test output."
        direct_payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "tools": [chat_tool(tool_name)],
            "tool_choice": "auto",
            "temperature": 0,
            "stream": False,
        }
        run_case(f"direct nonstream {model}", url, tokens[model], direct_payload)

        proxy_payload = {
            "model": model,
            "input": [{"role": "user", "content": prompt}],
            "tools": [responses_tool(tool_name)],
            "tool_choice": "auto",
            "temperature": 0,
            "stream": False,
        }
        run_case(f"proxy responses nonstream {model}", LOCAL_RESPONSES_URL, "local-proxy", proxy_payload)

        stream_payload = dict(proxy_payload)
        stream_payload["stream"] = True
        run_sse_case(f"proxy responses stream {model}", LOCAL_RESPONSES_URL, "local-proxy", stream_payload)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
