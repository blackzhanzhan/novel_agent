from typing import Callable

from flask import Blueprint, jsonify

from utils.book_storage import get_book_paths, inspect_book_layout_integrity
from utils.git_utils import format_git_error, run_git


def create_blueprint(
    *,
    storage_root: str,
    require_book_id: Callable[[dict | None], tuple[str | None, tuple | None]],
    json_error: Callable[[str, str, int], tuple],
) -> Blueprint:
    bp = Blueprint("history", __name__)

    def _parse_rows(log_text: str, refs_by_commit: dict[str, list[str]] | None = None) -> list[dict]:
        rows: list[dict] = []
        refs_by_commit = refs_by_commit or {}
        for line in log_text.splitlines():
            parts = line.split("\t", 3)
            if len(parts) != 4:
                continue
            commit_id, parents, timestamp, message = parts
            parent_ids = [parent for parent in parents.split() if parent]
            rows.append(
                {
                    "commit_id": commit_id,
                    "parent_id": parent_ids[0] if parent_ids else None,
                    "parent_ids": parent_ids,
                    "timestamp": timestamp,
                    "message": message,
                    "refs": refs_by_commit.get(commit_id, []),
                }
            )
        return rows

    def _collect_refs(repo_dir: str) -> dict[str, list[str]]:
        refs_text = run_git(
            repo_dir,
            ["for-each-ref", "--format=%(objectname)\t%(refname:short)"],
        ).stdout
        refs_by_commit: dict[str, list[str]] = {}
        for line in refs_text.splitlines():
            parts = line.strip().split("\t", 1)
            if len(parts) != 2:
                continue
            commit_id, ref_name = parts
            if not commit_id or not ref_name:
                continue
            refs = refs_by_commit.setdefault(commit_id, [])
            if ref_name not in refs:
                refs.append(ref_name)
        for commit_id, refs in refs_by_commit.items():
            refs_by_commit[commit_id] = sorted(refs)
        return refs_by_commit

    @bp.get("/books/history")
    def books_history():
        book_id, book_err = require_book_id(None)
        if book_err:
            return book_err

        paths = get_book_paths(book_id, storage_root)
        integrity = inspect_book_layout_integrity(book_id, storage_root)
        if not integrity["exists"]:
            return json_error("BOOK_NOT_FOUND", f"book storage is missing for {book_id}; initialize or repair it first", 404)
        if integrity["needs_repair"]:
            return json_error("LAYOUT_REPAIR_REQUIRED", "repository layout is incomplete; call /books/repair_layout first", 409)
        repo_dir = paths["book_dir"]

        try:
            log_text = run_git(
                repo_dir,
                ["log", "--date=iso", "--pretty=format:%H\t%P\t%ad\t%s"],
            ).stdout
        except Exception as exc:
            return json_error("GIT_COMMIT_FAILED", format_git_error(exc) or "failed to read git history", 500)

        rows = _parse_rows(log_text)

        return jsonify({"status": "success", "book_id": book_id, "total": len(rows), "history": rows}), 200

    @bp.get("/books/git_graph")
    def books_git_graph():
        book_id, book_err = require_book_id(None)
        if book_err:
            return book_err

        paths = get_book_paths(book_id, storage_root)
        integrity = inspect_book_layout_integrity(book_id, storage_root)
        if not integrity["exists"]:
            return json_error("BOOK_NOT_FOUND", f"book storage is missing for {book_id}; initialize or repair it first", 404)
        if integrity["needs_repair"]:
            return json_error("LAYOUT_REPAIR_REQUIRED", "repository layout is incomplete; call /books/repair_layout first", 409)
        repo_dir = paths["book_dir"]

        try:
            log_text = run_git(
                repo_dir,
                ["log", "--all", "--date=iso", "--pretty=format:%H\t%P\t%ad\t%s"],
            ).stdout
            refs_by_commit = _collect_refs(repo_dir)
        except Exception as exc:
            return json_error("GIT_COMMIT_FAILED", format_git_error(exc) or "failed to read git graph", 500)

        commits = _parse_rows(log_text, refs_by_commit)
        return jsonify({"status": "success", "book_id": book_id, "total": len(commits), "commits": commits}), 200

    return bp
