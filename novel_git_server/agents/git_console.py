from __future__ import annotations

import os
import subprocess
from typing import Any, Callable

from flask import Blueprint, jsonify, request

from utils.book_storage import get_book_paths, inspect_book_layout_integrity
from utils.git_utils import ensure_repo, format_git_error, is_nothing_to_commit_error, run_git

DEFAULT_BOOTSTRAP_COMMIT_MESSAGE = "chore: bootstrap repository baseline"
DEFAULT_BOOTSTRAP_LAYOUT_MESSAGE = "chore: bootstrap tracked layout files"
DEFAULT_GIT_USER_NAME = "LoreGit Bot"
DEFAULT_GIT_USER_EMAIL = "loregit@example.local"
DIFF_SCOPES = {"unstaged", "staged", "commit"}


def _ensure_repo_identity(repo_dir: str) -> None:
    checks = {
        "user.name": DEFAULT_GIT_USER_NAME,
        "user.email": DEFAULT_GIT_USER_EMAIL,
    }
    for key, default in checks.items():
        value = ""
        try:
            value = run_git(repo_dir, ["config", "--get", key]).stdout.strip()
        except subprocess.CalledProcessError:
            value = ""
        if value:
            continue
        run_git(repo_dir, ["config", key, default])


def _ensure_initial_commit(repo_dir: str) -> None:
    try:
        run_git(repo_dir, ["rev-parse", "HEAD"])
        return
    except subprocess.CalledProcessError:
        pass

    _ensure_repo_identity(repo_dir)
    run_git(repo_dir, ["add", "--all"])
    try:
        run_git(repo_dir, ["commit", "-m", DEFAULT_BOOTSTRAP_COMMIT_MESSAGE])
    except subprocess.CalledProcessError as exc:
        if not is_nothing_to_commit_error(exc):
            raise
        run_git(repo_dir, ["commit", "--allow-empty", "-m", DEFAULT_BOOTSTRAP_COMMIT_MESSAGE])


def _ensure_layout_files_tracked(repo_dir: str) -> None:
    tracked_candidates = [
        "world_model.md",
        "summary.md",
        "status_card.md",
        "style_guide.md",
        "style_fingerprint.md",
        "style_review.md",
        "style_constraints_for_continuation.md",
        "error_archive.md",
        "domain_rules.md",
        "metadata.json",
        ".gitignore",
    ]
    existing = [name for name in tracked_candidates if os.path.exists(os.path.join(repo_dir, name))]
    if not existing:
        return

    tracked_text = run_git(repo_dir, ["ls-files", "--", *existing]).stdout
    tracked = {line.strip() for line in tracked_text.splitlines() if line.strip()}
    missing_tracked = [name for name in existing if name not in tracked]
    if not missing_tracked:
        return

    run_git(repo_dir, ["add", "--", *missing_tracked])
    status = run_git(repo_dir, ["status", "--porcelain", "--", *missing_tracked]).stdout
    if not status.strip():
        return
    _ensure_repo_identity(repo_dir)
    try:
        run_git(repo_dir, ["commit", "-m", DEFAULT_BOOTSTRAP_LAYOUT_MESSAGE, "--", *missing_tracked])
    except subprocess.CalledProcessError as exc:
        if not is_nothing_to_commit_error(exc):
            raise


def _should_bootstrap_layout_tracking(repo_dir: str) -> bool:
    # Metadata-only bootstrap repositories need one follow-up commit that tracks
    # core layout files. Avoid running this on normal history reads.
    try:
        commit_count_text = run_git(repo_dir, ["rev-list", "--count", "HEAD"]).stdout.strip()
        head_subject = run_git(repo_dir, ["log", "-1", "--pretty=%s"]).stdout.strip()
    except subprocess.CalledProcessError:
        return False

    try:
        commit_count = int(commit_count_text or "0")
    except ValueError:
        return False

    return commit_count == 1 and head_subject == "chore: update book metadata"


def _prepare_repo(paths: dict[str, str]) -> str:
    repo_dir = paths["book_dir"]
    ensure_repo(repo_dir)
    _ensure_initial_commit(repo_dir)
    if _should_bootstrap_layout_tracking(repo_dir):
        _ensure_layout_files_tracked(repo_dir)
    return repo_dir


def _current_branch(repo_dir: str) -> str:
    branch = run_git(repo_dir, ["branch", "--show-current"]).stdout.strip()
    if branch:
        return branch
    symbolic = run_git(repo_dir, ["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
    return symbolic or "(detached)"


def _list_local_branches(repo_dir: str) -> list[str]:
    output = run_git(repo_dir, ["for-each-ref", "--format=%(refname:short)", "refs/heads"]).stdout
    branches = [line.strip() for line in output.splitlines() if line.strip()]
    return branches


def _resolve_mainline_branch(repo_dir: str, current_branch: str) -> str:
    head_names = set(_list_local_branches(repo_dir))
    if "main" in head_names:
        return "main"
    if "master" in head_names:
        return "master"
    return current_branch


def _head_commit(repo_dir: str) -> str:
    return run_git(repo_dir, ["rev-parse", "HEAD"]).stdout.strip()


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
                "message": "repository layout is incomplete; call /books/repair_layout before opening Git console",
                "book_id": book_id,
                "integrity": integrity,
            }
        ),
        409,
    )


def _require_ready_repo(book_id: str, storage_root: str):
    paths = get_book_paths(book_id, storage_root)
    integrity = inspect_book_layout_integrity(book_id, storage_root)
    if not integrity["exists"]:
        return None, integrity, _book_missing_response(book_id, storage_root)
    if integrity["needs_repair"]:
        return None, integrity, _layout_repair_required_response(book_id, storage_root)
    return paths["book_dir"], integrity, None


def _parse_status_line(line: str) -> dict[str, Any] | None:
    if len(line) < 4:
        return None
    index_status = line[0]
    worktree_status = line[1]
    path_part = line[3:].strip()
    if not path_part:
        return None

    if " -> " in path_part:
        old_path, new_path = path_part.split(" -> ", 1)
        path = new_path.strip()
        previous_path = old_path.strip()
    else:
        path = path_part
        previous_path = None

    staged = index_status not in {" ", "?"}
    unstaged = worktree_status != " "
    is_untracked = index_status == "?" and worktree_status == "?"

    return {
        "path": path,
        "previous_path": previous_path,
        "index_status": index_status,
        "worktree_status": worktree_status,
        "staged": staged,
        "unstaged": unstaged,
        "is_untracked": is_untracked,
    }


def _status_entries(repo_dir: str) -> list[dict[str, Any]]:
    output = run_git(repo_dir, ["status", "--porcelain"]).stdout
    entries = []
    for raw in output.splitlines():
        parsed = _parse_status_line(raw)
        if parsed:
            entries.append(parsed)
    entries.sort(key=lambda row: row["path"])
    return entries


def _status_summary(entries: list[dict[str, Any]]) -> dict[str, Any]:
    staged_count = sum(1 for row in entries if row["staged"])
    unstaged_count = sum(1 for row in entries if row["unstaged"])
    untracked_count = sum(1 for row in entries if row["is_untracked"])
    return {
        "is_dirty": bool(entries),
        "staged_count": staged_count,
        "unstaged_count": unstaged_count,
        "untracked_count": untracked_count,
    }


def _normalize_rel_path(raw_path: Any) -> str:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("path is required")

    # Normalize separators first so .git guards behave consistently across OSes.
    normalized_input = raw_path.strip().replace("\\", "/")
    normalized = os.path.normpath(normalized_input).replace("\\", "/")
    if normalized in {"", "."}:
        raise ValueError("path is required")
    if os.path.isabs(normalized):
        raise ValueError("absolute path is forbidden")
    if normalized == ".." or normalized.startswith("../"):
        raise ValueError("path escapes repository")

    # Forbid access to the internal .git directory only, while allowing
    # legal dotfiles like .gitignore/.gitattributes/.gitmodules.
    path_segments = [segment for segment in normalized.split("/") if segment and segment != "."]
    if any(segment == ".git" for segment in path_segments):
        raise ValueError("path inside .git is forbidden")
    return normalized


def _assert_path_inside_repo(repo_dir: str, rel_path: str) -> str:
    abs_repo = os.path.abspath(repo_dir)
    abs_path = os.path.abspath(os.path.join(abs_repo, rel_path))
    if os.path.commonpath([abs_repo, abs_path]) != abs_repo:
        raise ValueError("path escapes repository")
    return abs_path


def _read_worktree_file(repo_dir: str, rel_path: str) -> str:
    abs_path = _assert_path_inside_repo(repo_dir, rel_path)
    if not os.path.exists(abs_path):
        return ""
    if os.path.isdir(abs_path):
        raise ValueError("path must point to a file")
    with open(abs_path, "r", encoding="utf-8", errors="replace") as file_obj:
        return file_obj.read()


def _git_object_exists(repo_dir: str, object_spec: str) -> bool:
    try:
        run_git(repo_dir, ["cat-file", "-e", object_spec])
        return True
    except subprocess.CalledProcessError:
        return False


def _read_git_blob(repo_dir: str, object_spec: str) -> str:
    if not _git_object_exists(repo_dir, object_spec):
        return ""
    return run_git(repo_dir, ["show", object_spec]).stdout


def _refs_by_commit(repo_dir: str) -> dict[str, list[str]]:
    refs_text = run_git(
        repo_dir,
        ["for-each-ref", "--format=%(objectname)\t%(refname:short)"],
    ).stdout
    refs: dict[str, list[str]] = {}
    for line in refs_text.splitlines():
        parts = line.strip().split("\t", 1)
        if len(parts) != 2:
            continue
        commit_id, ref_name = parts
        if not commit_id or not ref_name:
            continue
        ref_bucket = refs.setdefault(commit_id, [])
        if ref_name not in ref_bucket:
            ref_bucket.append(ref_name)
    for commit_id, names in refs.items():
        refs[commit_id] = sorted(names)
    return refs


def _history_rows(repo_dir: str, limit: int) -> list[dict[str, Any]]:
    refs = _refs_by_commit(repo_dir)
    log_text = run_git(
        repo_dir,
        [
            "log",
            f"--max-count={limit}",
            "--date=iso",
            "--pretty=format:%H\t%P\t%ad\t%an\t%ae\t%s",
        ],
    ).stdout

    rows: list[dict[str, Any]] = []
    for line in log_text.splitlines():
        parts = line.split("\t", 5)
        if len(parts) != 6:
            continue
        commit_id, parents, timestamp, author_name, author_email, message = parts
        parent_ids = [token for token in parents.split() if token]
        rows.append(
            {
                "commit_id": commit_id,
                "short_id": commit_id[:8],
                "parent_ids": parent_ids,
                "timestamp": timestamp,
                "author_name": author_name,
                "author_email": author_email,
                "message": message,
                "refs": refs.get(commit_id, []),
            }
        )
    return rows


def _sanitize_branch_name(raw_name: Any) -> str:
    if not isinstance(raw_name, str) or not raw_name.strip():
        raise ValueError("branch_name is required")
    branch_name = raw_name.strip()
    if branch_name.startswith("-"):
        raise ValueError("branch_name is invalid")
    return branch_name


def _branch_exists(repo_dir: str, branch_name: str) -> bool:
    try:
        run_git(repo_dir, ["show-ref", "--verify", f"refs/heads/{branch_name}"])
        return True
    except subprocess.CalledProcessError:
        return False


def _ensure_branch_name_valid(repo_dir: str, branch_name: str) -> None:
    run_git(repo_dir, ["check-ref-format", "--branch", branch_name])


def _resolve_commit(repo_dir: str, raw_ref: Any) -> str:
    if isinstance(raw_ref, str) and raw_ref.strip():
        resolved = raw_ref.strip()
    else:
        resolved = "HEAD"
    return run_git(repo_dir, ["rev-parse", "--verify", f"{resolved}^{{commit}}"]).stdout.strip()


def _delete_other_branches(repo_dir: str, current_branch: str) -> tuple[list[str], list[dict[str, str]]]:
    deleted: list[str] = []
    skipped: list[dict[str, str]] = []
    for branch_name in _list_local_branches(repo_dir):
        if branch_name == current_branch:
            continue
        try:
            run_git(repo_dir, ["branch", "-D", branch_name])
            deleted.append(branch_name)
        except subprocess.CalledProcessError as exc:
            skipped.append(
                {
                    "branch": branch_name,
                    "reason": format_git_error(exc) or "failed to delete branch",
                }
            )
    return deleted, skipped


def create_blueprint(
    *,
    storage_root: str,
    parse_json_payload: Callable[[list[str] | None], tuple[dict | None, tuple | None]],
    require_book_id: Callable[[dict | None], tuple[str | None, tuple | None]],
    json_error: Callable[[str, str, int], tuple],
) -> Blueprint:
    bp = Blueprint("git_console", __name__)

    @bp.get("/books/git_status")
    def books_git_status():
        book_id, book_err = require_book_id(None)
        if book_err:
            return book_err

        repo_dir, _, ready_err = _require_ready_repo(book_id, storage_root)
        if ready_err:
            return ready_err
        assert repo_dir is not None

        current_branch = _current_branch(repo_dir)
        entries = _status_entries(repo_dir)
        summary = _status_summary(entries)
        return (
            jsonify(
                {
                    "status": "success",
                    "book_id": book_id,
                    "current_branch": current_branch,
                    "mainline_branch": _resolve_mainline_branch(repo_dir, current_branch),
                    "head_commit": _head_commit(repo_dir),
                    **summary,
                }
            ),
            200,
        )

    @bp.get("/books/git_branches")
    def books_git_branches():
        book_id, book_err = require_book_id(None)
        if book_err:
            return book_err

        repo_dir, _, ready_err = _require_ready_repo(book_id, storage_root)
        if ready_err:
            return ready_err
        assert repo_dir is not None

        current_branch = _current_branch(repo_dir)
        mainline_branch = _resolve_mainline_branch(repo_dir, current_branch)
        rows_text = run_git(
            repo_dir,
            [
                "for-each-ref",
                "--sort=-committerdate",
                "--format=%(refname:short)\t%(objectname)\t%(committerdate:iso)\t%(contents:subject)",
                "refs/heads",
            ],
        ).stdout

        branches: list[dict[str, Any]] = []
        for line in rows_text.splitlines():
            parts = line.split("\t", 3)
            if len(parts) != 4:
                continue
            name, commit_id, updated_at, subject = parts
            branches.append(
                {
                    "name": name,
                    "head_commit": commit_id,
                    "updated_at": updated_at,
                    "head_message": subject,
                    "is_current": name == current_branch,
                    "is_mainline": name == mainline_branch,
                }
            )

        return (
            jsonify(
                {
                    "status": "success",
                    "book_id": book_id,
                    "current_branch": current_branch,
                    "mainline_branch": mainline_branch,
                    "branches": branches,
                }
            ),
            200,
        )

    @bp.get("/books/git_history_list")
    def books_git_history_list():
        book_id, book_err = require_book_id(None)
        if book_err:
            return book_err

        raw_limit = request.args.get("limit")
        try:
            limit = int(raw_limit) if raw_limit else 150
        except ValueError:
            limit = 150
        limit = max(1, min(limit, 600))

        repo_dir, _, ready_err = _require_ready_repo(book_id, storage_root)
        if ready_err:
            return ready_err
        assert repo_dir is not None
        commits = _history_rows(repo_dir, limit)

        return (
            jsonify(
                {
                    "status": "success",
                    "book_id": book_id,
                    "total": len(commits),
                    "commits": commits,
                }
            ),
            200,
        )

    @bp.get("/books/git_working_tree")
    def books_git_working_tree():
        book_id, book_err = require_book_id(None)
        if book_err:
            return book_err

        repo_dir, _, ready_err = _require_ready_repo(book_id, storage_root)
        if ready_err:
            return ready_err
        assert repo_dir is not None
        entries = _status_entries(repo_dir)
        summary = _status_summary(entries)

        return (
            jsonify(
                {
                    "status": "success",
                    "book_id": book_id,
                    **summary,
                    "entries": entries,
                }
            ),
            200,
        )

    @bp.get("/books/git_file_view")
    def books_git_file_view():
        book_id, book_err = require_book_id(None)
        if book_err:
            return book_err

        raw_path = request.args.get("path")
        try:
            rel_path = _normalize_rel_path(raw_path)
        except ValueError as exc:
            return json_error("INVALID_PATH", str(exc), 400)

        raw_ref = request.args.get("ref")

        repo_dir, _, ready_err = _require_ready_repo(book_id, storage_root)
        if ready_err:
            return ready_err
        assert repo_dir is not None

        try:
            if isinstance(raw_ref, str) and raw_ref.strip():
                ref = raw_ref.strip()
                content = _read_git_blob(repo_dir, f"{ref}:{rel_path}")
                if content == "":
                    return json_error("FILE_NOT_FOUND", f"{rel_path} not found at {ref}", 404)
                source = ref
            else:
                content = _read_worktree_file(repo_dir, rel_path)
                source = "working_tree"
                if content == "":
                    abs_path = _assert_path_inside_repo(repo_dir, rel_path)
                    if not os.path.exists(abs_path):
                        return json_error("FILE_NOT_FOUND", f"{rel_path} not found in working tree", 404)
        except subprocess.CalledProcessError as exc:
            return json_error("GIT_OPERATION_FAILED", format_git_error(exc) or "failed to read file", 500)
        except ValueError as exc:
            return json_error("INVALID_PATH", str(exc), 400)

        return (
            jsonify(
                {
                    "status": "success",
                    "book_id": book_id,
                    "path": rel_path,
                    "source": source,
                    "content": content,
                }
            ),
            200,
        )

    @bp.get("/books/git_diff_view")
    def books_git_diff_view():
        book_id, book_err = require_book_id(None)
        if book_err:
            return book_err

        raw_scope = request.args.get("scope", "unstaged")
        scope = raw_scope.strip() if isinstance(raw_scope, str) else "unstaged"
        if scope not in DIFF_SCOPES:
            return json_error("INVALID_PAYLOAD", f"scope must be one of {sorted(DIFF_SCOPES)}", 400)

        try:
            rel_path = _normalize_rel_path(request.args.get("path"))
        except ValueError as exc:
            return json_error("INVALID_PATH", str(exc), 400)

        repo_dir, _, ready_err = _require_ready_repo(book_id, storage_root)
        if ready_err:
            return ready_err
        assert repo_dir is not None

        try:
            if scope == "unstaged":
                old_text = _read_git_blob(repo_dir, f"HEAD:{rel_path}")
                new_text = _read_worktree_file(repo_dir, rel_path)
                old_label = "HEAD"
                new_label = "Working Tree"
            elif scope == "staged":
                old_text = _read_git_blob(repo_dir, f"HEAD:{rel_path}")
                new_text = _read_git_blob(repo_dir, f":{rel_path}")
                old_label = "HEAD"
                new_label = "Index"
            else:
                commit_id_raw = request.args.get("commit_id")
                if not isinstance(commit_id_raw, str) or not commit_id_raw.strip():
                    return json_error("MISSING_FIELD", "commit_id is required when scope=commit", 400)
                commit_id = _resolve_commit(repo_dir, commit_id_raw)
                parent_line = run_git(repo_dir, ["rev-list", "--parents", "-n", "1", commit_id]).stdout.strip()
                parent_tokens = parent_line.split()
                parent_id = parent_tokens[1] if len(parent_tokens) > 1 else None

                old_text = _read_git_blob(repo_dir, f"{parent_id}:{rel_path}") if parent_id else ""
                new_text = _read_git_blob(repo_dir, f"{commit_id}:{rel_path}")
                old_label = parent_id[:8] if parent_id else "<root>"
                new_label = commit_id[:8]

            changed = old_text != new_text
        except subprocess.CalledProcessError as exc:
            return json_error("GIT_OPERATION_FAILED", format_git_error(exc) or "failed to load diff", 500)
        except ValueError as exc:
            return json_error("INVALID_PATH", str(exc), 400)

        return (
            jsonify(
                {
                    "status": "success",
                    "book_id": book_id,
                    "scope": scope,
                    "path": rel_path,
                    "old_label": old_label,
                    "new_label": new_label,
                    "old_text": old_text,
                    "new_text": new_text,
                    "changed": changed,
                }
            ),
            200,
        )

    @bp.get("/books/git_commit_files")
    def books_git_commit_files():
        book_id, book_err = require_book_id(None)
        if book_err:
            return book_err

        commit_raw = request.args.get("commit_id")
        if not isinstance(commit_raw, str) or not commit_raw.strip():
            return json_error("MISSING_FIELD", "commit_id is required", 400)

        repo_dir, _, ready_err = _require_ready_repo(book_id, storage_root)
        if ready_err:
            return ready_err
        assert repo_dir is not None

        try:
            commit_id = _resolve_commit(repo_dir, commit_raw)
            show_text = run_git(repo_dir, ["show", "--pretty=format:", "--name-status", commit_id]).stdout
        except subprocess.CalledProcessError as exc:
            return json_error("GIT_OPERATION_FAILED", format_git_error(exc) or "failed to read commit files", 500)

        files: list[dict[str, Any]] = []
        for line in show_text.splitlines():
            parts = line.split("\t")
            if not parts:
                continue
            status_token = parts[0].strip()
            if not status_token:
                continue
            status_code = status_token[0]
            path = parts[-1].strip() if len(parts) >= 2 else ""
            previous_path = parts[1].strip() if status_code == "R" and len(parts) >= 3 else None
            if not path:
                continue
            files.append(
                {
                    "path": path,
                    "status": status_code,
                    "previous_path": previous_path,
                }
            )

        return (
            jsonify(
                {
                    "status": "success",
                    "book_id": book_id,
                    "commit_id": commit_id,
                    "files": files,
                }
            ),
            200,
        )

    @bp.post("/books/git_checkout")
    def books_git_checkout():
        payload, err = parse_json_payload(["branch_name"])
        if err:
            return err

        book_id, book_err = require_book_id(payload)
        if book_err:
            return book_err

        try:
            branch_name = _sanitize_branch_name(payload.get("branch_name"))
        except ValueError as exc:
            return json_error("INVALID_PAYLOAD", str(exc), 400)

        # force=true: discard all local changes + untracked files before checkout
        force = payload.get("force", False) is True

        repo_dir, _, ready_err = _require_ready_repo(book_id, storage_root)
        if ready_err:
            return ready_err
        assert repo_dir is not None

        if not force:
            entries = _status_entries(repo_dir)
            if entries:
                return (
                    jsonify(
                        {
                            "status": "error",
                            "code": "WORKTREE_DIRTY",
                            "message": "working tree has uncommitted changes; checkout blocked",
                            "entries": entries,
                        }
                    ),
                    409,
                )

        if not _branch_exists(repo_dir, branch_name):
            return json_error("BRANCH_NOT_FOUND", f"branch does not exist: {branch_name}", 404)

        try:
            if force:
                # -f overrides modified tracked files
                run_git(repo_dir, ["checkout", "-f", branch_name])
                # -ffd also removes untracked files/dirs including nested git repos
                run_git(repo_dir, ["clean", "-ffd"])
            else:
                run_git(repo_dir, ["checkout", branch_name])
        except subprocess.CalledProcessError as exc:
            return json_error("GIT_OPERATION_FAILED", format_git_error(exc) or "failed to checkout branch", 500)

        current_branch = _current_branch(repo_dir)
        return (
            jsonify(
                {
                    "status": "success",
                    "book_id": book_id,
                    "current_branch": current_branch,
                    "mainline_branch": _resolve_mainline_branch(repo_dir, current_branch),
                    "head_commit": _head_commit(repo_dir),
                    "force": force,
                }
            ),
            200,
        )

    @bp.post("/books/git_merge")
    def books_git_merge():
        payload, err = parse_json_payload(["source_branch"])
        if err:
            return err

        book_id, book_err = require_book_id(payload)
        if book_err:
            return book_err

        try:
            source_branch = _sanitize_branch_name(payload.get("source_branch"))
        except ValueError as exc:
            return json_error("INVALID_PAYLOAD", str(exc), 400)

        no_ff = payload.get("no_ff", False) is True
        raw_message = payload.get("message", "")
        if not isinstance(raw_message, str):
            raw_message = ""

        repo_dir, _, ready_err = _require_ready_repo(book_id, storage_root)
        if ready_err:
            return ready_err
        assert repo_dir is not None

        current_branch = _current_branch(repo_dir)

        if source_branch == current_branch:
            return json_error("INVALID_PAYLOAD", "source_branch must differ from current branch", 400)

        if not _branch_exists(repo_dir, source_branch):
            return json_error("BRANCH_NOT_FOUND", f"branch does not exist: {source_branch}", 404)

        entries = _status_entries(repo_dir)
        if entries:
            return (
                jsonify(
                    {
                        "status": "error",
                        "code": "WORKTREE_DIRTY",
                        "message": "working tree has uncommitted changes; merge blocked",
                        "entries": entries,
                    }
                ),
                409,
            )

        # Snapshot target commit BEFORE merge to determine fast_forward later.
        try:
            target_commit = run_git(repo_dir, ["rev-parse", source_branch]).stdout.strip()
        except subprocess.CalledProcessError as exc:
            return json_error("GIT_OPERATION_FAILED", format_git_error(exc) or "failed to resolve source branch", 500)

        # Build merge command.
        # P1 guard: --no-ff without -m would open an interactive editor and hang the process.
        effective_msg = raw_message.strip() or f"Merge branch '{source_branch}' into '{current_branch}'"
        cmd = ["merge"]
        if no_ff:
            cmd += ["--no-ff", "-m", effective_msg]
        cmd += [source_branch]

        try:
            result = run_git(repo_dir, cmd)
            # P2: detect "already up to date" from git output.
            # git may write this to stdout OR stderr, and may be localised
            # (e.g. Chinese: "已经是最新的。"), so check combined output case-insensitively.
            combined_out = (result.stdout + result.stderr).lower()
            _UP_TO_DATE_MARKERS = ("already up to date", "already up-to-date", "已经是最新的")
            if any(marker in combined_out for marker in _UP_TO_DATE_MARKERS):
                return (
                    jsonify(
                        {
                            "status": "success",
                            "book_id": book_id,
                            "current_branch": current_branch,
                            "source_branch": source_branch,
                            "merge_type": "up_to_date",
                            "commit_id": _head_commit(repo_dir),
                        }
                    ),
                    200,
                )

            new_head = _head_commit(repo_dir)
            # FF detection: if HEAD advanced exactly to the source tip, it was fast_forward.
            merge_type = "fast_forward" if new_head == target_commit else "merge_commit"

            return (
                jsonify(
                    {
                        "status": "success",
                        "book_id": book_id,
                        "current_branch": current_branch,
                        "source_branch": source_branch,
                        "merge_type": merge_type,
                        "commit_id": new_head,
                    }
                ),
                200,
            )

        except subprocess.CalledProcessError:
            # P0 guard: extract conflicted files BEFORE abort. abort clears all markers.
            try:
                conflict_text = run_git(repo_dir, ["diff", "--name-only", "--diff-filter=U"]).stdout
                conflicted_files = [line.strip() for line in conflict_text.splitlines() if line.strip()]
            except subprocess.CalledProcessError:
                conflicted_files = []
            try:
                run_git(repo_dir, ["merge", "--abort"])
            except subprocess.CalledProcessError:
                pass
            return (
                jsonify(
                    {
                        "status": "error",
                        "code": "MERGE_CONFLICT",
                        "message": "merge conflict detected; merge aborted",
                        "conflicted_files": conflicted_files,
                    }
                ),
                409,
            )

    @bp.post("/books/git_branch_create")
    def books_git_branch_create():
        payload, err = parse_json_payload(["branch_name"])
        if err:
            return err

        book_id, book_err = require_book_id(payload)
        if book_err:
            return book_err

        try:
            branch_name = _sanitize_branch_name(payload.get("branch_name"))
        except ValueError as exc:
            return json_error("INVALID_PAYLOAD", str(exc), 400)

        checkout_after_create = payload.get("checkout", True)
        checkout_after_create = False if checkout_after_create is False else True

        repo_dir, _, ready_err = _require_ready_repo(book_id, storage_root)
        if ready_err:
            return ready_err
        assert repo_dir is not None

        if _branch_exists(repo_dir, branch_name):
            return json_error("BRANCH_EXISTS", f"branch already exists: {branch_name}", 409)

        try:
            _ensure_branch_name_valid(repo_dir, branch_name)
            from_commit = _resolve_commit(repo_dir, payload.get("from_ref"))
        except subprocess.CalledProcessError as exc:
            return json_error("INVALID_PAYLOAD", format_git_error(exc) or "invalid branch name or source ref", 400)

        try:
            run_git(repo_dir, ["branch", branch_name, from_commit])
        except subprocess.CalledProcessError as exc:
            return json_error("GIT_OPERATION_FAILED", format_git_error(exc) or "failed to create branch", 500)

        if checkout_after_create:
            entries = _status_entries(repo_dir)
            if entries:
                return (
                    jsonify(
                        {
                            "status": "error",
                            "code": "WORKTREE_DIRTY",
                            "message": "working tree has uncommitted changes; checkout blocked",
                            "entries": entries,
                        }
                    ),
                    409,
                )
            try:
                run_git(repo_dir, ["checkout", branch_name])
            except subprocess.CalledProcessError as exc:
                return json_error("GIT_OPERATION_FAILED", format_git_error(exc) or "failed to checkout branch", 500)

        current_branch = _current_branch(repo_dir)
        return (
            jsonify(
                {
                    "status": "success",
                    "book_id": book_id,
                    "branch_name": branch_name,
                    "from_commit": from_commit,
                    "checked_out": checkout_after_create,
                    "current_branch": current_branch,
                    "head_commit": _head_commit(repo_dir),
                }
            ),
            200,
        )

    @bp.post("/books/git_hard_rollback")
    def books_git_hard_rollback():
        payload, err = parse_json_payload(["target_commit"])
        if err:
            return err

        book_id, book_err = require_book_id(payload)
        if book_err:
            return book_err

        delete_other_branches = payload.get("delete_other_branches", True)
        delete_other_branches = False if delete_other_branches is False else True

        repo_dir, _, ready_err = _require_ready_repo(book_id, storage_root)
        if ready_err:
            return ready_err
        assert repo_dir is not None

        current_branch = _current_branch(repo_dir)
        if current_branch in {"", "HEAD", "(detached)"}:
            return json_error("DETACHED_HEAD_NOT_SUPPORTED", "hard rollback requires a checked-out local branch", 409)

        try:
            target_commit = _resolve_commit(repo_dir, payload.get("target_commit"))
        except subprocess.CalledProcessError as exc:
            return json_error("INVALID_PAYLOAD", format_git_error(exc) or "target_commit is invalid", 400)

        try:
            run_git(repo_dir, ["reset", "--hard", target_commit])
        except subprocess.CalledProcessError as exc:
            return json_error("GIT_OPERATION_FAILED", format_git_error(exc) or "failed to hard reset branch", 500)

        deleted_branches: list[str] = []
        skipped_branches: list[dict[str, str]] = []
        if delete_other_branches:
            deleted_branches, skipped_branches = _delete_other_branches(repo_dir, current_branch)

        return (
            jsonify(
                {
                    "status": "success",
                    "book_id": book_id,
                    "current_branch": current_branch,
                    "head_commit": _head_commit(repo_dir),
                    "target_commit": target_commit,
                    "delete_other_branches": delete_other_branches,
                    "deleted_branches": deleted_branches,
                    "skipped_branches": skipped_branches,
                }
            ),
            200,
        )

    @bp.post("/books/git_stage")
    def books_git_stage():
        payload, err = parse_json_payload(["path"])
        if err:
            return err

        book_id, book_err = require_book_id(payload)
        if book_err:
            return book_err

        try:
            rel_path = _normalize_rel_path(payload.get("path"))
        except ValueError as exc:
            return json_error("INVALID_PATH", str(exc), 400)

        repo_dir, _, ready_err = _require_ready_repo(book_id, storage_root)
        if ready_err:
            return ready_err
        assert repo_dir is not None

        try:
            run_git(repo_dir, ["add", "--all", "--", rel_path])
        except subprocess.CalledProcessError as exc:
            return json_error("GIT_OPERATION_FAILED", format_git_error(exc) or "failed to stage file", 500)

        entries = _status_entries(repo_dir)
        return (
            jsonify(
                {
                    "status": "success",
                    "book_id": book_id,
                    "path": rel_path,
                    "entries": entries,
                    **_status_summary(entries),
                }
            ),
            200,
        )

    @bp.post("/books/git_unstage")
    def books_git_unstage():
        payload, err = parse_json_payload(["path"])
        if err:
            return err

        book_id, book_err = require_book_id(payload)
        if book_err:
            return book_err

        try:
            rel_path = _normalize_rel_path(payload.get("path"))
        except ValueError as exc:
            return json_error("INVALID_PATH", str(exc), 400)

        repo_dir, _, ready_err = _require_ready_repo(book_id, storage_root)
        if ready_err:
            return ready_err
        assert repo_dir is not None

        try:
            run_git(repo_dir, ["reset", "HEAD", "--", rel_path])
        except subprocess.CalledProcessError as exc:
            return json_error("GIT_OPERATION_FAILED", format_git_error(exc) or "failed to unstage file", 500)

        entries = _status_entries(repo_dir)
        return (
            jsonify(
                {
                    "status": "success",
                    "book_id": book_id,
                    "path": rel_path,
                    "entries": entries,
                    **_status_summary(entries),
                }
            ),
            200,
        )

    @bp.post("/books/git_stage_all")
    def books_git_stage_all():
        payload = request.get_json(silent=True)
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            return json_error("INVALID_PAYLOAD", "request body must be application/json object", 400)

        book_id, book_err = require_book_id(payload)
        if book_err:
            return book_err

        repo_dir, _, ready_err = _require_ready_repo(book_id, storage_root)
        if ready_err:
            return ready_err
        assert repo_dir is not None

        try:
            run_git(repo_dir, ["add", "--all"])
        except subprocess.CalledProcessError as exc:
            return json_error("GIT_OPERATION_FAILED", format_git_error(exc) or "failed to stage all files", 500)

        entries = _status_entries(repo_dir)
        return (
            jsonify(
                {
                    "status": "success",
                    "book_id": book_id,
                    "entries": entries,
                    **_status_summary(entries),
                }
            ),
            200,
        )

    @bp.post("/books/git_commit")
    def books_git_commit():
        payload, err = parse_json_payload(["message"])
        if err:
            return err

        book_id, book_err = require_book_id(payload)
        if book_err:
            return book_err

        raw_message = payload.get("message")
        if not isinstance(raw_message, str) or not raw_message.strip():
            return json_error("INVALID_PAYLOAD", "message must be a non-empty string", 400)
        message = raw_message.strip()

        repo_dir, _, ready_err = _require_ready_repo(book_id, storage_root)
        if ready_err:
            return ready_err
        assert repo_dir is not None

        staged_text = run_git(repo_dir, ["diff", "--cached", "--name-only"]).stdout
        staged_files = [line.strip() for line in staged_text.splitlines() if line.strip()]
        if not staged_files:
            return json_error("NOTHING_STAGED", "no staged files to commit", 400)

        try:
            _ensure_repo_identity(repo_dir)
            run_git(repo_dir, ["commit", "-m", message])
        except subprocess.CalledProcessError as exc:
            return json_error("GIT_OPERATION_FAILED", format_git_error(exc) or "failed to create commit", 500)

        current_branch = _current_branch(repo_dir)
        return (
            jsonify(
                {
                    "status": "success",
                    "book_id": book_id,
                    "commit_id": _head_commit(repo_dir),
                    "current_branch": current_branch,
                    "mainline_branch": _resolve_mainline_branch(repo_dir, current_branch),
                    "files": staged_files,
                }
            ),
            200,
        )

    return bp
