from __future__ import annotations

import json
import os
import sys
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

APP_NAME = "SHTUClaudeProxy"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8082
DEFAULT_UPSTREAM_URL = "https://genaiapi.shanghaitech.edu.cn/api/v1/response"
DEFAULT_MODEL_ID = "GPT-5.5"


def default_claude_settings_path() -> str:
    return str(Path.home() / ".claude" / "settings.json")


def default_claude_path() -> str:
    found = shutil.which("claude.cmd") or shutil.which("claude.exe") or shutil.which("claude")
    if found:
        return found
    appdata = os.getenv("APPDATA")
    if appdata:
        return str(Path(appdata) / "npm" / "claude.cmd")
    return "claude"


def path_has_other_user_home(value: str) -> bool:
    if not value:
        return False
    normalized = value.replace("/", "\\").lower()
    current_home = str(Path.home()).replace("/", "\\").lower()
    users_root = str(Path.home().parent).replace("/", "\\").lower()
    return normalized.startswith(users_root + "\\") and not normalized.startswith(current_home + "\\")


def portable_claude_path(value: str) -> str:
    value = (value or "").strip()
    if not value or path_has_other_user_home(value):
        return default_claude_path()
    expanded = os.path.expandvars(value)
    if expanded != value:
        return expanded
    candidate = Path(value)
    if candidate.is_absolute() and not candidate.exists() and "node_modules" not in value:
        found = default_claude_path()
        return found or value
    return value


def portable_settings_path(value: str) -> str:
    value = (value or "").strip()
    if not value or path_has_other_user_home(value):
        return default_claude_settings_path()
    return os.path.expandvars(value)


@dataclass
class ModelConfig:
    name: str
    model_id: str
    base_url: str
    api_key: str
    upstream_model: str

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModelConfig":
        model_id = str(data.get("model_id") or data.get("id") or DEFAULT_MODEL_ID).strip()
        return cls(
            name=str(data.get("name") or model_id).strip(),
            model_id=model_id,
            base_url=str(data.get("base_url") or DEFAULT_UPSTREAM_URL).strip(),
            api_key=str(data.get("api_key") or "").strip(),
            upstream_model=str(data.get("upstream_model") or model_id).strip(),
        )

    def to_dict(self) -> Dict[str, str]:
        return {
            "name": self.name,
            "model_id": self.model_id,
            "base_url": self.base_url,
            "api_key": self.api_key,
            "upstream_model": self.upstream_model,
        }


@dataclass
class AppConfig:
    host: str
    port: int
    default_model_id: str
    timeout: int
    claude_path: str
    claude_settings_path: str
    models: List[ModelConfig]

    @classmethod
    def default(cls) -> "AppConfig":
        return cls(
            host=DEFAULT_HOST,
            port=DEFAULT_PORT,
            default_model_id=DEFAULT_MODEL_ID,
            timeout=300,
            claude_path=default_claude_path(),
            claude_settings_path=default_claude_settings_path(),
            models=[
                ModelConfig(
                    name="Default GPT-5.5",
                    model_id=DEFAULT_MODEL_ID,
                    base_url=DEFAULT_UPSTREAM_URL,
                    api_key="",
                    upstream_model=DEFAULT_MODEL_ID,
                )
            ],
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppConfig":
        default = cls.default()
        models = [ModelConfig.from_dict(item) for item in data.get("models", []) if isinstance(item, dict)]
        return cls(
            host=str(data.get("host") or default.host).strip(),
            port=int(data.get("port") or default.port),
            default_model_id=str(data.get("default_model_id") or (models[0].model_id if models else default.default_model_id)).strip(),
            timeout=int(data.get("timeout") or default.timeout),
            claude_path=portable_claude_path(str(data.get("claude_path") or default.claude_path)),
            claude_settings_path=portable_settings_path(str(data.get("claude_settings_path") or default.claude_settings_path)),
            models=models or default.models,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "default_model_id": self.default_model_id,
            "timeout": self.timeout,
            "claude_path": self.claude_path,
            "claude_settings_path": self.claude_settings_path,
            "models": [model.to_dict() for model in self.models],
        }

    def find_model(self, requested_model: Optional[str]) -> ModelConfig:
        candidates = [requested_model, self.default_model_id]
        for candidate in candidates:
            if not candidate:
                continue
            for model in self.models:
                if candidate in (model.model_id, model.name, model.upstream_model):
                    return model
        return self.models[0]


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        base = os.getenv("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_NAME
    return Path(__file__).resolve().parent


def config_path() -> Path:
    env_path = os.getenv("CLAUDE_RESPONSES_PROXY_CONFIG")
    if env_path:
        return Path(env_path)
    return app_dir() / "config.json"


def load_config(path: Optional[Path] = None) -> AppConfig:
    target = path or config_path()
    if not target.exists():
        config = AppConfig.default()
        save_config(config, target)
        return config
    try:
        return AppConfig.from_dict(json.loads(target.read_text(encoding="utf-8-sig")))
    except Exception:
        return AppConfig.default()


def save_config(config: AppConfig, path: Optional[Path] = None) -> None:
    target = path or config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(config.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

