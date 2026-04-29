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
    estimate_anthropic_input_tokens,
    extract_text_delta,
    filter_thinking_text_delta,
    merge_tool_call,
    parse_tool_arguments,
    stop_reason_from_done,
    tool_arguments_json,
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
    assert_true(
        any(message.get("role") == "user" and "<tool_result" in message.get("content", "") and "hello" in message.get("content", "") for message in chat_payload["messages"]),
        "chat history missing visible tool result fallback",
    )

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


def exercise_mixed_tool_result_ordering() -> None:
    body = {
        "model": "smoke-model",
        "stream": True,
        "messages": [
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "toolu_01", "name": "read_file", "input": {"path": "README.md"}}
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "toolu_01", "content": [{"type": "text", "text": "file contents"}]},
                {"type": "text", "text": "Now summarize it."},
            ]},
        ],
    }

    chat_messages = anthropic_messages_to_chat_completions(body, "fallback", "upstream")["messages"]
    assert_true(chat_messages[1]["role"] == "tool", "chat tool result should immediately follow assistant tool call")
    assert_true(chat_messages[2]["role"] == "user", "chat user text should follow tool results")
    assert_true(chat_messages[1]["content"] == "file contents", "chat tool result content mismatch")
    assert_true("file contents" in chat_messages[2]["content"], "chat visible tool result should include tool content")
    assert_true("Now summarize it." in chat_messages[2]["content"], "chat visible tool result should preserve user text")

    response_items = anthropic_messages_to_responses(body, "fallback", "upstream")["input"]
    assert_true(response_items[1]["type"] == "function_call_output", "responses tool output should immediately follow function call")
    assert_true(response_items[2]["role"] == "user", "responses user text should follow tool output")


def exercise_model_suffix_routing() -> None:
    default_model = ModelConfig(
        name="Default GLM",
        model_id="chatglm",
        base_url="https://example.invalid/v1/chat/completions",
        api_key="key",
        upstream_model="glm-chat",
        api_format="chat_completions",
    )
    haiku_model = ModelConfig(
        name="Claude Haiku Alias",
        model_id="claude-haiku-4-5",
        base_url="https://example.invalid/v1/chat/completions",
        api_key="key",
        upstream_model="minimax",
        api_format="chat_completions",
    )
    sonnet_alias = ModelConfig(
        name="Claude Sonnet Alias",
        model_id="claude-sonnet-4-6",
        base_url="https://example.invalid/v1/chat/completions",
        api_key="key",
        upstream_model="deepseek-pro",
        api_format="chat_completions",
    )
    direct_deepseek = ModelConfig(
        name="Direct DeepSeek",
        model_id="deepseek-pro",
        base_url="https://example.invalid/v1/chat/completions",
        api_key="key",
        upstream_model="deepseek-pro",
        api_format="chat_completions",
    )
    config = AppConfig(
        host="127.0.0.1",
        port=18082,
        default_model_id="chatglm",
        model_env={key: "chatglm" for key in MODEL_ENV_KEYS},
        timeout=30,
        claude_path="claude",
        claude_settings_path="/tmp/settings.json",
        models=[default_model, haiku_model, sonnet_alias, direct_deepseek],
    )

    routed = config.find_model("claude-haiku-4-5-20251001")
    assert_true(routed.model_id == "claude-haiku-4-5", "dated Claude model ID should route to configured alias")
    routed_direct = config.find_model("deepseek-pro")
    assert_true(routed_direct.model_id == "deepseek-pro", "exact model ID should beat upstream model alias matches")


def exercise_count_tokens_estimate() -> None:
    body = {
        "system": "You are Claude Code.",
        "tools": [{"name": "Bash", "input_schema": {"type": "object"}}],
        "messages": [
            {"role": "user", "content": "Run echo."},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "toolu_01", "name": "Bash", "input": {"command": "echo hello"}}
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "toolu_01", "content": "hello\n"}
            ]},
        ],
    }
    assert_true(estimate_anthropic_input_tokens(body) > 10, "count_tokens estimate should be non-zero")


def exercise_multi_tool_call_delta() -> None:
    kind, parsed = extract_text_delta(None, json.dumps({
        "choices": [{
            "delta": {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "call_01",
                        "type": "function",
                        "function": {"name": "Bash", "arguments": "{\"command\":\"pwd\"}"},
                    },
                    {
                        "index": 1,
                        "id": "call_02",
                        "type": "function",
                        "function": {"name": "LS", "arguments": "{\"path\":\".\"}"},
                    },
                ]
            }
        }]
    }))
    assert_true(kind == "tool_calls_delta" and parsed is not None, "multi tool call delta not detected")
    tool_calls = []
    for payload in parsed["tool_calls"]:
        merge_tool_call(tool_calls, payload)
    assert_true(len(tool_calls) == 2, "multi tool call delta dropped a tool")
    assert_true(tool_calls[0]["name"] == "Bash", "first tool call name mismatch")
    assert_true(tool_calls[1]["name"] == "LS", "second tool call name mismatch")


def exercise_cumulative_tool_call_delta() -> None:
    tool_calls = []
    partial = '{"description":"检查百度网络请求","prompt":"检查百度","run_in_background":true'
    full = '{"description":"检查百度网络请求","prompt":"检查百度", "run_in_background": true}'

    merge_tool_call(tool_calls, {
        "index": 0,
        "id": "call_agent",
        "name": "Agent",
        "arguments": partial,
    })
    merge_tool_call(tool_calls, {
        "index": 0,
        "arguments": full,
    })
    merge_tool_call(tool_calls, {
        "index": 0,
        "arguments": full,
    })

    repaired_agent_arguments = parse_tool_arguments(tool_calls[0]["arguments"])
    assert_true(
        repaired_agent_arguments["description"] == "检查百度网络请求"
        and repaired_agent_arguments["prompt"] == "检查百度"
        and repaired_agent_arguments["run_in_background"] is True,
        "cumulative tool-call argument snapshots should replace earlier partial snapshots",
    )


def exercise_tool_argument_repair_and_thinking_filter() -> None:
    observed_minimax_arguments = '</think>{\n  "command": "whoami"\n}'
    assert_true(
        parse_tool_arguments(observed_minimax_arguments)["command"] == "whoami",
        "tool argument parser should ignore leading thinking close tag",
    )
    assert_true(
        json.loads(tool_arguments_json(observed_minimax_arguments))["command"] == "whoami",
        "streaming tool arguments should be emitted as strict JSON",
    )
    nested_json_string_arguments = '"{\\"file_path\\": \\"/tmp/sample.txt\\", \\"old_string\\": \\"beta\\", \\"new_string\\": \\"gamma\\"}"'
    repaired_edit_arguments = parse_tool_arguments(nested_json_string_arguments)
    assert_true(
        repaired_edit_arguments["file_path"] == "/tmp/sample.txt",
        "tool argument parser should unwrap JSON strings containing objects",
    )
    assert_true(
        "arguments" not in repaired_edit_arguments,
        "repaired nested tool arguments should not keep an extra arguments wrapper",
    )
    wrapped_arguments_object = '{"arguments":"{\\"pattern\\": \\"beta\\", \\"path\\": \\"/tmp/sample.txt\\", \\"output_mode\\": \\"content\\"}"}'
    repaired_grep_arguments = parse_tool_arguments(wrapped_arguments_object)
    assert_true(
        repaired_grep_arguments["pattern"] == "beta",
        "tool argument parser should unwrap objects that only contain a JSON arguments string",
    )
    wrapped_arguments_dict = '{"arguments":{"description":"review","prompt":"inspect the diff"}}'
    repaired_agent_arguments = parse_tool_arguments(wrapped_arguments_dict)
    assert_true(
        repaired_agent_arguments["description"] == "review" and repaired_agent_arguments["prompt"] == "inspect the diff",
        "tool argument parser should unwrap objects that only contain an arguments object",
    )
    double_wrapped_arguments_object = (
        '{"arguments":"{\\"arguments\\": \\"{\\\\\\"file_path\\\\\\": '
        '\\\\\\"/tmp/sample.txt\\\\\\", \\\\\\"old_string\\\\\\": \\\\\\"beta\\\\\\", '
        '\\\\\\"new_string\\\\\\": \\\\\\"gamma\\\\\\"}\\"}"}'
    )
    repaired_double_wrapped_arguments = parse_tool_arguments(double_wrapped_arguments_object)
    assert_true(
        repaired_double_wrapped_arguments["old_string"] == "beta",
        "tool argument parser should unwrap repeated arguments wrappers",
    )

    state = {"in_thinking": False}
    assert_true(filter_thinking_text_delta("<think>The user", state) == "", "thinking prefix should be suppressed")
    assert_true(filter_thinking_text_delta(" is reasoning</think>Visible", state) == "Visible", "text after thinking block should remain")
    assert_true(filter_thinking_text_delta(" text", state) == " text", "normal text should pass through")

    dsml_state = {"in_thinking": False}
    assert_true(
        filter_thinking_text_delta("\n\n<｜DSML｜tool_calls", dsml_state) == "",
        "DSML tool-call wrapper should not leak as assistant text",
    )
    assert_true(
        filter_thinking_text_delta('\n<｜DSML｜invoke name="Grep">', dsml_state) == "",
        "DSML invoke markup should remain suppressed while the wrapper is open",
    )
    assert_true(
        filter_thinking_text_delta("</｜DSML｜tool_calls>Visible", dsml_state) == "Visible",
        "text after a DSML tool-call wrapper should remain visible",
    )

    split_dsml_state = {"in_thinking": False}
    assert_true(
        filter_thinking_text_delta("\n\n<｜DSM", split_dsml_state) == "",
        "partial DSML wrapper prefix should be buffered instead of leaked",
    )
    assert_true(
        filter_thinking_text_delta("L｜tool_calls", split_dsml_state) == "",
        "split DSML wrapper suffix should complete suppression",
    )


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
        exercise_mixed_tool_result_ordering()
        exercise_model_suffix_routing()
        exercise_count_tokens_estimate()
        exercise_multi_tool_call_delta()
        exercise_cumulative_tool_call_delta()
        exercise_tool_argument_repair_and_thinking_filter()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    print("SHTUClaudeProxy smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
