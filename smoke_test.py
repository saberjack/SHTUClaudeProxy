from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import cli
from config_store import AppConfig, MODEL_ENV_KEYS, ModelConfig, save_config
from platform_utils import launch_script_text, portable_claude_path, portable_settings_path
from proxy import (
    anthropic_messages_to_chat_completions,
    anthropic_messages_to_responses,
    extract_text_delta,
    merge_tool_call,
    parse_tool_arguments,
    stop_reason_from_done,
)


def make_config(tmpdir: Path) -> AppConfig:
    model = ModelConfig(
        name="Smoke Model",
        model_id="smoke-model",
        base_url="https://example.invalid/v1/responses",
        api_key="smoke-key",
        upstream_model="smoke-upstream",
        api_format="responses",
    )
    return AppConfig(
        host="127.0.0.1",
        port=18082,
        default_model_id="smoke-model",
        model_env={key: "smoke-model" for key in MODEL_ENV_KEYS},
        timeout=30,
        claude_path="claude",
        claude_settings_path=str(tmpdir / ".claude" / "settings.json"),
        models=[model],
    )


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def exercise_tool_call_translation() -> None:
    body = {
        "model": "smoke-model",
        "stream": True,
        "tool_choice": {"type": "auto"},
        "tools": [{
            "name": "read_file",
            "description": "Read a file",
            "input_schema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        }],
        "messages": [
            {"role": "user", "content": "Read README.md"},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "toolu_01", "name": "read_file", "input": {"path": "README.md"}}
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "toolu_01", "content": "hello"}
            ]},
        ],
    }

    chat_payload = anthropic_messages_to_chat_completions(body, "fallback", "upstream")
    assert_true("tools" in chat_payload, "chat payload missing tools")
    assert_true(chat_payload["tools"][0]["function"]["name"] == "read_file", "chat tool name mismatch")
    assert_true(any("tool_calls" in message for message in chat_payload["messages"]), "chat history missing tool_calls")
    assert_true(any(message.get("role") == "tool" for message in chat_payload["messages"]), "chat history missing tool result")

    responses_payload = anthropic_messages_to_responses(body, "fallback", "upstream")
    assert_true("tools" in responses_payload, "responses payload missing tools")
    assert_true(any(item.get("type") == "function_call" for item in responses_payload["input"]), "responses history missing function_call")
    assert_true(any(item.get("type") == "function_call_output" for item in responses_payload["input"]), "responses history missing function_call_output")

    kind, parsed = extract_text_delta(None, json.dumps({
        "choices": [{
            "delta": {
                "tool_calls": [{
                    "index": 0,
                    "id": "call_01",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{\"path\":"},
                }]
            }
        }]
    }))
    assert_true(kind == "tool_call_delta" and parsed is not None, "chat tool call delta not detected")
    tool_calls = []
    merge_tool_call(tool_calls, parsed)
    merge_tool_call(tool_calls, {"index": 0, "arguments": "\"README.md\"}"})
    assert_true(tool_calls[0]["id"] == "call_01", "merged tool call id mismatch")
    assert_true(parse_tool_arguments(tool_calls[0]["arguments"])["path"] == "README.md", "tool arguments parse mismatch")
    assert_true(stop_reason_from_done({"finish_reason": "tool_calls"}, tool_calls) == "tool_use", "tool stop reason mismatch")


def main() -> int:
    tmpdir = Path.cwd() / ".smoke_tmp"
    if tmpdir.exists():
        shutil.rmtree(tmpdir)
    tmpdir.mkdir(parents=True)
    try:
        config = make_config(tmpdir)
        config_path = tmpdir / "config.json"
        save_config(config, config_path)

        env = cli.claude_env(config)
        assert_true(env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:18082", "base URL env mismatch")
        assert_true(env["ANTHROPIC_MODEL"] == "smoke-model", "model env mismatch")
        assert_true(env["ANTHROPIC_AUTH_TOKEN"] == "local-proxy", "auth token env mismatch")

        settings_path = cli.write_claude_settings(config)
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        assert_true(settings["env"]["ANTHROPIC_MODEL"] == "smoke-model", "settings model mismatch")
        assert_true(settings["env"]["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:18082", "settings base URL mismatch")

        script = launch_script_text(env, "claude")
        assert_true("ANTHROPIC_BASE_URL" in script, "launch script missing base URL")
        assert_true("ANTHROPIC_MODEL" in script, "launch script missing model")
        script_path = tmpdir / ("claude-shtu.ps1" if os.name == "nt" else "claude-shtu.sh")
        script_path.write_text(script, encoding="utf-8")
        assert_true(script_path.exists(), "launch script was not created")

        assert_true(portable_claude_path("") != "", "portable claude path fallback empty")
        assert_true(portable_settings_path("").endswith(str(Path(".claude") / "settings.json")), "settings fallback mismatch")
        exercise_tool_call_translation()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    print("SHTUClaudeProxy smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
