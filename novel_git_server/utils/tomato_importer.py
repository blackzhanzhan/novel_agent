from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any


BOOK_INFO_FILE_RE = re.compile(r"^0+[_-].*\.txt$", re.IGNORECASE)
CHAPTER_FILE_RE = re.compile(r"^(?P<index>\d+)[_-](?P<title>.+)\.txt$", re.IGNORECASE)
TITLE_LINE_RE = re.compile(
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
INVALID_FILENAME_CHARS = set('\\/:*?"<>|')
SHORT_CHAPTER_WARNING_CHARS = 300
SHORT_CHAPTER_BLOCK_CHARS = 80
FRAGMENTED_MIN_LINES = 20
FRAGMENTED_MAX_AVG_CHARS_PER_LINE = 18
DOWNLOAD_RESIDUE_RE = re.compile(
    r"(?:"
    r"本书.*(?:来自|下载)"
    r"|小说下载器"
    r"|下载地址"
    r"|请收藏"
    r"|www\."
    r"|https?://"
    r")",
    re.IGNORECASE,
)


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")


def _trim_outer_blank_lines(lines: list[str]) -> list[str]:
    start = 0
    end = len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return lines[start:end]


def _normalize_title_for_compare(title: str) -> str:
    return re.sub(r"\s+", "", title.strip().lstrip("#").strip()).casefold()


def _safe_title(title: str) -> str:
    cleaned_chars: list[str] = []
    for ch in title.strip():
        if ch in INVALID_FILENAME_CHARS or ch.isspace():
            cleaned_chars.append("_")
        else:
            cleaned_chars.append(ch)
    cleaned = "".join(cleaned_chars).strip("._")
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return (cleaned or "chapter")[:80]


def _parse_metadata(text: str) -> dict[str, str]:
    metadata: dict[str, str] = {}
    key_map = {
        "书名": "book_name",
        "作者": "author",
        "状态": "status",
        "评分": "score",
        "字数": "word_count",
        "章节": "chapter_count",
        "分类": "category",
        "标签": "tags",
        "在读": "reader_count",
        "简介": "description",
    }
    lines = _normalize_newlines(text).split("\n")
    collecting_description = False
    description_lines: list[str] = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            if collecting_description and description_lines:
                description_lines.append("")
            continue
        if collecting_description:
            description_lines.append(line)
            continue
        if "=" in line and line.lower().startswith("book_id="):
            metadata["source_book_id"] = line.split("=", 1)[1].strip()
            continue
        if "：" not in line:
            continue
        key, value = line.split("：", 1)
        normalized_key = key.strip()
        mapped_key = key_map.get(normalized_key)
        if not mapped_key:
            continue
        if mapped_key == "description":
            collecting_description = True
            if value.strip():
                description_lines.append(value.strip())
        else:
            metadata[mapped_key] = value.strip()
    if description_lines:
        metadata["description"] = "\n".join(description_lines).strip()
    return metadata


def _resolve_source_dir(source_dir: str | os.PathLike[str], allowed_root: str | os.PathLike[str] | None) -> Path:
    source = Path(source_dir).expanduser().resolve()
    if not source.is_dir():
        raise ValueError(f"source_dir is not a readable directory: {source}")

    if allowed_root is not None:
        root = Path(allowed_root).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"allowed_root is not a readable directory: {root}")
        if os.path.commonpath([str(source), str(root)]) != str(root):
            raise ValueError("source_dir escapes allowed_root")

    return source


def _chapter_sort_key(path: Path) -> tuple[int, str]:
    match = CHAPTER_FILE_RE.match(path.name)
    if not match:
        return (10**9, path.name)
    return (int(match.group("index")), path.name)


def _discover_files(source_dir: Path) -> tuple[Path | None, list[Path], list[dict[str, Any]]]:
    warnings: list[dict[str, Any]] = []
    metadata_file: Path | None = None
    chapter_files: list[Path] = []

    for path in sorted(source_dir.iterdir(), key=lambda p: p.name):
        if not path.is_file() or path.suffix.lower() != ".txt":
            continue
        if BOOK_INFO_FILE_RE.match(path.name):
            metadata_file = path
            continue
        if not CHAPTER_FILE_RE.match(path.name):
            warnings.append(
                {
                    "code": "UNRECOGNIZED_TXT_FILE",
                    "message": "txt file does not match Tomato bulk chapter filename pattern",
                    "file": path.name,
                }
            )
            continue
        chapter_files.append(path)

    chapter_files.sort(key=_chapter_sort_key)
    return metadata_file, chapter_files, warnings


def _derive_chapter_title(path: Path, text: str) -> tuple[int, str, list[str]]:
    match = CHAPTER_FILE_RE.match(path.name)
    if not match:
        raise ValueError(f"chapter filename is invalid: {path.name}")
    index = int(match.group("index"))
    file_title = match.group("title").strip()
    file_title = re.sub(r"\.txt$", "", file_title, flags=re.IGNORECASE).strip()

    warnings: list[str] = []
    lines = _trim_outer_blank_lines(_normalize_newlines(text).split("\n"))
    first_non_empty = next((line.strip() for line in lines if line.strip()), "")
    if first_non_empty and TITLE_LINE_RE.match(first_non_empty):
        return index, first_non_empty, warnings
    if first_non_empty and _normalize_title_for_compare(first_non_empty) == _normalize_title_for_compare(file_title):
        return index, first_non_empty, warnings
    if not file_title:
        warnings.append("MISSING_TITLE")
        return index, f"第{index}章", warnings
    return index, file_title, warnings


def _body_without_duplicate_title(text: str, title: str) -> str:
    lines = _trim_outer_blank_lines(_normalize_newlines(text).split("\n"))
    first_non_empty_idx = next((idx for idx, line in enumerate(lines) if line.strip()), None)
    if first_non_empty_idx is None:
        return ""

    first_line = lines[first_non_empty_idx].strip()
    if _normalize_title_for_compare(first_line) == _normalize_title_for_compare(title):
        del lines[first_non_empty_idx]
        while first_non_empty_idx < len(lines) and not lines[first_non_empty_idx].strip():
            del lines[first_non_empty_idx]

    return "\n".join(_trim_outer_blank_lines(lines)).rstrip()


def _markdown_for_chapter(title: str, body: str) -> str:
    if body:
        return f"# {title}\n\n{body.rstrip()}\n"
    return f"# {title}\n"


def _text_stats(text: str) -> dict[str, int]:
    non_whitespace = re.sub(r"\s+", "", text)
    return {
        "chars": len(text),
        "non_whitespace_chars": len(non_whitespace),
        "line_count": len(text.splitlines()),
    }


def _add_issue(issues: list[dict[str, Any]], severity: str, code: str, message: str, **extra: Any) -> None:
    issues.append({"severity": severity, "code": code, "message": message, **extra})


def _evaluate_quality(chapters: list[dict[str, Any]]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []

    if not chapters:
        _add_issue(issues, "block", "NO_CHAPTERS", "没有解析到任何章节。")

    seen_indices: dict[int, str] = {}
    seen_hashes: dict[str, str] = {}
    indices = [chapter["index"] for chapter in chapters]
    for chapter in chapters:
        index = chapter["index"]
        title = chapter["title"]
        label = f"{index:04d} {title}"
        non_ws = chapter["non_whitespace_chars"]
        line_count = chapter["line_count"]

        if index in seen_indices:
            _add_issue(
                issues,
                "block",
                "DUPLICATE_CHAPTER_INDEX",
                "章节序号重复。",
                chapter=label,
                first=seen_indices[index],
            )
        else:
            seen_indices[index] = label

        if not chapter["body"].strip():
            _add_issue(issues, "block", "EMPTY_CHAPTER", "章节正文为空。", chapter=label)
        elif non_ws < SHORT_CHAPTER_BLOCK_CHARS:
            _add_issue(
                issues,
                "block",
                "TOO_SHORT_CHAPTER",
                "章节正文过短，疑似下载失败或切章错误。",
                chapter=label,
                non_whitespace_chars=non_ws,
            )
        elif non_ws < SHORT_CHAPTER_WARNING_CHARS:
            _add_issue(
                issues,
                "warn",
                "SHORT_CHAPTER",
                "章节正文偏短，请人工确认是否为序章/番外/短章。",
                chapter=label,
                non_whitespace_chars=non_ws,
            )

        if chapter["content_hash"] in seen_hashes:
            _add_issue(
                issues,
                "block",
                "DUPLICATE_CHAPTER_CONTENT",
                "章节正文 hash 重复，疑似重复章节。",
                chapter=label,
                first=seen_hashes[chapter["content_hash"]],
            )
        else:
            seen_hashes[chapter["content_hash"]] = label

        avg_chars_per_line = non_ws / line_count if line_count else non_ws
        if line_count >= FRAGMENTED_MIN_LINES and avg_chars_per_line < FRAGMENTED_MAX_AVG_CHARS_PER_LINE:
            _add_issue(
                issues,
                "block",
                "HIGH_LINE_FRAGMENTATION",
                "章节行数密度异常，疑似每句或每小段被硬拆行。",
                chapter=label,
                line_count=line_count,
                non_whitespace_chars=non_ws,
                avg_chars_per_line=round(avg_chars_per_line, 2),
            )

        if DOWNLOAD_RESIDUE_RE.search(chapter["body"]):
            _add_issue(
                issues,
                "block",
                "DOWNLOAD_RESIDUE",
                "章节正文存在疑似下载器/广告残留。",
                chapter=label,
            )

    if indices:
        expected = list(range(min(indices), max(indices) + 1))
        missing = sorted(set(expected) - set(indices))
        if missing:
            _add_issue(
                issues,
                "block",
                "CHAPTER_INDEX_GAP",
                "章节序号不连续。",
                missing_indices=missing,
            )

    block_count = sum(1 for issue in issues if issue["severity"] == "block")
    warn_count = sum(1 for issue in issues if issue["severity"] == "warn")
    return {
        "can_confirm": block_count == 0,
        "risk_level": "block" if block_count else "warn" if warn_count else "ok",
        "block_count": block_count,
        "warn_count": warn_count,
        "issues": issues,
    }


def parse_tomato_bulk_export(
    source_dir: str | os.PathLike[str],
    *,
    allowed_root: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Parse a Tomato-Novel-Downloader txt+bulk_files export directory.

    The parser intentionally preserves the upstream reading layout. It only
    normalizes line endings, removes duplicated leading title lines, and wraps
    each chapter in a Markdown H1 so downstream storage can read it as `.md`.
    """

    source = _resolve_source_dir(source_dir, allowed_root)
    metadata_file, chapter_files, warnings = _discover_files(source)

    metadata: dict[str, str] = {}
    if metadata_file is not None:
        metadata = _parse_metadata(_read_text(metadata_file))

    chapters: list[dict[str, Any]] = []
    for chapter_file in chapter_files:
        raw_text = _read_text(chapter_file)
        index, title, title_warnings = _derive_chapter_title(chapter_file, raw_text)
        body = _body_without_duplicate_title(raw_text, title)
        markdown = _markdown_for_chapter(title, body)
        body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
        chapter_stats = _text_stats(body)
        chapters.append(
            {
                "index": index,
                "title": title,
                "safe_title": _safe_title(title),
                "source_file": chapter_file.name,
                "target_file": f"{index:04d}_{_safe_title(title)}.md",
                "body": body,
                "markdown": markdown,
                "content_hash": body_hash,
                "warnings": title_warnings,
                **chapter_stats,
            }
        )

    report = {
        "source_dir": str(source),
        "metadata_file": metadata_file.name if metadata_file else None,
        "book_name": metadata.get("book_name") or source.name,
        "chapter_count": len(chapters),
        "total_non_whitespace_chars": sum(chapter["non_whitespace_chars"] for chapter in chapters),
        "warnings": warnings,
        "source_files": [chapter["source_file"] for chapter in chapters],
    }
    quality = _evaluate_quality(chapters)

    return {
        "source_dir": str(source),
        "book_name": report["book_name"],
        "metadata": metadata,
        "chapters": chapters,
        "report": report,
        "quality": quality,
    }
