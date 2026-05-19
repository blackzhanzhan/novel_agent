"""Parse single-file TXT output from Tomato-Novel-Downloader into chapter dicts.

Expected TXT structure::

    书名：xxx
    作者：xxx
    book_id=xxx
    ...

    ========================================

    【第一卷：xxx】

    第1章 title

    　　content...

    ----------------------------------------

    第2章 title

    　　content...
"""

from __future__ import annotations

import re
from typing import Any

_META_SEPARATOR = "=" * 40
_CHAPTER_SEPARATOR = "-" * 40
_TITLE_RE = re.compile(
    r"^(?:"
    r"第[0-9零〇一二三四五六七八九十百千万两]+[章节回卷集部篇].*"
    r"|Chapter\s*[0-9]+.*"
    r"|楔子.*"
    r"|序章.*"
    r"|引子.*"
    r"|番外.*"
    r"|特别篇.*"
    r"|if线.*"
    r")$",
    re.IGNORECASE,
)
_VOLUME_RE = re.compile(r"^【(.+)】$")


def parse_txt(raw: str) -> dict[str, Any]:
    """Parse a single-file TXT download into metadata + chapters.

    Returns dict with keys: metadata, chapters.
    Each chapter: {index, title, body, volume}.
    """
    raw = raw.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")

    # Split metadata header from chapter content
    parts = raw.split(_META_SEPARATOR, 1)
    if len(parts) == 2:
        metadata = _parse_metadata(parts[0])
        body_text = parts[1]
    else:
        metadata = {}
        body_text = raw

    chapters = _parse_chapters(body_text)
    return {"metadata": metadata, "chapters": chapters, "chapter_count": len(chapters)}


def _parse_metadata(header: str) -> dict[str, str]:
    result: dict[str, str] = {}
    collecting_desc = False
    desc_lines: list[str] = []

    for raw_line in header.split("\n"):
        line = raw_line.strip()
        if not line:
            if collecting_desc and desc_lines:
                desc_lines.append("")
            continue

        if collecting_desc:
            desc_lines.append(line)
            continue

        # Key-value patterns: "书名：xxx" or "book_id=xxx"
        kv_colon = line.split("：", 1)
        if len(kv_colon) == 2 and len(kv_colon[0]) <= 6:
            result[kv_colon[0].strip()] = kv_colon[1].strip()
            continue

        kv_eq = line.split("=", 1)
        if len(kv_eq) == 2 and len(kv_eq[0]) <= 20:
            result[kv_eq[0].strip()] = kv_eq[1].strip()
            continue

        if line == "简介：":
            collecting_desc = True

    if desc_lines:
        result["简介"] = "\n".join(desc_lines).strip()

    # Map to English keys
    key_map = {
        "书名": "book_name",
        "作者": "author",
        "book_id": "book_id",
        "状态": "status",
        "评分": "score",
        "字数": "word_count",
        "章节": "chapter_count",
        "分类": "category",
        "标签": "tags",
        "在读": "reader_count",
        "简介": "description",
    }
    mapped: dict[str, str] = {}
    for cn_key, en_key in key_map.items():
        if cn_key in result:
            mapped[en_key] = result[cn_key]
    # Copy any unmapped keys
    for k, v in result.items():
        if k not in key_map:
            mapped[k] = v

    return mapped


def _parse_chapters(body: str) -> list[dict[str, Any]]:
    # Split by chapter separator lines
    segments = re.split(r"\n" + re.escape(_CHAPTER_SEPARATOR) + r"\s*\n", body)
    if not segments:
        return []

    chapters: list[dict[str, Any]] = []
    current_volume = ""
    index = 0

    for segment in segments:
        segment = segment.strip()
        if not segment:
            continue

        lines = segment.split("\n")
        content_start = 0

        # Extract volume markers and chapter title from top of segment
        for i, line in enumerate(lines):
            stripped = line.strip()
            vol_match = _VOLUME_RE.match(stripped)
            if vol_match:
                current_volume = vol_match.group(1)
                content_start = i + 1
                continue
            if _TITLE_RE.match(stripped):
                index += 1
                chapters.append({
                    "index": index,
                    "title": stripped,
                    "body": "\n".join(lines[i + 1 :]).strip(),
                    "volume": current_volume,
                })
                content_start = i + 1
                break
            # Non-empty non-title non-volume line before title = skip
            if stripped:
                break

    return chapters
