import json
import logging
import os
import re
import subprocess
import threading
from datetime import datetime, timezone
from typing import Any, Callable

from flask import Blueprint, jsonify, request

from utils.book_storage import TRACKED_LAYOUT_FILES, ensure_book_layout, validate_book_id
from utils.git_utils import (
    ensure_repo,
    ensure_repo_identity,
    format_git_error,
    is_nothing_to_commit_error,
    resolve_head,
    run_git,
)
from utils.tomato_importer import parse_tomato_bulk_export
from utils.tomato_search import get_book_info, search_novels
from utils.tomato_download_adapter import adapt_download
from utils.session_runtime import delete_book_conversations

logger = logging.getLogger(__name__)

_DELIMITER = "|||CHAPTER_START|||"

_summary_progress: dict[str, dict[str, Any]] = {}
_download_progress: dict[str, dict[str, Any]] = {}
_task_cancel_lock = threading.Lock()
_download_cancel_events: dict[str, threading.Event] = {}
_summary_cancel_events: dict[str, threading.Event] = {}


def _register_task_cancel_event(
    registry: dict[str, threading.Event],
    book_id: str,
) -> threading.Event:
    cancel_event = threading.Event()
    with _task_cancel_lock:
        previous = registry.get(book_id)
        registry[book_id] = cancel_event
    if previous is not None and previous is not cancel_event:
        previous.set()
    return cancel_event


def _clear_task_cancel_event(
    registry: dict[str, threading.Event],
    book_id: str,
    cancel_event: threading.Event,
) -> None:
    with _task_cancel_lock:
        if registry.get(book_id) is cancel_event:
            registry.pop(book_id, None)


def cancel_book_background_work(book_id: str) -> None:
    """Stop any active Tomato import/summary work for a book."""
    with _task_cancel_lock:
        download_event = _download_cancel_events.pop(book_id, None)
        summary_event = _summary_cancel_events.pop(book_id, None)
        _download_progress.pop(book_id, None)
        _summary_progress.pop(book_id, None)

    if download_event is not None:
        download_event.set()
    if summary_event is not None:
        summary_event.set()

    try:
        from utils.tomato_exe_client import stop_shared_client

        stop_shared_client()
    except Exception:
        logger.exception("Failed to stop shared Tomato client for %s", book_id)


def _format_chapters_for_dify(book_dir: str) -> str:
    """Read all chapter .md files from disk, format with delimiter for Dify."""
    chapters_dir = os.path.join(book_dir, "chapters")
    if not os.path.isdir(chapters_dir):
        return ""
    chapter_files = sorted(
        f for f in os.listdir(chapters_dir) if f.endswith(".md")
    )
    if not chapter_files:
        return ""
    parts: list[str] = []
    for fname in chapter_files:
        path = os.path.join(chapters_dir, fname)
        with open(path, "r", encoding="utf-8") as f:
            text = f.read().strip()
        if text:
            parts.append(text)
    return _DELIMITER.join(parts)


def _get_chapter_titles(book_dir: str) -> dict[int, str]:
    """Return {chapter_index: title} from chapter files on disk."""
    chapters_dir = os.path.join(book_dir, "chapters")
    if not os.path.isdir(chapters_dir):
        return {}
    titles: dict[int, str] = {}
    for fname in os.listdir(chapters_dir):
        if not fname.endswith(".md"):
            continue
        parts = fname.split("_", 1)
        if len(parts) < 2:
            continue
        try:
            idx = int(parts[0])
        except ValueError:
            continue
        path = os.path.join(chapters_dir, fname)
        with open(path, "r", encoding="utf-8") as f:
            first_line = f.readline().strip()
        if first_line.startswith("# "):
            titles[idx] = first_line[2:]
    return titles


def _parse_chapter_index(heading: str) -> int | None:
    """Parse chapter index from headings like 第1章 or 第一百二十三章."""
    m = re.match(r"第(\d+)章", heading)
    if m:
        return int(m.group(1))

    m = re.match(r"第([零〇一二两三四五六七八九十百千万]+)章", heading)
    if not m:
        return None

    digit_map = {
        "零": 0,
        "〇": 0,
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    unit_map = {"十": 10, "百": 100, "千": 1000, "万": 10000}

    total = 0
    section = 0
    number = 0
    for char in m.group(1):
        if char in digit_map:
            number = digit_map[char]
            continue
        unit = unit_map.get(char)
        if unit is None:
            return None
        if unit == 10000:
            section = (section + number) * unit
            total += section
            section = 0
        else:
            section += (number or 1) * unit
        number = 0

    return total + section + number


def _normalize_summary(raw: str, chapter_titles: dict[int, str]) -> str:
    """Post-process LLM summary to fix formatting inconsistencies across batches.

    For segment-level constraint extraction format (## Batch Archive: with ###
    sub-headings), only strip decorative separators and normalize spacing.
    For legacy per-chapter format, apply chapter heading/body normalization.
    """
    # Strip decorative ==== separators (don't promote them to headings)
    raw = re.sub(r"^=+\s*.*?\s*=+\s*$", "", raw, count=0, flags=re.MULTILINE)

    # Segment-level format: light-touch normalization only
    if "### 故事阶段" in raw or "### 核心驱动进度" in raw:
        # Normalize heading spacing: ensure ## and ### headings have blank lines before them
        raw = re.sub(r"([^\n])\n(##)", r"\1\n\n\2", raw)
        raw = re.sub(r"([^\n])\n(###)", r"\1\n\n\2", raw)
        # Collapse 3+ consecutive blank lines
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw

    lines = raw.split("\n")
    result: list[str] = []
    prev_was_chapter_heading = False

    for line in lines:
        stripped = line.strip()

        # Only process lines that look like chapter headings
        _BODY_PREFIXES = ("简述：", "设定：", "人物：")
        if not stripped.startswith("# 第"):
            # If previous line was a chapter heading and this line is non-empty body
            # text without a known prefix, add 简述：
            if prev_was_chapter_heading and stripped and not stripped.startswith("#"):
                if not stripped.startswith(_BODY_PREFIXES):
                    stripped = f"简述：{stripped}"
                result.append("")
                result.append(stripped)
                prev_was_chapter_heading = False
                continue
            prev_was_chapter_heading = False
            result.append(line)
            continue

        heading = stripped[2:]  # drop '# '
        idx = _parse_chapter_index(heading)
        if idx is None:
            result.append(line)
            continue
        known_title = chapter_titles.get(idx)

        if known_title is None:
            result.append(line)
            prev_was_chapter_heading = True
            continue

        if heading == known_title:
            result.append(f"# {known_title}")
            prev_was_chapter_heading = True
            continue

        # heading differs from known_title — body text is on the same line
        if heading.startswith(known_title):
            rest = heading[len(known_title) :].strip()
        else:
            if "简述：" in heading:
                title_part, _, body_part = heading.partition("简述：")
                result.append(f"# {title_part.strip()}")
                result.append("")
                result.append(f"简述：{body_part.strip()}")
                prev_was_chapter_heading = False
                continue
            result.append(f"# {known_title}")
            prev_was_chapter_heading = True
            continue

        if rest:
            if not rest.startswith(("简述：", "设定：", "人物：")):
                rest = f"简述：{rest}"
            result.append(f"# {known_title}")
            result.append("")
            result.append(rest)
            prev_was_chapter_heading = False
        else:
            result.append(f"# {known_title}")
            prev_was_chapter_heading = True

    output = "\n".join(result)
    # Ensure every chapter heading is preceded by a blank line
    output = re.sub(r"([^\n])\n(# 第(?:\d+|[零〇一二两三四五六七八九十百千万]+)章)", r"\1\n\n\2", output)
    # Ensure top-level header is followed by a blank line
    output = re.sub(r"(# 全书大纲汇总)\n([^#\n])", r"\1\n\n\2", output)
    # Collapse 3+ consecutive blank lines into 2
    output = re.sub(r"\n{3,}", "\n\n", output)
    return output


def _is_layered_archive_summary(text: str) -> bool:
    """Return True for segment-level constraint extraction or legacy batch-archive format."""
    markers = (
        "LONGFORM_LAYERED_ARCHIVE_V1",
        "# Batch Archive:",
        "## Batch Archive:",
        "### 故事阶段",
        "### 核心驱动进度",
        "### 伏笔台账",
        "## Batch Overview",
        "## Batch Index",
        "# 批次档案",
        "## 本批总览",
        "## 本批索引",
    )
    return any(marker in text for marker in markers)


def _merge_batch_answers(full_answer: list[str]) -> str:
    """Deduplicate, sort by chapter range, and merge batch answers.

    Each batch answer from Dify contains a ``# Batch Archive: CHxx-CHyy``
    heading (or Chinese variant).  Multiple large-batch runs can overlap
    or arrive out of order.  This function extracts the chapter range from
    each batch, sorts by start chapter, and deduplicates exact-range
    duplicates (keeping the later one).

    NOTE: We no longer subsume overlapping ranges because distinct batches
    (e.g. 番外 vs mainline) may share the same numeric range but contain
    entirely different content.  Only exact (start, end) duplicates are
    collapsed.
    """
    if not full_answer:
        return ""
    if len(full_answer) == 1:
        return full_answer[0].strip()

    # Extract (start_ch, end_ch) from each answer
    range_re = re.compile(
        r"^#{1,2}\s*(?:Batch Archive|批次档案)\s*[:：]\s*CH(\d+)\s*[-–—]\s*(\d+)",
        re.MULTILINE,
    )
    tagged: list[tuple[int, int, str]] = []
    untagged: list[str] = []

    for answer in full_answer:
        answer = answer.strip()
        if not answer:
            continue
        m = range_re.search(answer)
        if m:
            start_ch, end_ch = int(m.group(1)), int(m.group(2))
            tagged.append((start_ch, end_ch, answer))
        else:
            untagged.append(answer)

    # Sort tagged by start chapter, then by end chapter descending (wider first)
    tagged.sort(key=lambda t: (t[0], -t[1]))
    deduped: list[str] = []
    seen_ranges: set[tuple[int, int]] = set()
    for start_ch, end_ch, answer in tagged:
        if (start_ch, end_ch) in seen_ranges:
            # Exact duplicate range — keep the later one
            deduped[-1] = answer
        else:
            deduped.append(answer)
            seen_ranges.add((start_ch, end_ch))

    parts = deduped + untagged
    return "\n\n".join(parts)


def _extract_batch_title(summary: str, index: int) -> str:
    match = re.search(r"^#{1,2}\s*(?:Batch Archive|批次档案)\s*[:：]\s*(.+?)\s*$", summary, flags=re.MULTILINE)
    if match and match.group(1).strip():
        return match.group(1).strip()
    return f"Batch {index}"


def _extract_markdown_section(summary: str, headings: tuple[str, ...]) -> str:
    lines = summary.splitlines()
    collected: list[str] = []
    capturing = False
    heading_set = set(headings)
    capture_level = 0  # 2 for ##, 3 for ###

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("### "):
            heading = stripped[4:].strip()
            if capturing and capture_level == 3:
                break
            if heading in heading_set:
                capturing = True
                capture_level = 3
                continue
            if capturing and capture_level == 2:
                # Inside a ## section, ### is a subsection — keep capturing
                pass
        elif stripped.startswith("## "):
            heading = stripped[3:].strip()
            if capturing:
                break
            if heading in heading_set:
                capturing = True
                capture_level = 2
                continue
        elif capturing and stripped.startswith("# ") and not stripped.startswith("### "):
            break

        if capturing:
            collected.append(line)

    return "\n".join(collected).strip()


def _compact_section_lines(section: str, *, limit: int) -> list[str]:
    lines: list[str] = []
    for raw_line in section.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("```"):
            continue
        if len(line) > 220:
            line = f"{line[:220]}..."
        lines.append(line)
        if len(lines) >= limit:
            break
    return lines


def _build_layered_archive_overview(batch_summaries: list[str]) -> str:
    valid_batches = [item.strip() for item in batch_summaries if item and item.strip()]
    if not valid_batches or not any(_is_layered_archive_summary(item) for item in valid_batches):
        return ""

    lines = [
        "# 全书总汇总（自动索引）",
        "",
        f"- 段落数：{len(valid_batches)}",
        "- 生成方式：按段落档案提取叙事约束；完整段落记录保留在下方。",
        "- 使用提示：先读本节掌握全局阶段和线索状态，再按段落回查约束细节。",
        "",
    ]

    # Detect format: new segment-level vs legacy batch-level
    is_segment_format = any("故事阶段" in item for item in valid_batches)

    for index, summary in enumerate(valid_batches, start=1):
        title = _extract_batch_title(summary, index)
        lines.extend([f"## 段落 {index}：{title}", ""])

        if is_segment_format:
            for field in ("故事阶段", "核心驱动进度", "线索状态"):
                section = _extract_markdown_section(summary, (field,))
                section_lines = _compact_section_lines(section, limit=5)
                if section_lines:
                    lines.append(f"### {field}")
                    lines.extend(section_lines)
                    lines.append("")
        else:
            overview = _extract_markdown_section(summary, ("Batch Overview", "本批总览"))
            overview_lines = _compact_section_lines(overview, limit=8)
            if overview_lines:
                lines.extend(overview_lines)
                lines.append("")

            batch_index = _extract_markdown_section(summary, ("Batch Index", "本批索引"))
            index_lines = _compact_section_lines(batch_index, limit=10)
            if index_lines:
                lines.append("### 本批索引摘录")
                lines.extend(index_lines)
                lines.append("")

    return "\n".join(lines).strip()


def _compose_layered_archive_summary(batch_summaries: list[str], body: str) -> str:
    """Place a deterministic whole-book overview above the preserved batch archives."""
    normalized_body = body.strip()
    overview = _build_layered_archive_overview(batch_summaries)
    if not overview:
        return normalized_body
    if normalized_body.startswith("# 全书总汇总（自动索引）"):
        return normalized_body
    return f"{overview}\n\n---\n\n# 分批阅读档案\n\n{normalized_body}".strip()


def _write_summary(
    book_dir: str,
    book_name: str,
    content: str,
    *,
    chapter_count: int | None = None,
    total_batches: int | None = None,
) -> None:
    """Write summary.md and its completion metadata in one archive commit."""
    import subprocess

    summary_path = os.path.join(book_dir, "summary.md")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(content)
    commit_paths = ["summary.md"]
    if chapter_count is not None and total_batches is not None:
        try:
            if _update_summary_metadata(book_dir, chapter_count, total_batches):
                commit_paths.append("metadata.json")
        except Exception:
            logger.warning("Failed to update summary metadata for %s", book_name, exc_info=True)
    try:
        ensure_repo(book_dir)
        run_git(book_dir, ["add", "--", *commit_paths])
        status_output = run_git(book_dir, ["status", "--porcelain", "--", *commit_paths]).stdout
        if status_output.strip():
            try:
                run_git(book_dir, ["commit", "-m", f"[AI_Summary] {book_name}", "--", *commit_paths])
            except subprocess.CalledProcessError as exc:
                if not is_nothing_to_commit_error(exc):
                    raise
        logger.info("Wrote summary.md for %s", book_name)
    except Exception:
        logger.exception("Failed to commit summary.md for %s", book_name)


def _update_summary_metadata(book_dir: str, chapter_count: int, total_batches: int) -> bool:
    """Update metadata.json with summary completion info."""
    meta_path = os.path.join(book_dir, "metadata.json")
    if not os.path.exists(meta_path):
        return False
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)
    meta["summary_complete"] = True
    meta["total_chapters"] = chapter_count
    meta["processed_batches"] = total_batches
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    logger.info("Updated metadata.json: summary_complete=True, %d chapters, %d batches", chapter_count, total_batches)
    return True


def _trigger_summary_generation(
    book_dir: str,
    book_name: str,
    chapter_count: int,
    dify_registry: dict | None = None,
) -> None:
    """Fire-and-forget: run backend summary archive pipeline to generate summary.md."""
    # Derive book_id from book_dir for progress tracking
    book_id = os.path.basename(book_dir)

    cancel_event = _register_task_cancel_event(_summary_cancel_events, book_id)
    try:
        from pipelines.summary_archive import run_pipeline

        def _record_progress(progress: dict[str, Any]) -> None:
            status = progress.get("status")
            if status == "success":
                status = "done"
            _summary_progress[book_id] = {
                "book_name": book_name,
                **progress,
                "status": status,
            }

        result = run_pipeline(
            book_id=book_id,
            book_dir=book_dir,
            book_name=book_name,
            cancel_event=cancel_event,
            progress_callback=_record_progress,
        )
        status = result.get("status")
        if status == "success":
            _summary_progress[book_id] = {
                "status": "done",
                "book_name": book_name,
                "chars": result.get("chars", 0),
                "total_batches": result.get("total_batches"),
                "chapter_count": result.get("chapter_count", chapter_count),
                "commit_id": result.get("commit_id"),
            }
        elif status in {"cancelled", "no_chapters"}:
            _summary_progress[book_id] = {"book_name": book_name, **result}
        else:
            _summary_progress[book_id] = {
                "status": "failed",
                "book_name": book_name,
                "error": result.get("error") or "summary pipeline failed",
            }
    except Exception:
        logger.exception("Failed to generate summary via backend summary archive pipeline for %s", book_name)
        _summary_progress[book_id] = {
            "status": "failed",
            "book_name": book_name,
            "error": "see backend logs",
        }
    finally:
        _clear_task_cancel_event(_summary_cancel_events, book_id, cancel_event)
    return

def _find_missing_chapters(summary_text: str, chapter_titles: dict[int, str]) -> list[int]:
    """Return chapter indices that have a heading but no 简述 body."""
    missing: list[int] = []
    lines = summary_text.split("\n")
    heading_indices = []
    for i, line in enumerate(lines):
        s = line.strip()
        if not s.startswith("# 第"):
            continue
        ch_num = _parse_chapter_index(s[2:])
        if ch_num is None:
            continue
        heading_indices.append((i, ch_num))

    for j, (idx, ch_num) in enumerate(heading_indices):
        if ch_num not in chapter_titles:
            continue
        found_body = False
        for k in range(idx + 1, min(len(lines), idx + 4)):
            if lines[k].strip().startswith("简述："):
                found_body = True
                break
            elif lines[k].strip().startswith("#"):
                break
        if not found_body:
            missing.append(ch_num)
    return missing


def _patch_summary(summary_text: str, patch_text: str, chapter_titles: dict[int, str]) -> str:
    """Insert retry results into the correct positions in the existing summary."""
    patch_lines = patch_text.split("\n")
    # Collect (chapter_index, [lines]) from the patch
    patches: dict[int, list[str]] = {}
    current_idx: int | None = None
    current_lines: list[str] = []
    for line in patch_lines:
        s = line.strip()
        ch_idx = _parse_chapter_index(s[2:]) if s.startswith("# ") else None
        if ch_idx is not None:
            if current_idx is not None:
                patches[current_idx] = current_lines
            current_idx = ch_idx
            current_lines = [line]
        elif current_idx is not None:
            current_lines.append(line)
    if current_idx is not None:
        patches[current_idx] = current_lines

    if not patches:
        return summary_text

    # Walk the summary and replace missing chapters' blocks
    lines = summary_text.split("\n")
    result: list[str] = []
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        ch_idx = _parse_chapter_index(s[2:]) if s.startswith("# ") else None
        if ch_idx is not None and ch_idx in patches:
            # Skip old block (heading + optional blank + optional body)
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("#"):
                i += 1
            # Insert patched block
            result.append("")
            result.extend(patches[ch_idx])
            continue
        result.append(lines[i])
        i += 1

    output = "\n".join(result)
    output = re.sub(r"\n{3,}", "\n\n", output)
    return output


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _chapter_summary(chapter: dict[str, Any]) -> dict[str, Any]:
    return {
        "index": chapter["index"],
        "title": chapter["title"],
        "source_file": chapter["source_file"],
        "target_file": chapter["target_file"],
        "content_hash": chapter["content_hash"],
        "chars": chapter["chars"],
        "non_whitespace_chars": chapter["non_whitespace_chars"],
        "line_count": chapter["line_count"],
        "warnings": chapter.get("warnings", []),
    }


def _preview_payload(parsed: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "success",
        "book_name": parsed["book_name"],
        "source_dir": parsed["source_dir"],
        "metadata": parsed["metadata"],
        "report": parsed["report"],
        "quality": parsed.get("quality", {}),
        "chapters": [_chapter_summary(chapter) for chapter in parsed["chapters"]],
    }


def _commit_paths(repo_dir: str, rel_paths: list[str], message: str) -> str:
    ensure_repo(repo_dir)
    ensure_repo_identity(repo_dir)

    # Stage tracked layout files (small fixed set)
    tracked_scope = [
        rel_path
        for rel_path in TRACKED_LAYOUT_FILES
        if os.path.exists(os.path.join(repo_dir, rel_path))
    ]
    if tracked_scope:
        run_git(repo_dir, ["add", "--", *tracked_scope])

    # Stage chapter files by directory to avoid command-line overflow on Windows
    chapter_dirs = sorted({os.path.dirname(p) for p in rel_paths if "/" in p or "\\" in p})
    for d in chapter_dirs:
        run_git(repo_dir, ["add", "--", d])

    # Stage root-level files from rel_paths
    root_files = [p for p in rel_paths if "/" not in p and "\\" not in p and p not in tracked_scope]
    if root_files:
        run_git(repo_dir, ["add", "--", *root_files])

    status_output = run_git(repo_dir, ["status", "--porcelain"]).stdout
    if not status_output.strip():
        return resolve_head(repo_dir, message)
    try:
        run_git(repo_dir, ["commit", "-m", message])
    except subprocess.CalledProcessError as exc:
        if not is_nothing_to_commit_error(exc):
            raise
    return resolve_head(repo_dir, message)


def _write_import_report(repo_dir: str, parsed: dict[str, Any], rel_paths: list[str]) -> str:
    report = {
        "imported_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source": {
            "kind": "tomato_bulk_files",
            "source_dir": parsed["source_dir"],
            "metadata": parsed["metadata"],
        },
        "report": parsed["report"],
        "quality": parsed.get("quality", {}),
        "chapters": [_chapter_summary(chapter) for chapter in parsed["chapters"]],
        "written_files": rel_paths,
    }
    report_path = os.path.join(repo_dir, "import_report.json")
    with open(report_path, "w", encoding="utf-8") as report_file:
        json.dump(report, report_file, ensure_ascii=False, indent=2)
        report_file.write("\n")
    return "import_report.json"


def _resolve_source_args(payload: dict[str, Any]) -> tuple[str | None, str | None, tuple | None]:
    source_dir = payload.get("source_dir")
    if not isinstance(source_dir, str) or not source_dir.strip():
        return None, None, (jsonify({"status": "error", "code": "MISSING_FIELD", "message": "source_dir is required"}), 400)
    allowed_root = payload.get("allowed_root") or os.environ.get("TOMATO_LIBRARY_ROOT")
    if allowed_root is not None and not isinstance(allowed_root, str):
        return None, None, (
            jsonify({"status": "error", "code": "INVALID_PAYLOAD", "message": "allowed_root must be a string"}),
            400,
        )
    return source_dir.strip(), allowed_root.strip() if isinstance(allowed_root, str) and allowed_root.strip() else None, None


def _download_via_exe(
    book_id: str,
    project_root: str,
    cancel_event: threading.Event | None = None,
) -> dict | None:
    """Try downloading via Tomato-Novel-Downloader exe. Returns adapted dict or None."""
    import shutil
    from pathlib import Path

    from utils.tomato_exe_client import TomatoJobCancelled, build_client_from_env
    from utils.tomato_txt_parser import parse_txt
    from utils.tomato_importer import _safe_title, _text_stats

    client = build_client_from_env()
    if client is None:
        return None
    owns_cancel_event = cancel_event is None
    if cancel_event is None:
        cancel_event = _register_task_cancel_event(_download_cancel_events, book_id)
    download_dir = os.path.join(project_root, ".runtime", "tomato_downloads", book_id)
    try:
        if cancel_event.is_set():
            raise TomatoJobCancelled(f"Download job for {book_id} cancelled")
        client.ensure_running()
        client.configure(novel_format="txt", bulk_files=False)
        os.makedirs(download_dir, exist_ok=True)
        client.set_save_path(str(Path(download_dir).resolve()))

        def _on_progress(saved: int, total: int, state: str) -> None:
            _download_progress[book_id] = {
                "status": "downloading",
                "saved_chapters": saved,
                "chapter_total": total,
                "state": state,
            }

        _download_progress[book_id] = {
            "status": "downloading",
            "saved_chapters": 0,
            "chapter_total": 0,
            "state": "pending",
        }
        try:
            job = client.download_book(book_id, on_progress=_on_progress, cancel_event=cancel_event)
            if cancel_event.is_set():
                raise TomatoJobCancelled(f"Download job for {book_id} cancelled")
        finally:
            _download_progress.pop(book_id, None)
        book_name = job.get("title", "")
        txt_path = client.find_output_txt(book_name)
        if txt_path is None or not txt_path.exists():
            logger.warning("exe download succeeded but output TXT not found for %s", book_id)
            return None
        raw = txt_path.read_text(encoding="utf-8")
        result = parse_txt(raw)
        chapters_raw = result["chapters"]
        if not chapters_raw:
            return None
        # Convert to adapted format (same shape as adapt_download output)
        import hashlib

        chapters: list[dict[str, Any]] = []
        for idx, ch in enumerate(chapters_raw, start=1):
            body = ch["body"]
            title = ch["title"]
            safe = _safe_title(title)
            stats = _text_stats(body)
            chapters.append({
                "index": idx,
                "title": title,
                "safe_title": safe,
                "source_file": f"exe:{idx}",
                "target_file": f"{idx:04d}_{safe}.md",
                "body": body,
                "markdown": f"# {title}\n\n{body.rstrip()}\n",
                "content_hash": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                "chars": stats["chars"],
                "non_whitespace_chars": stats["non_whitespace_chars"],
                "line_count": stats["line_count"],
                "warnings": [],
            })
        # Download staging dir will be cleaned in finally block below.
        return {
            "book_id": book_id,
            "book_name": book_name,
            "author": result["metadata"].get("author", ""),
            "chapter_count": len(chapters),
            "chapters": chapters,
            "quality": {"can_confirm": True, "risk_level": "ok", "block_count": 0, "warn_count": 0, "issues": []},
        }
    except TomatoJobCancelled:
        _download_progress[book_id] = {
            "status": "cancelled",
            "saved_chapters": 0,
            "chapter_total": 0,
            "state": "cancelled",
        }
        raise
    except Exception:
        logger.warning("exe download failed for %s, falling back", book_id, exc_info=True)
        return None
    finally:
        try:
            shutil.rmtree(download_dir, ignore_errors=True)
        except Exception:
            pass
        # Clean up artifacts the exe may have created outside download_dir
        # (book-name directories and txt files under novel_git_server/)
        try:
            _server_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            for entry in os.listdir(_server_dir):
                full = os.path.join(_server_dir, entry)
                if entry.startswith(book_id + "_") and os.path.isdir(full):
                    shutil.rmtree(full, ignore_errors=True)
                elif entry.endswith(".txt") and book_id not in entry and entry != "requirements.txt" and os.path.isfile(full):
                    # Heuristic: large non-requirements txt likely from exe
                    if os.path.getsize(full) > 100_000:
                        try:
                            os.remove(full)
                        except Exception:
                            pass
        except Exception:
            pass
        if owns_cancel_event:
            _clear_task_cancel_event(_download_cancel_events, book_id, cancel_event)


def _download_via_fallback(book_id: str, cancel_event: threading.Event | None = None) -> dict | None:
    """Fallback download via tomato_search pure HTTP. Returns adapted dict or None."""
    from utils.tomato_exe_client import TomatoJobCancelled
    from utils.tomato_search import download_book as _download_book

    if cancel_event is not None and cancel_event.is_set():
        raise TomatoJobCancelled(f"Download job for {book_id} cancelled")
    _download_progress[book_id] = {
        "status": "downloading",
        "saved_chapters": 0,
        "chapter_total": 0,
        "state": "fallback",
    }
    try:
        download_result = _download_book(book_id)
        if cancel_event is not None and cancel_event.is_set():
            raise TomatoJobCancelled(f"Download job for {book_id} cancelled")
    except Exception as exc:
        if isinstance(exc, TomatoJobCancelled):
            raise
        logger.error("fallback download failed for %s: %s", book_id, exc)
        return None
    finally:
        if cancel_event is None or not cancel_event.is_set():
            _download_progress.pop(book_id, None)
    return adapt_download(download_result)


def _download_online_book(book_id: str, project_root: str) -> dict | None:
    from utils.tomato_exe_client import TomatoJobCancelled

    cancel_event = _register_task_cancel_event(_download_cancel_events, book_id)
    try:
        if cancel_event.is_set():
            raise TomatoJobCancelled(f"Download job for {book_id} cancelled")
        adapted = _download_via_exe(book_id, project_root=project_root, cancel_event=cancel_event)
        if cancel_event.is_set():
            raise TomatoJobCancelled(f"Download job for {book_id} cancelled")
        if adapted is None:
            adapted = _download_via_fallback(book_id, cancel_event=cancel_event)
        if cancel_event.is_set():
            raise TomatoJobCancelled(f"Download job for {book_id} cancelled")
    except TomatoJobCancelled:
        _download_progress[book_id] = {
            "status": "cancelled",
            "saved_chapters": 0,
            "chapter_total": 0,
            "state": "cancelled",
        }
        return {
            "cancelled": True,
            "book_id": book_id,
        }
    finally:
        _clear_task_cancel_event(_download_cancel_events, book_id, cancel_event)
    return adapted


def create_blueprint(
    *,
    storage_root: str,
    parse_json_payload: Callable[[list[str] | None], tuple[dict | None, tuple | None]],
    require_book_id: Callable[[dict | None], tuple[str | None, tuple | None]],
    json_error: Callable[[str, str, int], tuple],
    dify_agent_registry: dict | None = None,
) -> Blueprint:
    bp = Blueprint("tomato_import", __name__)

    @bp.post("/books/tomato/preview")
    def tomato_preview():
        payload, err = parse_json_payload(["source_dir"])
        if err:
            return err

        source_dir, allowed_root, source_err = _resolve_source_args(payload)
        if source_err:
            return source_err

        try:
            parsed = parse_tomato_bulk_export(source_dir, allowed_root=allowed_root)
        except ValueError as exc:
            return json_error("INVALID_SOURCE_DIR", str(exc), 400)
        return jsonify(_preview_payload(parsed)), 200

    @bp.post("/books/tomato/confirm")
    def tomato_confirm():
        payload, err = parse_json_payload(["source_dir"])
        if err:
            return err

        book_id, book_err = require_book_id(payload)
        if book_err:
            return book_err

        source_dir, allowed_root, source_err = _resolve_source_args(payload)
        if source_err:
            return source_err

        overwrite = _coerce_bool(payload.get("overwrite", False))
        force = _coerce_bool(payload.get("force", False))
        try:
            parsed = parse_tomato_bulk_export(source_dir, allowed_root=allowed_root)
        except ValueError as exc:
            return json_error("INVALID_SOURCE_DIR", str(exc), 400)

        if not parsed["chapters"]:
            return json_error("NO_CHAPTERS_PARSED", "no chapter txt files were parsed from source_dir", 400)

        quality = parsed.get("quality", {})
        if quality and not quality.get("can_confirm", True) and not force:
            return (
                jsonify(
                    {
                        "status": "error",
                        "code": "QUALITY_GATE_BLOCKED",
                        "message": "tomato import quality gate blocked this import; set force=true to override after review",
                        "quality": quality,
                        "preview": _preview_payload(parsed),
                    }
                ),
                422,
            )

        book_name = parsed.get("book_name") or payload.get("book_name")
        normalized_book_name = book_name.strip() if isinstance(book_name, str) and book_name.strip() else None
        paths = ensure_book_layout(book_id, storage_root, book_name=normalized_book_name)
        repo_dir = paths["book_dir"]

        collisions = [
            chapter["target_file"]
            for chapter in parsed["chapters"]
            if os.path.exists(os.path.join(paths["chapters_dir"], chapter["target_file"]))
        ]
        if collisions and not overwrite:
            return (
                jsonify(
                    {
                        "status": "error",
                        "code": "CHAPTER_EXISTS",
                        "message": "target chapter files already exist; set overwrite=true to replace them",
                        "book_id": book_id,
                        "collisions": collisions,
                    }
                ),
                409,
            )

        rel_paths: list[str] = []
        for chapter in parsed["chapters"]:
            chapter_path = os.path.join(paths["chapters_dir"], chapter["target_file"])
            with open(chapter_path, "w", encoding="utf-8") as chapter_file:
                chapter_file.write(chapter["markdown"])
            rel_paths.append(f"chapters/{chapter['target_file']}")

        rel_paths.append(_write_import_report(repo_dir, parsed, rel_paths))
        message = f"import tomato chapters ({len(parsed['chapters'])} total)"
        try:
            commit_id = _commit_paths(repo_dir, rel_paths, message)
        except Exception as exc:
            return json_error("GIT_COMMIT_FAILED", format_git_error(exc) or "failed to commit tomato import", 500)

        return (
            jsonify(
                {
                    **_preview_payload(parsed),
                    "book_id": book_id,
                    "saved_count": len(parsed["chapters"]),
                    "written_files": rel_paths,
                    "force_used": force,
                    "commit_id": commit_id,
                }
            ),
            200,
        )

    @bp.post("/books/tomato/online_import")
    def tomato_online_import():
        """Download a book from Tomato Novel online and import it.

        Body: {"book_id": "...", "overwrite": false, "force": false}
        """
        payload, err = parse_json_payload(["book_id"])
        if err:
            return err

        book_id = payload.get("book_id", "").strip()
        if not book_id:
            return json_error("MISSING_FIELD", "book_id is required", 400)

        overwrite = _coerce_bool(payload.get("overwrite", False))
        force = _coerce_bool(payload.get("force", False))

        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        adapted = _download_online_book(book_id, project_root=project_root)
        if adapted and adapted.get("cancelled"):
            return json_error("DOWNLOAD_CANCELLED", "download was cancelled", 409)
        if adapted is None:
            return json_error("DOWNLOAD_FAILED", "all download methods failed", 502)

        chapters = adapted["chapters"]
        if not chapters:
            return json_error("NO_CHAPTERS", "download returned zero chapters", 400)

        quality = adapted["quality"]
        if quality and not quality.get("can_confirm", True) and not force:
            return (
                jsonify({
                    "status": "error",
                    "code": "QUALITY_GATE_BLOCKED",
                    "message": "online import quality gate blocked; set force=true to override",
                    "quality": quality,
                    "book_name": adapted["book_name"],
                    "chapter_count": adapted["chapter_count"],
                }),
                422,
            )

        try:
            resolved_book_id = validate_book_id(payload.get("book_id_override") or book_id)
        except ValueError as exc:
            return json_error("INVALID_BOOK_ID", str(exc), 400)

        book_name = adapted.get("book_name")
        normalized_book_name = book_name.strip() if isinstance(book_name, str) and book_name.strip() else None
        workspace_existed_before_import = os.path.isdir(os.path.join(storage_root, resolved_book_id))
        paths = ensure_book_layout(resolved_book_id, storage_root, book_name=normalized_book_name)
        repo_dir = paths["book_dir"]

        collisions = [
            ch["target_file"]
            for ch in chapters
            if os.path.exists(os.path.join(paths["chapters_dir"], ch["target_file"]))
        ]
        if collisions and not overwrite:
            return (
                jsonify({
                    "status": "error",
                    "code": "CHAPTER_EXISTS",
                    "message": "target chapter files already exist; set overwrite=true",
                    "book_id": resolved_book_id,
                    "collisions": collisions,
                }),
                409,
            )

        if overwrite or not workspace_existed_before_import:
            delete_book_conversations(None, resolved_book_id)

        # When overwrite=true, remove stale chapter files from previous imports
        if overwrite:
            new_files = {ch["target_file"] for ch in chapters}
            chapters_dir = paths["chapters_dir"]
            for existing in os.listdir(chapters_dir):
                if existing.endswith(".md") and existing not in new_files:
                    os.remove(os.path.join(chapters_dir, existing))

        rel_paths: list[str] = []
        for ch in chapters:
            chapter_path = os.path.join(paths["chapters_dir"], ch["target_file"])
            with open(chapter_path, "w", encoding="utf-8") as chapter_file:
                chapter_file.write(ch["markdown"])
            rel_paths.append(f"chapters/{ch['target_file']}")

        online_report = {
            "imported_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "source": {
                "kind": "tomato_online",
                "book_id": book_id,
                "book_name": adapted["book_name"],
                "author": adapted["author"],
            },
            "quality": quality,
            "chapter_count": adapted["chapter_count"],
            "written_files": rel_paths,
        }
        report_path = os.path.join(repo_dir, "import_report.json")
        with open(report_path, "w", encoding="utf-8") as report_file:
            json.dump(online_report, report_file, ensure_ascii=False, indent=2)
            report_file.write("\n")
        rel_paths.append("import_report.json")

        message = f"import tomato online chapters ({len(chapters)} total)"
        try:
            commit_id = _commit_paths(repo_dir, rel_paths, message)
        except Exception as exc:
            return json_error("GIT_COMMIT_FAILED", format_git_error(exc) or "failed to commit", 500)

        # Fire-and-forget: trigger backend summary archive pipeline to generate summary.md.
        threading.Thread(
            target=_trigger_summary_generation,
            args=(repo_dir, adapted["book_name"], len(chapters), None),
            daemon=True,
        ).start()

        return jsonify({
            "status": "success",
            "book_id": resolved_book_id,
            "book_name": adapted["book_name"],
            "author": adapted["author"],
            "chapter_count": adapted["chapter_count"],
            "saved_count": len(chapters),
            "written_files": rel_paths,
            "quality": quality,
            "force_used": force,
            "commit_id": commit_id,
        }), 200

    @bp.post("/books/tomato/trigger_summary")
    def trigger_summary():
        """Manually trigger summary generation for an already-imported book."""
        payload, err = parse_json_payload(["book_id"])
        if err:
            return err

        book_id = payload.get("book_id", "").strip()
        if not book_id:
            return json_error("MISSING_FIELD", "book_id is required", 400)

        from utils.book_storage import get_book_metadata, validate_book_id

        try:
            validated_id = validate_book_id(book_id)
        except ValueError as exc:
            return json_error("INVALID_BOOK_ID", str(exc), 400)

        book_dir = os.path.join(storage_root, validated_id)
        if not os.path.isdir(book_dir):
            return json_error("NOT_FOUND", f"book {validated_id} not found", 404)

        metadata = get_book_metadata(validated_id, storage_root)
        book_name = metadata.get("book_name", validated_id)

        # Count chapters
        chapters_dir = os.path.join(book_dir, "chapters")
        chapter_count = 0
        if os.path.isdir(chapters_dir):
            chapter_count = len([f for f in os.listdir(chapters_dir) if f.endswith(".md")])

        threading.Thread(
            target=_trigger_summary_generation,
            args=(book_dir, book_name, chapter_count, None),
            daemon=True,
        ).start()

        return jsonify({
            "status": "triggered",
            "book_id": validated_id,
            "book_name": book_name,
            "chapter_count": chapter_count,
        }), 200

    @bp.get("/books/tomato/summary_status")
    def summary_status():
        """Poll summary generation progress for a book."""
        book_id = request.args.get("book_id", "").strip()
        if not book_id:
            return json_error("MISSING_FIELD", "book_id query param is required", 400)

        progress = _summary_progress.get(book_id)
        if not progress:
            return jsonify({"status": "idle", "book_id": book_id}), 200

        return jsonify({"book_id": book_id, **progress}), 200

    @bp.get("/books/tomato/download_status")
    def download_status():
        """Poll download progress for a book."""
        book_id = request.args.get("book_id", "").strip()
        if not book_id:
            return json_error("MISSING_FIELD", "book_id query param is required", 400)

        progress = _download_progress.get(book_id)
        if not progress:
            return jsonify({"status": "idle", "book_id": book_id}), 200

        return jsonify({"book_id": book_id, **progress}), 200

    @bp.get("/books/tomato/search")
    def tomato_search():
        """Search Tomato Novel by keyword.

        Query params: q (required), count (optional, default 20)
        """
        from flask import request

        query = request.args.get("q", "").strip()
        if not query:
            return json_error("MISSING_FIELD", "q query parameter is required", 400)
        count = request.args.get("count", 20, type=int)

        try:
            results = search_novels(query, count=count)
        except RuntimeError as exc:
            return json_error("SEARCH_FAILED", str(exc), 502)
        except Exception as exc:
            return json_error("SEARCH_FAILED", str(exc), 500)

        return jsonify({"status": "success", "query": query, "count": len(results), "results": results}), 200

    @bp.get("/books/tomato/book_info")
    def tomato_book_info():
        """Get book metadata without downloading.

        Query params: book_id (required)
        """
        from flask import request

        book_id = request.args.get("book_id", "").strip()
        if not book_id:
            return json_error("MISSING_FIELD", "book_id query parameter is required", 400)

        try:
            info = get_book_info(book_id)
        except RuntimeError as exc:
            return json_error("BOOK_INFO_FAILED", str(exc), 502)
        except Exception as exc:
            return json_error("BOOK_INFO_FAILED", str(exc), 500)

        return jsonify({"status": "success", **info}), 200

    return bp
