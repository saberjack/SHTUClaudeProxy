from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict

from config_store import AppConfig, MODEL_ENV_KEYS, config_path, load_config, save_config
from platform_utils import launch_script_filename, launch_script_text
from proxy import ProxyHandler, ThreadingHTTPServer


def claude_env(config: AppConfig) -> Dict[str, str]:
    env = {
        "ANTHROPIC_BASE_URL": f"http://{config.host}:{config.port}",
        "ANTHROPIC_AUTH_TOKEN": "local-proxy",
    }
    env.update(config.model_env)
    return env


def write_claude_settings(config: AppConfig) -> Path:
    settings_path = Path(config.claude_settings_path).expanduser()
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, object] = {}
    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text(encoding="utf-8-sig"))
        except Exception:
            backup = settings_path.with_suffix(settings_path.suffix + ".bak")
            backup.write_bytes(settings_path.read_bytes())
            existing = {}
    env = existing.get("env") if isinstance(existing.get("env"), dict) else {}
    env.update(claude_env(config))
    existing["env"] = env
    existing["includeCoAuthoredBy"] = False
    settings_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    return settings_path


def install_launch_script(config: AppConfig) -> Path:
    target_dir = Path.home() / "shtu-claude-proxy"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / launch_script_filename()
    target.write_text(launch_script_text(claude_env(config), config.claude_path), encoding="utf-8")
    if os.name != "nt":
        target.chmod(0o755)
    return target


def print_env(config: AppConfig) -> None:
    for key, value in claude_env(config).items():
        if os.name == "nt":
            print(f"$env:{key} = {json.dumps(value)}")
        else:
            safe = value.replace("'", "'\\''")
            print(f"export {key}='{safe}'")


def show_config(config: AppConfig) -> None:
    print(f"Config path: {config_path()}")
    print(f"Proxy URL: http://{config.host}:{config.port}")
    print(f"Claude path: {config.claude_path}")
    print(f"Claude settings: {config.claude_settings_path}")
    print("Model routing:")
    for key in MODEL_ENV_KEYS:
        print(f"  {key}: {config.model_env.get(key, config.default_model_id)}")
    print("Models:")
    for model in config.models:
        has_key = "yes" if model.api_key else "no"
        print(f"  - {model.model_id} -> {model.upstream_model} ({model.api_format}, key={has_key})")


def serve(config: AppConfig) -> None:
    import proxy

    proxy.ACTIVE_CONFIG = config
    server = ThreadingHTTPServer((config.host, config.port), ProxyHandler)
    print(f"SHTUClaudeProxy listening on http://{config.host}:{config.port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping proxy")
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SHTUClaudeProxy command-line tools")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("show-config", help="Show resolved config and model routing")
    subparsers.add_parser("print-env", help="Print shell commands for Claude Code environment variables")
    subparsers.add_parser("write-settings", help="Write Claude Code settings.json env block")
    subparsers.add_parser("install-launch-script", help="Install claude-shtu launch script")
    subparsers.add_parser("serve", help="Run proxy server without GUI")

    args = parser.parse_args(argv)
    config = load_config()

    if args.command == "show-config":
        show_config(config)
    elif args.command == "print-env":
        print_env(config)
    elif args.command == "write-settings":
        path = write_claude_settings(config)
        print(f"Wrote Claude settings: {path}")
    elif args.command == "install-launch-script":
        path = install_launch_script(config)
        print(f"Installed launch script: {path}")
    elif args.command == "serve":
        serve(config)
    else:
        parser.error(f"Unknown command: {args.command}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
