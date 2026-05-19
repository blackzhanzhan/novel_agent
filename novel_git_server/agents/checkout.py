import os
import subprocess
from typing import Callable

from flask import Blueprint, jsonify, request

from utils.book_storage import get_book_paths, inspect_book_layout_integrity
from utils.git_utils import run_git


ALLOWED_INCLUDES = {"world_model", "summary", "status_card", "chapters"}


def _parse_include(include_raw: str | None) -> list[str]:
    source = include_raw if isinstance(include_raw, str) and include_raw.strip() else "world_model,summary,chapters"
    return [token.strip() for token in source.split(",") if token.strip()]


def _parse_last_n(raw: str | None) -> int:
    if not isinstance(raw, str) or not raw.strip():
        return 3
    try:
        value = int(raw)
    except ValueError:
        return 3
    return max(1, value)


def _read_file(path: str) -> str:
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _read_from_commit(repo_dir: str, commit_id: str, rel_path: str) -> str:
    try:
        return run_git(repo_dir, ["show", f"{commit_id}:{rel_path}"]).stdout
    except subprocess.CalledProcessError:
        return ""


def _list_chapter_files(paths: dict, commit_id: str | None, last_n: int) -> list[tuple[str, str]]:
    chapters_dir = paths["chapters_dir"]
    repo_dir = paths["book_dir"]

    if not commit_id:
        names = sorted(name for name in os.listdir(chapters_dir) if name.lower().endswith(".md"))
        selected = names[-last_n:]
        rows = []
        for name in selected:
            abs_path = os.path.join(chapters_dir, name)
            rows.append((name, _read_file(abs_path)))
        return rows

    try:
        ls_output = run_git(repo_dir, ["ls-tree", "-r", "--name-only", commit_id, "chapters"]).stdout
    except subprocess.CalledProcessError:
        return []

    rel_paths = [line.strip() for line in ls_output.splitlines() if line.strip().lower().endswith(".md")]
    rel_paths.sort()
    selected = rel_paths[-last_n:]
    rows = []
    for rel_path in selected:
        name = os.path.basename(rel_path)
        rows.append((name, _read_from_commit(repo_dir, commit_id, rel_path.replace("\\", "/"))))
    return rows


def create_blueprint(
    *,
    storage_root: str,
    require_book_id: Callable[[dict | None], tuple[str | None, tuple | None]],
    json_error: Callable[[str, str, int], tuple],
) -> Blueprint:
    bp = Blueprint("checkout", __name__)

    @bp.get("/checkout")
    def checkout():
        book_id, book_err = require_book_id(None)
        if book_err:
            return book_err

        include_tokens = _parse_include(request.args.get("include"))
        unknown_tokens = [token for token in include_tokens if token not in ALLOWED_INCLUDES]
        if unknown_tokens:
            return json_error("INVALID_PAYLOAD", f"unknown include tokens: {', '.join(unknown_tokens)}", 400)

        last_n = _parse_last_n(request.args.get("last_n"))
        commit_id = request.args.get("commit_id")
        if isinstance(commit_id, str):
            commit_id = commit_id.strip() or None

        paths = get_book_paths(book_id, storage_root)
        integrity = inspect_book_layout_integrity(book_id, storage_root)
        if not integrity["exists"]:
            return json_error("BOOK_NOT_FOUND", f"book storage is missing for {book_id}; initialize or repair it first", 404)
        if integrity["needs_repair"]:
            return json_error("LAYOUT_REPAIR_REQUIRED", "repository layout is incomplete; call /books/repair_layout first", 409)
        parts: list[str] = []

        if "world_model" in include_tokens:
            text = (
                _read_from_commit(paths["book_dir"], commit_id, "world_model.md")
                if commit_id
                else _read_file(paths["world_model_path"])
            )
            parts.append("## world_model\n" + text)

        if "summary" in include_tokens:
            text = (
                _read_from_commit(paths["book_dir"], commit_id, "summary.md")
                if commit_id
                else _read_file(paths["summary_path"])
            )
            parts.append("## summary\n" + text)

        if "status_card" in include_tokens:
            text = (
                _read_from_commit(paths["book_dir"], commit_id, "status_card.md")
                if commit_id
                else _read_file(paths["status_card_path"])
            )
            parts.append("## status_card\n" + text)

        if "chapters" in include_tokens:
            chapter_rows = _list_chapter_files(paths, commit_id, last_n)
            for name, content in chapter_rows:
                parts.append(f"## chapter:{name}\n{content}")

        markdown = "\n\n".join(part.rstrip() for part in parts if part is not None).strip()
        return (
            jsonify(
                {
                    "status": "success",
                    "book_id": book_id,
                    "payload": {
                        "include": include_tokens,
                        "last_n": last_n,
                        "commit_id": commit_id,
                        "markdown": markdown,
                    },
                }
            ),
            200,
        )

    return bp
