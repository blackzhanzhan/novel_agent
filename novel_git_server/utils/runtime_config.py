from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ENV_FILE_NAME = ".env.local"
DEFAULT_DIFY_BASE_URL = "http://localhost/v1"
DEFAULT_DIFY_TIMEOUT_SECONDS = 90
DEFAULT_MODEL_PROVIDER = "deepseek"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"
DEFAULT_OPENAI_COMPATIBLE_BASE_URL = "https://api.openai.com/v1"


@dataclass(frozen=True)
class RuntimeConfigItem:
    key: str
    group: str
    label: str
    secret: bool = False
    default: str | None = None
    aliases: tuple[str, ...] = ()


RUNTIME_CONFIG_ITEMS: tuple[RuntimeConfigItem, ...] = (
    RuntimeConfigItem(
        "DIFY_BASE_URL",
        "dify_service",
        "Dify Service API base URL",
        default=DEFAULT_DIFY_BASE_URL,
    ),
    RuntimeConfigItem(
        "DIFY_TIMEOUT_SECONDS",
        "dify_service",
        "Dify request timeout seconds",
        default=str(DEFAULT_DIFY_TIMEOUT_SECONDS),
    ),
    RuntimeConfigItem(
        "DIFY_WORLD_MODEL_API_KEY",
        "dify_agents",
        "World model Agent API key",
        secret=True,
        aliases=("DIFY_WORLD_CORE_API_KEY", "DIFY_API_KEY"),
    ),
    RuntimeConfigItem(
        "DIFY_STYLE_GUIDE_API_KEY",
        "dify_agents",
        "Style Agent API key",
        secret=True,
        aliases=("DIFY_STYLE_API_KEY", "DIFY_API_KEY"),
    ),
    RuntimeConfigItem(
        "DIFY_OUTLINE_API_KEY",
        "dify_agents",
        "Outline Agent API key",
        secret=True,
        aliases=("DIFY_API_KEY",),
    ),
    RuntimeConfigItem(
        "DIFY_CONTINUATION_API_KEY",
        "dify_agents",
        "Continuation Agent API key",
        secret=True,
        aliases=("DIFY_API_KEY",),
    ),
    RuntimeConfigItem(
        "DIFY_REVIEW_API_KEY",
        "dify_agents",
        "Review Agent API key",
        secret=True,
        aliases=("DIFY_API_KEY",),
    ),
    RuntimeConfigItem(
        "MODEL_PROVIDER",
        "model_provider",
        "Batch pipeline model provider",
        default=DEFAULT_MODEL_PROVIDER,
    ),
    RuntimeConfigItem(
        "OPENAI_COMPATIBLE_BASE_URL",
        "model_provider",
        "OpenAI-compatible base URL",
        default=DEFAULT_OPENAI_COMPATIBLE_BASE_URL,
        aliases=("OPENAI_BASE_URL", "OPENAI_API_BASE"),
    ),
    RuntimeConfigItem(
        "OPENAI_COMPATIBLE_MODEL",
        "model_provider",
        "OpenAI-compatible model",
        aliases=("OPENAI_MODEL",),
    ),
    RuntimeConfigItem(
        "OPENAI_COMPATIBLE_API_KEY",
        "model_provider",
        "OpenAI-compatible API key",
        secret=True,
        aliases=("OPENAI_API_KEY",),
    ),
    RuntimeConfigItem(
        "DEEPSEEK_BASE_URL",
        "model_provider",
        "Legacy DeepSeek base URL",
        default=DEFAULT_DEEPSEEK_BASE_URL,
    ),
    RuntimeConfigItem(
        "DEEPSEEK_MODEL",
        "model_provider",
        "Legacy DeepSeek model",
        default=DEFAULT_DEEPSEEK_MODEL,
    ),
    RuntimeConfigItem(
        "SUMMARY_ARCHIVE_MODEL",
        "model_provider",
        "Summary archive model override",
    ),
    RuntimeConfigItem(
        "DEEPSEEK_API_KEY",
        "model_provider",
        "DeepSeek-compatible API key",
        secret=True,
    ),
)

SUPPORTED_RUNTIME_CONFIG_KEYS = frozenset(item.key for item in RUNTIME_CONFIG_ITEMS)


def runtime_env_path(config_dir: str | os.PathLike[str], filename: str = ENV_FILE_NAME) -> Path:
    return Path(config_dir).resolve() / filename


def parse_env_file(config_dir: str | os.PathLike[str], filename: str = ENV_FILE_NAME) -> dict[str, str]:
    path = runtime_env_path(config_dir, filename)
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        parsed = _parse_env_assignment(raw_line)
        if parsed is None:
            continue
        key, value = parsed
        values[key] = value
    return values


def build_runtime_config_view(
    config_dir: str | os.PathLike[str],
    *,
    process_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    env = process_env if process_env is not None else os.environ
    local_values = parse_env_file(config_dir)

    items: list[dict[str, Any]] = []
    values_by_key: dict[str, dict[str, Any]] = {}
    for item in RUNTIME_CONFIG_ITEMS:
        value, source, source_key = _resolve_config_item(item, local_values=local_values, process_env=env)
        configured = bool(value.strip()) if isinstance(value, str) else False
        if item.default is not None and source == "default":
            configured = bool(value.strip())

        entry: dict[str, Any] = {
            "key": item.key,
            "group": item.group,
            "label": item.label,
            "secret": item.secret,
            "configured": configured,
            "source": source,
            "source_key": source_key,
        }
        if item.secret:
            entry["masked_value"] = mask_secret(value) if configured else ""
            entry["suffix"] = value[-4:] if configured and len(value) >= 4 else ""
        else:
            entry["value"] = value
        values_by_key[item.key] = entry
        items.append(entry)

    return {
        "env_file_exists": runtime_env_path(config_dir).exists(),
        "items": items,
        "config": values_by_key,
        "groups": _build_group_summary(items),
    }


def normalize_runtime_config_updates(raw_values: Any) -> tuple[dict[str, str], list[dict[str, str]]]:
    if not isinstance(raw_values, dict):
        return {}, [{"key": "", "message": "values must be an object"}]

    item_by_key = {item.key: item for item in RUNTIME_CONFIG_ITEMS}
    normalized: dict[str, str] = {}
    errors: list[dict[str, str]] = []

    for key, raw_value in raw_values.items():
        if key not in SUPPORTED_RUNTIME_CONFIG_KEYS:
            errors.append({"key": str(key), "message": "unsupported runtime config key"})
            continue
        item = item_by_key[key]
        if raw_value is None:
            value = ""
        elif isinstance(raw_value, (str, int, float, bool)):
            value = str(raw_value).strip()
        else:
            errors.append({"key": key, "message": "value must be a string, number, boolean, or null"})
            continue

        if "\n" in value or "\r" in value:
            errors.append({"key": key, "message": "value must be a single line"})
            continue
        if item.secret and _looks_like_masked_secret(value):
            continue
        if key == "MODEL_PROVIDER" and value:
            value = value.lower().replace("-", "_")
            if value not in {"deepseek", "openai_compatible"}:
                errors.append({"key": key, "message": "model provider must be deepseek or openai_compatible"})
                continue
        if key == "DIFY_TIMEOUT_SECONDS" and value and coerce_timeout_seconds(value, default=0) <= 0:
            errors.append({"key": key, "message": "timeout must be a positive integer"})
            continue
        if key.endswith("_BASE_URL") and value and not _looks_like_url(value):
            errors.append({"key": key, "message": "base URL must start with http:// or https://"})
            continue
        normalized[key] = value

    return normalized, errors


def write_runtime_config_file(
    config_dir: str | os.PathLike[str],
    updates: dict[str, str],
    filename: str = ENV_FILE_NAME,
) -> Path:
    config_path = runtime_env_path(config_dir, filename)
    config_path.parent.mkdir(parents=True, exist_ok=True)

    existing_lines = config_path.read_text(encoding="utf-8").splitlines() if config_path.exists() else []
    seen: set[str] = set()
    next_lines: list[str] = []

    for raw_line in existing_lines:
        parsed = _parse_env_assignment(raw_line)
        if parsed is None:
            next_lines.append(raw_line)
            continue
        key, _ = parsed
        if key not in updates:
            next_lines.append(raw_line)
            continue
        seen.add(key)
        value = updates[key].strip()
        if value:
            next_lines.append(f"{key}={_format_env_value(value)}")

    missing_keys = [key for key in updates if key not in seen and updates[key].strip()]
    if missing_keys and next_lines and next_lines[-1].strip():
        next_lines.append("")
    for key in missing_keys:
        next_lines.append(f"{key}={_format_env_value(updates[key].strip())}")

    payload = "\n".join(next_lines).rstrip() + ("\n" if next_lines else "")
    fd, tmp_name = tempfile.mkstemp(prefix=".env.local.", suffix=".tmp", dir=str(config_path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as tmp_file:
            tmp_file.write(payload)
        os.replace(tmp_name, config_path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
    return config_path


def apply_runtime_updates_to_process_env(updates: dict[str, str], *, process_env: dict[str, str] | None = None) -> None:
    env = process_env if process_env is not None else os.environ
    for key, value in updates.items():
        if value.strip():
            env[key] = value.strip()
        else:
            env.pop(key, None)


def coerce_timeout_seconds(raw_value: Any, *, default: int = DEFAULT_DIFY_TIMEOUT_SECONDS) -> int:
    try:
        timeout = int(str(raw_value).strip())
    except (TypeError, ValueError):
        return default
    return timeout if timeout > 0 else default


def mask_secret(value: str) -> str:
    normalized = (value or "").strip()
    if not normalized:
        return ""
    suffix = normalized[-4:] if len(normalized) >= 4 else normalized
    return f"****{suffix}"


def _resolve_config_item(
    item: RuntimeConfigItem,
    *,
    local_values: dict[str, str],
    process_env: dict[str, str],
) -> tuple[str, str, str]:
    for key in (item.key, *item.aliases):
        local_value = local_values.get(key, "").strip()
        if local_value:
            return local_value, "local_env", key
    for key in (item.key, *item.aliases):
        env_value = process_env.get(key, "").strip()
        if env_value:
            return env_value, "process_env", key
    if item.default is not None:
        return item.default, "default", item.key
    return "", "missing", item.key


def _build_group_summary(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for item in items:
        group_name = str(item["group"])
        group = groups.setdefault(group_name, {"group": group_name, "configured": 0, "total": 0, "missing_keys": []})
        group["total"] += 1
        if item.get("configured"):
            group["configured"] += 1
        else:
            group["missing_keys"].append(item.get("key"))
    return list(groups.values())


def _parse_env_assignment(raw_line: str) -> tuple[str, str] | None:
    line = raw_line.strip()
    if not line or line.startswith("#"):
        return None
    if line.startswith("export "):
        line = line[len("export ") :].strip()
    if "=" not in line:
        return None
    key, raw_value = line.split("=", 1)
    key = key.strip()
    if not key:
        return None
    value = raw_value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return key, value


def _format_env_value(value: str) -> str:
    if not value:
        return ""
    if any(ch.isspace() for ch in value) or "#" in value or '"' in value or "'" in value:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _looks_like_url(value: str) -> bool:
    lowered = value.lower()
    return lowered.startswith("http://") or lowered.startswith("https://")


def _looks_like_masked_secret(value: str) -> bool:
    stripped = value.strip()
    if not stripped:
        return False
    return "****" in stripped or stripped.startswith("***")
