"""Adapt online Tomato Novel download results to the local storage pipeline.

Bridges tomato_search.download_book() output to the chapter format expected
by book_storage + git commit, with quality gates from tomato_importer.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from utils.tomato_importer import (
    SHORT_CHAPTER_BLOCK_CHARS,
    SHORT_CHAPTER_WARNING_CHARS,
    _markdown_for_chapter,
    _safe_title,
    _text_stats,
)

_ARABIC_CHAPTER_RE = re.compile(r"第\s*(\d+)\s*章")


def _chapter_number(raw_chapter: dict[str, Any]) -> int | None:
    title = str(raw_chapter.get("title") or "")
    match = _ARABIC_CHAPTER_RE.search(title)
    if not match:
        return None
    return int(match.group(1))


def _ordered_raw_chapters(raw_chapters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    numbered = [_chapter_number(ch) for ch in raw_chapters]
    known_count = sum(number is not None for number in numbered)
    if known_count < max(2, len(raw_chapters) // 2):
        return raw_chapters
    return sorted(
        raw_chapters,
        key=lambda ch: (
            _chapter_number(ch) is None,
            _chapter_number(ch) or int(ch.get("index", 0)),
            int(ch.get("index", 0)),
        ),
    )


def adapt_download(
    download_result: dict[str, Any],
) -> dict[str, Any]:
    """Convert download_book() output to storage-ready chapter format.

    Returns dict with keys: book_name, author, chapter_count, chapters, quality.
    Each chapter has: index, title, safe_title, target_file, body, markdown,
    content_hash, chars, non_whitespace_chars, line_count, warnings.
    """
    chapters: list[dict[str, Any]] = []
    raw_chapters = _ordered_raw_chapters(list(download_result.get("chapters", [])))
    for index, raw_ch in enumerate(raw_chapters, start=1):
        body = raw_ch.get("body", "")
        title = raw_ch.get("title") or f"第{raw_ch['index']}章"
        safe = _safe_title(title)
        stats = _text_stats(body)
        body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()

        warnings: list[str] = []
        if raw_ch.get("error"):
            warnings.append(f"DOWNLOAD_ERROR:{raw_ch['error']}")

        chapters.append({
            "index": index,
            "title": title,
            "safe_title": safe,
            "source_file": f"online:{raw_ch.get('index', index)}",
            "target_file": f"{index:04d}_{safe}.md",
            "body": body,
            "markdown": _markdown_for_chapter(title, body),
            "content_hash": body_hash,
            "chars": stats["chars"],
            "non_whitespace_chars": stats["non_whitespace_chars"],
            "line_count": stats["line_count"],
            "warnings": warnings,
        })

    quality = _evaluate_online_quality(chapters)
    return {
        "book_id": download_result.get("book_id", ""),
        "book_name": download_result.get("book_name", ""),
        "author": download_result.get("author", ""),
        "chapter_count": len(chapters),
        "chapters": chapters,
        "quality": quality,
    }


def _evaluate_online_quality(chapters: list[dict[str, Any]]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    if not chapters:
        issues.append({"severity": "block", "code": "NO_CHAPTERS", "message": "没有下载到任何章节。"})

    seen_hashes: dict[str, str] = {}
    for ch in chapters:
        label = f"{ch['index']:04d} {ch['title']}"
        non_ws = ch["non_whitespace_chars"]

        if not ch["body"].strip():
            issues.append({"severity": "block", "code": "EMPTY_CHAPTER", "message": "章节正文为空。", "chapter": label})
        elif non_ws < SHORT_CHAPTER_BLOCK_CHARS:
            issues.append({
                "severity": "block", "code": "TOO_SHORT_CHAPTER",
                "message": "章节正文过短，疑似下载失败。", "chapter": label,
                "non_whitespace_chars": non_ws,
            })
        elif non_ws < SHORT_CHAPTER_WARNING_CHARS:
            issues.append({
                "severity": "warn", "code": "SHORT_CHAPTER",
                "message": "章节正文偏短。", "chapter": label,
                "non_whitespace_chars": non_ws,
            })

        if ch["content_hash"] in seen_hashes:
            issues.append({
                "severity": "block", "code": "DUPLICATE_CHAPTER_CONTENT",
                "message": "章节正文 hash 重复。", "chapter": label,
                "first": seen_hashes[ch["content_hash"]],
            })
        else:
            seen_hashes[ch["content_hash"]] = label

        for w in ch.get("warnings", []):
            if w.startswith("DOWNLOAD_ERROR:"):
                issues.append({
                    "severity": "block", "code": "DOWNLOAD_ERROR",
                    "message": f"下载失败: {w.split(':', 1)[1]}", "chapter": label,
                })

    block_count = sum(1 for issue in issues if issue["severity"] == "block")
    warn_count = sum(1 for issue in issues if issue["severity"] == "warn")
    return {
        "can_confirm": block_count == 0,
        "risk_level": "block" if block_count else "warn" if warn_count else "ok",
        "block_count": block_count,
        "warn_count": warn_count,
        "issues": issues,
    }
