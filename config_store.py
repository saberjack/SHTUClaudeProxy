from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from platform_utils import app_dir, default_claude_path, default_claude_settings_path, portable_claude_path, portable_settings_path

APP_NAME = "SHTUClaudeProxy"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8082
DEFAULT_RESPONSES_URL = "https://genaiapi.shanghaitech.edu.cn/api/v1/response"
DEFAULT_CHAT_COMPLETIONS_URL = "https://genaiapi.shanghaitech.edu.cn/api/v1/start"
DEFAULT_UPSTREAM_URL = DEFAULT_CHAT_COMPLETIONS_URL
DEFAULT_API_FORMAT = "chat_completions"
DEFAULT_MODEL_ID = "GPT-5.5"
MODEL_ENV_KEYS = (
    "ANTHROPIC_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_REASONING_MODEL",
)


def strip_model_date_suffix(model_id: str) -> str:
    prefix, separator, suffix = model_id.rpartition("-")
    if separator and len(suffix) == 8 and suffix.isdigit():
        return prefix
    return model_id


@dataclass
class ModelConfig:
    name: str
    model_id: str
    base_url: str
    api_key: str
    upstream_model: str
    api_format: str

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModelConfig":
        model_id = str(data.get("model_id") or data.get("id") or DEFAULT_MODEL_ID).strip()
        return cls(
            name=str(data.get("name") or model_id).strip(),
            model_id=model_id,
            base_url=str(data.get("base_url") or DEFAULT_UPSTREAM_URL).strip(),
            api_key=str(data.get("api_key") or "").strip(),
            upstream_model=str(data.get("upstream_model") or model_id).strip(),
            api_format=str(data.get("api_format") or DEFAULT_API_FORMAT).strip(),
        )

    def to_dict(self) -> Dict[str, str]:
        return {
            "name": self.name,
            "model_id": self.model_id,
            "base_url": self.base_url,
            "api_key": self.api_key,
            "upstream_model": self.upstream_model,
            "api_format": self.api_format,
        }


@dataclass
class AppConfig:
    host: str
    port: int
    default_model_id: str
    model_env: Dict[str, str]
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
            model_env={key: DEFAULT_MODEL_ID for key in MODEL_ENV_KEYS},
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
                    api_format=DEFAULT_API_FORMAT,
                )
            ],
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppConfig":
        default = cls.default()
        models = [ModelConfig.from_dict(item) for item in data.get("models", []) if isinstance(item, dict)]
        default_model_id = str(data.get("default_model_id") or (models[0].model_id if models else default.default_model_id)).strip()
        raw_model_env = data.get("model_env") if isinstance(data.get("model_env"), dict) else {}
        model_env = {
            key: str(raw_model_env.get(key) or default_model_id).strip()
            for key in MODEL_ENV_KEYS
        }
        return cls(
            host=str(data.get("host") or default.host).strip(),
            port=int(data.get("port") or default.port),
            default_model_id=default_model_id,
            model_env=model_env,
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
            "model_env": self.model_env,
            "timeout": self.timeout,
            "claude_path": self.claude_path,
            "claude_settings_path": self.claude_settings_path,
            "models": [model.to_dict() for model in self.models],
        }

    def find_model(self, requested_model: Optional[str]) -> ModelConfig:
        for candidate in (requested_model, self.default_model_id):
            if not candidate:
                continue
            candidates = [candidate]
            normalized = strip_model_date_suffix(candidate)
            if normalized != candidate:
                candidates.append(normalized)
            for model_candidate in candidates:
                for model in self.models:
                    if model_candidate in (model.model_id, model.name):
                        return model
            for model_candidate in candidates:
                for model in self.models:
                    if model_candidate == model.upstream_model:
                        return model
        return self.models[0]


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
