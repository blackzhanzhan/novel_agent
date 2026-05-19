from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class DifyAgentRoute:
    agent_key: str
    routed_agent: str
    route_exact_files: frozenset[str]
    route_prefixes: tuple[str, ...]
    readable_exact_files: frozenset[str]
    readable_prefixes: tuple[str, ...]
    writable_exact_files: frozenset[str]
    base_url: str
    api_key: str
    timeout_seconds: int
    default_write_scope: str

    def matches_route_target(self, normalized_rel_path: str) -> bool:
        return (
            normalized_rel_path in self.route_exact_files
            or any(normalized_rel_path.startswith(prefix) for prefix in self.route_prefixes)
        )

    def can_read(self, normalized_rel_path: str) -> bool:
        return (
            normalized_rel_path in self.readable_exact_files
            or any(normalized_rel_path.startswith(prefix) for prefix in self.readable_prefixes)
        )

    def can_write(self, normalized_rel_path: str) -> bool:
        return normalized_rel_path in self.writable_exact_files


def _pick_env(env: dict[str, str], keys: list[str], default: str) -> str:
    for key in keys:
        value = env.get(key, "").strip()
        if value:
            return value
    return default


def _pick_timeout(env: dict[str, str], keys: list[str], default: int) -> int:
    for key in keys:
        raw_value = env.get(key, "").strip()
        if not raw_value:
            continue
        try:
            timeout = int(raw_value)
        except ValueError:
            continue
        if timeout > 0:
            return timeout
    return default


def _build_world_model_route(env: dict[str, str], default_base_url: str, default_api_key: str, default_timeout_seconds: int) -> DifyAgentRoute:
    return DifyAgentRoute(
        agent_key="world_model",
        routed_agent="world_model",
        route_exact_files=frozenset(
            {
                "world_model.md",
                "status_card.md",
                "summary.md",
                "error_archive.md",
                "domain_rules.md",
            }
        ),
        route_prefixes=("chapters/",),
        readable_exact_files=frozenset(
            {
                "world_model.md",
                "status_card.md",
                "summary.md",
                "error_archive.md",
                "domain_rules.md",
            }
        ),
        readable_prefixes=("chapters/",),
        writable_exact_files=frozenset({"world_model.md", "status_card.md", "domain_rules.md"}),
        base_url=_pick_env(env, ["DIFY_WORLD_MODEL_BASE_URL", "DIFY_WORLD_CORE_BASE_URL"], default_base_url).rstrip("/"),
        api_key=_pick_env(env, ["DIFY_WORLD_MODEL_API_KEY", "DIFY_WORLD_CORE_API_KEY"], default_api_key),
        timeout_seconds=_pick_timeout(
            env,
            ["DIFY_WORLD_MODEL_TIMEOUT_SECONDS", "DIFY_WORLD_CORE_TIMEOUT_SECONDS"],
            default_timeout_seconds,
        ),
        default_write_scope="active_file_strict",
    )


def _build_style_guide_route(env: dict[str, str], default_base_url: str, default_api_key: str, default_timeout_seconds: int) -> DifyAgentRoute:
    style_files = frozenset(
        {
            "style_guide.md",
            "style_fingerprint.md",
            "style_review.md",
            "style_constraints_for_continuation.md",
        }
    )
    return DifyAgentRoute(
        agent_key="style_guide",
        routed_agent="style_guide",
        route_exact_files=style_files,
        route_prefixes=(),
        readable_exact_files=frozenset(
            {
                "style_guide.md",
                "style_fingerprint.md",
                "style_review.md",
                "style_constraints_for_continuation.md",
                "world_model.md",
                "status_card.md",
                "summary.md",
                "error_archive.md",
                "domain_rules.md",
            }
        ),
        readable_prefixes=("chapters/",),
        writable_exact_files=style_files,
        base_url=_pick_env(env, ["DIFY_STYLE_GUIDE_BASE_URL", "DIFY_STYLE_BASE_URL"], default_base_url).rstrip("/"),
        api_key=_pick_env(env, ["DIFY_STYLE_GUIDE_API_KEY", "DIFY_STYLE_API_KEY"], default_api_key),
        timeout_seconds=_pick_timeout(
            env,
            ["DIFY_STYLE_GUIDE_TIMEOUT_SECONDS", "DIFY_STYLE_TIMEOUT_SECONDS"],
            default_timeout_seconds,
        ),
        default_write_scope="active_file_strict",
    )


def _build_outline_route(env: dict[str, str], default_base_url: str, default_api_key: str, default_timeout_seconds: int) -> DifyAgentRoute:
    outline_files = frozenset(
        {
            "brainstorm.md",
            "master_outline.md",
            "arc_outline.md",
            "chapter_outline.md",
        }
    )
    return DifyAgentRoute(
        agent_key="outline",
        routed_agent="outline",
        route_exact_files=outline_files,
        route_prefixes=(),
        readable_exact_files=outline_files,
        readable_prefixes=(),
        writable_exact_files=outline_files,
        base_url=_pick_env(env, ["DIFY_OUTLINE_BASE_URL"], default_base_url).rstrip("/"),
        api_key=_pick_env(env, ["DIFY_OUTLINE_API_KEY"], default_api_key),
        timeout_seconds=_pick_timeout(env, ["DIFY_OUTLINE_TIMEOUT_SECONDS"], default_timeout_seconds),
        default_write_scope="active_file_strict",
    )


def _build_continuation_route(env: dict[str, str], default_base_url: str, default_api_key: str, default_timeout_seconds: int) -> DifyAgentRoute:
    return DifyAgentRoute(
        agent_key="continuation_agent",
        routed_agent="continuation_agent",
        route_exact_files=frozenset({"chapter_draft.md"}),
        route_prefixes=(),
        readable_exact_files=frozenset(
            {
                "chapter_draft.md",
                "chapter_outline.md",
                "arc_outline.md",
                "master_outline.md",
                "summary.md",
                "status_card.md",
                "world_model.md",
                "style_guide.md",
                "style_constraints_for_continuation.md",
                "error_archive.md",
                "domain_rules.md",
            }
        ),
        readable_prefixes=("chapters/",),
        writable_exact_files=frozenset({"chapter_draft.md"}),
        base_url=_pick_env(env, ["DIFY_CONTINUATION_BASE_URL"], default_base_url).rstrip("/"),
        api_key=_pick_env(env, ["DIFY_CONTINUATION_API_KEY"], default_api_key),
        timeout_seconds=_pick_timeout(env, ["DIFY_CONTINUATION_TIMEOUT_SECONDS"], default_timeout_seconds),
        default_write_scope="active_file_strict",
    )


def _build_review_route(env: dict[str, str], default_base_url: str, default_api_key: str, default_timeout_seconds: int) -> DifyAgentRoute:
    return DifyAgentRoute(
        agent_key="review_agent",
        routed_agent="review_agent",
        route_exact_files=frozenset({"chapter_draft.md"}),
        route_prefixes=(),
        readable_exact_files=frozenset(
            {
                "chapter_draft.md",
                "chapter_outline.md",
                "arc_outline.md",
                "master_outline.md",
                "summary.md",
                "status_card.md",
                "world_model.md",
                "style_guide.md",
                "style_constraints_for_continuation.md",
                "error_archive.md",
                "domain_rules.md",
            }
        ),
        readable_prefixes=("chapters/",),
        writable_exact_files=frozenset({"error_archive.md"}),
        base_url=_pick_env(env, ["DIFY_REVIEW_BASE_URL"], default_base_url).rstrip("/"),
        api_key=_pick_env(env, ["DIFY_REVIEW_API_KEY"], default_api_key),
        timeout_seconds=_pick_timeout(env, ["DIFY_REVIEW_TIMEOUT_SECONDS"], default_timeout_seconds),
        default_write_scope="generic",
    )


def build_dify_agent_registry(
    *,
    default_base_url: str,
    default_api_key: str,
    default_timeout_seconds: int,
    agent_keys: Iterable[str] | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, DifyAgentRoute]:
    source_env = env or os.environ
    allowed_keys = tuple(agent_keys or ("world_model",))

    builders = {
        "world_model": _build_world_model_route,
        "style_guide": _build_style_guide_route,
        "outline": _build_outline_route,
        "continuation_agent": _build_continuation_route,
        "review_agent": _build_review_route,
    }
    registry: dict[str, DifyAgentRoute] = {}
    for agent_key in allowed_keys:
        builder = builders.get(agent_key)
        if builder is None:
            continue
        registry[agent_key] = builder(source_env, default_base_url, default_api_key, default_timeout_seconds)
    return registry
