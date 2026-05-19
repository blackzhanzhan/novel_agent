import json
import logging
import os
import re
import subprocess
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
from typing import Any, Callable

from flask import Blueprint, jsonify, request

from utils.book_storage import (
    TRACKED_LAYOUT_FILES,
    ensure_book_layout,
    get_book_paths,
    get_virtual_core_file_content,
    inspect_book_layout_integrity,
    repair_book_layout,
)
from utils.file_lock import exclusive_file_lock
from utils.git_utils import ensure_repo, format_git_error, is_nothing_to_commit_error, run_git
from utils.markdown_sections import (
    MarkdownPatchApplyError,
    MarkdownSectionAmbiguousError,
    MarkdownSectionError,
    MarkdownSectionNotFoundError,
    apply_markdown_patch,
    build_markdown_outline,
    extract_markdown_section,
)

ALLOWED_EXTENSIONS = {".md", ".json"}
MAX_ARCHIVE_RANGE_LINES = 500
MAX_COLD_ARCHIVE_RANGE_LINES = 100
CORE_ARCHIVE_FILES = {
    "world_model.md",
    "summary.md",
    "status_card.md",
    "style_guide.md",
    "style_fingerprint.md",
    "style_review.md",
    "style_constraints_for_continuation.md",
    "error_archive.md",
    "domain_rules.md",
}
CORE_HOT_FILE_LABELS = {
    "world_model.md": "世界观底座",
    "status_card.md": "状态卡",
    "summary.md": "剧情总纲",
    "style_guide.md": "文风指南",
    "style_fingerprint.md": "叙事结构指纹",
    "style_review.md": "作者可读审查",
    "style_constraints_for_continuation.md": "续写硬约束",
    "error_archive.md": "错误档案",
    "domain_rules.md": "领域规则",
    "brainstorm.md": "头脑风暴",
    "master_outline.md": "总纲",
    "arc_outline.md": "篇章大纲",
    "chapter_outline.md": "逐章大纲",
    "chapter_draft.md": "续写草稿",
}
CORE_FILE_BLACKLIST_FOR_COLD_READ = {
    "summary.md",
    "world_model.md",
    "status_card.md",
}
COLD_ARCHIVE_NAME_PATTERNS = (
    re.compile(r"^chapter_.+\.md$", re.IGNORECASE),
    re.compile(r"^\d+.*\.md$"),
)
LOCKS_DIR_NAME = ".locks"
CONFLICTS_DIR_NAME = "conflicts"
ORIGIN_PREFIX_MAP = {
    "ai": "[AI_Update]",
    "explicit_user_write": "[AI_Update]",
    "user": "[User_Edit]",
}
MARKDOWN_SECTION_WRITE_ORIGIN = "explicit_user_write"
AI_WRITE_LOOP_GUARD_TARGETS = {"chapter_draft.md"}
AI_WRITE_LOOP_GUARD_PREFIX = "[AI_Update]"
AI_WRITE_LOOP_GUARD_MAX_RECENT_COMMITS = 6
AI_WRITE_LOOP_GUARD_WINDOW_SECONDS = 2 * 60 * 60
AI_WRITE_LOOP_GUARD_SUBJECT_RE = re.compile(
    r"\b(repair|round|final|length|style|tweak|padding|push|loop)\b",
    re.IGNORECASE,
)
LOGGER = logging.getLogger(__name__)


def _normalize_file_name(raw: Any) -> str:
    if not isinstance(raw, str) or not raw.strip():
        return ""
    normalized = raw.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _resolve_target_file(book_dir: str, file_name: str) -> tuple[str, str]:
    if not file_name:
        raise ValueError("file_name is required")
    if file_name.startswith("/"):
        raise ValueError("file_name must be a relative path")

    rel_path = os.path.normpath(file_name.replace("/", os.sep))
    if rel_path in {"", ".", os.pardir}:
        raise ValueError("file_name is invalid")
    if rel_path.startswith(os.pardir + os.sep):
        raise ValueError("file_name escapes book directory")
    if any(part == ".git" for part in rel_path.split(os.sep)):
        raise ValueError("file_name cannot target git internals")

    abs_book_dir = os.path.abspath(book_dir)
    abs_file_path = os.path.abspath(os.path.join(abs_book_dir, rel_path))
    if os.path.commonpath([abs_file_path, abs_book_dir]) != abs_book_dir:
        raise ValueError("file_name escapes book directory")

    ext = os.path.splitext(abs_file_path)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError("only .md and .json files are allowed")

    return abs_file_path, rel_path.replace(os.sep, "/")


def _is_allowed_cold_archive_name(file_name: str) -> bool:
    lowered = file_name.lower()
    if lowered in CORE_FILE_BLACKLIST_FOR_COLD_READ:
        return False
    return any(pattern.fullmatch(file_name) for pattern in COLD_ARCHIVE_NAME_PATTERNS)


def _extract_chapter_index_key(file_name: str) -> str | None:
    match = re.search(r"(\d+)", file_name)
    if not match:
        return None
    token = match.group(1)
    try:
        value = int(token)
    except ValueError:
        return None
    return f"{value:04d}"


def _find_chapter_file_by_prefix(chapters_dir: str, prefix_key: str) -> tuple[str, str] | None:
    if not os.path.isdir(chapters_dir):
        return None
    target_prefix = f"{prefix_key}_"
    for name in sorted(os.listdir(chapters_dir)):
        if not name.startswith(target_prefix):
            continue
        candidate_path = os.path.abspath(os.path.join(chapters_dir, name))
        if not os.path.isfile(candidate_path):
            continue
        return candidate_path, f"chapters/{name}"
    return None


def _resolve_cold_archive_file(book_dir: str, file_name: str) -> tuple[str, str]:
    if not file_name:
        raise ValueError("file_name is required")
    if file_name.startswith("/"):
        raise ValueError("file_name must be a relative path")

    rel_path = os.path.normpath(file_name.replace("/", os.sep))
    if rel_path in {"", ".", os.pardir}:
        raise ValueError("file_name is invalid")
    if rel_path.startswith(os.pardir + os.sep):
        raise ValueError("file_name escapes book directory")
    if any(part == ".git" for part in rel_path.split(os.sep)):
        raise ValueError("file_name cannot target git internals")

    normalized_rel_path = rel_path.replace(os.sep, "/")
    base_name = os.path.basename(rel_path)
    if base_name.lower() in CORE_FILE_BLACKLIST_FOR_COLD_READ:
        raise ValueError("file_name is forbidden for cold archive reader")
    chapter_index_key = _extract_chapter_index_key(base_name)
    if not _is_allowed_cold_archive_name(base_name) and chapter_index_key is None:
        raise ValueError("file_name must match chapter_*.md or ^\\d+.*\\.md$ or contain numeric chapter index")

    abs_book_dir = os.path.abspath(book_dir)
    chapters_dir = os.path.abspath(os.path.join(abs_book_dir, "chapters"))
    if os.path.commonpath([chapters_dir, abs_book_dir]) != abs_book_dir:
        raise ValueError("chapters directory escapes book directory")

    candidates: list[tuple[str, str]] = []
    if "/" in normalized_rel_path:
        if normalized_rel_path.count("/") > 1 or not normalized_rel_path.startswith("chapters/"):
            raise ValueError("cold archive file_name must be root filename or chapters/<filename>")
        if os.path.dirname(normalized_rel_path) != "chapters":
            raise ValueError("nested cold archive subdirectories are not allowed")
        abs_file_path = os.path.abspath(os.path.join(abs_book_dir, normalized_rel_path.replace("/", os.sep)))
        if os.path.commonpath([abs_file_path, chapters_dir]) != chapters_dir:
            raise ValueError("file_name escapes chapters directory")
        candidates.append((abs_file_path, normalized_rel_path))
    else:
        chapters_candidate = os.path.abspath(os.path.join(chapters_dir, base_name))
        if os.path.commonpath([chapters_candidate, chapters_dir]) != chapters_dir:
            raise ValueError("file_name escapes chapters directory")
        root_candidate = os.path.abspath(os.path.join(abs_book_dir, base_name))
        if os.path.commonpath([root_candidate, abs_book_dir]) != abs_book_dir:
            raise ValueError("file_name escapes book directory")
        candidates.append((chapters_candidate, f"chapters/{base_name}"))
        candidates.append((root_candidate, base_name))

    for candidate_path, candidate_rel in candidates:
        if os.path.exists(candidate_path):
            return candidate_path, candidate_rel

    if chapter_index_key is not None:
        prefix_hit = _find_chapter_file_by_prefix(chapters_dir, chapter_index_key)
        if prefix_hit is not None:
            return prefix_hit
    return candidates[0]


def _build_commit_message(origin: Any, message: Any, file_name: str) -> str:
    origin_key = origin.strip().lower() if isinstance(origin, str) else ""
    prefix = ORIGIN_PREFIX_MAP.get(origin_key, "[System_Update]")
    base_message = f"update {file_name}"
    if isinstance(message, str) and message.strip():
        base_message = message.strip()
    return f"{prefix} {base_message}"


def _recent_ai_write_commits(
    repo_dir: str,
    normalized_rel_path: str,
    *,
    now_ts: int | None = None,
    max_scan: int = 50,
) -> list[dict[str, Any]]:
    if normalized_rel_path not in AI_WRITE_LOOP_GUARD_TARGETS:
        return []
    now = now_ts if now_ts is not None else int(datetime.now(timezone.utc).timestamp())
    try:
        output = run_git(
            repo_dir,
            [
                "log",
                f"--max-count={max_scan}",
                "--pretty=format:%H%x1f%ct%x1f%s",
                "--",
                normalized_rel_path,
            ],
        ).stdout
    except subprocess.CalledProcessError:
        return []

    commits: list[dict[str, Any]] = []
    for raw_line in output.splitlines():
        commit_id, sep, rest = raw_line.partition("\x1f")
        if not sep:
            continue
        raw_ts, sep, subject = rest.partition("\x1f")
        if not sep:
            continue
        try:
            commit_ts = int(raw_ts)
        except ValueError:
            continue
        if now - commit_ts > AI_WRITE_LOOP_GUARD_WINDOW_SECONDS:
            break
        if not subject.startswith(AI_WRITE_LOOP_GUARD_PREFIX):
            break
        if not AI_WRITE_LOOP_GUARD_SUBJECT_RE.search(subject):
            break
        commits.append(
            {
                "commit_id": commit_id,
                "timestamp": commit_ts,
                "subject": subject,
            }
        )
    return commits


def _ai_write_loop_guard_message(repo_dir: str, normalized_rel_path: str) -> str | None:
    recent_commits = _recent_ai_write_commits(repo_dir, normalized_rel_path)
    if len(recent_commits) < AI_WRITE_LOOP_GUARD_MAX_RECENT_COMMITS:
        return None
    first = recent_commits[0]
    return (
        f"{normalized_rel_path} has {len(recent_commits)} recent repair-like {AI_WRITE_LOOP_GUARD_PREFIX} commits "
        f"inside {AI_WRITE_LOOP_GUARD_WINDOW_SECONDS} seconds; refusing another draft write. "
        "Stop the current continuation repair, rerun deterministic length/style gates, and open a bounded "
        f"repair plan instead of blind expansion. Latest guarded commit: {first['commit_id']} {first['subject']}"
    )


def _has_pending_changes(repo_dir: str, file_name: str) -> bool:
    status_result = run_git(repo_dir, ["status", "--porcelain", "--", file_name])
    status_output = status_result.stdout if hasattr(status_result, "stdout") else str(status_result)
    return bool(status_output.strip())


def _compute_text_etag(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _compute_file_etag(file_path: str) -> str:
    if not os.path.exists(file_path):
        return _compute_text_etag("")
    with open(file_path, "r", encoding="utf-8") as f:
        return _compute_text_etag(f.read())


def _normalize_base_etag(raw: Any) -> tuple[str | None, str | None]:
    if raw is None:
        return None, None
    if not isinstance(raw, str) or not raw.strip():
        return None, "base_etag must be a non-empty string"
    return raw.strip(), None


def _is_core_archive_file(normalized_rel_path: str) -> bool:
    return normalized_rel_path in CORE_ARCHIVE_FILES


def _safe_path_token(rel_path: str) -> str:
    cleaned = rel_path.replace("\\", "/").replace("/", "__")
    cleaned = "".join(ch for ch in cleaned if ch.isalnum() or ch in {"_", "-", "."})
    return cleaned or "file"


@contextmanager
def _path_lock(repo_dir: str, normalized_rel_path: str):
    locks_dir = os.path.join(repo_dir, LOCKS_DIR_NAME)
    os.makedirs(locks_dir, exist_ok=True)
    lock_name = f"{_safe_path_token(normalized_rel_path)}.lock"
    lock_path = os.path.join(locks_dir, lock_name)
    with open(lock_path, "a+", encoding="utf-8") as lock_file:
        with exclusive_file_lock(lock_file):
            yield


def _save_conflict_draft(
    repo_dir: str,
    normalized_rel_path: str,
    attempted_content: str,
    action: str,
    base_etag: str | None,
    current_etag: str,
) -> str:
    conflicts_dir = os.path.join(repo_dir, CONFLICTS_DIR_NAME)
    os.makedirs(conflicts_dir, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_name = _safe_path_token(normalized_rel_path)
    draft_name = f"{timestamp}_{safe_name}_{action}.ai_conflict_draft.md"
    draft_path = os.path.join(conflicts_dir, draft_name)
    payload = (
        f"# AI Conflict Draft\n\n"
        f"- file: `{normalized_rel_path}`\n"
        f"- action: `{action}`\n"
        f"- base_etag: `{base_etag or ''}`\n"
        f"- current_etag: `{current_etag}`\n\n"
        f"## Draft Content\n\n"
        f"{attempted_content}"
    )
    with open(draft_path, "w", encoding="utf-8") as f:
        f.write(payload)
    return draft_path


def _write_conflict_response(
    *,
    book_id: str,
    normalized_rel_path: str,
    base_etag: str | None,
    current_etag: str,
    draft_path: str,
):
    return (
        jsonify(
            {
                "status": "error",
                "code": "WRITE_CONFLICT",
                "message": (
                    "文件已被其他协作者更新，系统已保留 AI 草稿。"
                    "请人工合并 draft_file 后，重新读取目标文件并再次提交。"
                ),
                "book_id": book_id,
                "file_name": normalized_rel_path,
                "base_etag": base_etag,
                "current_etag": current_etag,
                "draft_file": draft_path,
            }
        ),
        409,
    )


def _parse_positive_line_number(raw_value: Any, field_name: str) -> tuple[int | None, str | None]:
    if raw_value is None:
        return None, f"{field_name} is required"
    text = str(raw_value).strip()
    if not text:
        return None, f"{field_name} is required"
    try:
        value = int(text)
    except (TypeError, ValueError):
        return None, f"{field_name} must be a positive integer"
    if value <= 0:
        return None, f"{field_name} must be a positive integer"
    return value, None


def _validate_line_window(start_line: int, end_line: int) -> str | None:
    if end_line < start_line:
        return "end_line must be greater than or equal to start_line"
    requested_lines = end_line - start_line + 1
    if requested_lines > MAX_ARCHIVE_RANGE_LINES:
        return (
            f"请求行数（{requested_lines}行）超过上限（{MAX_ARCHIVE_RANGE_LINES}行），"
            "请通过多次分段读取实现。"
        )
    return None


def _line_error_code(message: str) -> str:
    if message.endswith("is required"):
        return "MISSING_FIELD"
    return "INVALID_PAYLOAD"


def _parse_section_path_arg(raw_value: Any) -> tuple[list[str] | None, str | None]:
    if raw_value is None:
        return None, "section_path is required"
    if isinstance(raw_value, list):
        raw_items = raw_value
    else:
        text = str(raw_value).strip()
        if not text:
            return None, "section_path is required"
        if text.startswith("["):
            try:
                decoded = json.loads(text)
            except json.JSONDecodeError:
                return None, "section_path must be a JSON array of strings"
            if not isinstance(decoded, list):
                return None, "section_path must be a JSON array of strings"
            raw_items = decoded
        else:
            raw_items = [part.strip() for part in text.split(">")]

    parts: list[str] = []
    for item in raw_items:
        if not isinstance(item, str) or not item.strip():
            return None, "section_path must contain non-empty strings"
        parts.append(item.strip())
    if not parts:
        return None, "section_path is required"
    return parts, None


def _safe_current_head(repo_dir: str) -> str | None:
    try:
        return run_git(repo_dir, ["rev-parse", "HEAD"]).stdout.strip() or None
    except Exception:
        return None


@contextmanager
def _repo_lock(repo_dir: str):
    locks_dir = os.path.join(repo_dir, LOCKS_DIR_NAME)
    os.makedirs(locks_dir, exist_ok=True)
    lock_path = os.path.join(locks_dir, "draft_sandbox.lock")
    with open(lock_path, "a+", encoding="utf-8") as lock_file:
        with exclusive_file_lock(lock_file):
            yield


def _ensure_repo_identity(repo_dir: str) -> None:
    current_name = ""
    current_email = ""
    try:
        current_name = run_git(repo_dir, ["config", "--get", "user.name"]).stdout.strip()
    except subprocess.CalledProcessError:
        current_name = ""
    try:
        current_email = run_git(repo_dir, ["config", "--get", "user.email"]).stdout.strip()
    except subprocess.CalledProcessError:
        current_email = ""

    if not current_name:
        run_git(repo_dir, ["config", "user.name", "LoreGit Bot"])
    if not current_email:
        run_git(repo_dir, ["config", "user.email", "loregit@example.local"])


def _ensure_baseline_commit(repo_dir: str) -> None:
    if _safe_current_head(repo_dir):
        return
    _ensure_repo_identity(repo_dir)
    run_git(repo_dir, ["add", "--all"])
    run_git(repo_dir, ["commit", "-m", "chore: bootstrap repository baseline"])


def _ensure_layout_files_tracked(repo_dir: str) -> None:
    existing = [name for name in TRACKED_LAYOUT_FILES if os.path.exists(os.path.join(repo_dir, name))]
    if not existing:
        return
    run_git(repo_dir, ["add", "--", *existing])
    if not _has_pending_changes_for_paths(repo_dir, existing):
        return
    _ensure_repo_identity(repo_dir)
    run_git(repo_dir, ["commit", "-m", "chore: bootstrap tracked layout files", "--", *existing])


def _list_local_heads(repo_dir: str) -> set[str]:
    try:
        output = run_git(repo_dir, ["for-each-ref", "--format=%(refname:short)", "refs/heads"]).stdout
    except subprocess.CalledProcessError:
        return set()
    return {line.strip() for line in output.splitlines() if line.strip()}


def _resolve_mainline_branch(repo_dir: str) -> str:
    symbolic_head = ""
    try:
        symbolic_head = run_git(repo_dir, ["symbolic-ref", "--short", "HEAD"]).stdout.strip()
    except subprocess.CalledProcessError:
        symbolic_head = ""

    head_names = _list_local_heads(repo_dir)
    if symbolic_head and symbolic_head in head_names and symbolic_head != "draft/sandbox":
        return symbolic_head
    if "main" in head_names:
        return "main"
    if "master" in head_names:
        return "master"
    if symbolic_head and symbolic_head != "draft/sandbox":
        return symbolic_head
    for candidate in sorted(head_names):
        if candidate != "draft/sandbox":
            return candidate
    return "main"


def _ensure_draft_branch(repo_dir: str, mainline_branch: str, *, create_if_missing: bool) -> tuple[bool, bool]:
    head_names = _list_local_heads(repo_dir)
    if mainline_branch in head_names:
        run_git(repo_dir, ["checkout", mainline_branch])

    if "draft/sandbox" in head_names:
        run_git(repo_dir, ["checkout", "draft/sandbox"])
        return True, False

    if "draft/world_model" in head_names:
        run_git(repo_dir, ["checkout", "draft/world_model"])
        run_git(repo_dir, ["branch", "-m", "draft/sandbox"])
        return True, True

    if not create_if_missing:
        return False, False

    run_git(repo_dir, ["checkout", "-b", "draft/sandbox"])
    return True, False


def _has_pending_changes_for_paths(repo_dir: str, rel_paths: list[str]) -> bool:
    if not rel_paths:
        return False
    status = run_git(repo_dir, ["status", "--porcelain", "--", *rel_paths]).stdout
    return bool(status.strip())


def _infer_file_type(normalized_rel_path: str) -> str:
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
    if normalized_rel_path == "chapter_draft.md" or normalized_rel_path.startswith("chapters/"):
        return "chapter"
    return "world_core"


def _book_missing_response(book_id: str, storage_root: str):
    integrity = inspect_book_layout_integrity(book_id, storage_root)
    return (
        jsonify(
            {
                "status": "error",
                "code": "BOOK_NOT_FOUND",
                "message": f"book storage is missing for {book_id}; initialize or repair it first",
                "book_id": book_id,
                "integrity": integrity,
            }
        ),
        404,
    )


def _layout_repair_required_response(book_id: str, storage_root: str):
    integrity = inspect_book_layout_integrity(book_id, storage_root)
    return (
        jsonify(
            {
                "status": "error",
                "code": "LAYOUT_REPAIR_REQUIRED",
                "message": "repository layout is incomplete; call /books/repair_layout before normal reads/writes",
                "book_id": book_id,
                "integrity": integrity,
            }
        ),
        409,
    )


def _resolve_read_paths(book_id: str, storage_root: str):
    paths = get_book_paths(book_id, storage_root)
    integrity = inspect_book_layout_integrity(book_id, storage_root)
    if not integrity["exists"]:
        return None, integrity, _book_missing_response(book_id, storage_root)
    return paths, integrity, None


def _resolve_write_paths(book_id: str, storage_root: str):
    paths, integrity, err = _resolve_read_paths(book_id, storage_root)
    if err:
        return None, integrity, err
    if integrity["needs_repair"]:
        return None, integrity, _layout_repair_required_response(book_id, storage_root)
    return paths, integrity, None


def _read_existing_or_virtual(file_path: str, normalized_rel_path: str) -> tuple[str, bool, bool]:
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read(), True, False
    virtual_content = get_virtual_core_file_content(normalized_rel_path)
    if virtual_content is None:
        raise FileNotFoundError(normalized_rel_path)
    return virtual_content, False, True


def create_blueprint(
    *,
    storage_root: str,
    parse_json_payload: Callable[[list[str] | None], tuple[dict | None, tuple | None]],
    require_book_id: Callable[[dict | None], tuple[str | None, tuple | None]],
    json_error: Callable[[str, str, int], tuple],
) -> Blueprint:
    bp = Blueprint("archive", __name__)

    def _execute_markdown_section_writes(payload: dict[str, Any], *, tool_name: str):
        book_id, book_err = require_book_id(payload)
        if book_err:
            return book_err

        paths, integrity, path_err = _resolve_write_paths(book_id, storage_root)
        if path_err:
            return path_err
        assert paths is not None
        repo_dir = paths["book_dir"]

        raw_writes = payload.get("writes")
        if not isinstance(raw_writes, list) or not raw_writes:
            return json_error("INVALID_PAYLOAD", "writes must be a non-empty array", 400)

        normalized_writes: list[dict[str, Any]] = []
        for idx, raw_item in enumerate(raw_writes):
            if not isinstance(raw_item, dict):
                return json_error("INVALID_PAYLOAD", f"writes[{idx}] must be an object", 400)

            file_name = _normalize_file_name(raw_item.get("file_name"))
            if not file_name:
                return json_error("INVALID_PAYLOAD", f"writes[{idx}].file_name is required", 400)

            try:
                file_path, normalized_rel_path = _resolve_target_file(repo_dir, file_name)
            except ValueError as exc:
                return json_error("INVALID_PAYLOAD", f"writes[{idx}]: {exc}", 400)

            if not normalized_rel_path.lower().endswith(".md"):
                return json_error("INVALID_PAYLOAD", f"writes[{idx}].file_name must target a markdown file", 400)

            op = raw_item.get("op")
            if not isinstance(op, str) or op.strip() not in {"replace_section", "append_under_section"}:
                return json_error(
                    "INVALID_PAYLOAD",
                    f"writes[{idx}].op must be one of ['append_under_section', 'replace_section']",
                    400,
                )

            section_path, section_path_err = _parse_section_path_arg(raw_item.get("section_path"))
            if section_path_err:
                code = "INVALID_PAYLOAD" if "required" not in section_path_err else "MISSING_FIELD"
                return json_error(code, f"writes[{idx}].{section_path_err}", 400)
            assert section_path is not None

            content = raw_item.get("content")
            if not isinstance(content, str):
                return json_error("INVALID_PAYLOAD", f"writes[{idx}].content must be a string", 400)

            base_etag, base_etag_err = _normalize_base_etag(raw_item.get("base_etag"))
            if base_etag_err:
                return json_error("INVALID_PAYLOAD", f"writes[{idx}].{base_etag_err}", 400)
            if base_etag is None:
                return json_error("PRECONDITION_REQUIRED", f"writes[{idx}].base_etag is required", 428)

            normalized_writes.append(
                {
                    "index": idx,
                    "file_path": file_path,
                    "normalized_rel_path": normalized_rel_path,
                    "op": op.strip(),
                    "section_path": section_path,
                    "content": content,
                    "base_etag": base_etag,
                }
            )

        raw_message = payload.get("message")
        origin = payload.get("origin")
        if origin != MARKDOWN_SECTION_WRITE_ORIGIN:
            return json_error(
                "WRITE_INTENT_REQUIRED",
                f"{tool_name} requires origin='explicit_user_write' to confirm the user explicitly requested a draft write",
                428,
            )
        grouped_writes: dict[str, list[dict[str, Any]]] = {}
        for item in normalized_writes:
            grouped_writes.setdefault(item["normalized_rel_path"], []).append(item)

        ensure_repo(repo_dir)
        with _repo_lock(repo_dir):
            _ensure_baseline_commit(repo_dir)
            _ensure_layout_files_tracked(repo_dir)
            mainline_branch = _resolve_mainline_branch(repo_dir)
            _, migrated_from_legacy = _ensure_draft_branch(repo_dir, mainline_branch, create_if_missing=True)

            resolved_files: list[dict[str, Any]] = []
            for normalized_rel_path, file_writes in grouped_writes.items():
                file_path = file_writes[0]["file_path"]
                try:
                    original_content, _, _ = _read_existing_or_virtual(file_path, normalized_rel_path)
                except FileNotFoundError:
                    return json_error("INVALID_PAYLOAD", f"file not found: {normalized_rel_path}", 404)

                current_etag = _compute_text_etag(original_content)
                attempted_content = original_content
                try:
                    for write_item in file_writes:
                        attempted_content = apply_markdown_patch(
                            attempted_content,
                            {
                                "op": write_item["op"],
                                "section_path": write_item["section_path"],
                                "content": write_item["content"],
                            },
                        )
                except MarkdownSectionNotFoundError as exc:
                    return json_error("SECTION_NOT_FOUND", str(exc), 404)
                except MarkdownSectionAmbiguousError as exc:
                    return json_error("SECTION_PATH_AMBIGUOUS", str(exc), 409)
                except (MarkdownPatchApplyError, MarkdownSectionError) as exc:
                    return json_error("INVALID_PAYLOAD", str(exc), 400)

                stale_entry = next((item for item in file_writes if item["base_etag"] != current_etag), None)
                if stale_entry is not None:
                    draft_path = _save_conflict_draft(
                        repo_dir,
                        normalized_rel_path,
                        attempted_content,
                        "markdown_section_patch",
                        stale_entry["base_etag"],
                        current_etag,
                    )
                    return _write_conflict_response(
                        book_id=book_id,
                        normalized_rel_path=normalized_rel_path,
                        base_etag=stale_entry["base_etag"],
                        current_etag=current_etag,
                        draft_path=draft_path,
                    )

                resolved_files.append(
                    {
                        "file_path": file_path,
                        "normalized_rel_path": normalized_rel_path,
                        "original_content": original_content,
                        "new_content": attempted_content,
                    }
                )

            changed_files = [item for item in resolved_files if item["new_content"] != item["original_content"]]
            if not changed_files:
                response_body = {
                    "status": "success",
                    "book_id": book_id,
                    "branch": "draft/sandbox",
                    "mainline_branch": mainline_branch,
                    "commit_id": _safe_current_head(repo_dir),
                    "updated_files": [
                        {
                            "file_name": item["normalized_rel_path"],
                            "etag": _compute_text_etag(item["original_content"]),
                        }
                        for item in resolved_files
                    ],
                    "message": "No markdown section changes detected.",
                }
                if migrated_from_legacy:
                    response_body["warning"] = "legacy draft branch draft/world_model has been migrated to draft/sandbox"
                return jsonify(response_body), 200

            for item in changed_files:
                guard_message = _ai_write_loop_guard_message(repo_dir, item["normalized_rel_path"])
                if guard_message is not None:
                    return json_error("AI_WRITE_LOOP_GUARD", guard_message, 429)

            for item in changed_files:
                with open(item["file_path"], "w", encoding="utf-8") as handle:
                    handle.write(item["new_content"])

            rel_paths = [item["normalized_rel_path"] for item in changed_files]
            run_git(repo_dir, ["add", "--", *rel_paths])

            if _has_pending_changes_for_paths(repo_dir, rel_paths):
                _ensure_repo_identity(repo_dir)
                commit_message = _build_commit_message(origin, raw_message, rel_paths[0] if len(rel_paths) == 1 else "markdown sections")
                run_git(repo_dir, ["commit", "-m", commit_message, "--", *rel_paths])

            commit_id = _safe_current_head(repo_dir)
            response_body = {
                "status": "success",
                "book_id": book_id,
                "branch": "draft/sandbox",
                "mainline_branch": mainline_branch,
                "commit_id": commit_id,
                "updated_files": [
                    {
                        "file_name": item["normalized_rel_path"],
                        "etag": _compute_file_etag(item["file_path"]),
                    }
                    for item in changed_files
                ],
            }
            if migrated_from_legacy:
                response_body["warning"] = "legacy draft branch draft/world_model has been migrated to draft/sandbox"
            return jsonify(response_body), 200

    def _single_markdown_section_payload(payload: dict[str, Any], *, op: str) -> dict[str, Any]:
        synthetic = dict(payload)
        synthetic["writes"] = [
            {
                "file_name": payload.get("file_name"),
                "op": op,
                "section_path": payload.get("section_path"),
                "content": payload.get("content"),
                "base_etag": payload.get("base_etag"),
            }
        ]
        return synthetic

    def _replace_nth_text(content: str, old_text: str, new_text: str, occurrence: int | None) -> tuple[str | None, str | None, int]:
        matches = [match.start() for match in re.finditer(re.escape(old_text), content)]
        if not matches:
            return None, "TEXT_NOT_FOUND", 0
        if occurrence is None:
            if len(matches) != 1:
                return None, "TEXT_NOT_UNIQUE", len(matches)
            occurrence = 1
        if occurrence < 1 or occurrence > len(matches):
            return None, "TEXT_OCCURRENCE_OUT_OF_RANGE", len(matches)
        start = matches[occurrence - 1]
        end = start + len(old_text)
        return content[:start] + new_text + content[end:], None, len(matches)

    @bp.post("/api/draft/replace_text")
    def replace_text():
        payload, err = parse_json_payload(["file_name", "old_text", "new_text", "base_etag"])
        if err:
            return err
        assert payload is not None

        book_id, book_err = require_book_id(payload)
        if book_err:
            return book_err

        origin = payload.get("origin")
        if origin != MARKDOWN_SECTION_WRITE_ORIGIN:
            return json_error(
                "WRITE_INTENT_REQUIRED",
                "draft_replace_text requires origin='explicit_user_write' to confirm the user explicitly requested a draft write",
                428,
            )

        paths, integrity, path_err = _resolve_write_paths(book_id, storage_root)
        if path_err:
            return path_err
        assert paths is not None
        repo_dir = paths["book_dir"]

        file_name = _normalize_file_name(payload.get("file_name"))
        if not file_name:
            return json_error("MISSING_FIELD", "file_name is required", 400)
        try:
            file_path, normalized_rel_path = _resolve_target_file(repo_dir, file_name)
        except ValueError as exc:
            return json_error("INVALID_PAYLOAD", str(exc), 400)

        old_text = payload.get("old_text")
        if not isinstance(old_text, str) or not old_text:
            return json_error("INVALID_PAYLOAD", "old_text must be a non-empty string", 400)
        new_text = payload.get("new_text")
        if not isinstance(new_text, str):
            return json_error("INVALID_PAYLOAD", "new_text must be a string", 400)
        raw_occurrence = payload.get("occurrence")
        occurrence: int | None = None
        if raw_occurrence not in (None, ""):
            try:
                occurrence = int(raw_occurrence)
            except (TypeError, ValueError):
                return json_error("INVALID_PAYLOAD", "occurrence must be a positive integer", 400)
            if occurrence < 1:
                return json_error("INVALID_PAYLOAD", "occurrence must be a positive integer", 400)

        base_etag, base_etag_err = _normalize_base_etag(payload.get("base_etag"))
        if base_etag_err:
            return json_error("INVALID_PAYLOAD", base_etag_err, 400)
        if base_etag is None:
            return json_error("PRECONDITION_REQUIRED", "base_etag is required", 428)

        raw_message = payload.get("message")
        base_message = raw_message.strip() if isinstance(raw_message, str) and raw_message.strip() else "draft text replacement"

        ensure_repo(repo_dir)
        with _repo_lock(repo_dir):
            _ensure_baseline_commit(repo_dir)
            _ensure_layout_files_tracked(repo_dir)
            mainline_branch = _resolve_mainline_branch(repo_dir)
            _, migrated_from_legacy = _ensure_draft_branch(repo_dir, mainline_branch, create_if_missing=True)
            try:
                original_content, _, _ = _read_existing_or_virtual(file_path, normalized_rel_path)
            except FileNotFoundError:
                return json_error("INVALID_PAYLOAD", f"file not found: {normalized_rel_path}", 404)

            current_etag = _compute_text_etag(original_content)
            if base_etag != current_etag:
                attempted_content = original_content.replace(old_text, new_text, 1)
                draft_path = _save_conflict_draft(
                    repo_dir,
                    normalized_rel_path,
                    attempted_content,
                    "text_replace",
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

            new_content, replace_error, match_count = _replace_nth_text(original_content, old_text, new_text, occurrence)
            if replace_error == "TEXT_NOT_FOUND":
                return json_error("TEXT_NOT_FOUND", "old_text was not found in the current file", 404)
            if replace_error == "TEXT_NOT_UNIQUE":
                return json_error(
                    "TEXT_NOT_UNIQUE",
                    f"old_text matched {match_count} times; provide occurrence to select one exact match",
                    409,
                )
            if replace_error == "TEXT_OCCURRENCE_OUT_OF_RANGE":
                return json_error(
                    "TEXT_OCCURRENCE_OUT_OF_RANGE",
                    f"occurrence is out of range for {match_count} matches",
                    400,
                )
            assert new_content is not None

            if new_content == original_content:
                return (
                    jsonify(
                        {
                            "status": "success",
                            "book_id": book_id,
                            "branch": "draft/sandbox",
                            "mainline_branch": mainline_branch,
                            "commit_id": _safe_current_head(repo_dir),
                            "updated_files": [{"file_name": normalized_rel_path, "etag": current_etag}],
                            "match_count": match_count,
                            "message": "No text replacement changes detected.",
                        }
                    ),
                    200,
                )

            with open(file_path, "w", encoding="utf-8") as handle:
                handle.write(new_content)
            run_git(repo_dir, ["add", "--", normalized_rel_path])
            if _has_pending_changes_for_paths(repo_dir, [normalized_rel_path]):
                _ensure_repo_identity(repo_dir)
                commit_message = _build_commit_message(origin, base_message, normalized_rel_path)
                run_git(repo_dir, ["commit", "-m", commit_message, "--", normalized_rel_path])

            response_body = {
                "status": "success",
                "book_id": book_id,
                "branch": "draft/sandbox",
                "mainline_branch": mainline_branch,
                "commit_id": _safe_current_head(repo_dir),
                "updated_files": [{"file_name": normalized_rel_path, "etag": _compute_file_etag(file_path)}],
                "match_count": match_count,
            }
            if migrated_from_legacy:
                response_body["warning"] = "legacy draft branch draft/world_model has been migrated to draft/sandbox"
            return jsonify(response_body), 200

    @bp.get("/books/repo_integrity")
    def repo_integrity():
        book_id, book_err = require_book_id(None)
        if book_err:
            return book_err

        integrity = inspect_book_layout_integrity(book_id, storage_root)
        return (
            jsonify(
                {
                    "status": "success",
                    "book_id": book_id,
                    "integrity": integrity,
                }
            ),
            200,
        )

    @bp.post("/books/repair_layout")
    def repair_layout():
        payload, err = parse_json_payload()
        if err:
            return err
        assert payload is not None

        book_id, book_err = require_book_id(payload)
        if book_err:
            return book_err

        raw_book_name = payload.get("book_name")
        normalized_book_name = raw_book_name.strip() if isinstance(raw_book_name, str) and raw_book_name.strip() else None
        result = repair_book_layout(book_id, storage_root, book_name=normalized_book_name)
        return (
            jsonify(
                {
                    "status": "success",
                    "book_id": book_id,
                    "head_commit": result.get("head_commit"),
                    "repair_commits": result.get("repair_commits", []),
                    "integrity": result.get("integrity"),
                }
            ),
            200,
        )

    @bp.get("/books/get_file")
    def get_file():
        file_name = _normalize_file_name(request.args.get("file_name"))
        if not file_name:
            return json_error("MISSING_FIELD", "file_name is required", 400)

        book_id, book_err = require_book_id(None)
        if book_err:
            return book_err

        paths, integrity, err = _resolve_read_paths(book_id, storage_root)
        if err:
            return err
        assert paths is not None

        try:
            file_path, normalized_rel_path = _resolve_target_file(paths["book_dir"], file_name)
        except ValueError as exc:
            return json_error("INVALID_PAYLOAD", str(exc), 400)

        try:
            content, exists, virtual = _read_existing_or_virtual(file_path, normalized_rel_path)
        except FileNotFoundError:
            return json_error("INVALID_PAYLOAD", "file not found", 404)

        etag = _compute_text_etag(content)
        response = jsonify(
            {
                "status": "success",
                "book_id": book_id,
                "file_name": normalized_rel_path,
                "file_path": file_path,
                "etag": etag,
                "content": content,
                "exists": exists,
                "virtual": virtual,
                "integrity": integrity,
            }
        )
        response.headers["ETag"] = etag
        return response, 200

    @bp.get("/books/list_hot_files")
    def list_hot_files():
        book_id, book_err = require_book_id(None)
        if book_err:
            return book_err

        paths, integrity, err = _resolve_read_paths(book_id, storage_root)
        if err:
            return err
        assert paths is not None

        files: list[dict[str, Any]] = []
        for file_name in sorted(CORE_HOT_FILE_LABELS.keys()):
            file_path = os.path.join(paths["book_dir"], file_name)
            exists = os.path.exists(file_path)
            files.append(
                {
                    "file_name": file_name,
                    "file_type": _infer_file_type(file_name),
                    "label": CORE_HOT_FILE_LABELS[file_name],
                    "exists": exists,
                    "virtual": not exists,
                }
            )

        chapters_dir = paths["chapters_dir"]
        if os.path.isdir(chapters_dir):
            chapter_names = sorted(name for name in os.listdir(chapters_dir) if name.lower().endswith(".md"))
            for chapter_name in chapter_names:
                rel_name = f"chapters/{chapter_name}"
                files.append(
                    {
                        "file_name": rel_name,
                        "file_type": _infer_file_type(rel_name),
                        "label": chapter_name,
                        "exists": True,
                        "virtual": False,
                    }
                )

        return (
            jsonify(
                {
                    "status": "success",
                    "book_id": book_id,
                    "files": files,
                    "integrity": integrity,
                }
            ),
            200,
        )

    @bp.get("/books/get_archive_range")
    def get_archive_range():
        file_name = _normalize_file_name(request.args.get("file_name"))
        if not file_name:
            return json_error("MISSING_FIELD", "file_name is required", 400)

        start_line, start_err = _parse_positive_line_number(request.args.get("start_line"), "start_line")
        if start_err:
            return json_error(_line_error_code(start_err), start_err, 400)

        end_line, end_err = _parse_positive_line_number(request.args.get("end_line"), "end_line")
        if end_err:
            return json_error(_line_error_code(end_err), end_err, 400)

        assert start_line is not None and end_line is not None
        window_err = _validate_line_window(start_line, end_line)
        if window_err:
            return json_error("INVALID_PAYLOAD", window_err, 400)

        book_id, book_err = require_book_id(None)
        if book_err:
            return book_err

        paths, integrity, err = _resolve_read_paths(book_id, storage_root)
        if err:
            return err
        assert paths is not None

        try:
            file_path, normalized_rel_path = _resolve_target_file(paths["book_dir"], file_name)
        except ValueError as exc:
            return json_error("INVALID_PAYLOAD", str(exc), 400)

        try:
            file_content, exists, virtual = _read_existing_or_virtual(file_path, normalized_rel_path)
        except FileNotFoundError:
            return json_error("INVALID_PAYLOAD", "file not found", 404)

        lines = file_content.splitlines(keepends=True)
        etag = _compute_text_etag(file_content)

        selected_lines = lines[start_line - 1 : end_line]
        returned_end_line = (start_line + len(selected_lines) - 1) if selected_lines else (start_line - 1)

        response = jsonify(
            {
                "status": "success",
                "book_id": book_id,
                "file_name": normalized_rel_path,
                "file_path": file_path,
                "etag": etag,
                "start_line": start_line,
                "end_line": end_line,
                "returned_end_line": returned_end_line,
                "line_count": len(selected_lines),
                "total_lines": len(lines),
                "max_lines": MAX_ARCHIVE_RANGE_LINES,
                "content": "".join(selected_lines),
                "exists": exists,
                "virtual": virtual,
                "integrity": integrity,
            }
        )
        response.headers["ETag"] = etag
        return response, 200

    @bp.get("/books/get_markdown_outline")
    def get_markdown_outline():
        file_name = _normalize_file_name(request.args.get("file_name"))
        if not file_name:
            return json_error("MISSING_FIELD", "file_name is required", 400)

        book_id, book_err = require_book_id(None)
        if book_err:
            return book_err

        paths, integrity, err = _resolve_read_paths(book_id, storage_root)
        if err:
            return err
        assert paths is not None

        try:
            file_path, normalized_rel_path = _resolve_target_file(paths["book_dir"], file_name)
        except ValueError as exc:
            return json_error("INVALID_PAYLOAD", str(exc), 400)
        if not normalized_rel_path.lower().endswith(".md"):
            return json_error("INVALID_PAYLOAD", "get_markdown_outline only supports markdown files", 400)

        try:
            file_content, exists, virtual = _read_existing_or_virtual(file_path, normalized_rel_path)
        except FileNotFoundError:
            return json_error("INVALID_PAYLOAD", "file not found", 404)

        etag = _compute_text_etag(file_content)
        response = jsonify(
            {
                "status": "success",
                "book_id": book_id,
                "file_name": normalized_rel_path,
                "file_path": file_path,
                "etag": etag,
                "outline": build_markdown_outline(file_content),
                "exists": exists,
                "virtual": virtual,
                "integrity": integrity,
            }
        )
        response.headers["ETag"] = etag
        return response, 200

    @bp.get("/books/get_markdown_section")
    def get_markdown_section():
        file_name = _normalize_file_name(request.args.get("file_name"))
        if not file_name:
            return json_error("MISSING_FIELD", "file_name is required", 400)

        section_path, section_path_err = _parse_section_path_arg(request.args.get("section_path"))
        if section_path_err:
            return json_error("INVALID_PAYLOAD" if "required" not in section_path_err else "MISSING_FIELD", section_path_err, 400)
        assert section_path is not None

        book_id, book_err = require_book_id(None)
        if book_err:
            return book_err

        paths, integrity, err = _resolve_read_paths(book_id, storage_root)
        if err:
            return err
        assert paths is not None

        try:
            file_path, normalized_rel_path = _resolve_target_file(paths["book_dir"], file_name)
        except ValueError as exc:
            return json_error("INVALID_PAYLOAD", str(exc), 400)
        if not normalized_rel_path.lower().endswith(".md"):
            return json_error("INVALID_PAYLOAD", "get_markdown_section only supports markdown files", 400)

        try:
            file_content, exists, virtual = _read_existing_or_virtual(file_path, normalized_rel_path)
        except FileNotFoundError:
            return json_error("INVALID_PAYLOAD", "file not found", 404)

        try:
            section = extract_markdown_section(file_content, section_path)
        except MarkdownSectionNotFoundError as exc:
            return json_error("SECTION_NOT_FOUND", str(exc), 404)
        except MarkdownSectionAmbiguousError as exc:
            return json_error("SECTION_PATH_AMBIGUOUS", str(exc), 409)
        except MarkdownSectionError as exc:
            return json_error("INVALID_PAYLOAD", str(exc), 400)

        etag = _compute_text_etag(file_content)
        response = jsonify(
            {
                "status": "success",
                "book_id": book_id,
                "file_name": normalized_rel_path,
                "file_path": file_path,
                "etag": etag,
                "exists": exists,
                "virtual": virtual,
                "integrity": integrity,
                **section,
            }
        )
        response.headers["ETag"] = etag
        return response, 200

    @bp.post("/api/draft/sync_markdown_sections")
    def sync_markdown_sections():
        payload, err = parse_json_payload(["writes"])
        if err:
            return err
        assert payload is not None
        return _execute_markdown_section_writes(payload, tool_name="draft_sync_markdown_sections")

    @bp.post("/api/draft/append_markdown_section")
    def append_markdown_section():
        payload, err = parse_json_payload(["file_name", "section_path", "content", "base_etag"])
        if err:
            return err
        assert payload is not None
        return _execute_markdown_section_writes(
            _single_markdown_section_payload(payload, op="append_under_section"),
            tool_name="draft_append_markdown_section",
        )

    @bp.post("/api/draft/replace_markdown_section")
    def replace_markdown_section():
        payload, err = parse_json_payload(["file_name", "section_path", "content", "base_etag"])
        if err:
            return err
        assert payload is not None
        return _execute_markdown_section_writes(
            _single_markdown_section_payload(payload, op="replace_section"),
            tool_name="draft_replace_markdown_section",
        )

    @bp.get("/books/get_cold_archive_range")
    def get_cold_archive_range():
        file_name = _normalize_file_name(request.args.get("file_name"))
        if not file_name:
            return json_error("MISSING_FIELD", "file_name is required", 400)

        start_line, start_err = _parse_positive_line_number(request.args.get("start_line"), "start_line")
        if start_err:
            return json_error(_line_error_code(start_err), start_err, 400)

        end_line, end_err = _parse_positive_line_number(request.args.get("end_line"), "end_line")
        if end_err:
            return json_error(_line_error_code(end_err), end_err, 400)

        assert start_line is not None and end_line is not None
        if end_line < start_line:
            return json_error("INVALID_PAYLOAD", "end_line must be greater than or equal to start_line", 400)

        requested_lines = end_line - start_line + 1
        effective_end_line = end_line
        warnings: list[str] = []
        if requested_lines > MAX_COLD_ARCHIVE_RANGE_LINES:
            effective_end_line = start_line + MAX_COLD_ARCHIVE_RANGE_LINES - 1
            warnings.append(
                f"请求行数（{requested_lines}行）超过上限（{MAX_COLD_ARCHIVE_RANGE_LINES}行），"
                f"已自动截断到 {MAX_COLD_ARCHIVE_RANGE_LINES} 行。"
            )

        book_id, book_err = require_book_id(None)
        if book_err:
            return book_err

        paths, integrity, err = _resolve_read_paths(book_id, storage_root)
        if err:
            return err
        assert paths is not None

        try:
            file_path, normalized_rel_path = _resolve_cold_archive_file(paths["book_dir"], file_name)
        except ValueError as exc:
            return json_error("INVALID_PAYLOAD", str(exc), 400)

        if not os.path.exists(file_path):
            return json_error("INVALID_PAYLOAD", "file not found", 404)

        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        total_lines = len(lines)
        if end_line > total_lines:
            warnings.append(f"end_line ({end_line}) 超过文件总行数（{total_lines}），已平滑截断至文件末尾。")

        selected_lines = lines[start_line - 1 : effective_end_line]
        returned_end_line = (start_line + len(selected_lines) - 1) if selected_lines else (start_line - 1)

        return (
            jsonify(
                {
                    "status": "success",
                    "book_id": book_id,
                    "file_name": normalized_rel_path,
                    "real_file_name": os.path.basename(file_path),
                    "file_path": file_path,
                    "start_line": start_line,
                    "end_line": end_line,
                    "returned_end_line": returned_end_line,
                    "line_count": len(selected_lines),
                    "total_lines": total_lines,
                    "max_lines": MAX_COLD_ARCHIVE_RANGE_LINES,
                    "content": "".join(selected_lines),
                    "message": " ".join(warnings) if warnings else "success",
                    "integrity": integrity,
                }
            ),
            200,
        )

    @bp.post("/books/append_file")
    def append_file():
        payload, err = parse_json_payload(["file_name", "append_content"])
        if err:
            return err

        book_id, book_err = require_book_id(payload)
        if book_err:
            return book_err

        file_name = _normalize_file_name(payload.get("file_name"))
        if not file_name:
            return json_error("MISSING_FIELD", "file_name is required", 400)

        append_content = payload.get("append_content", "")
        if not isinstance(append_content, str):
            append_content = str(append_content)
        if not append_content:
            return (
                jsonify(
                    {
                        "status": "success",
                        "book_id": book_id,
                        "file_name": file_name,
                        "appended_chars": 0,
                        "message": "No append content provided, file is unchanged.",
                        "commit_id": None,
                    }
                ),
                200,
            )

        raw_book_name = payload.get("book_name")
        normalized_book_name = raw_book_name.strip() if isinstance(raw_book_name, str) and raw_book_name.strip() else None
        _, _, write_err = _resolve_write_paths(book_id, storage_root)
        if write_err:
            return write_err
        paths = ensure_book_layout(book_id, storage_root, book_name=normalized_book_name)
        repo_dir = paths["book_dir"]

        try:
            file_path, normalized_rel_path = _resolve_target_file(repo_dir, file_name)
        except ValueError as exc:
            return json_error("INVALID_PAYLOAD", str(exc), 400)

        base_etag, base_etag_err = _normalize_base_etag(payload.get("base_etag"))
        if base_etag_err:
            return json_error("INVALID_PAYLOAD", base_etag_err, 400)
        if _is_core_archive_file(normalized_rel_path) and base_etag is None:
            return json_error(
                "PRECONDITION_REQUIRED",
                f"base_etag is required for core archive file: {normalized_rel_path}",
                428,
            )

        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        raw_message = payload.get("message")
        if isinstance(raw_message, str) and raw_message.strip():
            base_message = raw_message.strip()
        else:
            base_message = f"append {normalized_rel_path}"
        message = _build_commit_message(payload.get("origin"), base_message, normalized_rel_path)

        with _path_lock(repo_dir, normalized_rel_path):
            existed_before = os.path.exists(file_path)
            original_content = ""
            if existed_before:
                with open(file_path, "r", encoding="utf-8") as f:
                    original_content = f.read()
            current_etag = _compute_text_etag(original_content)
            if base_etag is not None and base_etag != current_etag:
                draft_path = _save_conflict_draft(
                    repo_dir,
                    normalized_rel_path,
                    append_content,
                    "append",
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

            new_content = original_content + append_content

            temp_path = ""
            fd, temp_path = tempfile.mkstemp(prefix=".tmp_append_", suffix=".tmp", dir=os.path.dirname(file_path))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as temp_file:
                    temp_file.write(new_content)
                os.replace(temp_path, file_path)

                ensure_repo(repo_dir)
                run_git(repo_dir, ["add", "--", normalized_rel_path])
                if not _has_pending_changes(repo_dir, normalized_rel_path):
                    return (
                        jsonify(
                            {
                                "status": "success",
                                "book_id": book_id,
                                "file_name": normalized_rel_path,
                                "file_path": file_path,
                                "appended_chars": len(append_content),
                                "new_size": len(new_content),
                                "commit_id": _safe_current_head(repo_dir),
                                "etag": _compute_file_etag(file_path),
                                "message": "No changes detected, file is already up to date.",
                            }
                        ),
                        200,
                    )
                try:
                    run_git(repo_dir, ["commit", "-m", message, "--", normalized_rel_path])
                except subprocess.CalledProcessError as exc:
                    if is_nothing_to_commit_error(exc):
                        return (
                            jsonify(
                                {
                                    "status": "success",
                                    "book_id": book_id,
                                    "file_name": normalized_rel_path,
                                    "file_path": file_path,
                                    "appended_chars": len(append_content),
                                    "new_size": len(new_content),
                                    "commit_id": _safe_current_head(repo_dir),
                                    "etag": _compute_file_etag(file_path),
                                    "message": "No changes detected, file is already up to date.",
                                }
                            ),
                            200,
                        )
                    raise
                commit_id = run_git(repo_dir, ["rev-parse", "HEAD"]).stdout.strip()
            except subprocess.CalledProcessError as exc:
                LOGGER.exception(
                    "append_file git failed for book_id=%s file_name=%s",
                    book_id,
                    normalized_rel_path,
                )
                rollback_warning = None
                try:
                    if existed_before:
                        with open(file_path, "w", encoding="utf-8") as rollback_file:
                            rollback_file.write(original_content)
                    elif os.path.exists(file_path):
                        os.remove(file_path)
                except Exception as rollback_exc:
                    rollback_warning = f"rollback_failed: {rollback_exc}"
                    LOGGER.exception(
                        "append_file rollback failed for book_id=%s file_name=%s",
                        book_id,
                        normalized_rel_path,
                    )
                cmd = " ".join(str(part) for part in (exc.cmd or []))
                detail = format_git_error(exc) or str(exc)
                error_message = f"git command failed ({cmd}): {detail}" if cmd else f"git command failed: {detail}"
                error_payload = {
                    "status": "error",
                    "code": "GIT_COMMIT_FAILED",
                    "message": error_message,
                }
                if rollback_warning:
                    error_payload["warning"] = rollback_warning
                return jsonify(error_payload), 500
            except Exception as exc:
                LOGGER.exception(
                    "append_file unexpected failure for book_id=%s file_name=%s",
                    book_id,
                    normalized_rel_path,
                )
                rollback_warning = None
                try:
                    if existed_before:
                        with open(file_path, "w", encoding="utf-8") as rollback_file:
                            rollback_file.write(original_content)
                    elif os.path.exists(file_path):
                        os.remove(file_path)
                except Exception as rollback_exc:
                    rollback_warning = f"rollback_failed: {rollback_exc}"
                    LOGGER.exception(
                        "append_file rollback failed for book_id=%s file_name=%s",
                        book_id,
                        normalized_rel_path,
                    )
                error_payload = {
                    "status": "error",
                    "code": "GIT_COMMIT_FAILED",
                    "message": format_git_error(exc) or "failed to commit file append",
                }
                if rollback_warning:
                    error_payload["warning"] = rollback_warning
                return jsonify(error_payload), 500
            finally:
                if temp_path and os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except OSError:
                        pass

            return (
                jsonify(
                    {
                        "status": "success",
                        "book_id": book_id,
                        "file_name": normalized_rel_path,
                        "file_path": file_path,
                        "appended_chars": len(append_content),
                        "new_size": len(new_content),
                        "etag": _compute_file_etag(file_path),
                        "commit_id": commit_id,
                    }
                ),
                200,
            )

    @bp.post("/books/prepend_file")
    def prepend_file():
        payload, err = parse_json_payload(["file_name", "prepend_content"])
        if err:
            return err

        book_id, book_err = require_book_id(payload)
        if book_err:
            return book_err

        file_name = _normalize_file_name(payload.get("file_name"))
        if not file_name:
            return json_error("MISSING_FIELD", "file_name is required", 400)

        prepend_content = payload.get("prepend_content", "")
        if not isinstance(prepend_content, str):
            prepend_content = str(prepend_content)
        if not prepend_content.strip():
            return (
                jsonify(
                    {
                        "status": "success",
                        "book_id": book_id,
                        "file_name": file_name,
                        "prepended_chars": 0,
                        "message": "No prepend content provided, file is unchanged.",
                        "commit_id": None,
                    }
                ),
                200,
            )

        raw_book_name = payload.get("book_name")
        normalized_book_name = raw_book_name.strip() if isinstance(raw_book_name, str) and raw_book_name.strip() else None
        _, _, write_err = _resolve_write_paths(book_id, storage_root)
        if write_err:
            return write_err
        paths = ensure_book_layout(book_id, storage_root, book_name=normalized_book_name)
        repo_dir = paths["book_dir"]

        try:
            file_path, normalized_rel_path = _resolve_target_file(repo_dir, file_name)
        except ValueError as exc:
            return json_error("INVALID_PAYLOAD", str(exc), 400)

        base_etag, base_etag_err = _normalize_base_etag(payload.get("base_etag"))
        if base_etag_err:
            return json_error("INVALID_PAYLOAD", base_etag_err, 400)
        if _is_core_archive_file(normalized_rel_path) and base_etag is None:
            return json_error(
                "PRECONDITION_REQUIRED",
                f"base_etag is required for core archive file: {normalized_rel_path}",
                428,
            )

        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        raw_message = payload.get("message")
        if isinstance(raw_message, str) and raw_message.strip():
            base_message = raw_message.strip()
        else:
            base_message = f"prepend {normalized_rel_path}"
        message = _build_commit_message(payload.get("origin"), base_message, normalized_rel_path)

        with _path_lock(repo_dir, normalized_rel_path):
            existed_before = os.path.exists(file_path)
            current_content = ""
            if existed_before:
                with open(file_path, "r", encoding="utf-8") as f:
                    current_content = f.read()
            current_etag = _compute_text_etag(current_content)
            if base_etag is not None and base_etag != current_etag:
                draft_path = _save_conflict_draft(
                    repo_dir,
                    normalized_rel_path,
                    prepend_content,
                    "prepend",
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

            if current_content:
                new_content = prepend_content + "\n\n" + current_content
            else:
                new_content = prepend_content

            temp_path = ""
            fd, temp_path = tempfile.mkstemp(prefix=".tmp_prepend_", suffix=".tmp", dir=os.path.dirname(file_path))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as temp_file:
                    temp_file.write(new_content)
                os.replace(temp_path, file_path)

                ensure_repo(repo_dir)
                run_git(repo_dir, ["add", "--", normalized_rel_path])
                if not _has_pending_changes(repo_dir, normalized_rel_path):
                    return (
                        jsonify(
                            {
                                "status": "success",
                                "book_id": book_id,
                                "file_name": normalized_rel_path,
                                "file_path": file_path,
                                "prepended_chars": len(prepend_content),
                                "new_size": len(new_content),
                                "commit_id": _safe_current_head(repo_dir),
                                "etag": _compute_file_etag(file_path),
                                "message": "No changes detected, file is already up to date.",
                            }
                        ),
                        200,
                    )
                try:
                    run_git(repo_dir, ["commit", "-m", message, "--", normalized_rel_path])
                except subprocess.CalledProcessError as exc:
                    if is_nothing_to_commit_error(exc):
                        return (
                            jsonify(
                                {
                                    "status": "success",
                                    "book_id": book_id,
                                    "file_name": normalized_rel_path,
                                    "file_path": file_path,
                                    "prepended_chars": len(prepend_content),
                                    "new_size": len(new_content),
                                    "commit_id": _safe_current_head(repo_dir),
                                    "etag": _compute_file_etag(file_path),
                                    "message": "No changes detected, file is already up to date.",
                                }
                            ),
                            200,
                        )
                    raise
                commit_id = run_git(repo_dir, ["rev-parse", "HEAD"]).stdout.strip()
            except subprocess.CalledProcessError as exc:
                LOGGER.exception(
                    "prepend_file git failed for book_id=%s file_name=%s",
                    book_id,
                    normalized_rel_path,
                )
                rollback_warning = None
                try:
                    if existed_before:
                        with open(file_path, "w", encoding="utf-8") as rollback_file:
                            rollback_file.write(current_content)
                    elif os.path.exists(file_path):
                        os.remove(file_path)
                except Exception as rollback_exc:
                    rollback_warning = f"rollback_failed: {rollback_exc}"
                    LOGGER.exception(
                        "prepend_file rollback failed for book_id=%s file_name=%s",
                        book_id,
                        normalized_rel_path,
                    )
                cmd = " ".join(str(part) for part in (exc.cmd or []))
                detail = format_git_error(exc) or str(exc)
                error_message = f"git command failed ({cmd}): {detail}" if cmd else f"git command failed: {detail}"
                error_payload = {
                    "status": "error",
                    "code": "GIT_COMMIT_FAILED",
                    "message": error_message,
                }
                if rollback_warning:
                    error_payload["warning"] = rollback_warning
                return jsonify(error_payload), 500
            except Exception as exc:
                LOGGER.exception(
                    "prepend_file unexpected failure for book_id=%s file_name=%s",
                    book_id,
                    normalized_rel_path,
                )
                rollback_warning = None
                try:
                    if existed_before:
                        with open(file_path, "w", encoding="utf-8") as rollback_file:
                            rollback_file.write(current_content)
                    elif os.path.exists(file_path):
                        os.remove(file_path)
                except Exception as rollback_exc:
                    rollback_warning = f"rollback_failed: {rollback_exc}"
                    LOGGER.exception(
                        "prepend_file rollback failed for book_id=%s file_name=%s",
                        book_id,
                        normalized_rel_path,
                    )
                error_payload = {
                    "status": "error",
                    "code": "GIT_COMMIT_FAILED",
                    "message": format_git_error(exc) or "failed to commit file prepend",
                }
                if rollback_warning:
                    error_payload["warning"] = rollback_warning
                return jsonify(error_payload), 500
            finally:
                if temp_path and os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except OSError:
                        pass

            return (
                jsonify(
                    {
                        "status": "success",
                        "book_id": book_id,
                        "file_name": normalized_rel_path,
                        "file_path": file_path,
                        "prepended_chars": len(prepend_content),
                        "new_size": len(new_content),
                        "etag": _compute_file_etag(file_path),
                        "commit_id": commit_id,
                    }
                ),
                200,
            )

    @bp.post("/books/update_file")
    def update_file():
        payload, err = parse_json_payload(["file_name", "content"])
        if err:
            return err

        book_id, book_err = require_book_id(payload)
        if book_err:
            return book_err

        file_name = _normalize_file_name(payload.get("file_name"))
        if not file_name:
            return json_error("MISSING_FIELD", "file_name is required", 400)

        content = payload.get("content", "")
        if not isinstance(content, str):
            content = str(content)

        raw_book_name = payload.get("book_name")
        normalized_book_name = raw_book_name.strip() if isinstance(raw_book_name, str) and raw_book_name.strip() else None
        _, _, write_err = _resolve_write_paths(book_id, storage_root)
        if write_err:
            return write_err
        paths = ensure_book_layout(book_id, storage_root, book_name=normalized_book_name)
        repo_dir = paths["book_dir"]

        try:
            file_path, normalized_rel_path = _resolve_target_file(repo_dir, file_name)
        except ValueError as exc:
            return json_error("INVALID_PAYLOAD", str(exc), 400)

        base_etag, base_etag_err = _normalize_base_etag(payload.get("base_etag"))
        if base_etag_err:
            return json_error("INVALID_PAYLOAD", base_etag_err, 400)
        if _is_core_archive_file(normalized_rel_path) and base_etag is None:
            return json_error(
                "PRECONDITION_REQUIRED",
                f"base_etag is required for core archive file: {normalized_rel_path}",
                428,
            )

        message = _build_commit_message(payload.get("origin"), payload.get("message"), normalized_rel_path)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        with _path_lock(repo_dir, normalized_rel_path):
            existed_before = os.path.exists(file_path)
            original_content = ""
            if existed_before:
                with open(file_path, "r", encoding="utf-8") as f:
                    original_content = f.read()
            current_etag = _compute_text_etag(original_content)
            if base_etag is not None and base_etag != current_etag:
                draft_path = _save_conflict_draft(
                    repo_dir,
                    normalized_rel_path,
                    content,
                    "update",
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

            temp_path = ""
            fd, temp_path = tempfile.mkstemp(prefix=".tmp_update_", suffix=".tmp", dir=os.path.dirname(file_path))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as temp_file:
                    temp_file.write(content)
                os.replace(temp_path, file_path)

                ensure_repo(repo_dir)
                run_git(repo_dir, ["add", "--", normalized_rel_path])
                if not _has_pending_changes(repo_dir, normalized_rel_path):
                    return (
                        jsonify(
                            {
                                "status": "success",
                                "book_id": book_id,
                                "file_name": normalized_rel_path,
                                "file_path": file_path,
                                "etag": _compute_file_etag(file_path),
                                "commit_id": _safe_current_head(repo_dir),
                                "message": "No changes detected, file is already up to date.",
                            }
                        ),
                        200,
                    )
                try:
                    run_git(repo_dir, ["commit", "-m", message, "--", normalized_rel_path])
                except subprocess.CalledProcessError as exc:
                    if is_nothing_to_commit_error(exc):
                        return (
                            jsonify(
                                {
                                    "status": "success",
                                    "book_id": book_id,
                                    "file_name": normalized_rel_path,
                                    "file_path": file_path,
                                    "etag": _compute_file_etag(file_path),
                                    "commit_id": _safe_current_head(repo_dir),
                                    "message": "No changes detected, file is already up to date.",
                                }
                            ),
                            200,
                        )
                    raise
                commit_id = run_git(repo_dir, ["rev-parse", "HEAD"]).stdout.strip()
            except subprocess.CalledProcessError as exc:
                LOGGER.exception(
                    "update_file git failed for book_id=%s file_name=%s",
                    book_id,
                    normalized_rel_path,
                )
                rollback_warning = None
                try:
                    if existed_before:
                        with open(file_path, "w", encoding="utf-8") as rollback_file:
                            rollback_file.write(original_content)
                    elif os.path.exists(file_path):
                        os.remove(file_path)
                except Exception as rollback_exc:
                    rollback_warning = f"rollback_failed: {rollback_exc}"
                    LOGGER.exception(
                        "update_file rollback failed for book_id=%s file_name=%s",
                        book_id,
                        normalized_rel_path,
                    )
                cmd = " ".join(str(part) for part in (exc.cmd or []))
                detail = format_git_error(exc) or str(exc)
                error_message = f"git command failed ({cmd}): {detail}" if cmd else f"git command failed: {detail}"
                error_payload = {
                    "status": "error",
                    "code": "GIT_COMMIT_FAILED",
                    "message": error_message,
                }
                if rollback_warning:
                    error_payload["warning"] = rollback_warning
                return jsonify(error_payload), 500
            except Exception as exc:
                LOGGER.exception(
                    "update_file unexpected failure for book_id=%s file_name=%s",
                    book_id,
                    normalized_rel_path,
                )
                rollback_warning = None
                try:
                    if existed_before:
                        with open(file_path, "w", encoding="utf-8") as rollback_file:
                            rollback_file.write(original_content)
                    elif os.path.exists(file_path):
                        os.remove(file_path)
                except Exception as rollback_exc:
                    rollback_warning = f"rollback_failed: {rollback_exc}"
                    LOGGER.exception(
                        "update_file rollback failed for book_id=%s file_name=%s",
                        book_id,
                        normalized_rel_path,
                    )
                error_payload = {
                    "status": "error",
                    "code": "GIT_COMMIT_FAILED",
                    "message": format_git_error(exc) or "failed to commit file update",
                }
                if rollback_warning:
                    error_payload["warning"] = rollback_warning
                return jsonify(error_payload), 500
            finally:
                if temp_path and os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except OSError:
                        pass

            return (
                jsonify(
                    {
                        "status": "success",
                        "book_id": book_id,
                        "file_name": normalized_rel_path,
                        "file_path": file_path,
                        "etag": _compute_file_etag(file_path),
                        "commit_id": commit_id,
                    }
                ),
                200,
            )

    return bp
