#!/usr/bin/env python3
"""
Minimal Anthropic Messages -> OpenAI Responses streaming proxy for Claude Code.

This proxy accepts Claude Code's Anthropic-style /v1/messages requests and
forwards them to an OpenAI Responses-compatible endpoint, converting streaming
response.output_text.delta events into Anthropic-style SSE events.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from typing import Any, Dict, Iterable, List, Optional, Tuple

from config_store import AppConfig, ModelConfig, load_config

DEFAULT_UPSTREAM_URL = "https://genaiapi.shanghaitech.edu.cn/api/v1/response"
DEFAULT_MODEL = "GPT-5.5"
ANTHROPIC_VERSION = "2023-06-01"
ACTIVE_CONFIG: Optional[AppConfig] = None


def now_ms() -> int:
    return int(time.time() * 1000)


def log(message: str) -> None:
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}", file=sys.stderr, flush=True)


def current_config() -> AppConfig:
    global ACTIVE_CONFIG
    if ACTIVE_CONFIG is None:
        ACTIVE_CONFIG = load_config()
    return ACTIVE_CONFIG


def read_json_body(handler: BaseHTTPRequestHandler) -> Dict[str, Any]:
    length = int(handler.headers.get("content-length", "0") or "0")
    raw = handler.rfile.read(length) if length else b"{}"
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def send_json(handler: BaseHTTPRequestHandler, status: int, payload: Dict[str, Any]) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("content-type", "application/json; charset=utf-8")
    handler.send_header("content-length", str(len(data)))
    handler.send_header("access-control-allow-origin", "*")
    handler.end_headers()
    handler.wfile.write(data)


def send_sse_headers(handler: BaseHTTPRequestHandler) -> None:
    handler.send_response(200)
    handler.send_header("content-type", "text/event-stream; charset=utf-8")
    handler.send_header("cache-control", "no-cache")
    handler.send_header("connection", "close")
    handler.send_header("x-accel-buffering", "no")
    handler.end_headers()


def write_sse(handler: BaseHTTPRequestHandler, event: str, data: Dict[str, Any]) -> None:
    payload = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"
    handler.wfile.write(payload.encode("utf-8"))
    handler.wfile.flush()


def normalize_content_part(part: Dict[str, Any]) -> Any:
    part_type = part.get("type")
    if part_type == "text":
        return {"type": "input_text", "text": part.get("text", "")}
    if part_type == "image":
        source = part.get("source") or {}
        if source.get("type") == "base64":
            media_type = source.get("media_type", "image/png")
            data = source.get("data", "")
            return {"type": "input_image", "image_url": f"data:{media_type};base64,{data}"}
        if source.get("type") == "url":
            return {"type": "input_image", "image_url": source.get("url", "")}
    return {"type": "input_text", "text": json.dumps(part, ensure_ascii=False)}


def anthropic_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return "" if content is None else str(content)

    text_parts: List[str] = []
    for part in content:
        if isinstance(part, str):
            text_parts.append(part)
            continue
        if not isinstance(part, dict):
            text_parts.append(str(part))
            continue
        part_type = part.get("type")
        if part_type == "text":
            text_parts.append(part.get("text", ""))
        elif part_type == "tool_use":
            text_parts.append(
                f"[tool_use name={part.get('name', '')} id={part.get('id', '')}] "
                f"{json.dumps(part.get('input', {}), ensure_ascii=False)}"
            )
        elif part_type == "tool_result":
            text_parts.append(f"[tool_result id={part.get('tool_use_id', '')}] {part.get('content', '')}")
        elif part_type == "image":
            text_parts.append("[image]")
        else:
            text_parts.append(json.dumps(part, ensure_ascii=False))
    return "\n".join(part for part in text_parts if part)


def json_dumps_compact(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, separators=(",", ":"))


def tool_result_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return anthropic_content_to_text(content)
    if content is None:
        return ""
    return str(content)


def anthropic_tools_to_chat_tools(tools: Any) -> List[Dict[str, Any]]:
    converted: List[Dict[str, Any]] = []
    if not isinstance(tools, list):
        return converted
    for tool in tools:
        if not isinstance(tool, dict) or not tool.get("name"):
            continue
        function: Dict[str, Any] = {
            "name": tool.get("name"),
            "description": tool.get("description", ""),
            "parameters": tool.get("input_schema") or {"type": "object", "properties": {}},
        }
        converted.append({"type": "function", "function": function})
    return converted


def anthropic_tools_to_responses_tools(tools: Any) -> List[Dict[str, Any]]:
    converted: List[Dict[str, Any]] = []
    if not isinstance(tools, list):
        return converted
    for tool in tools:
        if not isinstance(tool, dict) or not tool.get("name"):
            continue
        converted.append({
            "type": "function",
            "name": tool.get("name"),
            "description": tool.get("description", ""),
            "parameters": tool.get("input_schema") or {"type": "object", "properties": {}},
        })
    return converted


def anthropic_tool_choice_to_openai(tool_choice: Any) -> Optional[Any]:
    if not isinstance(tool_choice, dict):
        return None
    choice_type = tool_choice.get("type")
    if choice_type == "auto":
        return "auto"
    if choice_type == "any":
        return "required"
    if choice_type == "tool" and tool_choice.get("name"):
        return {"type": "function", "function": {"name": tool_choice["name"]}}
    if choice_type == "none":
        return "none"
    return None


def anthropic_tool_choice_to_responses(tool_choice: Any) -> Optional[Any]:
    if not isinstance(tool_choice, dict):
        return None
    choice_type = tool_choice.get("type")
    if choice_type in ("auto", "none", "required"):
        return choice_type
    if choice_type == "any":
        return "required"
    if choice_type == "tool" and tool_choice.get("name"):
        return {"type": "function", "name": tool_choice["name"]}
    return None


def split_anthropic_content(content: Any) -> Tuple[str, List[Dict[str, Any]], List[Dict[str, Any]]]:
    text_parts: List[str] = []
    tool_uses: List[Dict[str, Any]] = []
    tool_results: List[Dict[str, Any]] = []
    if isinstance(content, str):
        return content, tool_uses, tool_results
    if not isinstance(content, list):
        return ("" if content is None else str(content)), tool_uses, tool_results
    for part in content:
        if isinstance(part, str):
            text_parts.append(part)
            continue
        if not isinstance(part, dict):
            text_parts.append(str(part))
            continue
        part_type = part.get("type")
        if part_type == "text":
            text_parts.append(part.get("text", ""))
        elif part_type == "tool_use":
            tool_uses.append(part)
        elif part_type == "tool_result":
            tool_results.append(part)
        elif part_type == "image":
            text_parts.append("[image]")
        else:
            text_parts.append(json.dumps(part, ensure_ascii=False))
    return "\n".join(part for part in text_parts if part), tool_uses, tool_results


def anthropic_message_to_chat_messages(message: Dict[str, Any]) -> List[Dict[str, Any]]:
    role = message.get("role", "user")
    if role not in ("user", "assistant", "system"):
        role = "user"
    text, tool_uses, tool_results = split_anthropic_content(message.get("content", ""))
    if tool_results:
        messages: List[Dict[str, Any]] = []
        if text:
            messages.append({"role": "user", "content": text})
        for result in tool_results:
            messages.append({
                "role": "tool",
                "tool_call_id": result.get("tool_use_id", ""),
                "content": tool_result_content_to_text(result.get("content", "")),
            })
        return messages
    if role == "assistant" and tool_uses:
        tool_calls = []
        for index, tool_use in enumerate(tool_uses):
            tool_calls.append({
                "id": tool_use.get("id") or f"call_{index}",
                "type": "function",
                "function": {
                    "name": tool_use.get("name", ""),
                    "arguments": json_dumps_compact(tool_use.get("input", {})),
                },
            })
        return [{"role": "assistant", "content": text or None, "tool_calls": tool_calls}]
    return [{"role": role, "content": text}]


def anthropic_message_to_responses_items(message: Dict[str, Any]) -> List[Dict[str, Any]]:
    role = message.get("role", "user")
    if role not in ("user", "assistant", "system"):
        role = "user"
    text, tool_uses, tool_results = split_anthropic_content(message.get("content", ""))
    items: List[Dict[str, Any]] = []
    if text:
        items.append({"role": role, "content": text})
    for tool_use in tool_uses:
        items.append({
            "type": "function_call",
            "call_id": tool_use.get("id", ""),
            "name": tool_use.get("name", ""),
            "arguments": json_dumps_compact(tool_use.get("input", {})),
        })
    for result in tool_results:
        items.append({
            "type": "function_call_output",
            "call_id": result.get("tool_use_id", ""),
            "output": tool_result_content_to_text(result.get("content", "")),
        })
    if not items:
        items.append({"role": role, "content": ""})
    return items


def anthropic_messages_to_responses(body: Dict[str, Any], fallback_model: str, upstream_model: Optional[str] = None) -> Dict[str, Any]:
    input_items: List[Dict[str, Any]] = []
    system_texts: List[str] = []

    system = body.get("system")
    if isinstance(system, str) and system.strip():
        system_texts.append(system)
    elif isinstance(system, list):
        for item in system:
            if isinstance(item, dict) and item.get("type") == "text":
                system_texts.append(item.get("text", ""))
            elif isinstance(item, str):
                system_texts.append(item)

    for message in body.get("messages", []):
        if not isinstance(message, dict):
            continue
        input_items.extend(anthropic_message_to_responses_items(message))

    payload: Dict[str, Any] = {
        "model": upstream_model or os.getenv("UPSTREAM_MODEL") or body.get("model") or fallback_model,
        "input": input_items,
        "stream": bool(body.get("stream", True)),
    }

    if system_texts:
        payload["instructions"] = "\n\n".join(system_texts)
    if isinstance(body.get("max_tokens"), int):
        payload["max_output_tokens"] = body["max_tokens"]
    if isinstance(body.get("temperature"), (int, float)):
        payload["temperature"] = body["temperature"]
    if isinstance(body.get("top_p"), (int, float)):
        payload["top_p"] = body["top_p"]

    tools = anthropic_tools_to_responses_tools(body.get("tools"))
    if tools:
        payload["tools"] = tools
    tool_choice = anthropic_tool_choice_to_responses(body.get("tool_choice"))
    if tool_choice is not None:
        payload["tool_choice"] = tool_choice

    return payload


def anthropic_messages_to_chat_completions(body: Dict[str, Any], fallback_model: str, upstream_model: Optional[str] = None) -> Dict[str, Any]:
    messages: List[Dict[str, Any]] = []

    system = body.get("system")
    if isinstance(system, str) and system.strip():
        messages.append({"role": "system", "content": system})
    elif isinstance(system, list):
        system_text = anthropic_content_to_text(system)
        if system_text:
            messages.append({"role": "system", "content": system_text})

    for message in body.get("messages", []):
        if not isinstance(message, dict):
            continue
        messages.extend(anthropic_message_to_chat_messages(message))

    payload: Dict[str, Any] = {
        "model": upstream_model or os.getenv("UPSTREAM_MODEL") or body.get("model") or fallback_model,
        "messages": messages,
        "stream": bool(body.get("stream", True)),
    }
    if isinstance(body.get("max_tokens"), int):
        payload["max_tokens"] = body["max_tokens"]
    if isinstance(body.get("temperature"), (int, float)):
        payload["temperature"] = body["temperature"]
    if isinstance(body.get("top_p"), (int, float)):
        payload["top_p"] = body["top_p"]

    tools = anthropic_tools_to_chat_tools(body.get("tools"))
    if tools:
        payload["tools"] = tools
    tool_choice = anthropic_tool_choice_to_openai(body.get("tool_choice"))
    if tool_choice is not None:
        payload["tool_choice"] = tool_choice
    return payload


def anthropic_messages_to_upstream(body: Dict[str, Any], model_config: ModelConfig, fallback_model: str, upstream_model: Optional[str]) -> Dict[str, Any]:
    if model_config.api_format == "chat_completions":
        return anthropic_messages_to_chat_completions(body, fallback_model, upstream_model)
    return anthropic_messages_to_responses(body, fallback_model, upstream_model)


def normalize_upstream_url(upstream_url: str, api_format: str) -> str:
    url = upstream_url.strip()
    if api_format == "chat_completions" and not url.rstrip("/").endswith("/chat/completions"):
        return url.rstrip("/") + "/chat/completions"
    return url


def upstream_error_message(exc: urllib.error.HTTPError) -> str:
    error_body = exc.read().decode("utf-8", errors="replace")
    return f"Upstream HTTP {exc.code}: {error_body}"


def open_upstream(payload: Dict[str, Any], auth_token: str, upstream_url: str, timeout: int, api_format: str = "responses") -> urllib.response.addinfourl:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "content-type": "application/json",
        "accept": "text/event-stream" if payload.get("stream") else "application/json",
        "authorization": f"Bearer {auth_token}",
    }
    request = urllib.request.Request(normalize_upstream_url(upstream_url, api_format), data=data, headers=headers, method="POST")
    return urllib.request.urlopen(request, timeout=timeout)


def iter_sse_lines(response: urllib.response.addinfourl) -> Iterable[Tuple[Optional[str], str]]:
    event: Optional[str] = None
    data_lines: List[str] = []
    while True:
        raw = response.readline()
        if not raw:
            if data_lines:
                yield event, "\n".join(data_lines)
            return
        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
        if line == "":
            if data_lines:
                yield event, "\n".join(data_lines)
            event = None
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].strip())


def extract_text_delta(event: Optional[str], data: str) -> Tuple[str, Optional[Dict[str, Any]]]:
    if data == "[DONE]":
        return "done", None
    try:
        obj = json.loads(data)
    except json.JSONDecodeError:
        return "ignore", None
    event_type = obj.get("type") or event
    if event_type == "response.output_text.delta":
        return "delta", {"text": obj.get("delta", "")}
    if event_type == "response.output_text.done":
        return "text_done", {"text": obj.get("text", "")}
    if event_type in ("response.output_item.added", "response.output_item.done"):
        item = obj.get("item") if isinstance(obj.get("item"), dict) else obj
        if item.get("type") == "function_call":
            return "tool_call", {
                "id": item.get("call_id") or item.get("id") or f"toolu_proxy_{now_ms()}",
                "name": item.get("name", ""),
                "arguments": item.get("arguments", "{}"),
                "replace_arguments": event_type == "response.output_item.done",
            }
    if event_type == "response.function_call_arguments.delta":
        return "tool_call_delta", {
            "id": obj.get("call_id") or obj.get("item_id") or "",
            "name": obj.get("name", ""),
            "arguments": obj.get("delta", ""),
        }
    if event_type == "response.function_call_arguments.done":
        return "tool_call", {
            "id": obj.get("call_id") or obj.get("item_id") or f"toolu_proxy_{now_ms()}",
            "name": obj.get("name", ""),
            "arguments": obj.get("arguments", "{}"),
            "replace_arguments": True,
        }
    if event_type == "response.completed":
        response_obj = obj.get("response") if isinstance(obj.get("response"), dict) else obj
        output = response_obj.get("output") if isinstance(response_obj, dict) else None
        if isinstance(output, list):
            for item in output:
                if isinstance(item, dict) and item.get("type") == "function_call":
                    return "tool_call", {
                        "id": item.get("call_id") or item.get("id") or f"toolu_proxy_{now_ms()}",
                        "name": item.get("name", ""),
                        "arguments": item.get("arguments", "{}"),
                        "replace_arguments": True,
                    }
        return "done", obj

    choices = obj.get("choices")
    if isinstance(choices, list) and choices:
        choice = choices[0] if isinstance(choices[0], dict) else {}
        delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else {}
        message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
        text = delta.get("content") or message.get("content") or ""
        if text:
            return "delta", {"text": text}
        tool_calls = delta.get("tool_calls") or message.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            tool_call = tool_calls[0] if isinstance(tool_calls[0], dict) else {}
            function = tool_call.get("function") if isinstance(tool_call.get("function"), dict) else {}
            arguments = function.get("arguments") or ""
            return "tool_call_delta" if delta else "tool_call", {
                "id": tool_call.get("id") or "",
                "index": tool_call.get("index", 0),
                "name": function.get("name", ""),
                "arguments": arguments,
                "replace_arguments": not bool(delta),
            }
        if choice.get("finish_reason"):
            finish_reason = choice.get("finish_reason")
            return "done", {"finish_reason": finish_reason, "raw": obj}

    if event_type in ("error", "response.failed") or obj.get("error"):
        return "error", obj
    return "ignore", obj


def parse_tool_arguments(arguments: Any) -> Dict[str, Any]:
    if isinstance(arguments, dict):
        return arguments
    if not isinstance(arguments, str) or not arguments.strip():
        return {}
    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError:
        return {"arguments": arguments}
    return parsed if isinstance(parsed, dict) else {"arguments": parsed}


def stop_reason_from_done(parsed: Optional[Dict[str, Any]], tool_calls: List[Dict[str, Any]]) -> str:
    if tool_calls:
        return "tool_use"
    finish_reason = parsed.get("finish_reason") if isinstance(parsed, dict) else None
    if finish_reason == "tool_calls":
        return "tool_use"
    if finish_reason in ("length", "max_tokens"):
        return "max_tokens"
    return "end_turn"


def merge_tool_call(tool_calls: List[Dict[str, Any]], parsed: Dict[str, Any]) -> None:
    index = int(parsed.get("index", 0) or 0)
    while len(tool_calls) <= index:
        tool_calls.append({"id": "", "name": "", "arguments": ""})
    target = tool_calls[index]
    if parsed.get("id"):
        target["id"] = parsed["id"]
    if parsed.get("name"):
        target["name"] = parsed["name"]
    arguments = str(parsed.get("arguments", ""))
    if parsed.get("replace_arguments"):
        target["arguments"] = arguments
    else:
        target["arguments"] = target.get("arguments", "") + arguments


def anthropic_message_id() -> str:
    return f"msg_proxy_{now_ms()}"


class ProxyHandler(BaseHTTPRequestHandler):
    server_version = "shtu-claude-proxy/0.1"

    def route_path(self) -> str:
        return urlparse(self.path).path.rstrip("/") or "/"

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("access-control-allow-origin", "*")
        self.send_header("access-control-allow-methods", "GET,POST,OPTIONS")
        self.send_header("access-control-allow-headers", "*")
        self.end_headers()

    def do_HEAD(self) -> None:
        if self.route_path() in ("/", "/health", "/v1"):
            self.send_response(200)
            self.send_header("content-type", "application/json; charset=utf-8")
            self.end_headers()
            return
        self.send_response(404)
        self.end_headers()

    def do_GET(self) -> None:
        if self.route_path() in ("/", "/health", "/v1"):
            send_json(self, 200, {"ok": True, "service": "shtu-claude-proxy"})
            return
        send_json(self, 404, {"type": "error", "error": {"type": "not_found_error", "message": "Not found"}})

    def do_POST(self) -> None:
        route_path = self.route_path()
        if route_path in ("/v1/messages/count_tokens", "/messages/count_tokens"):
            send_json(self, 200, {"input_tokens": 0})
            return
        if route_path not in ("/v1/messages", "/messages"):
            send_json(self, 404, {"type": "error", "error": {"type": "not_found_error", "message": "Use /v1/messages"}})
            return

        try:
            body = read_json_body(self)
            stream = bool(body.get("stream", True))
            config = current_config()
            model_config = config.find_model(body.get("model"))
            upstream_url = os.getenv("UPSTREAM_RESPONSES_URL") or model_config.base_url
            fallback_model = os.getenv("UPSTREAM_MODEL") or model_config.model_id
            upstream_model = os.getenv("UPSTREAM_MODEL") or model_config.upstream_model
            auth_token = os.getenv("UPSTREAM_API_KEY") or model_config.api_key or os.getenv("ANTHROPIC_AUTH_TOKEN") or ""
            timeout = int(os.getenv("UPSTREAM_TIMEOUT", str(config.timeout)))
            if not auth_token:
                send_json(self, 500, {"type": "error", "error": {"type": "authentication_error", "message": f"No API key configured for model {model_config.model_id}"}})
                return

            upstream_payload = anthropic_messages_to_upstream(body, model_config, fallback_model, upstream_model)
            log(
                "request "
                f"model={body.get('model')} route={model_config.model_id} "
                f"upstream_model={upstream_payload.get('model')} "
                f"format={model_config.api_format} "
                f"messages={len(body.get('messages', []))} stream={stream}"
            )
            if stream:
                upstream_payload["stream"] = True
                self.handle_streaming(body, upstream_payload, auth_token, upstream_url, timeout, model_config)
            else:
                self.handle_non_streaming(body, upstream_payload, auth_token, upstream_url, timeout, model_config)
        except Exception as exc:
            log(traceback.format_exc())
            if not self.wfile.closed:
                try:
                    send_json(self, 500, {"type": "error", "error": {"type": "api_error", "message": str(exc)}})
                except Exception:
                    pass

    def handle_streaming(self, body: Dict[str, Any], upstream_payload: Dict[str, Any], auth_token: str, upstream_url: str, timeout: int, model_config: ModelConfig) -> None:
        message_id = anthropic_message_id()
        model = model_config.model_id
        send_sse_headers(self)
        write_sse(self, "message_start", {
            "type": "message_start",
            "message": {
                "id": message_id,
                "type": "message",
                "role": "assistant",
                "model": model,
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 0, "output_tokens": 0},
            },
        })

        output_text_parts: List[str] = []
        tool_calls: List[Dict[str, Any]] = []
        delta_count = 0
        text_block_started = False
        text_block_stopped = False
        done_payload: Optional[Dict[str, Any]] = None
        try:
            with open_upstream(upstream_payload, auth_token, upstream_url, timeout, model_config.api_format) as response:
                log(f"upstream connected model={model_config.model_id} format={model_config.api_format} status={getattr(response, 'status', 'unknown')}")
                for event, data in iter_sse_lines(response):
                    kind, parsed = extract_text_delta(event, data)
                    if kind == "delta":
                        text = parsed.get("text", "") if parsed else ""
                        if not text:
                            continue
                        if not text_block_started:
                            write_sse(self, "content_block_start", {
                                "type": "content_block_start",
                                "index": 0,
                                "content_block": {"type": "text", "text": ""},
                            })
                            text_block_started = True
                        output_text_parts.append(text)
                        delta_count += 1
                        write_sse(self, "content_block_delta", {
                            "type": "content_block_delta",
                            "index": 0,
                            "delta": {"type": "text_delta", "text": text},
                        })
                    elif kind in ("tool_call", "tool_call_delta") and parsed:
                        merge_tool_call(tool_calls, parsed)
                    elif kind == "error":
                        write_sse(self, "error", {
                            "type": "error",
                            "error": {"type": "api_error", "message": json.dumps(parsed, ensure_ascii=False)},
                        })
                        return
                    elif kind == "done":
                        done_payload = parsed
                        break
        except urllib.error.HTTPError as exc:
            message = upstream_error_message(exc)
            log(f"upstream http error model={model_config.model_id} status={exc.code} body={message[:500]}")
            write_sse(self, "error", {
                "type": "error",
                "error": {"type": "api_error", "message": message},
            })
            self.close_connection = True
            return
        except Exception as exc:
            log(f"upstream connection error model={model_config.model_id} format={model_config.api_format} error={exc}")
            write_sse(self, "error", {
                "type": "error",
                "error": {"type": "api_error", "message": f"Upstream connection error: {exc}"},
            })
            self.close_connection = True
            return

        output_text = "".join(output_text_parts)
        if text_block_started and not text_block_stopped:
            write_sse(self, "content_block_stop", {"type": "content_block_stop", "index": 0})
            text_block_stopped = True
        next_index = 1 if text_block_started else 0
        for offset, tool_call in enumerate(tool_calls):
            block_index = next_index + offset
            tool_id = tool_call.get("id") or f"toolu_proxy_{now_ms()}_{offset}"
            tool_name = tool_call.get("name") or "tool"
            arguments = tool_call.get("arguments", "")
            write_sse(self, "content_block_start", {
                "type": "content_block_start",
                "index": block_index,
                "content_block": {"type": "tool_use", "id": tool_id, "name": tool_name, "input": {}},
            })
            write_sse(self, "content_block_delta", {
                "type": "content_block_delta",
                "index": block_index,
                "delta": {"type": "input_json_delta", "partial_json": arguments},
            })
            write_sse(self, "content_block_stop", {"type": "content_block_stop", "index": block_index})
        stop_reason = stop_reason_from_done(done_payload, tool_calls)
        log(f"response done model={model_config.model_id} deltas={delta_count} chars={len(output_text)} tools={len(tool_calls)}")
        write_sse(self, "message_delta", {
            "type": "message_delta",
            "delta": {"stop_reason": stop_reason, "stop_sequence": None},
            "usage": {"output_tokens": max(1, len(output_text) // 4) if output_text else 0},
        })
        write_sse(self, "message_stop", {"type": "message_stop"})
        self.close_connection = True

    def handle_non_streaming(self, body: Dict[str, Any], upstream_payload: Dict[str, Any], auth_token: str, upstream_url: str, timeout: int, model_config: ModelConfig) -> None:
        upstream_payload["stream"] = True
        text_parts: List[str] = []
        tool_calls: List[Dict[str, Any]] = []
        done_payload: Optional[Dict[str, Any]] = None
        try:
            with open_upstream(upstream_payload, auth_token, upstream_url, timeout, model_config.api_format) as response:
                log(f"upstream connected model={model_config.model_id} format={model_config.api_format} status={getattr(response, 'status', 'unknown')}")
                for event, data in iter_sse_lines(response):
                    kind, parsed = extract_text_delta(event, data)
                    if kind == "delta" and parsed:
                        text_parts.append(parsed.get("text", ""))
                    elif kind in ("tool_call", "tool_call_delta") and parsed:
                        merge_tool_call(tool_calls, parsed)
                    elif kind == "error":
                        send_json(self, 502, {
                            "type": "error",
                            "error": {"type": "api_error", "message": json.dumps(parsed, ensure_ascii=False)},
                        })
                        return
                    elif kind == "done":
                        done_payload = parsed
                        break
        except urllib.error.HTTPError as exc:
            message = upstream_error_message(exc)
            log(f"upstream http error model={model_config.model_id} status={exc.code} body={message[:500]}")
            send_json(self, 502, {"type": "error", "error": {"type": "api_error", "message": message}})
            return
        except Exception as exc:
            log(f"upstream connection error model={model_config.model_id} format={model_config.api_format} error={exc}")
            send_json(self, 502, {"type": "error", "error": {"type": "api_error", "message": f"Upstream connection error: {exc}"}})
            return
        text = "".join(text_parts)
        content: List[Dict[str, Any]] = []
        if text:
            content.append({"type": "text", "text": text})
        for offset, tool_call in enumerate(tool_calls):
            content.append({
                "type": "tool_use",
                "id": tool_call.get("id") or f"toolu_proxy_{now_ms()}_{offset}",
                "name": tool_call.get("name") or "tool",
                "input": parse_tool_arguments(tool_call.get("arguments", "")),
            })
        if not content:
            content.append({"type": "text", "text": ""})
        send_json(self, 200, {
            "id": anthropic_message_id(),
            "type": "message",
            "role": "assistant",
            "model": model_config.model_id,
            "content": content,
            "stop_reason": stop_reason_from_done(done_payload, tool_calls),
            "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": max(1, len(text) // 4) if text else 0},
        })

    def log_message(self, format: str, *args: Any) -> None:
        log(f"{self.client_address[0]} {format % args}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Anthropic Messages to OpenAI Responses proxy")
    config = load_config()
    parser.add_argument("--host", default=os.getenv("HOST", config.host))
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", str(config.port))))
    args = parser.parse_args()

    global ACTIVE_CONFIG
    ACTIVE_CONFIG = config
    server = ThreadingHTTPServer((args.host, args.port), ProxyHandler)
    log(f"Listening on http://{args.host}:{args.port}")
    log(f"Configured models: {', '.join(model.model_id for model in config.models)}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("Shutting down")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

