from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import re
from typing import Any, Iterable


ATX_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
FENCE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})")


class MarkdownSectionError(ValueError):
    pass


class MarkdownSectionNotFoundError(MarkdownSectionError):
    pass


class MarkdownSectionAmbiguousError(MarkdownSectionError):
    pass


class MarkdownPatchApplyError(MarkdownSectionError):
    pass


@dataclass(frozen=True)
class MarkdownSection:
    title: str
    level: int
    heading_line: int
    content_start_line: int
    end_line: int
    section_path: tuple[str, ...]
    raw_section_path: tuple[str, ...]
    ordinal: int

    @property
    def child_count(self) -> int:
        return len(self.section_path) - 1

    def to_outline_item(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "level": self.level,
            "section_path": list(self.section_path),
            "raw_section_path": list(self.raw_section_path),
            "heading_line": self.heading_line,
            "content_start_line": self.content_start_line,
            "end_line": self.end_line,
            "child_count": self.child_count,
            "ordinal": self.ordinal,
        }


def _split_lines(markdown: str) -> list[str]:
    return markdown.splitlines(keepends=True)


def _detect_frontmatter_end(lines: list[str]) -> int:
    if not lines:
        return 0
    first_line = lines[0].lstrip("\ufeff")
    if first_line.strip() != "---":
        return 0

    for index in range(1, len(lines)):
        marker = lines[index].strip()
        if marker in {"---", "..."}:
            return index + 1
    return 0


def _strip_trailing_line_ending(line: str) -> str:
    if line.endswith("\r\n"):
        return line[:-2]
    if line.endswith("\n") or line.endswith("\r"):
        return line[:-1]
    return line


def _normalize_path_tokens(section_path: Iterable[Any]) -> tuple[str, ...]:
    tokens: list[str] = []
    for raw in section_path:
        if not isinstance(raw, str) or not raw.strip():
            raise MarkdownSectionError("section_path must contain non-empty strings")
        tokens.append(raw.strip())
    if not tokens:
        raise MarkdownSectionError("section_path is required")
    return tuple(tokens)


def parse_markdown_sections(markdown: str) -> list[MarkdownSection]:
    lines = _split_lines(markdown)
    frontmatter_end = _detect_frontmatter_end(lines)
    sections: list[MarkdownSection] = []
    stack: list[dict[str, Any]] = []
    sibling_counts: dict[tuple[str, ...], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    in_fence = False
    active_fence_char = ""
    active_fence_len = 0

    for line_number in range(frontmatter_end + 1, len(lines) + 1):
        raw_line = _strip_trailing_line_ending(lines[line_number - 1])
        fence_match = FENCE_RE.match(raw_line)
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

        heading_match = ATX_HEADING_RE.match(raw_line)
        if not heading_match:
            continue

        level = len(heading_match.group(1))
        title = heading_match.group(2).strip()
        while stack and stack[-1]["level"] >= level:
            stack.pop()

        parent_raw_path = tuple(entry["raw_title"] for entry in stack)
        sibling_counts[parent_raw_path][title] += 1
        ordinal = sibling_counts[parent_raw_path][title]

        canonical_title = title if ordinal == 1 else f"{title} [{ordinal}]"
        section = MarkdownSection(
            title=title,
            level=level,
            heading_line=line_number,
            content_start_line=line_number + 1,
            end_line=len(lines),
            raw_section_path=parent_raw_path + (title,),
            section_path=tuple(entry["canonical_title"] for entry in stack) + (canonical_title,),
            ordinal=ordinal,
        )
        sections.append(section)
        stack.append(
            {
                "level": level,
                "raw_title": title,
                "canonical_title": canonical_title,
            }
        )

    if not sections:
        return []

    bounded: list[MarkdownSection] = []
    for index, section in enumerate(sections):
        end_line = len(lines)
        for next_section in sections[index + 1 :]:
            if next_section.level <= section.level:
                end_line = next_section.heading_line - 1
                break
        bounded.append(
            MarkdownSection(
                title=section.title,
                level=section.level,
                heading_line=section.heading_line,
                content_start_line=section.content_start_line,
                end_line=end_line,
                raw_section_path=section.raw_section_path,
                section_path=section.section_path,
                ordinal=section.ordinal,
            )
        )
    return bounded


def build_markdown_outline(markdown: str) -> list[dict[str, Any]]:
    return [section.to_outline_item() for section in parse_markdown_sections(markdown)]


def _matching_sections(markdown: str, section_path: tuple[str, ...]) -> list[MarkdownSection]:
    sections = parse_markdown_sections(markdown)
    raw_matches = [section for section in sections if section.raw_section_path == section_path]
    if raw_matches:
        return raw_matches
    return [section for section in sections if section.section_path == section_path]


def find_markdown_section(markdown: str, section_path: Iterable[Any]) -> MarkdownSection:
    normalized_path = _normalize_path_tokens(section_path)
    matches = _matching_sections(markdown, normalized_path)
    if not matches:
        raise MarkdownSectionNotFoundError(f"section_path not found: {' > '.join(normalized_path)}")
    if len(matches) > 1:
        raise MarkdownSectionAmbiguousError(
            f"section_path is ambiguous; use canonical path from outline: {' > '.join(normalized_path)}"
        )
    return matches[0]


def extract_markdown_section(markdown: str, section_path: Iterable[Any]) -> dict[str, Any]:
    lines = _split_lines(markdown)
    section = find_markdown_section(markdown, section_path)
    heading = "".join(lines[section.heading_line - 1 : section.heading_line])
    body = "".join(lines[section.content_start_line - 1 : section.end_line])
    full_markdown = "".join(lines[section.heading_line - 1 : section.end_line])
    return {
        "title": section.title,
        "level": section.level,
        "section_path": list(section.section_path),
        "raw_section_path": list(section.raw_section_path),
        "heading_line": section.heading_line,
        "content_start_line": section.content_start_line,
        "end_line": section.end_line,
        "heading": heading,
        "content": body,
        "content_length": len(body),
        "section_markdown": full_markdown,
        "ordinal": section.ordinal,
    }


def _normalize_patch_block(block: str, *, prefix_has_trailing_newline: bool, suffix_exists: bool) -> str:
    normalized = block or ""
    if normalized and prefix_has_trailing_newline is False and not normalized.startswith("\n"):
        normalized = "\n" + normalized
    if normalized and suffix_exists and not normalized.endswith("\n"):
        normalized = normalized + "\n"
    return normalized


def replace_markdown_section(markdown: str, section_path: Iterable[Any], replacement_markdown: str) -> str:
    lines = _split_lines(markdown)
    section = find_markdown_section(markdown, section_path)
    start_index = section.heading_line - 1
    end_index = section.end_line
    prefix = lines[:start_index]
    suffix = lines[end_index:]
    replacement = _normalize_patch_block(
        replacement_markdown,
        prefix_has_trailing_newline=(not prefix or prefix[-1].endswith("\n")),
        suffix_exists=bool(suffix),
    )
    return "".join(prefix) + replacement + "".join(suffix)


def append_under_markdown_section(markdown: str, section_path: Iterable[Any], appended_markdown: str) -> str:
    lines = _split_lines(markdown)
    section = find_markdown_section(markdown, section_path)
    insert_index = section.end_line
    prefix = lines[:insert_index]
    suffix = lines[insert_index:]
    appended = _normalize_patch_block(
        appended_markdown,
        prefix_has_trailing_newline=(not prefix or prefix[-1].endswith("\n")),
        suffix_exists=bool(suffix),
    )
    return "".join(prefix) + appended + "".join(suffix)


def apply_markdown_patch(markdown: str, write_item: dict[str, Any]) -> str:
    if not isinstance(write_item, dict):
        raise MarkdownPatchApplyError("write_item must be an object")

    op = write_item.get("op")
    section_path = write_item.get("section_path")
    content = write_item.get("content")
    if not isinstance(content, str):
        raise MarkdownPatchApplyError("write_item.content must be a string")

    if op == "replace_section":
        return replace_markdown_section(markdown, section_path, content)
    if op == "append_under_section":
        return append_under_markdown_section(markdown, section_path, content)

    raise MarkdownPatchApplyError("unsupported markdown patch op")


def replay_markdown_patch(latest_markdown: str, write_item: dict[str, Any]) -> str:
    return apply_markdown_patch(latest_markdown, write_item)
