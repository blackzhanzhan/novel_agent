import os
import subprocess
from contextlib import contextmanager
from typing import Sequence

from utils.file_lock import exclusive_file_lock


DEFAULT_BOOTSTRAP_COMMIT_MESSAGE = "chore: bootstrap repository baseline"
DEFAULT_BOOTSTRAP_LAYOUT_MESSAGE = "chore: bootstrap tracked layout files"
DEFAULT_GIT_USER_NAME = "LoreGit Bot"
DEFAULT_GIT_USER_EMAIL = "loregit@example.local"


def run_git(repo_dir: str, args: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=repo_dir,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


@contextmanager
def repo_lock(repo_dir: str, lock_name: str = "repo.lock"):
    locks_dir = os.path.join(repo_dir, ".locks")
    os.makedirs(locks_dir, exist_ok=True)
    lock_path = os.path.join(locks_dir, lock_name)
    with open(lock_path, "a+", encoding="utf-8") as lock_file:
        with exclusive_file_lock(lock_file):
            yield


def ensure_repo(repo_dir: str) -> None:
    if not os.path.isdir(os.path.join(repo_dir, ".git")):
        run_git(repo_dir, ["init"])
    run_git(repo_dir, ["status", "--porcelain"])


def ensure_repo_identity(repo_dir: str) -> None:
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


def has_valid_head(repo_dir: str) -> bool:
    try:
        return bool(run_git(repo_dir, ["rev-parse", "HEAD"]).stdout.strip())
    except subprocess.CalledProcessError:
        return False


def get_head_commit(repo_dir: str) -> str | None:
    try:
        return run_git(repo_dir, ["rev-parse", "HEAD"]).stdout.strip() or None
    except subprocess.CalledProcessError:
        return None


def ensure_initial_commit(repo_dir: str, message: str = DEFAULT_BOOTSTRAP_COMMIT_MESSAGE) -> str | None:
    if has_valid_head(repo_dir):
        return get_head_commit(repo_dir)

    ensure_repo_identity(repo_dir)
    run_git(repo_dir, ["add", "--all"])
    try:
        run_git(repo_dir, ["commit", "-m", message])
    except subprocess.CalledProcessError as exc:
        if not is_nothing_to_commit_error(exc):
            raise
        run_git(repo_dir, ["commit", "--allow-empty", "-m", message])
    return get_head_commit(repo_dir)


def ensure_tracked_files(repo_dir: str, file_names: Sequence[str], commit_message: str = DEFAULT_BOOTSTRAP_LAYOUT_MESSAGE) -> str | None:
    existing = [name for name in file_names if os.path.exists(os.path.join(repo_dir, name))]
    if not existing:
        return None

    tracked_text = run_git(repo_dir, ["ls-files", "--", *existing]).stdout
    tracked = {line.strip() for line in tracked_text.splitlines() if line.strip()}
    missing_tracked = [name for name in existing if name not in tracked]
    if not missing_tracked:
        return None

    run_git(repo_dir, ["add", "--", *missing_tracked])
    status = run_git(repo_dir, ["status", "--porcelain", "--", *missing_tracked]).stdout
    if not status.strip():
        return None

    ensure_repo_identity(repo_dir)
    try:
        run_git(repo_dir, ["commit", "-m", commit_message, "--", *missing_tracked])
    except subprocess.CalledProcessError as exc:
        if not is_nothing_to_commit_error(exc):
            raise
    return get_head_commit(repo_dir)


def resolve_head(repo_dir: str, message: str) -> str:
    try:
        return run_git(repo_dir, ["rev-parse", "HEAD"]).stdout.strip()
    except subprocess.CalledProcessError:
        run_git(repo_dir, ["commit", "--allow-empty", "-m", message])
        return run_git(repo_dir, ["rev-parse", "HEAD"]).stdout.strip()


def is_nothing_to_commit_error(exc: subprocess.CalledProcessError) -> bool:
    combined = f"{exc.stdout}\n{exc.stderr}".lower()
    return "nothing to commit" in combined or "nothing added to commit" in combined


def format_git_error(exc: Exception) -> str:
    if isinstance(exc, subprocess.CalledProcessError):
        return (exc.stderr or exc.stdout or "").strip()
    return str(exc)
