import os
import subprocess
from typing import Any, Callable

from flask import Blueprint, jsonify

from utils.book_storage import TRACKED_LAYOUT_FILES, ensure_book_layout, get_next_chapter_index
from utils.git_utils import (
    ensure_repo,
    ensure_repo_identity,
    format_git_error,
    is_nothing_to_commit_error,
    resolve_head,
    run_git,
)


DELIMITER = "|||CHAPTER_START|||"


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _derive_title(content: str) -> str:
    for line in content.splitlines():
        text = line.strip().lstrip("#").strip()
        if text:
            return text
    return "chapter"


def _safe_title(title: str) -> str:
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
    if not cleaned:
        return "chapter"
    return cleaned[:80]


def _normalize_batch_content(content: Any) -> str | None:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        normalized_items = [str(item) for item in content]
        return f"\n{DELIMITER}\n".join(normalized_items)
    return None


def _split_chapters(content: str) -> list[str]:
    chunks = []
    for piece in content.split(DELIMITER):
        trimmed = piece.strip()
        if trimmed:
            chunks.append(trimmed)
    return chunks


def _resolve_message(raw_message: Any, default_message: str) -> str:
    if isinstance(raw_message, str) and raw_message.strip():
        return raw_message.strip()
    return default_message


def _commit_book_paths(repo_dir: str, rel_paths: list[str], message: str) -> str:
    tracked_scope = [
        rel_path
        for rel_path in TRACKED_LAYOUT_FILES
        if os.path.exists(os.path.join(repo_dir, rel_path))
    ]
    commit_paths = list(dict.fromkeys([*tracked_scope, *rel_paths]))
    ensure_repo(repo_dir)
    ensure_repo_identity(repo_dir)
    run_git(repo_dir, ["add", "--", *commit_paths])
    status_output = run_git(repo_dir, ["status", "--porcelain", "--", *commit_paths]).stdout
    if not status_output.strip():
        return resolve_head(repo_dir, message)
    try:
        run_git(repo_dir, ["commit", "-m", message, "--", *commit_paths])
    except subprocess.CalledProcessError as exc:
        if not is_nothing_to_commit_error(exc):
            raise
    return resolve_head(repo_dir, message)


def create_blueprint(
    *,
    storage_root: str,
    parse_json_payload: Callable[[list[str] | None], tuple[dict | None, tuple | None]],
    require_book_id: Callable[[dict | None], tuple[str | None, tuple | None]],
    json_error: Callable[[str, str, int], tuple],
) -> Blueprint:
    bp = Blueprint("chapter", __name__)

    @bp.post("/books/add_chapter")
    def add_chapter():
        payload, err = parse_json_payload(["chapter_index", "content"])
        if err:
            return err

        book_id, book_err = require_book_id(payload)
        if book_err:
            return book_err

        chapter_index = _coerce_int(payload.get("chapter_index"))
        if chapter_index is None or chapter_index < 0:
            return json_error("MISSING_FIELD", "chapter_index must be a non-negative integer", 400)

        content = payload.get("content", "")
        if not isinstance(content, str):
            content = str(content)

        title = payload.get("title", "")
        if not isinstance(title, str):
            title = str(title)
        if not title.strip():
            title = _derive_title(content)
        safe_title = _safe_title(title)
        message = _resolve_message(payload.get("message"), f"add chapter {chapter_index:04d}: {title}")

        paths = ensure_book_layout(book_id, storage_root)
        repo_dir = paths["book_dir"]
        filename = f"{chapter_index:04d}_{safe_title}.md"
        chapter_path = os.path.join(paths["chapters_dir"], filename)
        rel_path = f"chapters/{filename}"

        with open(chapter_path, "w", encoding="utf-8") as f:
            f.write(content)

        try:
            commit_id = _commit_book_paths(repo_dir, [rel_path], message)
        except Exception as exc:
            return json_error("GIT_COMMIT_FAILED", format_git_error(exc) or "failed to commit chapter", 500)

        return (
            jsonify(
                {
                    "status": "success",
                    "book_id": book_id,
                    "chapter_index": chapter_index,
                    "title": title,
                    "commit_id": commit_id,
                    "file_path": chapter_path,
                }
            ),
            200,
        )

    @bp.post("/books/batch_import")
    def batch_import():
        payload, err = parse_json_payload(["content"])
        if err:
            return err

        book_id, book_err = require_book_id(payload)
        if book_err:
            return book_err

        normalized_content = _normalize_batch_content(payload.get("content"))
        if normalized_content is None:
            return json_error("INVALID_PAYLOAD", "content must be a string or list", 400)

        chapters = _split_chapters(normalized_content)
        if not chapters:
            return json_error("INVALID_PAYLOAD", "no chapters parsed from content", 400)

        book_name = payload.get("book_name")
        normalized_book_name = book_name.strip() if isinstance(book_name, str) and book_name.strip() else None
        paths = ensure_book_layout(book_id, storage_root, book_name=normalized_book_name)
        repo_dir = paths["book_dir"]
        next_index = get_next_chapter_index(book_id, storage_root)
        saved_count = 0
        rel_paths: list[str] = []

        for offset, chapter_text in enumerate(chapters):
            chapter_index = next_index + offset
            title = _derive_title(chapter_text)
            safe_title = _safe_title(title)
            filename = f"{chapter_index:04d}_{safe_title}.md"
            chapter_path = os.path.join(paths["chapters_dir"], filename)
            rel_path = f"chapters/{filename}"

            with open(chapter_path, "w", encoding="utf-8") as f:
                f.write(chapter_text)
            rel_paths.append(rel_path)
            saved_count += 1

        first_index = next_index
        last_index = next_index + len(chapters) - 1
        message = _resolve_message(
            payload.get("message"),
            f"import chapters {first_index:04d}-{last_index:04d} ({len(chapters)} total)",
        )

        try:
            commit_id = _commit_book_paths(repo_dir, rel_paths, message)
        except Exception as exc:
            return json_error("GIT_COMMIT_FAILED", format_git_error(exc) or "failed to commit batch import", 500)

        return (
            jsonify(
                {
                    "status": "success",
                    "saved_count": saved_count,
                    "total_parsed": len(chapters),
                    "book_id": book_id,
                    "commit_id": commit_id,
                }
            ),
            200,
        )

    return bp
