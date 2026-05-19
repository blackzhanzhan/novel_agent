import json
import logging
import os
import re
import subprocess
import tempfile
from secrets import token_hex
from typing import Any, Callable

from flask import Blueprint, Response, jsonify, request, stream_with_context

from agents.archive import (
    CORE_ARCHIVE_FILES,
    _build_commit_message,
    _compute_file_etag,
    _compute_text_etag,
    _normalize_base_etag,
    _normalize_file_name,
    _resolve_target_file,
    _safe_current_head,
    _save_conflict_draft,
    _write_conflict_response,
)
from utils.book_storage import (
    DEFAULT_CHAPTER_DRAFT,
    DEFAULT_WORLD_MODEL,
    get_book_metadata,
)
from utils.chapter_length import split_chapter_spans
from utils.dify_client import DifyClientError, chat_messages, chat_messages_stream, stop_chat_message
from utils.dify_registry import DifyAgentRoute
from utils.git_utils import ensure_repo, format_git_error, is_nothing_to_commit_error, run_git
from utils.session_runtime import get_agent_context, persist_turn, route_agent_to_session_agent

from agents.world_draft_dify import (  # noqa: F401
    DEDUCE_FILE_TYPES,
    SYNC_ALL_ALLOWED_OPS,
    SYNC_ALL_WRITE_SCOPES,
    DEFAULT_SYNC_ALL_WRITE_SCOPE,
    STRICT_ACTIVE_FILE_SCOPE,
    WORLD_CORE_WRITE_SCOPE,
    WORLD_MODEL_BOOTSTRAP_QUERY_PREFIX,
    _build_dify_query,
    _infer_file_type_from_path,
    _looks_like_init_intent,
    _normalize_text,
    _normalize_world_model_template_text,
    _resolve_deduce_file_type,
    _resolve_deduce_write_scope,
    _should_bootstrap_world_model_query,
    _world_model_template_has_substance,
)
from agents.world_draft_sse import (  # noqa: F401
    JSON_PAYLOAD_MARKER,
    STATUS_CARD_MAX_LINES,
    THINK_BLOCK_END,
    THINK_BLOCK_START,
    _build_stage_event_payload,
    _compact_agent_reasoning_text,
    _contains_cjk_text,
    _encode_sse_event,
    _extract_preview_payload,
    _extract_reasoning_payload,
    _extract_stream_conversation_id,
    _extract_stream_task_id,
    _extract_stream_text_candidate,
    _extract_stream_text_chunk,
    _extract_workflow_failure_message,
    _extract_workflow_output_text,
    _extract_workflow_sync_meta,
    _first_non_empty_text,
    _format_hidden_payload_error,
    _is_transient_workflow_failure,
    _looks_like_internal_scratchpad_text,
    _normalize_stream_event_name,
    _parse_json_payload,
    _sanitize_node_label,
    _split_text_and_think_blocks,
    _split_visible_stream_text,
    _starts_like_internal_scratchpad_text,
)
from agents.world_draft_git import (  # noqa: F401
    DRAFT_BRANCH_NAME,
    GITPYTHON_AVAILABLE,
    LEGACY_DRAFT_BRANCH_NAME,
    LOCKS_DIR_NAME,
    _branch_head_commit,
    _build_diff_preview,
    _build_review_diff_preview,
    _changed_draft_files,
    _compose_content,
    _draft_file_snapshot,
    _draft_file_snapshots,
    _empty_draft_snapshot,
    _ensure_baseline_commit,
    _ensure_draft_branch,
    _ensure_gitpython_or_raise,
    _ensure_layout_files_tracked,
    _ensure_repo_identity,
    _extract_dify_answer,
    _has_pending_changes_for_paths,
    _mainline_file_snapshot,
    _read_branch_file,
    _read_file_text,
    _repo_lock,
    _resolve_mainline_branch,
    _safe_int,
)
from agents.world_draft_layout import (  # noqa: F401
    _attach_warning,
    _book_missing_response,
    _ensure_ai_route_layout_ready,
    _layout_repair_required_response,
    _line_count,
    _resolve_virtual_active_file,
)

try:
    from git import Repo
    from git.exc import GitCommandError

    GITPYTHON_AVAILABLE = True
except Exception:  # pragma: no cover - dependency guard
    Repo = None  # type: ignore[assignment]
    GitCommandError = Exception  # type: ignore[assignment]
    GITPYTHON_AVAILABLE = False


DEFAULT_DIFY_USER = "loregit-ui"
LOGGER = logging.getLogger(__name__)
CHAPTER_DRAFT_FILE = "chapter_draft.md"


def _reset_canonized_chapter_draft(
    *,
    repo: Repo,
    repo_dir: str,
) -> str:
    draft_path = os.path.join(repo_dir, CHAPTER_DRAFT_FILE)
    with open(draft_path, "w", encoding="utf-8", newline="") as draft_file:
        draft_file.write(DEFAULT_CHAPTER_DRAFT)
    repo.git.add("--", CHAPTER_DRAFT_FILE)
    status = repo.git.status("--porcelain", "--", CHAPTER_DRAFT_FILE)
    if not status.strip():
        return ""
    _ensure_repo_identity(repo)
    repo.index.commit("reset canonized chapter draft")
    return repo.head.commit.hexsha


CHAPTER_CANON_NUMBER_RE = re.compile(r"第\s*([0-9０-９]+)\s*章")
FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")

ROUTE_AGENT_KEY_ALIASES = {
    "world_agent": "world_model",
    "outline_agent": "outline",
    "style_agent": "style_guide",
    "continuation": "continuation_agent",
    "review": "review_agent",
}


def _non_empty_str(raw: Any) -> str | None:
    return raw.strip() if isinstance(raw, str) and raw.strip() else None


def _safe_chapter_archive_title(title: str) -> str:
    invalid = set('\\/:*?"<>|')
    cleaned_chars: list[str] = []
    for ch in title.strip():
        if ch in invalid or ch.isspace():
            cleaned_chars.append("_")
        else:
            cleaned_chars.append(ch)
    cleaned = "".join(cleaned_chars).strip("._")
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return (cleaned or "chapter")[:80]


def _chapter_number_from_heading(title: str) -> int | None:
    match = CHAPTER_CANON_NUMBER_RE.search(title or "")
    if not match:
        return None
    value = match.group(1).translate(FULLWIDTH_DIGITS)
    return int(value) if value.isdigit() else None


def _chapter_archive_candidates(chapters_dir: str, number: int) -> list[str]:
    prefix = f"{number:04d}"
    if not os.path.isdir(chapters_dir):
        return []
    return sorted(
        name
        for name in os.listdir(chapters_dir)
        if name.lower().endswith(".md") and (name == f"{prefix}.md" or name.startswith(f"{prefix}_"))
    )


def _chapter_section_text(markdown: str, *, heading_line: int, end_line: int) -> str:
    lines = markdown.splitlines(keepends=True)
    return "".join(lines[heading_line - 1 : end_line])


def _plan_chapter_draft_canonization(
    *,
    chapters_dir: str,
    draft_markdown: str,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    spans = split_chapter_spans(draft_markdown)
    if not spans:
        return [], {
            "code": "CHAPTER_CANON_PARSE_FAILED",
            "message": "chapter_draft.md contains no parseable chapter headings",
            "status": 422,
        }

    planned: list[dict[str, Any]] = []
    seen_numbers: set[int] = set()
    for span in spans:
        number = _chapter_number_from_heading(span.title)
        if number is None:
            return [], {
                "code": "CHAPTER_CANON_PARSE_FAILED",
                "message": f"cannot parse chapter number from heading: {span.title}",
                "status": 422,
            }
        if number in seen_numbers:
            return [], {
                "code": "CHAPTER_CANON_DUPLICATE_CHAPTER",
                "message": f"duplicate chapter number in chapter_draft.md: {number}",
                "status": 422,
            }
        seen_numbers.add(number)

        section_text = _chapter_section_text(
            draft_markdown,
            heading_line=span.heading_line,
            end_line=span.end_line,
        )
        filename = f"{number:04d}_{_safe_chapter_archive_title(span.title)}.md"
        rel_path = f"chapters/{filename}"
        existing_names = _chapter_archive_candidates(chapters_dir, number)
        if existing_names:
            identical_name = None
            for existing_name in existing_names:
                existing_path = os.path.join(chapters_dir, existing_name)
                try:
                    with open(existing_path, "r", encoding="utf-8") as existing_file:
                        existing_text = existing_file.read()
                except OSError:
                    existing_text = ""
                if existing_text == section_text:
                    identical_name = existing_name
                    break
            if identical_name:
                planned.append(
                    {
                        "number": number,
                        "title": span.title,
                        "file_name": f"chapters/{identical_name}",
                        "status": "already_exists",
                        "heading_line": span.heading_line,
                        "end_line": span.end_line,
                    }
                )
                continue
            return [], {
                "code": "CHAPTER_CANON_CONFLICT",
                "message": f"chapter {number} already exists with different content: {', '.join(existing_names)}",
                "status": 409,
            }

        planned.append(
            {
                "number": number,
                "title": span.title,
                "file_name": rel_path,
                "filename": filename,
                "content": section_text,
                "status": "created",
                "heading_line": span.heading_line,
                "end_line": span.end_line,
            }
        )

    return planned, None


def _write_planned_chapter_files(
    *,
    repo: Repo,
    repo_dir: str,
    chapters_dir: str,
    planned: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str]:
    created_rel_paths: list[str] = []
    public_entries: list[dict[str, Any]] = []
    for entry in planned:
        public_entry = {
            "number": entry["number"],
            "title": entry["title"],
            "file_name": entry["file_name"],
            "status": entry["status"],
            "heading_line": entry["heading_line"],
            "end_line": entry["end_line"],
        }
        public_entries.append(public_entry)
        if entry.get("status") != "created":
            continue
        target_path = os.path.join(chapters_dir, entry["filename"])
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with open(target_path, "w", encoding="utf-8", newline="") as chapter_file:
            chapter_file.write(entry["content"])
        created_rel_paths.append(entry["file_name"])

    commit_id = ""
    if created_rel_paths:
        repo.git.add("--", *created_rel_paths)
        status = repo.git.status("--porcelain", "--", *created_rel_paths)
        if status.strip():
            _ensure_repo_identity(repo)
            repo.index.commit("archive accepted chapter draft")
            commit_id = repo.head.commit.hexsha
    return public_entries, commit_id


def _build_post_confirm_world_payload(
    *,
    book_id: str,
    materialized_chapters: list[dict[str, Any]],
) -> dict[str, Any] | None:
    chapter_refs = [
        {
            "number": entry.get("number"),
            "title": entry.get("title") or "",
            "file_name": entry.get("file_name") or "",
            "status": entry.get("status") or "",
        }
        for entry in materialized_chapters
        if isinstance(entry, dict) and entry.get("file_name")
    ]
    if not chapter_refs:
        return None
    numbers = [
        str(entry["number"])
        for entry in chapter_refs
        if isinstance(entry.get("number"), int)
    ]
    numbers_label = "、".join(numbers) if numbers else "刚确认的章节"
    refs_json = json.dumps(chapter_refs, ensure_ascii=False, indent=2)
    intent = (
        "【确认后状态/世界观接棒任务】\n"
        "本任务由前台在作者确认续写草稿入库后自动触发，不是闲聊，也不是审核 agent 任务。\n"
        "你是项目 world_model 路由，必须只维护创作状态与长期设定，不得改写、润色、扩写或重新生成章节正文。\n\n"
        f"已确认入库章节：{numbers_label}\n"
        "正式章节文件如下，请你自己读取这些 chapters/*.md，以及 status_card.md、world_model.md、summary.md、"
        "domain_rules.md、chapter_outline.md 和 error_archive.md 后再判断：\n"
        f"{refs_json}\n\n"
        "必须执行：\n"
        "1. 更新 status_card.md：把最新章节后的时间线、角色状态、当前冲突、开放承诺、下一章约束刷新到可供续写读取的状态。\n"
        "2. 判断是否需要更新 world_model.md：只有出现长期规则、身份关系、世界机制、时间线/轮回状态、硬约束、重大矛盾修复时才写入；普通临时状态不要塞进 world_model.md。\n"
        "3. 判断是否需要更新 domain_rules.md：只有出现可复用、可审查的领域规则时才写入。\n\n"
        "写入边界：\n"
        "- 允许写 status_card.md、world_model.md、domain_rules.md。\n"
        "- 不允许写 chapter_draft.md、chapters/*.md、chapter_outline.md、summary.md、style_*.md、error_archive.md。\n"
        "- status_card.md 是必刷目标；world_model.md 和 domain_rules.md 是按需目标。\n"
        "- 最终回复只用一句话概括你更新了哪些档案；不要把章节正文粘贴到回复里。"
    )
    return {
        "status": "pending",
        "action": "post_confirm_world_distill",
        "book_id": book_id,
        "route_agent_key": "world_model",
        "active_file": "status_card.md",
        "file_type": "world_core",
        "write_scope": "world_core",
        "dify_user": "loregit-ui-post-confirm",
        "intent": intent,
        "materialized_chapters": chapter_refs,
        "required_writes": ["status_card.md"],
        "optional_writes": ["world_model.md", "domain_rules.md"],
        "forbidden_writes": [
            "chapter_draft.md",
            "chapters/*.md",
            "chapter_outline.md",
            "summary.md",
            "style_*.md",
            "error_archive.md",
        ],
        "no_prose_boundary": {
            "payload_contains_chapter_prose": False,
            "world_model_route_must_not_rewrite_prose": True,
            "review_agent_is_not_responsible": True,
        },
    }


def _resolve_local_thread_id(payload: dict[str, Any]) -> str:
    return (
        _non_empty_str(payload.get("thread_id"))
        or _non_empty_str(payload.get("conversation_id"))
        or f"conv_{token_hex(8)}"
    )


def _resolve_upstream_conversation_id(
    *,
    dev_repo_root: str,
    book_id: str,
    agent_key: str,
    local_thread_id: str,
    payload: dict[str, Any],
) -> str | None:
    raw_payload_id = _non_empty_str(payload.get("upstream_conversation_id"))
    if raw_payload_id is None and _non_empty_str(payload.get("thread_id")):
        raw_payload_id = _non_empty_str(payload.get("conversation_id"))
    if raw_payload_id == local_thread_id:
        raw_payload_id = None
    try:
        session_agent = route_agent_to_session_agent(agent_key)
        context = get_agent_context(
            dev_repo_root,
            book_id=book_id,
            agent_key=session_agent,
            conversation_id=local_thread_id,
        )
        raw_context_id = context.get("upstream_conversation_id")
        if isinstance(raw_context_id, str) and raw_context_id.strip() and raw_context_id.strip() != local_thread_id:
            return raw_context_id.strip()
    except Exception as exc:  # pragma: no cover - memory lookup must not break a run
        LOGGER.warning("failed to resolve upstream conversation from local thread: %s", exc)
    return raw_payload_id



def call_dify_api_raw(
    markdown: str,
    payload: dict[str, Any] | None = None,
    *,
    dify_base_url: str,
    dify_api_key: str,
    dify_timeout_seconds: int,
) -> dict[str, Any]:
    if isinstance(payload, dict):
        mocked = payload.get("mock_ai_markdown")
        if isinstance(mocked, str):
            return {
                "answer": mocked,
                "conversation_id": payload.get("conversation_id"),
                "mode": "mock",
            }

    query = _build_dify_query(markdown, payload)

    inputs: dict[str, Any] = {}
    if isinstance(payload, dict):
        raw_book_id = payload.get("book_id")
        if isinstance(raw_book_id, str) and raw_book_id.strip():
            inputs["book_id"] = raw_book_id.strip()
        raw_book_name = payload.get("book_name")
        if isinstance(raw_book_name, str) and raw_book_name.strip():
            inputs["book_name"] = raw_book_name.strip()
        inputs["chapter_index"] = _safe_int(payload.get("chapter_index"), 0)
        raw_active_file = payload.get("active_file")
        if isinstance(raw_active_file, str) and raw_active_file.strip():
            inputs["active_file"] = raw_active_file.strip()
        raw_write_scope = payload.get("write_scope")
        if isinstance(raw_write_scope, str) and raw_write_scope.strip():
            inputs["write_scope"] = raw_write_scope.strip()
        raw_file_type = payload.get("file_type")
        if isinstance(raw_file_type, str) and raw_file_type.strip():
            inputs["file_type"] = raw_file_type.strip()
    else:
        inputs["chapter_index"] = 0

    conversation_id = None
    user = DEFAULT_DIFY_USER
    if isinstance(payload, dict):
        raw_conversation_id = payload.get("conversation_id")
        if isinstance(raw_conversation_id, str) and raw_conversation_id.strip():
            conversation_id = raw_conversation_id.strip()
        raw_user = payload.get("dify_user")
        if isinstance(raw_user, str) and raw_user.strip():
            user = raw_user.strip()

    return chat_messages(
        base_url=dify_base_url,
        api_key=dify_api_key,
        query=query,
        inputs=inputs,
        user=user,
        conversation_id=conversation_id,
        response_mode="blocking",
        timeout_seconds=max(1, int(dify_timeout_seconds)),
    )


def call_dify_api(
    markdown: str,
    payload: dict[str, Any] | None = None,
    *,
    dify_base_url: str,
    dify_api_key: str,
    dify_timeout_seconds: int,
) -> str:
    response = call_dify_api_raw(
        markdown,
        payload,
        dify_base_url=dify_base_url,
        dify_api_key=dify_api_key,
        dify_timeout_seconds=dify_timeout_seconds,
    )
    return _extract_dify_answer(response, markdown)


def create_blueprint(
    *,
    storage_root: str,
    dev_repo_root: str,
    parse_json_payload: Callable[[list[str] | None], tuple[dict | None, tuple | None]],
    require_book_id: Callable[[dict | None], tuple[str | None, tuple | None]],
    json_error: Callable[[str, str, int], tuple],
    dify_base_url: str,
    dify_api_key: str,
    dify_timeout_seconds: int,
    dify_agent_registry: dict[str, DifyAgentRoute] | None = None,
) -> Blueprint:
    bp = Blueprint("world_draft", __name__)
    _dify_agent_registry = dify_agent_registry if dify_agent_registry is not None else {}

    def _resolve_dify_route(normalized_rel_path: str) -> DifyAgentRoute | None:
        for route in _dify_agent_registry.values():
            if route.matches_route_target(normalized_rel_path):
                return route
        return None

    def _resolve_dify_route_for_payload(normalized_rel_path: str, payload: dict[str, Any]) -> DifyAgentRoute | None:
        raw_agent_key = payload.get("route_agent_key") or payload.get("agent_key") or payload.get("routed_agent")
        if isinstance(raw_agent_key, str) and raw_agent_key.strip():
            requested = ROUTE_AGENT_KEY_ALIASES.get(raw_agent_key.strip(), raw_agent_key.strip())
            route = _dify_agent_registry.get(requested)
            if route is None:
                return None
            if not route.matches_route_target(normalized_rel_path):
                return None
            return route
        return _resolve_dify_route(normalized_rel_path)

    def _sync_all_from_payload(payload: dict[str, Any], *, legacy_route: bool = False):
        book_id, book_err = require_book_id(payload)
        if book_err:
            return book_err

        raw_writes = payload.get("writes")
        if not isinstance(raw_writes, list) or not raw_writes:
            return json_error("INVALID_PAYLOAD", "writes must be a non-empty array", 400)

        raw_book_name = payload.get("book_name")
        normalized_book_name = raw_book_name.strip() if isinstance(raw_book_name, str) and raw_book_name.strip() else None
        paths, _, layout_err = _ensure_ai_route_layout_ready(
            book_id,
            storage_root,
            book_name=normalized_book_name,
        )
        if layout_err:
            return layout_err
        assert paths is not None
        repo_dir = paths["book_dir"]

        raw_write_scope = payload.get("write_scope")
        if raw_write_scope is None:
            write_scope = DEFAULT_SYNC_ALL_WRITE_SCOPE
        elif isinstance(raw_write_scope, str) and raw_write_scope.strip():
            write_scope = raw_write_scope.strip()
        else:
            return json_error("INVALID_PAYLOAD", "write_scope must be a non-empty string", 400)
        if write_scope not in SYNC_ALL_WRITE_SCOPES:
            return json_error(
                "INVALID_PAYLOAD",
                f"write_scope must be one of {sorted(SYNC_ALL_WRITE_SCOPES)}",
                400,
            )

        normalized_active_file = _normalize_file_name(payload.get("active_file"))
        normalized_active_target: str | None = None
        active_route: DifyAgentRoute | None = None
        if write_scope == STRICT_ACTIVE_FILE_SCOPE:
            if not normalized_active_file:
                return json_error(
                    "INVALID_PAYLOAD",
                    "active_file is required when write_scope=active_file_strict",
                    400,
                )
        if normalized_active_file:
            try:
                _, normalized_active_target = _resolve_target_file(repo_dir, normalized_active_file)
            except ValueError as exc:
                return json_error("INVALID_PAYLOAD", f"active_file: {exc}", 400)
            active_route = _resolve_dify_route(normalized_active_target)
            if active_route is None:
                return json_error(
                    "TARGET_PATH_FORBIDDEN",
                    f"active_file is not routed by any registered Dify agent: {normalized_active_target}",
                    400,
                )
            if not active_route.can_write(normalized_active_target):
                return json_error(
                    "TARGET_PATH_FORBIDDEN",
                    (
                        f"active_file is read-only for draft writes in routed agent {active_route.routed_agent}: "
                        f"{normalized_active_target}"
                    ),
                    400,
                )

        normalized_writes: list[dict[str, Any]] = []
        for idx, raw_item in enumerate(raw_writes):
            if not isinstance(raw_item, dict):
                return json_error("INVALID_PAYLOAD", f"writes[{idx}] must be an object", 400)

            file_name = _normalize_file_name(raw_item.get("file_name"))
            if not file_name:
                return json_error("INVALID_PAYLOAD", f"writes[{idx}].file_name is required", 400)

            op_raw = raw_item.get("op", "").strip().lower() if isinstance(raw_item.get("op"), str) else ""
            if op_raw not in SYNC_ALL_ALLOWED_OPS:
                return json_error(
                    "INVALID_PAYLOAD",
                    f"writes[{idx}].op must be one of {sorted(SYNC_ALL_ALLOWED_OPS)}",
                    400,
                )

            incoming_content = _normalize_text(raw_item.get("content"))
            base_etag, base_etag_err = _normalize_base_etag(raw_item.get("base_etag"))
            if base_etag_err:
                return json_error("INVALID_PAYLOAD", f"writes[{idx}].{base_etag_err}", 400)

            normalized_writes.append(
                {
                    "index": idx,
                    "file_name": file_name,
                    "op": op_raw,
                    "incoming_content": incoming_content,
                    "base_etag": base_etag,
                }
            )

        raw_message = payload.get("message")
        if isinstance(raw_message, str) and raw_message.strip():
            base_message = raw_message.strip()
        else:
            base_message = "draft sandbox sync_all"
        commit_message = _build_commit_message(payload.get("origin"), base_message, DRAFT_BRANCH_NAME)

        try:
            _ensure_gitpython_or_raise()
            with _repo_lock(repo_dir):
                repo = Repo(repo_dir)
                _ensure_baseline_commit(repo)
                _ensure_layout_files_tracked(repo, repo_dir)
                mainline_branch = _resolve_mainline_branch(repo)
                _, migrated_from_legacy = _ensure_draft_branch(repo, mainline_branch, create_if_missing=True)
                resolved_entries: list[dict[str, Any]] = []
                seen_paths: set[str] = set()
                resolved_route = active_route
                for item in normalized_writes:
                    try:
                        file_path, normalized_rel_path = _resolve_target_file(repo_dir, item["file_name"])
                    except ValueError as exc:
                        return json_error("INVALID_PAYLOAD", f"writes[{item['index']}]: {exc}", 400)

                    if resolved_route is None:
                        resolved_route = _resolve_dify_route(normalized_rel_path)
                    if resolved_route is None or not resolved_route.can_write(normalized_rel_path):
                        return json_error(
                            "TARGET_PATH_FORBIDDEN",
                            (
                                f"writes[{item['index']}].file_name is read-only or not writable by the routed Dify agent: "
                                f"{normalized_rel_path}"
                            ),
                            400,
                        )
                    if (
                        write_scope == STRICT_ACTIVE_FILE_SCOPE
                        and normalized_active_target
                        and normalized_rel_path != normalized_active_target
                    ):
                        return json_error(
                            "TARGET_PATH_FORBIDDEN",
                            (
                                f"writes[{item['index']}].file_name must match active_file "
                                f"when write_scope=active_file_strict: {normalized_active_target}"
                            ),
                            400,
                        )

                    if normalized_rel_path in seen_paths:
                        return json_error("INVALID_PAYLOAD", f"duplicate target file in writes: {normalized_rel_path}", 400)
                    seen_paths.add(normalized_rel_path)

                    existed_before = os.path.exists(file_path)
                    original_content = ""
                    if existed_before:
                        with open(file_path, "r", encoding="utf-8") as f:
                            original_content = f.read()

                    current_etag = _compute_text_etag(original_content)
                    base_etag = item["base_etag"]
                    if normalized_rel_path in CORE_ARCHIVE_FILES and base_etag is None:
                        return json_error(
                            "PRECONDITION_REQUIRED",
                            f"base_etag is required for core archive file: {normalized_rel_path}",
                            428,
                        )

                    if base_etag is not None and base_etag != current_etag:
                        draft_path = _save_conflict_draft(
                            repo_dir,
                            normalized_rel_path,
                            item["incoming_content"],
                            item["op"],
                            base_etag,
                            current_etag,
                        )
                        return _write_conflict_response(
                            book_id=book_id,
                            normalized_rel_path=normalized_rel_path,
                            base_etag=base_etag,
                            current_etag=current_etag,
                            draft_path=draft_path,
                        )

                    new_content = _compose_content(item["op"], original_content, item["incoming_content"])
                    # Auto-truncate status_card.md instead of rejecting.
                    # LLMs reliably ignore line-count Prompt constraints; enforce here.
                    _status_card_truncated = False
                    if normalized_rel_path == "status_card.md" and _line_count(new_content) > STATUS_CARD_MAX_LINES:
                        sc_lines = new_content.splitlines(keepends=True)
                        new_content = "".join(sc_lines[:STATUS_CARD_MAX_LINES])
                        _status_card_truncated = True
                    resolved_entries.append(
                        {
                            **item,
                            "file_path": file_path,
                            "normalized_rel_path": normalized_rel_path,
                            "existed_before": existed_before,
                            "original_content": original_content,
                            "new_content": new_content,
                            "status_card_truncated": _status_card_truncated,
                        }
                    )

                changed_entries = [entry for entry in resolved_entries if entry["new_content"] != entry["original_content"]]
                if not changed_entries:
                    response_body = {
                        "status": "success",
                        "book_id": book_id,
                        "branch": DRAFT_BRANCH_NAME,
                        "mainline_branch": mainline_branch,
                        "commit_id": _safe_current_head(repo_dir),
                        "updated_files": [
                            {
                                "file_name": entry["normalized_rel_path"],
                                "etag": _compute_file_etag(entry["file_path"]),
                            }
                            for entry in resolved_entries
                        ],
                        "message": "No changes detected, files are already up to date.",
                    }
                    if migrated_from_legacy:
                        response_body["warning"] = (
                            "legacy draft branch draft/world_model has been migrated to draft/sandbox"
                        )
                    if legacy_route:
                        response_body["warning"] = (
                            f"{response_body.get('warning', '')}; deprecated route: use /api/draft/sync_all".strip("; ")
                        )
                    return jsonify(response_body), 200

                written_entries: list[dict[str, Any]] = []
                temp_paths: list[str] = []
                try:
                    for entry in changed_entries:
                        os.makedirs(os.path.dirname(entry["file_path"]), exist_ok=True)
                        fd, temp_path = tempfile.mkstemp(
                            prefix=".tmp_sync_all_",
                            suffix=".tmp",
                            dir=os.path.dirname(entry["file_path"]),
                        )
                        temp_paths.append(temp_path)
                        with os.fdopen(fd, "w", encoding="utf-8") as temp_file:
                            temp_file.write(entry["new_content"])
                        os.replace(temp_path, entry["file_path"])
                        written_entries.append(entry)

                    ensure_repo(repo_dir)
                    rel_paths = [entry["normalized_rel_path"] for entry in resolved_entries]
                    for rel_path in rel_paths:
                        run_git(repo_dir, ["add", "--", rel_path])

                    if not _has_pending_changes_for_paths(repo_dir, rel_paths):
                        commit_id = _safe_current_head(repo_dir)
                    else:
                        try:
                            run_git(repo_dir, ["commit", "-m", commit_message, "--", *rel_paths])
                        except subprocess.CalledProcessError as exc:
                            if not is_nothing_to_commit_error(exc):
                                raise
                        commit_id = run_git(repo_dir, ["rev-parse", "HEAD"]).stdout.strip()
                except Exception as exc:
                    rollback_warning = None
                    try:
                        for entry in reversed(written_entries):
                            if entry["existed_before"]:
                                with open(entry["file_path"], "w", encoding="utf-8") as rollback_file:
                                    rollback_file.write(entry["original_content"])
                            elif os.path.exists(entry["file_path"]):
                                os.remove(entry["file_path"])
                    except Exception as rollback_exc:
                        rollback_warning = f"rollback_failed: {rollback_exc}"

                    error_payload = {
                        "status": "error",
                        "code": "GIT_COMMIT_FAILED",
                        "message": format_git_error(exc) or "failed to commit sync_all batch",
                    }
                    if rollback_warning:
                        error_payload["warning"] = rollback_warning
                    return jsonify(error_payload), 500
                finally:
                    for temp_path in temp_paths:
                        if os.path.exists(temp_path):
                            try:
                                os.remove(temp_path)
                            except OSError:
                                pass

                truncated_files = [
                    entry["normalized_rel_path"]
                    for entry in resolved_entries
                    if entry.get("status_card_truncated")
                ]
                response_body = {
                    "status": "success",
                    "book_id": book_id,
                    "branch": DRAFT_BRANCH_NAME,
                    "mainline_branch": mainline_branch,
                    "commit_id": commit_id,
                    "updated_files": [
                        {
                            "file_name": entry["normalized_rel_path"],
                            "etag": _compute_file_etag(entry["file_path"]),
                            **({"truncated": True} if entry.get("status_card_truncated") else {}),
                        }
                        for entry in resolved_entries
                    ],
                }
                warnings: list[str] = []
                if truncated_files:
                    warnings.append(
                        f"status_card.md auto-truncated to {STATUS_CARD_MAX_LINES} lines "
                        f"(LLM output exceeded limit; truncated: {truncated_files})"
                    )
                if migrated_from_legacy:
                    warnings.append("legacy draft branch draft/world_model has been migrated to draft/sandbox")
                if legacy_route:
                    warnings.append("deprecated route: use /api/draft/sync_all")
                if warnings:
                    response_body["warning"] = "; ".join(warnings)
                return jsonify(response_body), 200
        except GitCommandError as exc:
            return json_error("GIT_OPERATION_FAILED", str(exc), 500)
        except Exception as exc:
            return json_error("DRAFT_SYNC_ALL_FAILED", str(exc), 500)

    @bp.post("/api/draft/sync_all")
    def sync_all():
        payload, err = parse_json_payload(["writes"])
        if err:
            return err
        assert payload is not None
        return _sync_all_from_payload(payload, legacy_route=False)

    @bp.post("/api/world/deduce")
    def deduce_world():
        payload, err = parse_json_payload(["intent", "active_file"])
        if err:
            return err
        assert payload is not None

        book_id, book_err = require_book_id(payload)
        if book_err:
            return book_err

        active_file = _normalize_file_name(payload.get("active_file"))
        if not active_file:
            return json_error("INVALID_PAYLOAD", "active_file is required", 400)

        raw_book_name = payload.get("book_name")
        normalized_book_name = raw_book_name.strip() if isinstance(raw_book_name, str) and raw_book_name.strip() else None
        _, _, layout_err = _ensure_ai_route_layout_ready(
            book_id,
            storage_root,
            book_name=normalized_book_name,
        )
        if layout_err:
            return layout_err
        paths, repo_dir, file_path, normalized_rel_path, baseline_markdown, read_err = _resolve_virtual_active_file(
            book_id,
            storage_root,
            active_file,
        )
        if read_err:
            return read_err
        assert paths is not None and repo_dir is not None and file_path is not None and normalized_rel_path is not None
        dify_payload = dict(payload)
        local_thread_id = _resolve_local_thread_id(payload)
        resolved_file_type, file_type_err = _resolve_deduce_file_type(payload.get("file_type"), normalized_rel_path)
        if file_type_err:
            return json_error("INVALID_PAYLOAD", file_type_err, 400)
        assert resolved_file_type is not None
        dify_payload["file_type"] = resolved_file_type
        dify_route = _resolve_dify_route_for_payload(normalized_rel_path, payload)
        if dify_route is None:
            return json_error(
                "TARGET_PATH_FORBIDDEN",
                f"active_file is not routed by any registered Dify agent: {normalized_rel_path}",
                400,
            )
        if not dify_route.can_read(normalized_rel_path):
            return json_error(
                "TARGET_PATH_FORBIDDEN",
                f"active_file must be readable by routed agent {dify_route.routed_agent}: {normalized_rel_path}",
                400,
            )
        resolved_write_scope, write_scope_err = _resolve_deduce_write_scope(
            payload.get("write_scope"),
            payload.get("intent"),
            dify_route,
        )
        if write_scope_err:
            return json_error("INVALID_PAYLOAD", write_scope_err, 400)
        assert resolved_write_scope is not None
        dify_payload["book_id"] = book_id
        dify_payload["write_scope"] = resolved_write_scope
        upstream_conversation_id = _resolve_upstream_conversation_id(
            dev_repo_root=dev_repo_root,
            book_id=book_id,
            agent_key=dify_route.agent_key,
            local_thread_id=local_thread_id,
            payload=payload,
        )
        raw_book_name = payload.get("book_name")
        if not (isinstance(raw_book_name, str) and raw_book_name.strip()):
            metadata = get_book_metadata(book_id, storage_root)
            fallback_book_name = metadata.get("book_name") or book_id
            dify_payload["book_name"] = fallback_book_name
        if upstream_conversation_id:
            dify_payload["conversation_id"] = upstream_conversation_id
        else:
            dify_payload.pop("conversation_id", None)

        try:
            dify_response = call_dify_api_raw(
                baseline_markdown,
                dify_payload,
                dify_base_url=dify_route.base_url,
                dify_api_key=dify_route.api_key,
                dify_timeout_seconds=dify_route.timeout_seconds,
            )
        except DifyClientError as exc:
            details = str(exc)
            if exc.response_body:
                details = f"{details}; response={exc.response_body}"
            status = 502
            if isinstance(exc.status_code, int) and 400 <= exc.status_code < 500:
                status = 400
            return json_error("DIFY_API_FAILED", details, status)
        except Exception as exc:
            return json_error("DIFY_API_FAILED", str(exc), 502)

        try:
            branch_name = run_git(repo_dir, ["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip() or "unknown"
        except Exception:
            branch_name = "unknown"

        response_body = {
            "status": "success",
            "book_id": book_id,
            "branch": branch_name,
            "thread_id": local_thread_id,
            "file_name": normalized_rel_path,
            "content": _read_file_text(file_path),
            "etag": _compute_file_etag(file_path),
            "commit_id": _safe_current_head(repo_dir),
            "conversation_id": local_thread_id,
            "upstream_conversation_id": dify_response.get("conversation_id"),
            "answer": _extract_dify_answer(dify_response, ""),
            "file_type": resolved_file_type,
            "routed_agent": dify_route.routed_agent,
        }
        if isinstance(payload.get("mock_ai_markdown"), str) and not response_body["upstream_conversation_id"]:
            response_body["upstream_conversation_id"] = local_thread_id
        try:
            response_conversation_id = response_body.get("upstream_conversation_id")
            persist_turn(
                dev_repo_root,
                book_id=book_id,
                agent_key=route_agent_to_session_agent(dify_route.agent_key),
                conversation_id=local_thread_id,
                upstream_conversation_id=response_conversation_id.strip() if isinstance(response_conversation_id, str) and response_conversation_id.strip() else None,
                active_file=normalized_rel_path,
                user_text=str(payload.get("intent") or ""),
                assistant_text=str(response_body.get("answer") or ""),
                rewrite_user_message_id=payload.get("rewrite_user_message_id"),
            )
        except Exception as exc:  # pragma: no cover - session persistence must not break core flow
            LOGGER.warning("failed to persist blocking conversation turn: %s", exc)
        return jsonify(response_body), 200

    @bp.post("/api/world/stop_generation")
    def stop_world_generation():
        payload, err = parse_json_payload(["task_id", "active_file"])
        if err:
            return err
        assert payload is not None

        book_id, book_err = require_book_id(payload)
        if book_err:
            return book_err

        active_file = _normalize_file_name(payload.get("active_file"))
        if not active_file:
            return json_error("INVALID_PAYLOAD", "active_file is required", 400)

        task_id = str(payload.get("task_id") or "").strip()
        if not task_id:
            return json_error("INVALID_PAYLOAD", "task_id is required", 400)

        normalized_rel_path = active_file
        dify_route = _resolve_dify_route_for_payload(normalized_rel_path, payload)
        if dify_route is None:
            return json_error(
                "TARGET_PATH_FORBIDDEN",
                f"active_file is not routed by any registered Dify agent: {normalized_rel_path}",
                400,
            )
        if not dify_route.can_read(normalized_rel_path):
            return json_error(
                "TARGET_PATH_FORBIDDEN",
                f"active_file must be readable by routed agent {dify_route.routed_agent}: {normalized_rel_path}",
                400,
            )

        dify_user = DEFAULT_DIFY_USER
        raw_dify_user = payload.get("dify_user")
        if isinstance(raw_dify_user, str) and raw_dify_user.strip():
            dify_user = raw_dify_user.strip()

        try:
            stop_result = stop_chat_message(
                base_url=dify_route.base_url,
                api_key=dify_route.api_key,
                task_id=task_id,
                user=dify_user,
                timeout_seconds=max(1, int(dify_route.timeout_seconds)),
            )
        except DifyClientError as exc:
            details = str(exc)
            if exc.response_body:
                details = f"{details}; response={exc.response_body}"
            status = 502
            if isinstance(exc.status_code, int) and 400 <= exc.status_code < 500:
                status = exc.status_code
            return json_error("DIFY_STOP_FAILED", details, status)

        return (
            jsonify(
                {
                    "status": "success",
                    "book_id": book_id,
                    "task_id": task_id,
                    "active_file": normalized_rel_path,
                    "routed_agent": dify_route.routed_agent,
                    "result": stop_result.get("result", "success"),
                }
            ),
            200,
        )

    @bp.post("/api/world/deduce_stream")
    def deduce_world_stream():
        payload, err = parse_json_payload(["intent", "active_file"])
        if err:
            return err
        assert payload is not None

        book_id, book_err = require_book_id(payload)
        if book_err:
            return book_err

        active_file = _normalize_file_name(payload.get("active_file"))
        if not active_file:
            return json_error("INVALID_PAYLOAD", "active_file is required", 400)

        raw_book_name = payload.get("book_name")
        normalized_book_name = raw_book_name.strip() if isinstance(raw_book_name, str) and raw_book_name.strip() else None
        _, _, layout_err = _ensure_ai_route_layout_ready(
            book_id,
            storage_root,
            book_name=normalized_book_name,
        )
        if layout_err:
            return layout_err
        paths, repo_dir, file_path, normalized_rel_path, baseline_markdown, read_err = _resolve_virtual_active_file(
            book_id,
            storage_root,
            active_file,
        )
        if read_err:
            return read_err
        assert paths is not None and repo_dir is not None and file_path is not None and normalized_rel_path is not None
        baseline_etag = _compute_text_etag(baseline_markdown)

        dify_payload = dict(payload)
        resolved_file_type, file_type_err = _resolve_deduce_file_type(payload.get("file_type"), normalized_rel_path)
        if file_type_err:
            return json_error("INVALID_PAYLOAD", file_type_err, 400)
        assert resolved_file_type is not None
        dify_payload["file_type"] = resolved_file_type
        dify_route = _resolve_dify_route_for_payload(normalized_rel_path, payload)
        if dify_route is None:
            return json_error(
                "TARGET_PATH_FORBIDDEN",
                f"active_file is not routed by any registered Dify agent: {normalized_rel_path}",
                400,
            )
        if not dify_route.can_read(normalized_rel_path):
            return json_error(
                "TARGET_PATH_FORBIDDEN",
                f"active_file must be readable by routed agent {dify_route.routed_agent}: {normalized_rel_path}",
                400,
            )
        before_snapshots = _draft_file_snapshots(repo_dir, dify_route.writable_exact_files)
        resolved_write_scope, write_scope_err = _resolve_deduce_write_scope(
            payload.get("write_scope"),
            payload.get("intent"),
            dify_route,
        )
        if write_scope_err:
            return json_error("INVALID_PAYLOAD", write_scope_err, 400)
        assert resolved_write_scope is not None
        dify_payload["book_id"] = book_id
        dify_payload["write_scope"] = resolved_write_scope
        raw_book_name = payload.get("book_name")
        if not (isinstance(raw_book_name, str) and raw_book_name.strip()):
            metadata = get_book_metadata(book_id, storage_root)
            dify_payload["book_name"] = metadata.get("book_name") or book_id

        raw_thread_id = dify_payload.get("thread_id")
        raw_legacy_conversation_id = dify_payload.get("conversation_id")
        detached_job = bool(dify_payload.get("detached_job"))
        local_thread_id = _resolve_local_thread_id(
            {
                "thread_id": raw_thread_id,
                "conversation_id": raw_legacy_conversation_id,
            }
        )
        upstream_conversation_id = None if detached_job else _resolve_upstream_conversation_id(
            dev_repo_root=dev_repo_root,
            book_id=book_id,
            agent_key=dify_route.agent_key,
            local_thread_id=local_thread_id,
            payload=dify_payload,
        )
        if upstream_conversation_id:
            dify_payload["conversation_id"] = upstream_conversation_id
        else:
            dify_payload.pop("conversation_id", None)

        def _stream():
            yield _encode_sse_event(
                "ack",
                {
                    "status": "accepted",
                    "book_id": book_id,
                    "thread_id": local_thread_id,
                    "file_name": normalized_rel_path,
                    "active_file": normalized_rel_path,
                    "file_type": resolved_file_type,
                    "write_scope": resolved_write_scope,
                    "branch": DRAFT_BRANCH_NAME,
                    "base_etag": baseline_etag,
                    "routed_agent": dify_route.routed_agent,
                },
            )

            def _emit_completion_events(
                *,
                conversation_id: str | None,
                task_id: str | None,
                merged_answer: str,
                sync_status: str = "",
                sync_commit_id: str = "",
                sync_message: str = "",
                sync_result: str = "",
                write_confirmed_override: bool | None = None,
                warning: str = "",
                after_snapshots: dict[str, dict[str, Any]] | None = None,
            ):
                snapshot_map = after_snapshots or _draft_file_snapshots(repo_dir, dify_route.writable_exact_files)
                changed_files = _changed_draft_files(before_snapshots, snapshot_map)
                draft_changed = bool(changed_files)
                review_target = next(
                    (item for item in changed_files if item["file_name"] == normalized_rel_path),
                    changed_files[0] if changed_files else None,
                )
                snapshot = review_target["after"] if review_target else snapshot_map.get(normalized_rel_path, _empty_draft_snapshot())
                if write_confirmed_override is None:
                    write_confirmed = draft_changed or sync_status.lower() == "success"
                else:
                    write_confirmed = write_confirmed_override

                if not merged_answer.strip() and not draft_changed:
                    LOGGER.warning(
                        "[review-trigger] empty_answer file=%s routed_agent=%s task_id=%s",
                        normalized_rel_path,
                        dify_route.routed_agent,
                        task_id,
                    )
                    yield _encode_sse_event(
                        "error",
                        {
                            "code": "DIFY_EMPTY_ANSWER",
                            "message": "Dify workflow completed without a visible answer or draft changes.",
                            "status": 502,
                            "conversation_id": local_thread_id,
                            "upstream_conversation_id": conversation_id,
                            "thread_id": local_thread_id,
                            "task_id": task_id,
                        },
                    )
                    return

                if draft_changed:
                    diff_preview = _build_review_diff_preview(
                        repo_dir,
                        review_target["file_name"],
                        snapshot.get("content", ""),
                    )
                    LOGGER.warning(
                        "[review-trigger] draft_ready file=%s commit=%s etag=%s branch=%s routed_agent=%s",
                        review_target["file_name"],
                        snapshot.get("commit_id"),
                        snapshot.get("etag"),
                        DRAFT_BRANCH_NAME,
                        dify_route.routed_agent,
                    )
                    yield _encode_sse_event(
                        "draft_ready",
                        {
                            "book_id": book_id,
                            "file_name": review_target["file_name"],
                            "branch": DRAFT_BRANCH_NAME,
                            "commit_id": snapshot.get("commit_id"),
                            "etag": snapshot.get("etag"),
                            "content": snapshot.get("content"),
                            "diff_preview": diff_preview,
                            "draft_changed": True,
                            "changed_files": [item["file_name"] for item in changed_files],
                        },
                    )

                if not detached_job:
                    try:
                        persist_turn(
                            dev_repo_root,
                            book_id=book_id,
                            agent_key=route_agent_to_session_agent(dify_route.agent_key),
                            conversation_id=local_thread_id,
                            upstream_conversation_id=conversation_id.strip() if isinstance(conversation_id, str) and conversation_id.strip() else None,
                            active_file=normalized_rel_path,
                            user_text=str(payload.get("intent") or ""),
                            assistant_text=merged_answer,
                            rewrite_user_message_id=payload.get("rewrite_user_message_id"),
                        )
                    except Exception as exc:  # pragma: no cover - session persistence must not break core flow
                        LOGGER.warning("failed to persist streamed conversation turn: %s", exc)

                done_payload = {
                    "status": "success",
                    "book_id": book_id,
                    "thread_id": local_thread_id,
                    "file_name": normalized_rel_path,
                    "branch": DRAFT_BRANCH_NAME,
                    "conversation_id": local_thread_id,
                    "upstream_conversation_id": conversation_id,
                    "task_id": task_id,
                    "answer": merged_answer,
                    "draft_changed": draft_changed,
                    "write_confirmed": write_confirmed,
                    "review_target_file": review_target["file_name"] if review_target else normalized_rel_path,
                    "changed_files": [item["file_name"] for item in changed_files],
                    "hidden_payload_detected": has_seen_payload_marker,
                    "hidden_payload_valid": hidden_payload_valid,
                    "sync_status": sync_status,
                    "sync_commit_id": sync_commit_id,
                    "sync_message": sync_message,
                    "sync_result": sync_result,
                }
                if warning:
                    done_payload["warning"] = warning
                LOGGER.warning(
                    "[review-trigger] done file=%s review_target=%s changed_files=%s draft_changed=%s write_confirmed=%s hidden_payload_detected=%s hidden_payload_valid=%s sync_status=%s sync_commit_id=%s routed_agent=%s",
                    normalized_rel_path,
                    review_target["file_name"] if review_target else normalized_rel_path,
                    [item["file_name"] for item in changed_files],
                    draft_changed,
                    write_confirmed,
                    has_seen_payload_marker,
                    hidden_payload_valid,
                    sync_status,
                    sync_commit_id,
                    dify_route.routed_agent,
                )
                yield _encode_sse_event("done", done_payload)

            conversation_id = None
            task_id = None
            answer_chunks: list[str] = []
            has_emitted_delta = False
            has_emitted_fallback_delta = False
            is_payload_mode = False
            has_seen_payload_marker = False
            pending_marker_tail = ""
            pending_think_tail = ""
            in_think_block = False
            active_think_buffer = ""
            hidden_files_buffer: list[str] = []
            hidden_payload_valid = False
            hidden_payload_error: str | None = None
            pipeline_sync_status = ""
            pipeline_sync_commit_id = ""
            pipeline_sync_message = ""
            pipeline_sync_result = ""
            max_dify_attempts = 2
            dify_attempt = 1
            mock_answer = payload.get("mock_ai_markdown")
            last_preview_signature = ""
            last_compacted_scratchpad_text = ""
            pending_reasoning_scratchpad = ""
            suppressing_reasoning_scratchpad = False
            pending_visible_scratchpad = ""
            suppressing_visible_scratchpad = False
            try:
                if isinstance(mock_answer, str):
                    conversation_id = payload.get("conversation_id")
                    if mock_answer:
                        answer_chunks.append(mock_answer)
                        has_emitted_delta = True
                        yield _encode_sse_event(
                            "delta",
                            {
                                "text": mock_answer,
                                "conversation_id": local_thread_id,
                                "upstream_conversation_id": conversation_id,
                                "thread_id": local_thread_id,
                            },
                        )
                else:
                    query = _build_dify_query(baseline_markdown, dify_payload)

                    inputs: dict[str, Any] = {
                        "book_id": book_id,
                        "chapter_index": _safe_int(dify_payload.get("chapter_index"), 0),
                        "active_file": normalized_rel_path,
                        "file_type": resolved_file_type,
                        "write_scope": resolved_write_scope,
                    }
                    raw_resolved_book_name = dify_payload.get("book_name")
                    if isinstance(raw_resolved_book_name, str) and raw_resolved_book_name.strip():
                        inputs["book_name"] = raw_resolved_book_name.strip()

                    raw_conversation_id = dify_payload.get("conversation_id")
                    if isinstance(raw_conversation_id, str) and raw_conversation_id.strip():
                        conversation_id = raw_conversation_id.strip()

                    raw_dify_user = dify_payload.get("dify_user")
                    dify_user = DEFAULT_DIFY_USER
                    if isinstance(raw_dify_user, str) and raw_dify_user.strip():
                        dify_user = raw_dify_user.strip()

                    def _mark_dify_conversation_reset(_old_conversation_id: str) -> None:
                        nonlocal conversation_id
                        conversation_id = None

                    retry_stream = False

                    def _iter_dify_streams():
                        nonlocal retry_stream
                        while dify_attempt <= max_dify_attempts:
                            retry_stream = False
                            for stream_event in chat_messages_stream(
                                base_url=dify_route.base_url,
                                api_key=dify_route.api_key,
                                query=query,
                                inputs=inputs,
                                user=dify_user,
                                conversation_id=conversation_id,
                                response_mode="streaming",
                                timeout_seconds=max(1, int(dify_route.timeout_seconds)),
                                on_conversation_reset=_mark_dify_conversation_reset,
                            ):
                                yield stream_event
                                if retry_stream:
                                    break
                            if retry_stream:
                                continue
                            break

                    for stream_event in _iter_dify_streams():
                        stream_conversation_id = _extract_stream_conversation_id(stream_event)
                        if stream_conversation_id:
                            conversation_id = stream_conversation_id
                        stream_task_id = _extract_stream_task_id(stream_event)
                        if stream_task_id:
                            task_id = stream_task_id

                        stage_payload = _build_stage_event_payload(stream_event)
                        if stage_payload:
                            if task_id:
                                stage_payload["task_id"] = task_id
                            yield _encode_sse_event("stage", stage_payload)

                        reasoning_payload = _extract_reasoning_payload(stream_event)
                        if reasoning_payload:
                            reasoning_text = str(reasoning_payload.get("text") or "")
                            if pending_reasoning_scratchpad:
                                if _contains_cjk_text(reasoning_text) and not _starts_like_internal_scratchpad_text(reasoning_text):
                                    compacted_text = _compact_agent_reasoning_text(pending_reasoning_scratchpad, "agent_thought")
                                    if compacted_text and compacted_text != last_compacted_scratchpad_text:
                                        last_compacted_scratchpad_text = compacted_text
                                        compact_payload = {
                                            "label": "已深度思考",
                                            "text": compacted_text,
                                            "source_event": "scratchpad_compacted",
                                            "status": "streaming",
                                        }
                                        if task_id:
                                            compact_payload["task_id"] = task_id
                                        yield _encode_sse_event("reasoning", compact_payload)
                                    pending_reasoning_scratchpad = ""
                                    suppressing_reasoning_scratchpad = False
                                else:
                                    pending_reasoning_scratchpad = f"{pending_reasoning_scratchpad} {reasoning_text}".strip()
                                    if _looks_like_internal_scratchpad_text(pending_reasoning_scratchpad) or len(pending_reasoning_scratchpad) >= 800:
                                        compacted_text = _compact_agent_reasoning_text(pending_reasoning_scratchpad, "agent_thought")
                                        if compacted_text and compacted_text != last_compacted_scratchpad_text:
                                            last_compacted_scratchpad_text = compacted_text
                                            compact_payload = {
                                                "label": "已深度思考",
                                                "text": compacted_text,
                                                "source_event": "scratchpad_compacted",
                                                "status": "streaming",
                                            }
                                            if task_id:
                                                compact_payload["task_id"] = task_id
                                            yield _encode_sse_event("reasoning", compact_payload)
                                        pending_reasoning_scratchpad = ""
                                        suppressing_reasoning_scratchpad = True
                                    continue
                            if suppressing_reasoning_scratchpad and not _contains_cjk_text(reasoning_text):
                                continue
                            if suppressing_reasoning_scratchpad and _contains_cjk_text(reasoning_text):
                                suppressing_reasoning_scratchpad = False
                            if _starts_like_internal_scratchpad_text(reasoning_text):
                                pending_reasoning_scratchpad = reasoning_text
                                if _looks_like_internal_scratchpad_text(pending_reasoning_scratchpad):
                                    compacted_text = _compact_agent_reasoning_text(pending_reasoning_scratchpad, "agent_thought")
                                    if compacted_text and compacted_text != last_compacted_scratchpad_text:
                                        last_compacted_scratchpad_text = compacted_text
                                        compact_payload = {
                                            "label": "已深度思考",
                                            "text": compacted_text,
                                            "source_event": "scratchpad_compacted",
                                            "status": "streaming",
                                        }
                                        if task_id:
                                            compact_payload["task_id"] = task_id
                                        yield _encode_sse_event("reasoning", compact_payload)
                                    pending_reasoning_scratchpad = ""
                                    suppressing_reasoning_scratchpad = True
                                continue
                            if task_id:
                                reasoning_payload["task_id"] = task_id
                            yield _encode_sse_event("reasoning", reasoning_payload)

                        if not has_emitted_delta:
                            preview_payload = _extract_preview_payload(stream_event)
                            if preview_payload:
                                preview_signature = (
                                    f"{preview_payload.get('label','')}|"
                                    f"{preview_payload.get('text','')}|"
                                    f"{preview_payload.get('source_event','')}"
                                )
                                if preview_signature != last_preview_signature:
                                    last_preview_signature = preview_signature
                                    if task_id:
                                        preview_payload["task_id"] = task_id
                                    yield _encode_sse_event("preview", preview_payload)

                        workflow_sync_meta = _extract_workflow_sync_meta(stream_event)
                        if workflow_sync_meta:
                            if workflow_sync_meta.get("sync_status"):
                                pipeline_sync_status = workflow_sync_meta["sync_status"]
                            if workflow_sync_meta.get("sync_commit_id"):
                                pipeline_sync_commit_id = workflow_sync_meta["sync_commit_id"]
                            if workflow_sync_meta.get("sync_message"):
                                pipeline_sync_message = workflow_sync_meta["sync_message"]
                            if workflow_sync_meta.get("sync_result"):
                                pipeline_sync_result = workflow_sync_meta["sync_result"]

                        workflow_failure_message = _extract_workflow_failure_message(stream_event)
                        if workflow_failure_message:
                            after_snapshots = _draft_file_snapshots(repo_dir, dify_route.writable_exact_files)
                            draft_changed = bool(_changed_draft_files(before_snapshots, after_snapshots))
                            has_sync_side_effect = bool(
                                pipeline_sync_status
                                or pipeline_sync_commit_id
                                or pipeline_sync_message
                                or pipeline_sync_result
                            )
                            can_retry_workflow_failure = (
                                dify_attempt < max_dify_attempts
                                and _is_transient_workflow_failure(workflow_failure_message)
                                and not has_emitted_delta
                                and not has_emitted_fallback_delta
                                and not has_seen_payload_marker
                                and not is_payload_mode
                                and not draft_changed
                                and not has_sync_side_effect
                            )
                            LOGGER.warning(
                                "[review-trigger] workflow_failure file=%s routed_agent=%s attempt=%s retry=%s message=%s",
                                normalized_rel_path,
                                dify_route.routed_agent,
                                dify_attempt,
                                can_retry_workflow_failure,
                                workflow_failure_message,
                            )
                            if can_retry_workflow_failure:
                                yield _encode_sse_event(
                                    "stage",
                                    {
                                        "stage_code": "dify_retry",
                                        "stage_text": "Dify \u4e34\u65f6\u5931\u8d25\uff0c\u6b63\u5728\u81ea\u52a8\u91cd\u8bd5 1/1...",
                                        "source_event": "workflow_failed",
                                        "status": "streaming",
                                    },
                                )
                                dify_attempt += 1
                                conversation_id = None
                                task_id = None
                                retry_stream = True
                                continue
                            yield _encode_sse_event(
                                "error",
                                {
                                    "code": "DIFY_WORKFLOW_FAILED",
                                    "message": workflow_failure_message,
                                    "status": 502,
                                },
                            )
                            return

                        text_chunk = _extract_stream_text_chunk(stream_event)
                        if text_chunk:
                            if is_payload_mode:
                                hidden_files_buffer.append(text_chunk)
                            else:
                                think_segments, in_think_block, pending_think_tail = _split_text_and_think_blocks(
                                    text_chunk,
                                    in_think_block=in_think_block,
                                    pending_tail=pending_think_tail,
                                )
                                for segment_type, segment_text in think_segments:
                                    if segment_type == "think_stream":
                                        if not segment_text:
                                            continue
                                        active_think_buffer = f"{active_think_buffer}{segment_text}"
                                        yield _encode_sse_event(
                                            "reasoning",
                                            {
                                                "label": "已深度思考",
                                                "text": segment_text,
                                                "append": True,
                                                "source_event": "think_block",
                                                "status": "streaming",
                                            },
                                        )
                                        continue
                                    if segment_type == "think_complete":
                                        if segment_text:
                                            active_think_buffer = f"{active_think_buffer}{segment_text}"
                                        if not active_think_buffer:
                                            continue
                                        yield _encode_sse_event(
                                            "reasoning",
                                            {
                                                "label": "已深度思考",
                                                "text": active_think_buffer,
                                                "source_event": "think_block",
                                                "status": "done",
                                            },
                                        )
                                        active_think_buffer = ""
                                        continue
                                    if not segment_text:
                                        continue
                                    if pending_visible_scratchpad:
                                        if _contains_cjk_text(segment_text) and not _starts_like_internal_scratchpad_text(segment_text):
                                            compacted_text = _compact_agent_reasoning_text(pending_visible_scratchpad, "agent_thought")
                                            if compacted_text and compacted_text != last_compacted_scratchpad_text:
                                                last_compacted_scratchpad_text = compacted_text
                                                yield _encode_sse_event(
                                                    "reasoning",
                                                    {
                                                        "label": "已深度思考",
                                                        "text": compacted_text,
                                                        "source_event": "scratchpad_compacted",
                                                        "status": "streaming",
                                                    },
                                                )
                                            pending_visible_scratchpad = ""
                                            suppressing_visible_scratchpad = False
                                        else:
                                            pending_visible_scratchpad = f"{pending_visible_scratchpad}{segment_text}"
                                            if _looks_like_internal_scratchpad_text(pending_visible_scratchpad) or len(pending_visible_scratchpad) >= 800:
                                                compacted_text = _compact_agent_reasoning_text(pending_visible_scratchpad, "agent_thought")
                                                if compacted_text and compacted_text != last_compacted_scratchpad_text:
                                                    last_compacted_scratchpad_text = compacted_text
                                                    yield _encode_sse_event(
                                                        "reasoning",
                                                        {
                                                            "label": "已深度思考",
                                                            "text": compacted_text,
                                                            "source_event": "scratchpad_compacted",
                                                            "status": "streaming",
                                                        },
                                                    )
                                                pending_visible_scratchpad = ""
                                                suppressing_visible_scratchpad = True
                                            continue
                                    if suppressing_visible_scratchpad and not _contains_cjk_text(segment_text):
                                        continue
                                    if suppressing_visible_scratchpad and _contains_cjk_text(segment_text):
                                        suppressing_visible_scratchpad = False
                                    if not has_emitted_delta and _starts_like_internal_scratchpad_text(segment_text):
                                        pending_visible_scratchpad = segment_text
                                        if _looks_like_internal_scratchpad_text(pending_visible_scratchpad):
                                            compacted_text = _compact_agent_reasoning_text(pending_visible_scratchpad, "agent_thought")
                                            if compacted_text and compacted_text != last_compacted_scratchpad_text:
                                                last_compacted_scratchpad_text = compacted_text
                                                yield _encode_sse_event(
                                                    "reasoning",
                                                    {
                                                        "label": "已深度思考",
                                                        "text": compacted_text,
                                                        "source_event": "scratchpad_compacted",
                                                        "status": "streaming",
                                                    },
                                                )
                                            pending_visible_scratchpad = ""
                                            suppressing_visible_scratchpad = True
                                        continue
                                    if _looks_like_internal_scratchpad_text(segment_text):
                                        compacted_text = _compact_agent_reasoning_text(segment_text, "agent_thought")
                                        if compacted_text and compacted_text != last_compacted_scratchpad_text:
                                            last_compacted_scratchpad_text = compacted_text
                                            yield _encode_sse_event(
                                                "reasoning",
                                                {
                                                    "label": "已深度思考",
                                                    "text": compacted_text,
                                                    "source_event": "scratchpad_compacted",
                                                    "status": "streaming",
                                                },
                                            )
                                        continue

                                    visible_text, next_pending_tail, payload_seed, reached_payload_mode = _split_visible_stream_text(
                                        segment_text, pending_marker_tail
                                    )
                                    pending_marker_tail = next_pending_tail
                                    if visible_text:
                                        answer_chunks.append(visible_text)
                                        has_emitted_delta = True
                                        yield _encode_sse_event(
                                            "delta",
                                            {
                                                "text": visible_text,
                                                "conversation_id": local_thread_id,
                                                "upstream_conversation_id": conversation_id,
                                                "thread_id": local_thread_id,
                                                "task_id": task_id,
                                            },
                                        )
                                    if reached_payload_mode:
                                        is_payload_mode = True
                                        has_seen_payload_marker = True
                                        pending_marker_tail = ""
                                        if payload_seed:
                                            hidden_files_buffer.append(payload_seed)
                        elif not has_emitted_delta and not has_emitted_fallback_delta:
                            event_name = _normalize_stream_event_name(stream_event)
                            if event_name == "workflow_finished":
                                fallback_text = _extract_workflow_output_text(stream_event)
                                if fallback_text:
                                    if is_payload_mode:
                                        hidden_files_buffer.append(fallback_text)
                                    else:
                                        think_segments, in_think_block, pending_think_tail = _split_text_and_think_blocks(
                                            fallback_text,
                                            in_think_block=in_think_block,
                                            pending_tail=pending_think_tail,
                                        )
                                        for segment_type, segment_text in think_segments:
                                            if segment_type == "think_stream":
                                                if not segment_text:
                                                    continue
                                                active_think_buffer = f"{active_think_buffer}{segment_text}"
                                                yield _encode_sse_event(
                                                    "reasoning",
                                                    {
                                                        "label": "已深度思考",
                                                        "text": segment_text,
                                                        "append": True,
                                                        "source_event": "think_block",
                                                        "status": "streaming",
                                                    },
                                                )
                                                continue
                                            if segment_type == "think_complete":
                                                if segment_text:
                                                    active_think_buffer = f"{active_think_buffer}{segment_text}"
                                                if not active_think_buffer:
                                                    continue
                                                yield _encode_sse_event(
                                                    "reasoning",
                                                    {
                                                        "label": "已深度思考",
                                                        "text": active_think_buffer,
                                                        "source_event": "think_block",
                                                        "status": "done",
                                                    },
                                                )
                                                active_think_buffer = ""
                                                continue
                                            if not segment_text:
                                                continue
                                            if pending_visible_scratchpad:
                                                if _contains_cjk_text(segment_text) and not _starts_like_internal_scratchpad_text(segment_text):
                                                    compacted_text = _compact_agent_reasoning_text(pending_visible_scratchpad, "agent_thought")
                                                    if compacted_text and compacted_text != last_compacted_scratchpad_text:
                                                        last_compacted_scratchpad_text = compacted_text
                                                        yield _encode_sse_event(
                                                            "reasoning",
                                                            {
                                                                "label": "已深度思考",
                                                                "text": compacted_text,
                                                                "source_event": "scratchpad_compacted",
                                                                "status": "streaming",
                                                            },
                                                        )
                                                    pending_visible_scratchpad = ""
                                                    suppressing_visible_scratchpad = False
                                                else:
                                                    pending_visible_scratchpad = f"{pending_visible_scratchpad}{segment_text}"
                                                    if _looks_like_internal_scratchpad_text(pending_visible_scratchpad) or len(pending_visible_scratchpad) >= 800:
                                                        compacted_text = _compact_agent_reasoning_text(pending_visible_scratchpad, "agent_thought")
                                                        if compacted_text and compacted_text != last_compacted_scratchpad_text:
                                                            last_compacted_scratchpad_text = compacted_text
                                                            yield _encode_sse_event(
                                                                "reasoning",
                                                                {
                                                                    "label": "已深度思考",
                                                                    "text": compacted_text,
                                                                    "source_event": "scratchpad_compacted",
                                                                    "status": "streaming",
                                                                },
                                                            )
                                                        pending_visible_scratchpad = ""
                                                        suppressing_visible_scratchpad = True
                                                    continue
                                            if suppressing_visible_scratchpad and not _contains_cjk_text(segment_text):
                                                continue
                                            if suppressing_visible_scratchpad and _contains_cjk_text(segment_text):
                                                suppressing_visible_scratchpad = False
                                            if not has_emitted_delta and _starts_like_internal_scratchpad_text(segment_text):
                                                pending_visible_scratchpad = segment_text
                                                if _looks_like_internal_scratchpad_text(pending_visible_scratchpad):
                                                    compacted_text = _compact_agent_reasoning_text(pending_visible_scratchpad, "agent_thought")
                                                    if compacted_text and compacted_text != last_compacted_scratchpad_text:
                                                        last_compacted_scratchpad_text = compacted_text
                                                        yield _encode_sse_event(
                                                            "reasoning",
                                                            {
                                                                "label": "已深度思考",
                                                                "text": compacted_text,
                                                                "source_event": "scratchpad_compacted",
                                                                "status": "streaming",
                                                            },
                                                        )
                                                    pending_visible_scratchpad = ""
                                                    suppressing_visible_scratchpad = True
                                                continue
                                            if _looks_like_internal_scratchpad_text(segment_text):
                                                compacted_text = _compact_agent_reasoning_text(segment_text, "agent_thought")
                                                if compacted_text and compacted_text != last_compacted_scratchpad_text:
                                                    last_compacted_scratchpad_text = compacted_text
                                                    yield _encode_sse_event(
                                                        "reasoning",
                                                        {
                                                            "label": "已深度思考",
                                                            "text": compacted_text,
                                                            "source_event": "scratchpad_compacted",
                                                            "status": "streaming",
                                                        },
                                                    )
                                                continue
                                            (
                                                visible_fallback,
                                                next_pending_tail,
                                                payload_seed,
                                                reached_payload_mode,
                                            ) = _split_visible_stream_text(segment_text, pending_marker_tail)
                                            pending_marker_tail = next_pending_tail
                                            if visible_fallback:
                                                has_emitted_fallback_delta = True
                                                has_emitted_delta = True
                                                answer_chunks.append(visible_fallback)
                                                yield _encode_sse_event(
                                                    "delta",
                                                    {
                                                        "text": visible_fallback,
                                                        "conversation_id": local_thread_id,
                                                        "upstream_conversation_id": conversation_id,
                                                        "thread_id": local_thread_id,
                                                        "task_id": task_id,
                                                        "source": "workflow_finished.outputs.text",
                                                    },
                                                )
                                            if reached_payload_mode:
                                                is_payload_mode = True
                                                has_seen_payload_marker = True
                                                pending_marker_tail = ""
                                                if payload_seed:
                                                    hidden_files_buffer.append(payload_seed)
                if pending_marker_tail and not is_payload_mode:
                    answer_chunks.append(pending_marker_tail)
                    has_emitted_delta = True
                    yield _encode_sse_event(
                        "delta",
                        {
                            "text": pending_marker_tail,
                            "conversation_id": local_thread_id,
                            "upstream_conversation_id": conversation_id,
                            "thread_id": local_thread_id,
                            "task_id": task_id,
                            "source": "marker_tail_flush",
                        },
                    )
                parsed_hidden_files: list[dict[str, str]] = []
                if has_seen_payload_marker:
                    hidden_payload = "".join(hidden_files_buffer)
                    parsed_hidden_files, hidden_payload_error = _parse_json_payload(
                        hidden_payload,
                        set(dify_route.writable_exact_files),
                    )
                    hidden_payload_valid = not hidden_payload_error and bool(parsed_hidden_files)
                    if not hidden_payload_valid:
                        LOGGER.warning(
                            "[review-trigger] hidden_payload_invalid file=%s routed_agent=%s error=%s",
                            normalized_rel_path,
                            dify_route.routed_agent,
                            hidden_payload_error or "marker detected but payload is invalid",
                        )
                        yield _encode_sse_event(
                            "error",
                            {
                                "code": "JSON_PAYLOAD_INVALID",
                                "message": hidden_payload_error or "marker detected but payload is invalid",
                                "status": 422,
                            },
                        )
                        return
                    LOGGER.warning(
                        "[compat-path] hidden payload detected file=%s routed_agent=%s files=%s",
                        normalized_rel_path,
                        dify_route.routed_agent,
                        [entry.get("file_name") for entry in parsed_hidden_files],
                    )
                merged_answer = "".join(answer_chunks)
                yield from _emit_completion_events(
                    conversation_id=conversation_id,
                    task_id=task_id,
                    merged_answer=merged_answer,
                    sync_status=pipeline_sync_status,
                    sync_commit_id=pipeline_sync_commit_id,
                    sync_message=pipeline_sync_message,
                    sync_result=pipeline_sync_result,
                )
            except DifyClientError as exc:
                message = str(exc)
                if exc.response_body:
                    message = f"{message}; response={exc.response_body}"
                after_snapshots = _draft_file_snapshots(repo_dir, dify_route.writable_exact_files)
                changed_files = _changed_draft_files(before_snapshots, after_snapshots)
                draft_changed = bool(changed_files)
                review_target = next(
                    (item for item in changed_files if item["file_name"] == normalized_rel_path),
                    changed_files[0] if changed_files else None,
                )
                if draft_changed:
                    merged_answer = "".join(answer_chunks)
                    yield from _emit_completion_events(
                        conversation_id=conversation_id,
                        task_id=task_id,
                        merged_answer=merged_answer,
                        sync_status="timeout_after_write",
                        sync_commit_id=(review_target["after"].get("commit_id", "") or "") if review_target else "",
                        sync_message=message,
                        warning="Dify API timed out after draft write; recovered from draft snapshot.",
                        write_confirmed_override=False,
                        after_snapshots=after_snapshots,
                    )
                    return
                status = 502
                if isinstance(exc.status_code, int) and 400 <= exc.status_code < 500:
                    status = 400
                yield _encode_sse_event(
                    "error",
                    {
                        "code": "DIFY_API_FAILED",
                        "message": message,
                        "status": status,
                    },
                )
            except Exception as exc:
                yield _encode_sse_event(
                    "error",
                    {
                        "code": "DIFY_STREAM_FAILED",
                        "message": str(exc),
                        "status": 500,
                    },
                )

        return Response(
            stream_with_context(_stream()),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @bp.post("/api/world/sync")
    def sync_world_model_legacy():
        payload, err = parse_json_payload(["content"])
        if err:
            return err
        assert payload is not None

        book_id, book_err = require_book_id(payload)
        if book_err:
            return book_err
        raw_book_name = payload.get("book_name")
        normalized_book_name = raw_book_name.strip() if isinstance(raw_book_name, str) and raw_book_name.strip() else None
        paths, _, layout_err = _ensure_ai_route_layout_ready(
            book_id,
            storage_root,
            book_name=normalized_book_name,
        )
        if layout_err:
            return layout_err
        assert paths is not None
        world_etag = _compute_file_etag(paths["world_model_path"])

        human_markdown = _normalize_text(payload.get("content"))
        ai_markdown = call_dify_api(
            human_markdown,
            payload,
            dify_base_url=dify_base_url,
            dify_api_key=dify_api_key,
            dify_timeout_seconds=dify_timeout_seconds,
        )
        legacy_payload = {
            "book_id": book_id,
            "origin": payload.get("origin", "ai"),
            "message": payload.get("message", "legacy world sync via draft sandbox"),
            "writes": [
                {
                    "file_name": "world_model.md",
                    "op": "update",
                    "content": ai_markdown,
                    "base_etag": payload.get("base_etag") or world_etag,
                }
            ],
        }
        response = _sync_all_from_payload(legacy_payload, legacy_route=True)
        if isinstance(response, tuple) and len(response) == 2:
            response_obj, status_code = response
            try:
                body = response_obj.get_json(silent=True)
            except Exception:
                body = None
            if isinstance(body, dict) and status_code == 200:
                body["content"] = ai_markdown
                return jsonify(body), status_code
        return response

    @bp.post("/api/draft/rollback")
    def rollback_draft():
        payload, err = parse_json_payload(["commit_hash"])
        if err:
            return err
        assert payload is not None

        book_id, book_err = require_book_id(payload)
        if book_err:
            return book_err

        target_hash = payload.get("commit_hash")
        if not isinstance(target_hash, str) or not target_hash.strip():
            return json_error("MISSING_FIELD", "commit_hash is required", 400)

        paths, _, layout_err = _ensure_ai_route_layout_ready(book_id, storage_root)
        if layout_err:
            return layout_err
        assert paths is not None
        repo_dir = paths["book_dir"]

        try:
            _ensure_gitpython_or_raise()
            with _repo_lock(repo_dir):
                repo = Repo(repo_dir)
                mainline_branch = _resolve_mainline_branch(repo)
                has_draft, migrated_from_legacy = _ensure_draft_branch(
                    repo,
                    mainline_branch,
                    create_if_missing=False,
                )
                if not has_draft:
                    return json_error("DRAFT_BRANCH_NOT_FOUND", "draft branch does not exist", 404)

                repo.git.checkout(DRAFT_BRANCH_NAME)
                repo.git.reset("--hard", target_hash.strip())

                response_body = {
                    "status": "success",
                    "book_id": book_id,
                    "branch": DRAFT_BRANCH_NAME,
                    "commit_id": repo.head.commit.hexsha,
                    "content": _read_file_text(paths["world_model_path"]),
                }
                if migrated_from_legacy:
                    response_body["warning"] = (
                        "legacy draft branch draft/world_model has been migrated to draft/sandbox"
                    )
                return jsonify(response_body), 200
        except GitCommandError as exc:
            return json_error("GIT_OPERATION_FAILED", str(exc), 500)
        except Exception as exc:
            return json_error("DRAFT_ROLLBACK_FAILED", str(exc), 500)

    @bp.post("/api/world/rollback")
    def rollback_world_legacy():
        return _attach_warning(rollback_draft(), "deprecated route: use /api/draft/rollback")

    @bp.post("/api/draft/confirm")
    def confirm_draft():
        payload = request.get_json(silent=True)
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            return json_error("INVALID_PAYLOAD", "request body must be application/json object", 400)

        book_id, book_err = require_book_id(payload)
        if book_err:
            return book_err

        paths, _, layout_err = _ensure_ai_route_layout_ready(book_id, storage_root)
        if layout_err:
            return layout_err
        assert paths is not None
        repo_dir = paths["book_dir"]

        try:
            _ensure_gitpython_or_raise()
            with _repo_lock(repo_dir):
                repo = Repo(repo_dir)

                mainline_branch = _resolve_mainline_branch(repo)
                has_draft, migrated_from_legacy = _ensure_draft_branch(
                    repo,
                    mainline_branch,
                    create_if_missing=False,
                )
                if not has_draft:
                    return json_error("DRAFT_BRANCH_NOT_FOUND", "draft branch does not exist", 404)

                head_names = {head.name for head in repo.heads}
                if mainline_branch not in head_names:
                    return json_error("MAINLINE_BRANCH_NOT_FOUND", f"{mainline_branch} branch does not exist", 404)

                changed_files = [
                    item["file_name"]
                    for item in _changed_draft_files(
                        {CHAPTER_DRAFT_FILE: _mainline_file_snapshot(repo_dir, CHAPTER_DRAFT_FILE)},
                        {CHAPTER_DRAFT_FILE: _draft_file_snapshot(repo_dir, CHAPTER_DRAFT_FILE)},
                    )
                ]
                should_canonize_chapter_draft = CHAPTER_DRAFT_FILE in changed_files
                materialized_chapters: list[dict[str, Any]] = []
                canon_commit_id = ""
                draft_reset_commit_id = ""
                if should_canonize_chapter_draft:
                    repo.git.checkout(DRAFT_BRANCH_NAME)
                    draft_markdown = _read_branch_file(repo_dir, DRAFT_BRANCH_NAME, CHAPTER_DRAFT_FILE)
                    planned_chapters, canon_error = _plan_chapter_draft_canonization(
                        chapters_dir=paths["chapters_dir"],
                        draft_markdown=draft_markdown,
                    )
                    if canon_error:
                        repo.git.checkout(mainline_branch)
                        return json_error(
                            canon_error["code"],
                            canon_error["message"],
                            int(canon_error["status"]),
                        )
                    materialized_chapters, canon_commit_id = _write_planned_chapter_files(
                        repo=repo,
                        repo_dir=repo_dir,
                        chapters_dir=paths["chapters_dir"],
                        planned=planned_chapters,
                    )

                repo.git.checkout(mainline_branch)
                repo.git.merge(DRAFT_BRANCH_NAME)
                if materialized_chapters:
                    draft_reset_commit_id = _reset_canonized_chapter_draft(
                        repo=repo,
                        repo_dir=repo_dir,
                    )
                repo.delete_head(DRAFT_BRANCH_NAME, force=True)
                remaining_heads = {head.name for head in repo.heads}
                draft_branch_deleted = DRAFT_BRANCH_NAME not in remaining_heads

                response_body = {
                    "status": "success",
                    "book_id": book_id,
                    "mainline_branch": mainline_branch,
                    "merged_branch": DRAFT_BRANCH_NAME,
                    "commit_id": repo.head.commit.hexsha,
                    "draft_branch_deleted": draft_branch_deleted,
                    "materialized_chapters": materialized_chapters,
                    "chapter_canon_commit_id": canon_commit_id,
                    "chapter_draft_reset_commit_id": draft_reset_commit_id,
                    "post_confirm_payload": _build_post_confirm_world_payload(
                        book_id=book_id,
                        materialized_chapters=materialized_chapters,
                    ),
                    "post_confirm_actions": (
                        [
                            {
                                "action": "distill_status_card",
                                "agent_key": "world_model",
                                "target_file": "status_card.md",
                                "required": True,
                            },
                            {
                                "action": "consider_world_model_update",
                                "agent_key": "world_model",
                                "target_file": "world_model.md",
                                "required": False,
                            },
                        ]
                        if materialized_chapters
                        else []
                    ),
                }
                if migrated_from_legacy:
                    response_body["warning"] = (
                        "legacy draft branch draft/world_model has been migrated to draft/sandbox"
                    )
                return jsonify(response_body), 200
        except GitCommandError as exc:
            message = str(exc)
            if "CONFLICT" in message.upper():
                return json_error("MERGE_CONFLICT", message, 409)
            return json_error("GIT_OPERATION_FAILED", message, 500)
        except Exception as exc:
            return json_error("DRAFT_CONFIRM_FAILED", str(exc), 500)

    @bp.post("/api/world/confirm")
    def confirm_world_legacy():
        return _attach_warning(confirm_draft(), "deprecated route: use /api/draft/confirm")

    # ── LangGraph batch init pipeline ──────────────────────────────────
    @bp.post("/api/world/init_batch_pipeline")
    def init_batch_pipeline():
        """Trigger LangGraph iterative-refinement pipeline to initialize
        world_model.md from all summary.md Batch Archives."""
        import json as _json
        import threading
        from queue import Queue, Empty
        from pipelines.batch_parser import parse_summary_batches
        from pipelines.world_model_init import run_pipeline

        payload = request.get_json(silent=True) or {}
        book_id, book_err = require_book_id(payload)
        if book_err:
            return book_err
        force_rebuild = payload.get("force_rebuild") is True

        paths, _, layout_err = _ensure_ai_route_layout_ready(book_id, storage_root)
        if layout_err:
            return layout_err
        assert paths is not None
        book_dir = paths["book_dir"]
        summary_path = paths["summary_path"]

        if not os.path.exists(summary_path):
            return json_error("SUMMARY_NOT_FOUND", "summary.md not found", 404)

        sse_queue: Queue = Queue()

        def _sse(event: str, data: dict) -> str:
            return f"event: {event}\ndata: {_json.dumps(data, ensure_ascii=False)}\n\n"

        def generate():
            all_batches = parse_summary_batches(summary_path)
            yield _sse("ack", {"total_batches": len(all_batches), "book_id": book_id, "force_rebuild": force_rebuild})

            # Run pipeline in background thread, drain SSE queue concurrently
            pipeline_error = [None]
            def _run():
                try:
                    run_pipeline(
                        book_id=book_id,
                        book_dir=book_dir,
                        summary_path=summary_path,
                        sse_queue=sse_queue,
                        force_rebuild=force_rebuild,
                    )
                except Exception as exc:
                    pipeline_error[0] = str(exc)
                    sse_queue.put({"event": "error", "data": {"message": str(exc)}})

            t = threading.Thread(target=_run, daemon=True)
            t.start()

            try:
                while t.is_alive() or not sse_queue.empty():
                    try:
                        evt = sse_queue.get(timeout=1.0)
                        yield _sse(evt["event"], evt["data"])
                    except Empty:
                        continue
            except GeneratorExit:
                pass
            finally:
                if pipeline_error[0]:
                    yield _sse("error", {"message": pipeline_error[0]})
                yield _sse("pipeline_end", {})

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return bp
