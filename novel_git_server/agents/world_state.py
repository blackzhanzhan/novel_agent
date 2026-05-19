import subprocess
from typing import Any, Callable

from flask import Blueprint, jsonify

from utils.book_storage import ensure_book_layout, resolve_book_id
from utils.git_utils import ensure_repo, format_git_error, is_nothing_to_commit_error, resolve_head, run_git


def create_blueprint(
    *,
    storage_root: str,
    parse_json_payload: Callable[[list[str] | None], tuple[dict | None, tuple | None]],
    json_error: Callable[[str, str, int], tuple],
) -> Blueprint:
    bp = Blueprint("world_state", __name__)

    @bp.post("/commit_world_state")
    def commit_world_state():
        payload, err = parse_json_payload(["content"])
        if err:
            return err

        raw_book_name = payload.get("book_name")
        normalized_book_name = raw_book_name.strip() if isinstance(raw_book_name, str) and raw_book_name.strip() else None
        try:
            book_id = resolve_book_id(payload.get("book_id"), raw_book_name, storage_root)
        except ValueError as exc:
            return json_error("MISSING_FIELD", str(exc), 400)

        content = payload.get("content", "")
        if not isinstance(content, str):
            content = str(content)

        message: Any = payload.get("message", "update world state")
        if not isinstance(message, str) or not message.strip():
            message = "update world state"
        message = message.strip()

        paths = ensure_book_layout(book_id, storage_root, book_name=normalized_book_name)
        repo_dir = paths["book_dir"]
        world_model_path = paths["world_model_path"]

        with open(world_model_path, "w", encoding="utf-8") as f:
            f.write(content)

        try:
            ensure_repo(repo_dir)
            run_git(repo_dir, ["add", "--", "world_model.md"])
            status_output = run_git(repo_dir, ["status", "--porcelain", "--", "world_model.md"]).stdout
            if not status_output.strip():
                commit_id = resolve_head(repo_dir, message)
                return (
                    jsonify(
                        {
                            "status": "success",
                            "book_id": book_id,
                            "commit_id": commit_id,
                            "file_path": world_model_path,
                        }
                    ),
                    200,
                )
            try:
                run_git(repo_dir, ["commit", "-m", message, "--", "world_model.md"])
            except subprocess.CalledProcessError as exc:
                if not is_nothing_to_commit_error(exc):
                    raise
            commit_id = resolve_head(repo_dir, message)
        except Exception as exc:
            return json_error("GIT_COMMIT_FAILED", format_git_error(exc) or "failed to commit world state", 500)

        return (
            jsonify(
                {
                    "status": "success",
                    "book_id": book_id,
                    "commit_id": commit_id,
                    "file_path": world_model_path,
                }
            ),
            200,
        )

    return bp
