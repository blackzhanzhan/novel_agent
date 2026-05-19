from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def resolve_project_dir() -> Path:
    script_dir = Path(__file__).resolve().parent
    candidates = [script_dir, script_dir.parent]
    for candidate in candidates:
        if (candidate / "app.py").exists():
            return candidate
    raise RuntimeError(
        "Cannot locate project root. Expected to find app.py near this script. "
        "Move the script back under novel_git_server/tools or novel_git_server."
    )


PROJECT_DIR = resolve_project_dir()
DATA_DIR = PROJECT_DIR / "data"
STORAGE_DIR = PROJECT_DIR / "storage"
BOOK_GITIGNORE_LINES = ["*.tmp", "*.log", "__pycache__/"]


def info(message: str) -> None:
    print(f"[refactor] {message}")


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def validate_runtime_safety() -> None:
    required_files = [
        "app.py",
        "agents/world_state.py",
        "utils/book_storage.py",
    ]
    missing = [name for name in required_files if not (PROJECT_DIR / name).exists()]
    if missing:
        raise RuntimeError(
            f"Project root validation failed. Missing files in {PROJECT_DIR}: {missing}"
        )

    if DATA_DIR.parent.resolve() != PROJECT_DIR.resolve() or DATA_DIR.name != "data":
        raise RuntimeError(f"Unsafe DATA_DIR detected: {DATA_DIR}")
    if STORAGE_DIR.parent.resolve() != PROJECT_DIR.resolve() or STORAGE_DIR.name != "storage":
        raise RuntimeError(f"Unsafe STORAGE_DIR detected: {STORAGE_DIR}")


def choose_latest(paths: list[Path]) -> Path | None:
    existing = [p for p in paths if p.exists()]
    if not existing:
        return None
    return max(existing, key=lambda p: p.stat().st_mtime)


def ensure_storage_layout() -> None:
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)


def consolidate_single_file(target: Path, candidates: list[Path]) -> None:
    latest = choose_latest(candidates + [target])
    if latest is None:
        return

    target.parent.mkdir(parents=True, exist_ok=True)
    if latest.resolve() != target.resolve():
        shutil.copy2(latest, target)
        info(f"copied latest {latest} -> {target}")
    else:
        info(f"kept latest {target}")

    for candidate in candidates:
        if candidate.exists() and candidate.resolve() != target.resolve():
            candidate.unlink(missing_ok=True)
            info(f"removed legacy file {candidate}")


def remove_empty_data_dir() -> None:
    if not DATA_DIR.exists():
        return
    if not _is_within(DATA_DIR, PROJECT_DIR):
        raise RuntimeError(f"Unsafe directory removal blocked: {DATA_DIR}")
    for child in sorted(DATA_DIR.rglob("*"), reverse=True):
        if child.is_dir():
            try:
                child.rmdir()
            except OSError:
                pass
    try:
        DATA_DIR.rmdir()
        info(f"removed empty dir {DATA_DIR}")
    except OSError:
        info(f"kept non-empty dir {DATA_DIR}")


def _write_book_gitignore(book_dir: Path) -> None:
    gitignore_path = book_dir / ".gitignore"
    existing = []
    if gitignore_path.exists():
        existing = gitignore_path.read_text(encoding="utf-8").splitlines()
    merged = existing[:]
    for line in BOOK_GITIGNORE_LINES:
        if line not in merged:
            merged.append(line)
    gitignore_path.write_text("\n".join(merged).strip() + "\n", encoding="utf-8")


def ensure_book_git_repos() -> None:
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    reserved_dirs = {"backup", "_legacy_archive"}

    for entry in sorted(STORAGE_DIR.iterdir()):
        if not entry.is_dir() or entry.name.startswith(".") or entry.name in reserved_dirs:
            continue
        git_dir = entry / ".git"
        if not git_dir.exists():
            subprocess.run(["git", "init"], cwd=entry, check=True)
            info(f"initialized book git repo in {entry}")
        else:
            info(f"book git repo already exists: {git_dir}")
        _write_book_gitignore(entry)


def main() -> None:
    validate_runtime_safety()
    ensure_storage_layout()

    consolidate_single_file(
        STORAGE_DIR / "database.json",
        [PROJECT_DIR / "database.json", DATA_DIR / "database.json"],
    )
    consolidate_single_file(
        STORAGE_DIR / "snapshot_template.md",
        [DATA_DIR / "snapshot_template.md"],
    )
    consolidate_single_file(
        STORAGE_DIR / "world_model.md",
        [PROJECT_DIR / "world_model.md", DATA_DIR / "world_model.md"],
    )

    remove_empty_data_dir()
    ensure_book_git_repos()
    info("done")


if __name__ == "__main__":
    main()
