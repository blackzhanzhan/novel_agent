import logging
import os
import json
import shutil
import stat
import time
from difflib import SequenceMatcher
from typing import Any, Callable

from flask import Blueprint, jsonify, request

from utils.book_storage import get_book_metadata, repair_book_layout, smart_resolve_id, validate_book_id
from utils.session_runtime import delete_book_conversations

logger = logging.getLogger(__name__)

PENDING_DELETE_DIR = "_pending_delete"


def _remove_readonly(func, path, _exc_info):
    # Handle read-only files (WinError 5)
    try:
        os.chmod(path, stat.S_IWRITE)
    except OSError:
        pass
    # Handle locked files (WinError 32) with retries
    for attempt in range(5):
        try:
            func(path)
            return
        except PermissionError:
            if attempt < 4:
                time.sleep(0.3 * (attempt + 1))
            else:
                raise


def _ensure_inside_storage_root(storage_root: str, path: str) -> str:
    root = os.path.abspath(storage_root)
    abs_path = os.path.abspath(path)
    if os.path.commonpath([root, abs_path]) != root:
        raise ValueError("resolved delete path escapes storage root")
    return abs_path


def _pending_delete_marker_path(storage_root: str, book_id: str) -> str:
    safe_book_id = validate_book_id(book_id)
    marker_dir = _ensure_inside_storage_root(storage_root, os.path.join(storage_root, PENDING_DELETE_DIR))
    return _ensure_inside_storage_root(marker_dir, os.path.join(marker_dir, f"{safe_book_id}.json"))


def _is_book_pending_delete(storage_root: str, book_id: str) -> bool:
    return os.path.exists(_pending_delete_marker_path(storage_root, book_id))


def _clear_pending_delete_marker(storage_root: str, book_id: str) -> None:
    try:
        os.remove(_pending_delete_marker_path(storage_root, book_id))
    except FileNotFoundError:
        pass


def _mark_book_pending_delete(storage_root: str, book_id: str, book_name: str, reason: str) -> None:
    marker_path = _pending_delete_marker_path(storage_root, book_id)
    os.makedirs(os.path.dirname(marker_path), exist_ok=True)
    payload = {
        "book_id": book_id,
        "book_name": book_name,
        "reason": reason,
        "marked_at": int(time.time()),
    }
    tmp_path = f"{marker_path}.{os.getpid()}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp_path, marker_path)


def _cleanup_pending_book(storage_root: str, book_id: str) -> bool:
    book_dir = _ensure_inside_storage_root(storage_root, os.path.join(storage_root, validate_book_id(book_id)))
    if not os.path.isdir(book_dir):
        _clear_pending_delete_marker(storage_root, book_id)
        return True
    try:
        shutil.rmtree(book_dir, onexc=_remove_readonly)
    except OSError:
        return False
    _clear_pending_delete_marker(storage_root, book_id)
    logger.info("Cleaned pending-delete book %s", book_id)
    return True


def _should_hide_book_entry(storage_root: str, book_id: str) -> bool:
    if not _is_book_pending_delete(storage_root, book_id):
        return False
    _cleanup_pending_book(storage_root, book_id)
    return _is_book_pending_delete(storage_root, book_id) or not os.path.isdir(os.path.join(storage_root, book_id))


def _trash_locked_book(storage_root: str, book_id: str, book_name: str) -> tuple:
    """Move a locked book directory to a _trash_ name so it can be cleaned up later."""
    book_dir = _ensure_inside_storage_root(storage_root, os.path.join(storage_root, book_id))

    # Best-effort: remove all contents first (files, subdirs)
    for entry in os.listdir(book_dir):
        path = os.path.join(book_dir, entry)
        try:
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path, onexc=_remove_readonly)
            else:
                os.remove(path)
        except OSError:
            pass

    # Retry the rmdir a few more times with longer waits
    for _ in range(10):
        try:
            os.rmdir(book_dir)
            logger.info("Deleted book %s (%s) after retry", book_id, book_name)
            return jsonify({"status": "success", "book_id": book_id, "book_name": book_name}), 200
        except OSError:
            time.sleep(0.5)

    # Final fallback: rename to trash
    trash_name = f"_trash_{int(time.time())}_{book_id}"
    trash_path = _ensure_inside_storage_root(storage_root, os.path.join(storage_root, trash_name))
    try:
        os.rename(book_dir, trash_path)
        logger.info("Renamed locked book %s to %s", book_id, trash_name)
        return jsonify({
            "status": "success",
            "book_id": book_id,
            "book_name": book_name,
            "note": f"directory renamed to {trash_name} (locked by another process)",
        }), 200
    except OSError as exc:
        _mark_book_pending_delete(storage_root, book_id, book_name, str(exc))
        logger.warning("Marked locked book %s as pending delete after rename failed: %s", book_id, exc)
        return jsonify({
            "status": "success",
            "book_id": book_id,
            "book_name": book_name,
            "cleanup_pending": True,
            "note": "book hidden from library; physical cleanup will retry after the lock is released",
        }), 200


def _normalize_query(value: str | None) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().casefold()


def _score_match(query_norm: str, book_id: str, book_name: str) -> float:
    id_norm = book_id.casefold()
    name_norm = book_name.casefold()

    score = 0.0
    if query_norm == id_norm or query_norm == name_norm:
        score = 1.0
    else:
        if query_norm and query_norm in name_norm:
            score = max(score, 0.95)
        if query_norm and query_norm in id_norm:
            score = max(score, 0.90)
        if query_norm:
            score = max(score, SequenceMatcher(None, query_norm, name_norm).ratio())

    return score


def _cancel_book_background_work(book_id: str) -> None:
    try:
        from agents.tomato_import import cancel_book_background_work

        cancel_book_background_work(book_id)
    except Exception:
        logger.exception("Failed to cancel background work before deleting %s", book_id)


def create_blueprint(
    *,
    storage_root: str,
    parse_json_payload: Callable[[list[str] | None], tuple[dict | None, tuple | None]],
    json_error: Callable[[str, str, int], tuple],
) -> Blueprint:
    bp = Blueprint("library", __name__)

    @bp.post("/books/init")
    def init_book():
        payload, err = parse_json_payload(["book_name"])
        if err:
            return err

        book_name: Any = payload.get("book_name")
        if not isinstance(book_name, str) or not book_name.strip():
            return json_error("MISSING_FIELD", "book_name is required", 400)
        normalized_book_name = book_name.strip()

        raw_book_id = payload.get("book_id")
        if isinstance(raw_book_id, str) and raw_book_id.strip():
            try:
                book_id = validate_book_id(raw_book_id)
            except ValueError as exc:
                return json_error("MISSING_FIELD", str(exc), 400)
        else:
            # Smart resolution prevents "ID of ID" when user accidentally sends an existing
            # `book_id` string via `book_name`.
            book_id = smart_resolve_id(normalized_book_name, storage_root)

        paths = repair_book_layout(book_id, storage_root, book_name=normalized_book_name)
        metadata = get_book_metadata(book_id, storage_root)

        return (
            jsonify(
                {
                    "status": "success",
                    "book_id": book_id,
                    "book_name": metadata.get("book_name", book_id),
                    "book_dir": paths["book_dir"],
                    "metadata_path": metadata.get("metadata_path", paths["metadata_path"]),
                }
            ),
            200,
        )

    @bp.get("/books/search")
    def search_books():
        query = request.args.get("query")
        query_norm = _normalize_query(query)
        if not query_norm:
            return json_error("MISSING_FIELD", "query is required", 400)

        matches = []
        try:
            entries = sorted(os.listdir(storage_root))
        except OSError as exc:
            return json_error("INVALID_PAYLOAD", str(exc), 500)

        for name in entries:
            book_dir = os.path.join(storage_root, name)
            if not os.path.isdir(book_dir) or name.startswith(".") or name.startswith("_trash_") or name == PENDING_DELETE_DIR:
                continue

            try:
                book_id = validate_book_id(name)
                if _should_hide_book_entry(storage_root, book_id):
                    continue
                metadata = get_book_metadata(book_id, storage_root)
                book_name = metadata.get("book_name", book_id)
                if not isinstance(book_name, str) or not book_name.strip():
                    book_name = book_id
                score = _score_match(query_norm, book_id, book_name)
                if score < 0.30:
                    continue
                matches.append(
                    {
                        "book_id": book_id,
                        "book_name": book_name,
                        "score": round(score, 4),
                    }
                )
            except Exception:
                # Ignore a single broken folder and continue scanning.
                continue

        matches.sort(key=lambda row: (-row["score"], row["book_name"], row["book_id"]))

        return (
            jsonify(
                {
                    "status": "success",
                    "query": query,
                    "total": len(matches),
                    "matches": matches,
                }
            ),
            200,
        )

    @bp.delete("/books/<book_id>")
    def delete_book(book_id: str):
        try:
            validated_id = validate_book_id(book_id)
        except ValueError as exc:
            return json_error("INVALID_BOOK_ID", str(exc), 400)

        book_dir = os.path.join(storage_root, validated_id)
        if not os.path.isdir(book_dir):
            if _is_book_pending_delete(storage_root, validated_id):
                delete_book_conversations(None, validated_id)
                _clear_pending_delete_marker(storage_root, validated_id)
                return jsonify({"status": "success", "book_id": validated_id, "cleanup_pending": False}), 200
            return json_error("NOT_FOUND", f"book {validated_id} not found", 404)

        metadata = get_book_metadata(validated_id, storage_root)
        book_name = metadata.get("book_name", validated_id)
        _cancel_book_background_work(validated_id)
        delete_book_conversations(None, validated_id)

        try:
            shutil.rmtree(book_dir, onexc=_remove_readonly)
        except OSError:
            # On Windows, directory may be locked by a process with CWD inside it.
            # Remove all contents and rename the empty shell to a trash name.
            logger.warning("rmtree failed for %s, falling back to trash-rename", validated_id)
            try:
                return _trash_locked_book(storage_root, validated_id, book_name)
            except OSError as exc2:
                logger.exception("Trash-rename also failed for %s", validated_id)
                return json_error("DELETE_FAILED", str(exc2), 500)

        logger.info("Deleted book %s (%s)", validated_id, book_name)
        return jsonify({"status": "success", "book_id": validated_id, "book_name": book_name}), 200

    @bp.get("/books/list")
    def list_books():
        books = []
        try:
            entries = sorted(os.listdir(storage_root))
        except OSError:
            return jsonify({"status": "success", "total": 0, "books": books}), 200

        for name in entries:
            book_dir = os.path.join(storage_root, name)
            if not os.path.isdir(book_dir) or name.startswith(".") or name.startswith("_trash_") or name == PENDING_DELETE_DIR:
                continue
            try:
                book_id = validate_book_id(name)
                if _should_hide_book_entry(storage_root, book_id):
                    continue
                metadata = get_book_metadata(book_id, storage_root)
                book_name = metadata.get("book_name", book_id)
                if not isinstance(book_name, str) or not book_name.strip():
                    book_name = book_id
                books.append({"book_id": book_id, "book_name": book_name})
            except Exception:
                continue

        return jsonify({"status": "success", "total": len(books), "books": books}), 200

    return bp
