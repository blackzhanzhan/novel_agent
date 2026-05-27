"""Dify query construction and intent detection for world deduce routes."""

import re
from typing import Any

from agents.archive import _normalize_file_name
from utils.book_storage import DEFAULT_WORLD_MODEL
from utils.dify_registry import DifyAgentRoute

SYNC_ALL_ALLOWED_OPS = {"update", "append", "prepend"}
SYNC_ALL_WRITE_SCOPES = {"generic", "world_core", "active_file_strict"}
DEFAULT_SYNC_ALL_WRITE_SCOPE = "generic"
STRICT_ACTIVE_FILE_SCOPE = "active_file_strict"
WORLD_CORE_WRITE_SCOPE = "world_core"
DEDUCE_FILE_TYPES = {"world_core", "summary", "outline", "style", "chapter", "error_archive"}


def _normalize_text(raw: Any) -> str:
    if isinstance(raw, str):
        return raw
    if raw is None:
        return ""
    return str(raw)


def _normalize_world_model_template_text(markdown: str) -> str:
    return "\n".join(line.strip() for line in markdown.splitlines() if line.strip())


def _world_model_template_has_substance(markdown: str) -> bool:
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("#", ">")):
            continue
        if re.fullmatch(r"[-*]\s*[^:：]+[:：]\s*", stripped):
            continue
        return True
    return False


def _looks_like_init_intent(intent: Any) -> bool:
    if not isinstance(intent, str):
        return False
    lowered = intent.strip().lower()
    if not lowered:
        return False
    hints = (
        "初始化",
        "init",
        "bootstrap",
        "双写",
        "双核心",
        "双底座",
    )
    return any(h in lowered for h in hints)


WORLD_MODEL_BOOTSTRAP_QUERY_PREFIX = (
    "【世界模型初始化任务】\n"
    "当前 active_file=world_model.md，且文件仍处于模板/初始化状态。\n"
    "请把这次回复写成可直接沉淀进 world_model.md 的创作约束引擎初版，而不是普通事实档案。\n"
    "必须围绕读者承诺与主轴、冲突发动机、硬约束、软假设、未回收承诺、矛盾与风险、下游工作流接口组织内容。\n"
    "若证据不足，请明确标成待确认或软假设，不要伪造确定性。\n"
    "用户原始意图："
)


def _should_bootstrap_world_model_query(active_file: Any, markdown: Any) -> bool:
    normalized_active_file = ""
    if isinstance(active_file, str) and active_file.strip():
        try:
            normalized_active_file = _normalize_file_name(active_file)
        except Exception:
            normalized_active_file = active_file.strip()
    if normalized_active_file != "world_model.md":
        return False

    content = _normalize_text(markdown)
    if not content.strip():
        return True
    if _normalize_world_model_template_text(content) == _normalize_world_model_template_text(DEFAULT_WORLD_MODEL):
        return True
    return not _world_model_template_has_substance(content)


def _build_dify_query(markdown: str, payload: dict[str, Any] | None = None) -> str:
    query = _normalize_text(markdown)
    if isinstance(payload, dict):
        raw_intent = payload.get("intent")
        # Rewrite landing-button intents so Dify question-classifier
        # routes to COMMIT_AGENT instead of DISCUSS_AGENT.
        if isinstance(raw_intent, str) and raw_intent.strip():
            if re.search(r"(大纲落档按钮请求|目标文件[：:]\s*\S+\.md)", raw_intent):
                _m = re.search(r"目标文件[：:]\s*(\S+\.md)", raw_intent)
                _target = _m.group(1) if _m else payload.get("active_file", "master_outline.md")
                raw_intent = (
                    f"请立即为 {_target} 生成大纲草稿并写入。"
                    "这是写入/归档/保存请求，不是讨论。"
                    "请调用 draft_replace_markdown_section 工具完成写入。"
                )
        if isinstance(raw_intent, str) and raw_intent.strip():
            query = raw_intent.strip()
        if _should_bootstrap_world_model_query(payload.get("active_file"), markdown):
            if query.strip():
                return f"{WORLD_MODEL_BOOTSTRAP_QUERY_PREFIX}\n{query.strip()}"
            return WORLD_MODEL_BOOTSTRAP_QUERY_PREFIX
    return query


def _resolve_deduce_write_scope(raw_scope: Any, intent: Any, route: DifyAgentRoute) -> tuple[str | None, str | None]:
    if isinstance(raw_scope, str) and raw_scope.strip():
        normalized = raw_scope.strip()
        if normalized not in SYNC_ALL_WRITE_SCOPES:
            return None, f"write_scope must be one of {sorted(SYNC_ALL_WRITE_SCOPES)}"
        if normalized == "generic":
            return None, "write_scope=generic is not allowed for world deduce route"
        if (
            normalized == STRICT_ACTIVE_FILE_SCOPE
            and route.agent_key == "world_model"
            and _looks_like_init_intent(intent)
        ):
            return WORLD_CORE_WRITE_SCOPE, None
        return normalized, None

    if raw_scope is not None:
        return None, "write_scope must be a non-empty string when provided"

    if route.agent_key == "world_model" and _looks_like_init_intent(intent):
        return WORLD_CORE_WRITE_SCOPE, None
    return route.default_write_scope, None


def _infer_file_type_from_path(normalized_rel_path: str) -> str | None:
    if normalized_rel_path in {"world_model.md", "status_card.md"}:
        return "world_core"
    if normalized_rel_path == "summary.md":
        return "summary"
    if normalized_rel_path in {"brainstorm.md", "master_outline.md", "arc_outline.md", "chapter_outline.md"}:
        return "outline"
    if normalized_rel_path in {
        "style_guide.md",
        "style_fingerprint.md",
        "style_review.md",
        "style_constraints_for_continuation.md",
    }:
        return "style"
    if normalized_rel_path == "error_archive.md":
        return "error_archive"
    if normalized_rel_path == "domain_rules.md":
        return "domain_rules"
    if normalized_rel_path == "chapter_draft.md":
        return "chapter"
    if normalized_rel_path.startswith("chapters/") and normalized_rel_path.lower().endswith(".md"):
        return "chapter"
    return None


def _resolve_deduce_file_type(raw_file_type: Any, normalized_rel_path: str) -> tuple[str | None, str | None]:
    inferred = _infer_file_type_from_path(normalized_rel_path)
    if not inferred:
        return None, f"active_file is not supported for deduce route: {normalized_rel_path}"

    if raw_file_type is None:
        return inferred, None
    if not isinstance(raw_file_type, str) or not raw_file_type.strip():
        return None, "file_type must be a non-empty string when provided"

    file_type = raw_file_type.strip()
    if file_type not in DEDUCE_FILE_TYPES:
        return None, f"file_type must be one of {sorted(DEDUCE_FILE_TYPES)}"
    if file_type != inferred:
        return None, f"file_type '{file_type}' does not match active_file '{normalized_rel_path}'"
    return file_type, None
