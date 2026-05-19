from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


CHAPTER_TITLE_RE = re.compile(
    r"^(?:#{1,6}[ \t]+)?(第[0-9０-９]+章[^\r\n]*)[ \t]*#*[ \t]*$"
)
FENCE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})")
CJK_RE = re.compile(r"[\u4e00-\u9fff]")


@dataclass(frozen=True)
class ChapterSpan:
    title: str
    heading_line: int
    content_start_line: int
    end_line: int
    content: str


def _split_lines(markdown: str) -> list[str]:
    return markdown.splitlines(keepends=True)


def _strip_line_ending(line: str) -> str:
    if line.endswith("\r\n"):
        return line[:-2]
    if line.endswith("\n") or line.endswith("\r"):
        return line[:-1]
    return line


def split_chapter_spans(markdown: str) -> list[ChapterSpan]:
    lines = _split_lines(markdown)
    headings: list[tuple[int, str]] = []
    in_fence = False
    active_fence_char = ""
    active_fence_len = 0

    for line_number, raw_line in enumerate(lines, start=1):
        line = _strip_line_ending(raw_line)
        fence_match = FENCE_RE.match(line)
        if fence_match:
            fence_marker = fence_match.group(1)
            fence_char = fence_marker[0]
            fence_len = len(fence_marker)
            if not in_fence:
                in_fence = True
                active_fence_char = fence_char
                active_fence_len = fence_len
            elif fence_char == active_fence_char and fence_len >= active_fence_len:
                in_fence = False
                active_fence_char = ""
                active_fence_len = 0
            continue

        if in_fence:
            continue

        title_match = CHAPTER_TITLE_RE.match(line.strip())
        if title_match:
            headings.append((line_number, title_match.group(1).strip()))

    spans: list[ChapterSpan] = []
    for index, (heading_line, title) in enumerate(headings):
        next_heading_line = headings[index + 1][0] if index + 1 < len(headings) else len(lines) + 1
        content_start_line = heading_line + 1
        end_line = next_heading_line - 1
        content = "".join(lines[content_start_line - 1 : end_line])
        spans.append(
            ChapterSpan(
                title=title,
                heading_line=heading_line,
                content_start_line=content_start_line,
                end_line=end_line,
                content=content,
            )
        )
    return spans


def count_text_units(text: str) -> dict[str, int]:
    return {
        "chars": len(text),
        "non_whitespace_chars": len(re.sub(r"\s+", "", text)),
        "cjk_chars": len(CJK_RE.findall(text)),
        "line_count": len(text.splitlines()),
    }


def measure_chapter_lengths(
    markdown: str,
    *,
    min_chars: int = 2200,
    target_chars: int = 2500,
    max_chars: int = 3200,
) -> dict[str, Any]:
    chapters: list[dict[str, Any]] = []
    for span in split_chapter_spans(markdown):
        counts = count_text_units(span.content)
        non_whitespace_chars = counts["non_whitespace_chars"]
        below_min = non_whitespace_chars < min_chars
        below_target = non_whitespace_chars < target_chars
        above_max = non_whitespace_chars > max_chars
        chapters.append(
            {
                "title": span.title,
                "heading_line": span.heading_line,
                "content_start_line": span.content_start_line,
                "end_line": span.end_line,
                **counts,
                "min_chars": min_chars,
                "target_chars": target_chars,
                "max_chars": max_chars,
                "below_min": below_min,
                "below_target": below_target,
                "above_max": above_max,
                "deficit_to_min": max(0, min_chars - non_whitespace_chars),
                "deficit_to_target": max(0, target_chars - non_whitespace_chars),
                "excess_over_max": max(0, non_whitespace_chars - max_chars),
                "status": "under_min" if below_min else "over_max" if above_max else "ok",
            }
        )

    return {
        "ok": bool(chapters) and all(not chapter["below_min"] for chapter in chapters),
        "chapter_count": len(chapters),
        "min_chars": min_chars,
        "target_chars": target_chars,
        "max_chars": max_chars,
        "chapters": chapters,
        "under_min_count": sum(1 for chapter in chapters if chapter["below_min"]),
        "below_target_count": sum(1 for chapter in chapters if chapter["below_target"]),
        "over_max_count": sum(1 for chapter in chapters if chapter["above_max"]),
        "total_non_whitespace_chars": sum(chapter["non_whitespace_chars"] for chapter in chapters),
        "total_cjk_chars": sum(chapter["cjk_chars"] for chapter in chapters),
    }
