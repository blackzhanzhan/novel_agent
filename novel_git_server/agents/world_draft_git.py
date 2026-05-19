"""Draft git operations extracted from world_draft.py for maintainability."""

import os
import subprocess
from contextlib import contextmanager
from difflib import unified_diff
from typing import Any

from agents.archive import _compute_text_etag
from utils.book_storage import TRACKED_LAYOUT_FILES
from utils.file_lock import exclusive_file_lock
from utils.git_utils import run_git

try:
    from git import Repo

    GITPYTHON_AVAILABLE = True
except Exception:  # pragma: no cover - dependency guard
    Repo = None  # type: ignore[assignment]
    GITPYTHON_AVAILABLE = False


DRAFT_BRANCH_NAME = "draft/sandbox"
LEGACY_DRAFT_BRANCH_NAME = "draft/world_model"
LOCKS_DIR_NAME = ".locks"


@contextmanager
def _repo_lock(repo_dir: str):
    locks_dir = os.path.join(repo_dir, LOCKS_DIR_NAME)
    os.makedirs(locks_dir, exist_ok=True)
    lock_path = os.path.join(locks_dir, "draft_sandbox.lock")
    with open(lock_path, "w", encoding="utf-8") as lock_file:
        with exclusive_file_lock(lock_file):
            yield


def _ensure_gitpython_or_raise() -> None:
    if GITPYTHON_AVAILABLE:
        return
    raise RuntimeError("GitPython is required for draft branch workflow. Install with: pip install GitPython")


def _ensure_repo_identity(repo: Repo) -> None:
    reader = repo.config_reader()
    missing_name = not reader.has_option("user", "name")
    missing_email = not reader.has_option("user", "email")
    if not missing_name and not missing_email:
        return

    writer = repo.config_writer()
    try:
        if missing_name:
            writer.set_value("user", "name", "LoreGit Bot")
        if missing_email:
            writer.set_value("user", "email", "loregit@example.local")
    finally:
        writer.release()


def _ensure_baseline_commit(repo: Repo) -> None:
    if repo.head.is_valid():
        return
    _ensure_repo_identity(repo)
    repo.git.add("--all")
    repo.index.commit("chore: bootstrap repository baseline")


def _ensure_layout_files_tracked(repo: Repo, repo_dir: str) -> None:
    tracked_candidates = list(TRACKED_LAYOUT_FILES)
    existing = [name for name in tracked_candidates if os.path.exists(os.path.join(repo_dir, name))]
    if not existing:
        return

    repo.index.add(existing)
    status = repo.git.status("--porcelain", "--", *existing)
    if not status.strip():
        return
    _ensure_repo_identity(repo)
    repo.index.commit("chore: bootstrap tracked layout files")


def _ensure_draft_branch(repo: Repo, mainline_branch: str, *, create_if_missing: bool) -> tuple[bool, bool]:
    head_names = {head.name for head in repo.heads}
    if mainline_branch in head_names:
        repo.git.checkout(mainline_branch)

    if DRAFT_BRANCH_NAME in head_names:
        repo.git.checkout(DRAFT_BRANCH_NAME)
        return True, False

    if LEGACY_DRAFT_BRANCH_NAME in head_names:
        repo.git.checkout(LEGACY_DRAFT_BRANCH_NAME)
        repo.git.branch("-m", DRAFT_BRANCH_NAME)
        return True, True

    if not create_if_missing:
        return False, False

    repo.git.checkout("-b", DRAFT_BRANCH_NAME)
    return True, False


def _compose_content(op: str, original_content: str, incoming_content: str) -> str:
    if op == "update":
        return incoming_content
    if op == "append":
        return original_content + incoming_content
    if op == "prepend":
        if original_content:
            return incoming_content + "\n\n" + original_content
        return incoming_content
    raise ValueError(f"unsupported op: {op}")


def _has_pending_changes_for_paths(repo_dir: str, rel_paths: list[str]) -> bool:
    if not rel_paths:
        return False
    status = run_git(repo_dir, ["status", "--porcelain", "--", *rel_paths]).stdout
    return bool(status.strip())


def _safe_int(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return default
    return default


def _extract_dify_answer(response: dict[str, Any], fallback: str) -> str:
    answer = response.get("answer")
    if isinstance(answer, str) and answer.strip():
        return answer
    data = response.get("data")
    if isinstance(data, dict):
        nested_answer = data.get("answer")
        if isinstance(nested_answer, str) and nested_answer.strip():
            return nested_answer
    return fallback


def _read_file_text(path: str) -> str:
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _resolve_mainline_branch(repo: "Repo") -> str:
    symbolic_head = ""
    try:
        symbolic_head = repo.git.symbolic_ref("--short", "HEAD").strip()
    except Exception:
        symbolic_head = ""

    head_names = {head.name for head in repo.heads}
    if symbolic_head and symbolic_head in head_names and symbolic_head != DRAFT_BRANCH_NAME:
        return symbolic_head
    if "main" in head_names:
        return "main"
    if "master" in head_names:
        return "master"
    if symbolic_head and symbolic_head != DRAFT_BRANCH_NAME:
        return symbolic_head
    for candidate in sorted(head_names):
        if candidate != DRAFT_BRANCH_NAME:
            return candidate
    return "main"


def _branch_head_commit(repo_dir: str, branch_name: str) -> str | None:
    try:
        return run_git(repo_dir, ["rev-parse", branch_name]).stdout.strip()
    except subprocess.CalledProcessError:
        return None


def _read_branch_file(repo_dir: str, branch_name: str, file_name: str) -> str:
    if not _branch_head_commit(repo_dir, branch_name):
        return ""
    try:
        return run_git(repo_dir, ["show", f"{branch_name}:{file_name}"]).stdout or ""
    except (subprocess.CalledProcessError, UnicodeDecodeError):
        return ""


def _draft_file_snapshot(repo_dir: str, file_name: str) -> dict[str, Any]:
    commit_id = _branch_head_commit(repo_dir, DRAFT_BRANCH_NAME)
    if not commit_id:
        return {
            "exists": False,
            "commit_id": None,
            "content": "",
            "etag": _compute_text_etag(""),
        }

    content = _read_branch_file(repo_dir, DRAFT_BRANCH_NAME, file_name)
    return {
        "exists": True,
        "commit_id": commit_id,
        "content": content,
        "etag": _compute_text_etag(content),
    }


def _mainline_file_snapshot(repo_dir: str, file_name: str) -> dict[str, Any]:
    if not GITPYTHON_AVAILABLE:
        return _empty_draft_snapshot()
    try:
        repo = Repo(repo_dir)
        mainline_branch = _resolve_mainline_branch(repo)
    except Exception:
        return _empty_draft_snapshot()

    commit_id = _branch_head_commit(repo_dir, mainline_branch)
    if not commit_id:
        return _empty_draft_snapshot()

    content = _read_branch_file(repo_dir, mainline_branch, file_name)
    return {
        "exists": True,
        "commit_id": commit_id,
        "content": content,
        "etag": _compute_text_etag(content),
    }


def _empty_draft_snapshot() -> dict[str, Any]:
    return {
        "exists": False,
        "commit_id": None,
        "content": "",
        "etag": _compute_text_etag(""),
    }


def _draft_file_snapshots(repo_dir: str, file_names: list[str] | tuple[str, ...] | set[str]) -> dict[str, dict[str, Any]]:
    snapshots: dict[str, dict[str, Any]] = {}
    for file_name in sorted({name for name in file_names if isinstance(name, str) and name.strip()}):
        snapshots[file_name] = _draft_file_snapshot(repo_dir, file_name)
    return snapshots


def _changed_draft_files(before_snapshots: dict[str, dict[str, Any]], after_snapshots: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    changed: list[dict[str, Any]] = []
    for file_name in sorted(set(before_snapshots) | set(after_snapshots)):
        before = before_snapshots.get(file_name) or _empty_draft_snapshot()
        after = after_snapshots.get(file_name) or _empty_draft_snapshot()
        if before.get("etag") != after.get("etag"):
            changed.append(
                {
                    "file_name": file_name,
                    "before": before,
                    "after": after,
                }
            )
    return changed


def _build_diff_preview(file_name: str, before: str, after: str, max_lines: int = 160) -> str:
    if before == after:
        return ""

    diff_lines = list(
        unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=f"a/{file_name}",
            tofile=f"b/{file_name}",
            lineterm="",
        )
    )
    if len(diff_lines) <= max_lines:
        return "\n".join(diff_lines)

    clipped = diff_lines[:max_lines]
    clipped.append(f"... (diff truncated, total={len(diff_lines)} lines)")
    return "\n".join(clipped)


def _build_review_diff_preview(repo_dir: str, file_name: str, draft_content: str) -> str:
    baseline = _mainline_file_snapshot(repo_dir, file_name)
    return _build_diff_preview(
        file_name,
        baseline.get("content", ""),
        draft_content,
    )
