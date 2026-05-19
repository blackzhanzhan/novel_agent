"""Layout readiness helpers extracted from world_draft.py for maintainability."""

import os

from flask import jsonify

from agents.archive import _normalize_file_name, _resolve_target_file
from agents.world_draft_dify import _infer_file_type_from_path
from agents.world_draft_git import _read_file_text
from utils.book_storage import (
    ensure_book_layout,
    get_book_paths,
    get_virtual_core_file_content,
    inspect_book_layout_integrity,
    repair_book_layout,
)


def _line_count(text: str) -> int:
    if text == "":
        return 0
    return text.count("\n") + 1


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
                "message": "repository layout is incomplete; repair it before running AI world deduction",
                "book_id": book_id,
                "integrity": integrity,
            }
        ),
        409,
    )


def _ensure_ai_route_layout_ready(book_id: str, storage_root: str, *, book_name: str | None = None):
    integrity = inspect_book_layout_integrity(book_id, storage_root)
    if not integrity["needs_repair"]:
        return ensure_book_layout(book_id, storage_root, book_name=book_name), integrity, None

    # AI routes should aggressively self-heal. Missing repo/layout/tracked files
    # should not block brainstorm/world/style discussion flows.
    repaired = repair_book_layout(book_id, storage_root, book_name=book_name)
    repaired_integrity = repaired["integrity"]
    if not repaired_integrity["needs_repair"]:
        return repaired, repaired_integrity, None

    return None, repaired_integrity, _layout_repair_required_response(book_id, storage_root)


def _resolve_virtual_active_file(book_id: str, storage_root: str, active_file: str):
    paths = get_book_paths(book_id, storage_root)
    integrity = inspect_book_layout_integrity(book_id, storage_root)
    if not integrity["exists"]:
        return None, None, None, None, None, _book_missing_response(book_id, storage_root)

    repo_dir = paths["book_dir"]
    try:
        file_path, normalized_rel_path = _resolve_target_file(repo_dir, active_file)
    except ValueError as exc:
        return None, None, None, None, None, (jsonify({"status": "error", "code": "INVALID_PAYLOAD", "message": str(exc)}), 400)

    if os.path.exists(file_path):
        baseline_markdown = _read_file_text(file_path)
        return paths, repo_dir, file_path, normalized_rel_path, baseline_markdown, None

    virtual_content = get_virtual_core_file_content(normalized_rel_path)
    if virtual_content is None:
        inferred_type = _infer_file_type_from_path(normalized_rel_path)
        if inferred_type is None:
            return None, None, None, None, None, (
                jsonify(
                    {
                        "status": "error",
                        "code": "TARGET_PATH_FORBIDDEN",
                        "message": f"active_file must be readable by a routed Dify agent: {normalized_rel_path}",
                    }
                ),
                400,
            )
        return None, None, None, None, None, (jsonify({"status": "error", "code": "NOT_FOUND", "message": f"file not found: {normalized_rel_path}"}), 404)
    return paths, repo_dir, file_path, normalized_rel_path, virtual_content, None


def _attach_warning(response: tuple, warning_text: str) -> tuple:
    if not isinstance(response, tuple) or len(response) != 2:
        return response
    response_obj, status_code = response
    try:
        body = response_obj.get_json(silent=True)
    except Exception:
        return response
    if not isinstance(body, dict):
        return response

    existing = body.get("warning")
    if isinstance(existing, str) and existing.strip():
        body["warning"] = f"{existing}; {warning_text}"
    else:
        body["warning"] = warning_text
    return jsonify(body), status_code
