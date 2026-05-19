"""Backend-owned summary archive pipeline.

This pipeline replaces the retired Dify reading_archive_agent path for fixed
Tomato import summary generation. It summarizes imported source chapters into
`summary.md`; it does not generate continuation prose or outline cards.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Any, Callable

from utils.git_utils import (
    ensure_repo,
    ensure_repo_identity,
    is_nothing_to_commit_error,
    resolve_head,
    run_git,
)


ARCHIVE_MARKER = "LONGFORM_LAYERED_ARCHIVE_V1"
DEFAULT_MAX_BATCH_BYTES = 1_500_000
SUMMARY_COMMIT_MESSAGE_PREFIX = "[AI_Summary]"

ProgressCallback = Callable[[dict[str, Any]], None]
ModelInvoker = Callable[[str], str]


@dataclass(frozen=True)
class ChapterInput:
    index: int
    title: str
    file_name: str
    markdown: str


def _chapter_sort_key(path: Path) -> tuple[int, str]:
    match = re.match(r"^(\d+)", path.name)
    if match:
        return int(match.group(1)), path.name
    return 10**9, path.name


def load_chapters(book_dir: str | Path) -> list[ChapterInput]:
    chapters_dir = Path(book_dir) / "chapters"
    if not chapters_dir.is_dir():
        return []

    chapters: list[ChapterInput] = []
    for fallback_index, path in enumerate(sorted(chapters_dir.glob("*.md"), key=_chapter_sort_key), start=1):
        markdown = path.read_text(encoding="utf-8", errors="replace").strip()
        if not markdown:
            continue
        prefix_match = re.match(r"^(\d+)", path.name)
        index = int(prefix_match.group(1)) if prefix_match else fallback_index
        first_line = markdown.splitlines()[0].strip() if markdown.splitlines() else ""
        title = first_line[2:].strip() if first_line.startswith("# ") else f"CH{index}"
        chapters.append(ChapterInput(index=index, title=title, file_name=path.name, markdown=markdown))
    return chapters


def split_chapter_batches(
    chapters: list[ChapterInput],
    *,
    max_batch_bytes: int = DEFAULT_MAX_BATCH_BYTES,
) -> list[list[ChapterInput]]:
    batches: list[list[ChapterInput]] = []
    current: list[ChapterInput] = []
    current_bytes = 0

    for chapter in chapters:
        chapter_bytes = len(chapter.markdown.encode("utf-8"))
        if current and current_bytes + chapter_bytes > max_batch_bytes:
            batches.append(current)
            current = []
            current_bytes = 0
        current.append(chapter)
        current_bytes += chapter_bytes

    if current:
        batches.append(current)
    return batches


def _build_llm(max_tokens: int = 8192):
    from utils.model_provider import create_chat_model

    return create_chat_model(max_tokens=max_tokens, purpose="summary_archive")


def _invoke_langchain(prompt: str) -> str:
    from langchain_core.messages import HumanMessage

    response = _build_llm().invoke([HumanMessage(content=prompt)])
    content = getattr(response, "content", "")
    if isinstance(content, list):
        return "\n".join(str(item) for item in content)
    return str(content)


def _build_batch_prompt(
    *,
    book_name: str,
    batch: list[ChapterInput],
    batch_index: int,
    total_batches: int,
) -> str:
    start = batch[0].index
    end = batch[-1].index
    chapter_block = "\n\n---CHAPTER---\n\n".join(chapter.markdown for chapter in batch)
    return f"""You are the backend reading archive pipeline for a webnovel authoring workspace.

Task:
- Distill the provided source chapters into a reusable archive for downstream agents.
- Preserve plot facts, irreversible facts, open loops, relationship changes, promises, constraints, and payoffs.
- Do not invent new plot, outline cards, or continuation prose.
- Write in the same language as the source chapters.

Return markdown only, with exactly this top structure:
## Batch Archive: CH{start}-{end}

## Batch Overview
- ...

## Batch Index
- CH{start}: ...

## Irreversible Facts
- ...

## Open Loops And Promises
- ...

## Relationship And State Changes
- ...

## Downstream Constraints
- ...

Book: {book_name}
Batch: {batch_index}/{total_batches}
Chapter range: CH{start}-{end}

Source chapters:
{chapter_block}
"""


def _strip_code_fence(text: str) -> str:
    match = re.search(r"```(?:markdown|md)?\s*\n(.*?)```", text, flags=re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()


def _normalize_batch_answer(answer: str, batch: list[ChapterInput]) -> str:
    start = batch[0].index
    end = batch[-1].index
    text = _strip_code_fence(answer)
    text = text.replace(ARCHIVE_MARKER, "").strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    heading_re = re.compile(r"^##\s+Batch Archive:\s*CH\d+\s*[-\u2013\u2014]\s*\d+\s*$", re.MULTILINE)
    if heading_re.search(text):
        return text.strip() + "\n"
    return f"## Batch Archive: CH{start}-{end}\n\n{text.strip()}\n"


def _extract_section(text: str, heading: str, *, limit: int = 8) -> list[str]:
    pattern = re.compile(
        rf"^##\s+{re.escape(heading)}\s*$\n(?P<body>.*?)(?=^##\s+|\Z)",
        flags=re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if not match:
        return []
    lines: list[str] = []
    for raw_line in match.group("body").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if len(line) > 220:
            line = f"{line[:220]}..."
        lines.append(line)
        if len(lines) >= limit:
            break
    return lines


def compose_summary(batch_answers: list[str]) -> str:
    body = "\n\n".join(answer.strip() for answer in batch_answers if answer.strip())
    lines = [
        ARCHIVE_MARKER,
        "",
        "# Full Book Archive Index",
        "",
        f"- Batch count: {len(batch_answers)}",
        "- Generation owner: backend summary archive pipeline",
        "- Purpose: source-backed archive for world, style, outline, continuation, and review agents.",
        "",
    ]
    for idx, answer in enumerate(batch_answers, start=1):
        title_match = re.search(r"^##\s+Batch Archive:\s*(.+?)\s*$", answer, flags=re.MULTILINE)
        title = title_match.group(1).strip() if title_match else f"Batch {idx}"
        lines.extend([f"## Batch {idx}: {title}", ""])
        overview = _extract_section(answer, "Batch Overview", limit=4)
        index_lines = _extract_section(answer, "Batch Index", limit=6)
        if overview:
            lines.extend(overview)
            lines.append("")
        if index_lines:
            lines.append("### Index Snippet")
            lines.extend(index_lines)
            lines.append("")

    return "\n".join(lines).strip() + "\n\n---\n\n# Batch Archives\n\n" + body.strip() + "\n"


def _update_summary_metadata(book_dir: Path, chapter_count: int, total_batches: int) -> bool:
    meta_path = book_dir / "metadata.json"
    if not meta_path.exists():
        return False
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    next_metadata = dict(metadata)
    next_metadata["summary_complete"] = True
    next_metadata["total_chapters"] = chapter_count
    next_metadata["processed_batches"] = total_batches
    if next_metadata == metadata:
        return False
    meta_path.write_text(json.dumps(next_metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True


def _commit_summary(book_dir: Path, book_name: str, commit_paths: list[str]) -> str | None:
    ensure_repo(str(book_dir))
    ensure_repo_identity(str(book_dir))
    status = run_git(str(book_dir), ["status", "--porcelain", "--", *commit_paths]).stdout
    if not status.strip():
        return None
    run_git(str(book_dir), ["add", "--", *commit_paths])
    try:
        run_git(str(book_dir), ["commit", "-m", f"{SUMMARY_COMMIT_MESSAGE_PREFIX} {book_name}", "--", *commit_paths])
    except subprocess.CalledProcessError as exc:
        if not is_nothing_to_commit_error(exc):
            raise
    return resolve_head(str(book_dir), "summary archive")


def run_pipeline(
    *,
    book_id: str,
    book_dir: str | Path,
    book_name: str | None = None,
    cancel_event: Event | None = None,
    progress_callback: ProgressCallback | None = None,
    max_batch_bytes: int = DEFAULT_MAX_BATCH_BYTES,
    invoke_model: ModelInvoker | None = None,
) -> dict[str, Any]:
    """Generate, write, and commit summary.md from imported chapter files."""
    resolved_book_dir = Path(book_dir)
    resolved_book_name = book_name or book_id

    def emit(payload: dict[str, Any]) -> None:
        if progress_callback is not None:
            progress_callback(payload)

    emit({"status": "reading", "book_id": book_id, "book_name": resolved_book_name})
    chapters = load_chapters(resolved_book_dir)
    if not chapters:
        return {"status": "no_chapters", "book_id": book_id, "book_name": resolved_book_name}

    batches = split_chapter_batches(chapters, max_batch_bytes=max_batch_bytes)
    total_batches = len(batches)
    invoker = invoke_model or _invoke_langchain
    batch_answers: list[str] = []

    for batch_index, batch in enumerate(batches, start=1):
        if cancel_event is not None and cancel_event.is_set():
            return {"status": "cancelled", "book_id": book_id, "book_name": resolved_book_name}
        emit(
            {
                "status": "generating",
                "batch": batch_index,
                "total_batches": total_batches,
                "chapter_count": len(chapters),
                "book_name": resolved_book_name,
            }
        )
        prompt = _build_batch_prompt(
            book_name=resolved_book_name,
            batch=batch,
            batch_index=batch_index,
            total_batches=total_batches,
        )
        answer = invoker(prompt)
        if not isinstance(answer, str) or not answer.strip():
            raise RuntimeError(f"summary archive batch {batch_index}/{total_batches} returned empty output")
        batch_answers.append(_normalize_batch_answer(answer, batch))

    summary_content = compose_summary(batch_answers)
    emit({"status": "writing", "book_name": resolved_book_name, "chars": len(summary_content)})
    if cancel_event is not None and cancel_event.is_set():
        return {"status": "cancelled", "book_id": book_id, "book_name": resolved_book_name, "chars": len(summary_content)}

    summary_path = resolved_book_dir / "summary.md"
    summary_path.write_text(summary_content, encoding="utf-8")
    commit_paths = ["summary.md"]
    if _update_summary_metadata(resolved_book_dir, len(chapters), total_batches):
        commit_paths.append("metadata.json")
    commit_id = _commit_summary(resolved_book_dir, resolved_book_name, commit_paths)
    result = {
        "status": "success",
        "book_id": book_id,
        "book_name": resolved_book_name,
        "chapter_count": len(chapters),
        "total_batches": total_batches,
        "chars": len(summary_content),
        "commit_id": commit_id,
        "updated_files": commit_paths,
    }
    emit({**result, "status": "done"})
    return result
