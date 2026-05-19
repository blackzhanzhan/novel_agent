"""Promptless style artifact initialization pipeline.

This backend pipeline owns repeatable initialization/rebuild for the derived
style artifact trio. The conversational style Agent may still discuss and
revise style files with the author, but fixed initialization belongs here.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from queue import Queue
from typing import Any

from utils.git_utils import ensure_repo_identity, is_nothing_to_commit_error, run_git
from utils.style_diagnostics import generate_style_diagnostics


STYLE_ARTIFACT_FILES = (
    "style_fingerprint.md",
    "style_review.md",
    "style_constraints_for_continuation.md",
)

STYLE_INIT_COMMIT_MESSAGE = "style init: regenerate diagnostics artifacts"


def _normalize_markdown(content: str) -> str:
    return content.rstrip() + "\n"


def _is_placeholder_artifact(content: str, file_name: str) -> bool:
    stripped = content.strip()
    if not stripped:
        return True
    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    if len(lines) <= 1 and lines[0].startswith("#"):
        return True
    marker_by_file = {
        "style_fingerprint.md": "# 叙事结构指纹",
        "style_review.md": "# 作者可读审查",
        "style_constraints_for_continuation.md": "# 续写硬约束",
    }
    return stripped == marker_by_file.get(file_name, "").strip()


def _needs_generation(book_dir: Path) -> bool:
    for file_name in STYLE_ARTIFACT_FILES:
        path = book_dir / file_name
        if not path.exists() or not path.is_file():
            return True
        if _is_placeholder_artifact(path.read_text(encoding="utf-8", errors="replace"), file_name):
            return True
    return False


def _commit_files(book_dir: Path, file_names: tuple[str, ...], message: str) -> str | None:
    status = run_git(str(book_dir), ["status", "--porcelain", "--", *file_names]).stdout
    if not status.strip():
        return None
    ensure_repo_identity(str(book_dir))
    run_git(str(book_dir), ["add", "--", *file_names])
    try:
        run_git(str(book_dir), ["commit", "-m", message, "--", *file_names])
    except subprocess.CalledProcessError as exc:
        if not is_nothing_to_commit_error(exc):
            raise
    return run_git(str(book_dir), ["rev-parse", "HEAD"]).stdout.strip()


def _emit(sse_queue: Queue | None, event: str, data: dict[str, Any]) -> None:
    if sse_queue is not None:
        sse_queue.put({"event": event, "data": data})


def run_pipeline(
    *,
    book_id: str,
    book_dir: str | Path,
    sse_queue: Queue | None = None,
    source_count: int = 12,
    draft_file: str = "chapter_draft.md",
    draft_chapters: Any = None,
    force_rebuild: bool = False,
) -> dict[str, Any]:
    """Generate and commit the style diagnostic artifact trio."""
    resolved_book_dir = Path(book_dir)
    _emit(
        sse_queue,
        "ack",
        {
            "book_id": book_id,
            "total_steps": 2 + len(STYLE_ARTIFACT_FILES),
            "force_rebuild": force_rebuild,
            "artifacts": list(STYLE_ARTIFACT_FILES),
        },
    )

    if not force_rebuild and not _needs_generation(resolved_book_dir):
        _emit(
            sse_queue,
            "done",
            {
                "completed": 0,
                "failed": 0,
                "skipped": True,
                "force_rebuild": force_rebuild,
                "artifacts": list(STYLE_ARTIFACT_FILES),
            },
        )
        return {
            "status": "success",
            "skipped": True,
            "failed_artifacts": [],
            "updated_artifacts": [],
            "force_rebuild": force_rebuild,
        }

    _emit(sse_queue, "progress", {"step_index": 0, "total": 5, "title": "diagnostics", "status": "processing"})
    diagnostics = generate_style_diagnostics(
        book_dir=resolved_book_dir,
        source_count=source_count,
        draft_file=draft_file,
        draft_chapters=draft_chapters,
    )
    outputs = diagnostics.get("outputs") if isinstance(diagnostics, dict) else None
    if not isinstance(outputs, dict):
        error = "style diagnostics did not return outputs"
        _emit(sse_queue, "error", {"message": error})
        return {"status": "error", "failed_artifacts": list(STYLE_ARTIFACT_FILES), "error": error}

    updated_artifacts: list[str] = []
    for offset, file_name in enumerate(STYLE_ARTIFACT_FILES, start=1):
        content = outputs.get(file_name)
        if not isinstance(content, str) or not content.strip():
            error = f"diagnostics output missing required artifact: {file_name}"
            _emit(sse_queue, "error", {"message": error, "artifact": file_name})
            return {"status": "error", "failed_artifacts": [file_name], "error": error}
        _emit(
            sse_queue,
            "progress",
            {"step_index": offset, "total": 5, "title": file_name, "status": "writing"},
        )
        path = resolved_book_dir / file_name
        next_content = _normalize_markdown(content)
        existing = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
        if existing != next_content:
            path.write_text(next_content, encoding="utf-8")
            updated_artifacts.append(file_name)

    _emit(sse_queue, "progress", {"step_index": 4, "total": 5, "title": "git commit", "status": "processing"})
    commit_id = _commit_files(resolved_book_dir, STYLE_ARTIFACT_FILES, STYLE_INIT_COMMIT_MESSAGE)
    _emit(
        sse_queue,
        "done",
        {
            "completed": len(STYLE_ARTIFACT_FILES),
            "failed": 0,
            "skipped": False,
            "force_rebuild": force_rebuild,
            "artifacts": list(STYLE_ARTIFACT_FILES),
            "updated_artifacts": updated_artifacts,
            "commit_id": commit_id,
            "warnings": diagnostics.get("warnings", []),
            "source_files": diagnostics.get("source_files", []),
        },
    )
    return {
        "status": "success",
        "skipped": False,
        "failed_artifacts": [],
        "updated_artifacts": updated_artifacts,
        "commit_id": commit_id,
        "force_rebuild": force_rebuild,
        "diagnostics": diagnostics,
    }
