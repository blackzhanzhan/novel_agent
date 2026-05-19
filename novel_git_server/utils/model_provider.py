from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


DEFAULT_MODEL_PROVIDER = "deepseek"
MODEL_PROVIDER_DEEPSEEK = "deepseek"
MODEL_PROVIDER_OPENAI_COMPATIBLE = "openai_compatible"
SUPPORTED_MODEL_PROVIDERS = {MODEL_PROVIDER_DEEPSEEK, MODEL_PROVIDER_OPENAI_COMPATIBLE}

DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"
DEFAULT_OPENAI_COMPATIBLE_BASE_URL = "https://api.openai.com/v1"


@dataclass(frozen=True)
class BatchModelConfig:
    provider: str
    base_url: str
    api_key: str
    model: str
    purpose: str


def normalize_model_provider(raw_provider: str | None) -> str:
    normalized = (raw_provider or "").strip().lower().replace("-", "_")
    if normalized in {"openai", "openai_compatible", "openai_compat", "compatible"}:
        return MODEL_PROVIDER_OPENAI_COMPATIBLE
    if normalized in {"", "deepseek"}:
        return MODEL_PROVIDER_DEEPSEEK
    return normalized


def build_batch_model_config(
    *,
    env: Mapping[str, str] | None = None,
    purpose: str = "default",
) -> BatchModelConfig:
    source_env = env if env is not None else os.environ
    provider = normalize_model_provider(source_env.get("MODEL_PROVIDER"))
    if provider == MODEL_PROVIDER_DEEPSEEK and _has_openai_compatible_signal(source_env):
        provider = MODEL_PROVIDER_OPENAI_COMPATIBLE

    if provider == MODEL_PROVIDER_OPENAI_COMPATIBLE:
        model = (
            source_env.get("SUMMARY_ARCHIVE_MODEL", "").strip()
            if purpose == "summary_archive"
            else ""
        ) or _pick_env(
            source_env,
            ("OPENAI_COMPATIBLE_MODEL", "OPENAI_MODEL"),
            "",
        )
        return BatchModelConfig(
            provider=MODEL_PROVIDER_OPENAI_COMPATIBLE,
            base_url=_pick_env(
                source_env,
                ("OPENAI_COMPATIBLE_BASE_URL", "OPENAI_BASE_URL", "OPENAI_API_BASE"),
                DEFAULT_OPENAI_COMPATIBLE_BASE_URL,
            ).rstrip("/"),
            api_key=_pick_env(
                source_env,
                ("OPENAI_COMPATIBLE_API_KEY", "OPENAI_API_KEY"),
                "",
            ),
            model=model,
            purpose=purpose,
        )

    if provider != MODEL_PROVIDER_DEEPSEEK:
        raise RuntimeError(f"Unsupported MODEL_PROVIDER: {provider}")

    model = (
        source_env.get("SUMMARY_ARCHIVE_MODEL", "").strip()
        if purpose == "summary_archive"
        else ""
    ) or source_env.get("DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL).strip()
    return BatchModelConfig(
        provider=MODEL_PROVIDER_DEEPSEEK,
        base_url=source_env.get("DEEPSEEK_BASE_URL", DEFAULT_DEEPSEEK_BASE_URL).strip().rstrip("/"),
        api_key=source_env.get("DEEPSEEK_API_KEY", "").strip(),
        model=model or DEFAULT_DEEPSEEK_MODEL,
        purpose=purpose,
    )


def create_chat_model(*, max_tokens: int, purpose: str = "default"):
    config = build_batch_model_config(purpose=purpose)
    _validate_config(config)

    if config.provider == MODEL_PROVIDER_OPENAI_COMPATIBLE:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=config.model,
            api_key=config.api_key,
            base_url=config.base_url,
            max_tokens=max_tokens,
        )

    from langchain_deepseek import ChatDeepSeek

    return ChatDeepSeek(
        model=config.model,
        api_key=config.api_key,
        base_url=config.base_url,
        max_tokens=max_tokens,
    )


def _validate_config(config: BatchModelConfig) -> None:
    if not config.api_key:
        if config.provider == MODEL_PROVIDER_OPENAI_COMPATIBLE:
            raise RuntimeError("OPENAI_COMPATIBLE_API_KEY not set")
        raise RuntimeError("DEEPSEEK_API_KEY not set")
    if not config.base_url:
        if config.provider == MODEL_PROVIDER_OPENAI_COMPATIBLE:
            raise RuntimeError("OPENAI_COMPATIBLE_BASE_URL not set")
        raise RuntimeError("DEEPSEEK_BASE_URL not set")
    if not config.model:
        if config.provider == MODEL_PROVIDER_OPENAI_COMPATIBLE:
            raise RuntimeError("OPENAI_COMPATIBLE_MODEL not set")
        raise RuntimeError("DEEPSEEK_MODEL not set")


def _pick_env(env: Mapping[str, str], keys: tuple[str, ...], default: str) -> str:
    for key in keys:
        value = env.get(key, "").strip()
        if value:
            return value
    return default


def _has_openai_compatible_signal(env: Mapping[str, str]) -> bool:
    return any(
        env.get(key, "").strip()
        for key in (
            "OPENAI_COMPATIBLE_API_KEY",
            "OPENAI_COMPATIBLE_BASE_URL",
            "OPENAI_COMPATIBLE_MODEL",
        )
    )
