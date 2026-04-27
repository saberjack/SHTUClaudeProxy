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
        role = message.get("role", "user")
        if role not in ("user", "assistant", "system"):
            role = "user"
        content = message.get("content", "")
        # Responses-compatible endpoints vary on whether assistant messages can
        # contain typed input parts. Plain text is the safest representation for
        # multi-turn Claude Code history.
        if role == "assistant":
            input_items.append({"role": role, "content": anthropic_content_to_text(content)})
            continue
        if isinstance(content, str):
            input_items.append({"role": role, "content": content})
            continue
        if isinstance(content, list):
            converted_parts = []
            text_fallback: List[str] = []
            for part in content:
                if not isinstance(part, dict):
                    text_fallback.append(str(part))
                    continue
                part_type = part.get("type")
                if part_type == "text":
                    converted_parts.append({"type": "input_text", "text": part.get("text", "")})
                elif part_type == "tool_result":
                    text_fallback.append(f"Tool result {part.get('tool_use_id', '')}: {part.get('content', '')}")
                elif part_type == "tool_use":
                    text_fallback.append(f"Tool use {part.get('name', '')}: {json.dumps(part.get('input', {}), ensure_ascii=False)}")
                else:
                    converted_parts.append(normalize_content_part(part))
            if converted_parts and not text_fallback:
                input_items.append({"role": role, "content": converted_parts})
            else:
                text = "\n".join(text_fallback)
                if converted_parts:
                    text = "\n".join([p.get("text", "") for p in converted_parts if p.get("type") == "input_text"] + ([text] if text else []))
                input_items.append({"role": role, "content": text})

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

    # Claude Code may send tools. This minimal proxy tells the model about them
    # textually instead of translating tool-call protocols.
    tools = body.get("tools")
    if tools:
        tool_note = "Available Claude Code tools were provided, but this proxy only supports text streaming. " \
            "If you need real tool calls, extend the proxy to translate tool_use/tool_result.\n" \
            + json.dumps(tools, ensure_ascii=False)
        payload["instructions"] = (payload.get("instructions", "") + "\n\n" + tool_note).strip()

    return payload


def anthropic_messages_to_chat_completions(body: Dict[str, Any], fallback_model: str, upstream_model: Optional[str] = None) -> Dict[str, Any]:
    messages: List[Dict[str, str]] = []

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
        role = message.get("role", "user")
        if role not in ("user", "assistant", "system"):
            role = "user"
        messages.append({"role": role, "content": anthropic_content_to_text(message.get("content", ""))})

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

    tools = body.get("tools")
    if tools:
        tool_note = (
            "Available Claude Code tools were provided, but this proxy only supports text streaming for "
            "chat_completions mode. Tool schemas are included as context only.\n"
            + json.dumps(tools, ensure_ascii=False)
        )
        if messages and messages[0]["role"] == "system":
            messages[0]["content"] += "\n\n" + tool_note
        else:
            messages.insert(0, {"role": "system", "content": tool_note})
    return payload


def anthropic_messages_to_upstream(body: Dict[str, Any], model_config: ModelConfig, fallback_model: str, upstream_model: Optional[str]) -> Dict[str, Any]:
    if model_config.api_format == "chat_completions":
        return anthropic_messages_to_chat_completions(body, fallback_model, upstream_model)
    return anthropic_messages_to_responses(body, fallback_model, upstream_model)


def open_upstream(payload: Dict[str, Any], auth_token: str, upstream_url: str, timeout: int) -> urllib.response.addinfourl:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "content-type": "application/json",
        "accept": "text/event-stream" if payload.get("stream") else "application/json",
        "authorization": f"Bearer {auth_token}",
    }
    request = urllib.request.Request(upstream_url, data=data, headers=headers, method="POST")
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
    if event_type == "response.completed":
        return "done", obj

    choices = obj.get("choices")
    if isinstance(choices, list) and choices:
        choice = choices[0] if isinstance(choices[0], dict) else {}
        delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else {}
        message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
        text = delta.get("content") or message.get("content") or ""
        if text:
            return "delta", {"text": text}
        if choice.get("finish_reason"):
            return "done", obj

    if event_type in ("error", "response.failed") or obj.get("error"):
        return "error", obj
    return "ignore", obj


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
        write_sse(self, "content_block_start", {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        })

        output_text_parts: List[str] = []
        delta_count = 0
        try:
            with open_upstream(upstream_payload, auth_token, upstream_url, timeout) as response:
                log(f"upstream connected model={model_config.model_id} status={getattr(response, 'status', 'unknown')}")
                for event, data in iter_sse_lines(response):
                    kind, parsed = extract_text_delta(event, data)
                    if kind == "delta":
                        text = parsed.get("text", "") if parsed else ""
                        if not text:
                            continue
                        output_text_parts.append(text)
                        delta_count += 1
                        write_sse(self, "content_block_delta", {
                            "type": "content_block_delta",
                            "index": 0,
                            "delta": {"type": "text_delta", "text": text},
                        })
                    elif kind == "error":
                        write_sse(self, "error", {
                            "type": "error",
                            "error": {"type": "api_error", "message": json.dumps(parsed, ensure_ascii=False)},
                        })
                        return
                    elif kind == "done":
                        break
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            write_sse(self, "error", {
                "type": "error",
                "error": {"type": "api_error", "message": f"Upstream HTTP {exc.code}: {error_body}"},
            })
            return

        output_text = "".join(output_text_parts)
        log(f"response done model={model_config.model_id} deltas={delta_count} chars={len(output_text)}")
        write_sse(self, "content_block_stop", {"type": "content_block_stop", "index": 0})
        write_sse(self, "message_delta", {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": max(1, len(output_text) // 4) if output_text else 0},
        })
        write_sse(self, "message_stop", {"type": "message_stop"})
        self.close_connection = True

    def handle_non_streaming(self, body: Dict[str, Any], upstream_payload: Dict[str, Any], auth_token: str, upstream_url: str, timeout: int, model_config: ModelConfig) -> None:
        upstream_payload["stream"] = True
        text_parts: List[str] = []
        with open_upstream(upstream_payload, auth_token, upstream_url, timeout) as response:
            for event, data in iter_sse_lines(response):
                kind, parsed = extract_text_delta(event, data)
                if kind == "delta" and parsed:
                    text_parts.append(parsed.get("text", ""))
                elif kind == "done":
                    break
        text = "".join(text_parts)
        send_json(self, 200, {
            "id": anthropic_message_id(),
            "type": "message",
            "role": "assistant",
            "model": model_config.model_id,
            "content": [{"type": "text", "text": text}],
            "stop_reason": "end_turn",
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

