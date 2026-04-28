from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import cli
from config_store import AppConfig, MODEL_ENV_KEYS, ModelConfig, save_config
from platform_utils import launch_script_text, portable_claude_path, portable_settings_path


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
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    print("SHTUClaudeProxy smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
