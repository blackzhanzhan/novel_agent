import glob
import math
import os
from bisect import bisect_right
from pathlib import Path
from typing import Any, Callable

from flask import Blueprint, jsonify

from utils.book_storage import ensure_book_layout, get_book_paths
from utils.chapter_length import measure_chapter_lengths
from utils.domain_rules import validate_domain_rules
from utils.style_diagnostics import generate_style_diagnostics

DEFAULT_HIGHLIGHT_CONTEXT_SENTENCES = 2
MAX_HIGHLIGHT_CONTEXT_SENTENCES = 6
MAX_HIGHLIGHT_KEYWORDS = 20
MAX_TOTAL_HIGHLIGHT_CHARS = 1000
SENTENCE_BOUNDARIES = "。！？\n"
MAX_SENTENCE_BOUNDARY_SCAN_CHARS = 200
MAX_INLINE_DOMAIN_VALIDATION_CHARS = 50000


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _resolve_chapter_path(chapters_dir: str, chapter_index: int) -> str | None:
    prefix = f"{chapter_index:04d}"
    candidates = sorted(glob.glob(os.path.join(chapters_dir, f"{prefix}*.md")))
    if candidates:
        return candidates[0]
    fallback = os.path.join(chapters_dir, f"{prefix}.md")
    if os.path.exists(fallback):
        return fallback
    return None


def _chapter_index_from_name(name: str) -> int | None:
    token = name.split("_", 1)[0].split(".", 1)[0]
    return _coerce_int(token)


def _resolve_book_markdown_file(book_dir: str, file_name: Any) -> tuple[str | None, str | None]:
    raw_file_name = str(file_name or "chapter_draft.md").strip().replace("\\", "/")
    if not raw_file_name:
        return None, "file_name is required"
    if raw_file_name.startswith("/") or raw_file_name.startswith("../") or "/../" in raw_file_name:
        return None, "file_name must stay inside the book directory"
    if raw_file_name == ".." or raw_file_name.startswith(".."):
        return None, "file_name must stay inside the book directory"
    if not raw_file_name.lower().endswith(".md"):
        return None, "file_name must point to a markdown file"

    abs_book_dir = os.path.abspath(book_dir)
    abs_path = os.path.abspath(os.path.join(abs_book_dir, raw_file_name))
    if os.path.commonpath([abs_path, abs_book_dir]) != abs_book_dir:
        return None, "file_name must stay inside the book directory"
    return abs_path, None


def _normalize_keywords(raw_keywords: Any) -> tuple[list[str] | None, str | None]:
    if not isinstance(raw_keywords, list):
        return None, "keywords must be a list of strings"
    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw_keywords:
        token = item if isinstance(item, str) else str(item)
        token = token.strip()
        if not token:
            continue
        folded = token.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        normalized.append(token)
    if not normalized:
        return None, "keywords must contain at least one non-empty string"
    if len(normalized) > MAX_HIGHLIGHT_KEYWORDS:
        return None, f"keywords cannot exceed {MAX_HIGHLIGHT_KEYWORDS} items"
    return normalized, None


def _normalize_context_sentences(raw_context_sentences: Any) -> tuple[int | None, str | None]:
    if raw_context_sentences is None:
        return DEFAULT_HIGHLIGHT_CONTEXT_SENTENCES, None
    context_sentences = _coerce_int(raw_context_sentences)
    if context_sentences is None:
        return None, "context_sentences must be an integer"
    if context_sentences < 0:
        return None, "context_sentences must be a non-negative integer"
    if context_sentences > MAX_HIGHLIGHT_CONTEXT_SENTENCES:
        return None, f"context_sentences cannot exceed {MAX_HIGHLIGHT_CONTEXT_SENTENCES}"
    return context_sentences, None


def _build_keyword_forms(keywords: list[str]) -> list[tuple[str, str]]:
    return [(keyword, keyword.casefold()) for keyword in keywords]


def _scan_text_keyword_hits(text: str, keyword_forms: list[tuple[str, str]]) -> list[dict[str, Any]]:
    folded_text = text.casefold()
    raw_hits: list[dict[str, Any]] = []
    for keyword, folded_keyword in keyword_forms:
        if not folded_keyword:
            continue
        cursor = 0
        step = len(folded_keyword)
        while cursor < len(folded_text):
            hit_start = folded_text.find(folded_keyword, cursor)
            if hit_start < 0:
                break
            hit_end = hit_start + step
            raw_hits.append(
                {
                    "start_char": hit_start,
                    "end_char": hit_end,
                    "keyword": keyword,
                }
            )
            cursor = hit_start + step

    raw_hits.sort(key=lambda item: (item["start_char"], item["end_char"], item["keyword"]))
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[int, int, str]] = set()
    for hit in raw_hits:
        key = (hit["start_char"], hit["end_char"], hit["keyword"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(hit)
    return deduped


def _scan_left_sentence_boundary(text: str, start_idx: int) -> int:
    if start_idx <= 0:
        return 0
    scan_floor = max(0, start_idx - MAX_SENTENCE_BOUNDARY_SCAN_CHARS)
    for idx in range(start_idx - 1, scan_floor - 1, -1):
        if text[idx] in SENTENCE_BOUNDARIES:
            return idx + 1
    return scan_floor


def _scan_right_sentence_boundary(text: str, end_idx: int) -> int:
    if end_idx >= len(text):
        return len(text)
    scan_ceiling = min(len(text), end_idx + MAX_SENTENCE_BOUNDARY_SCAN_CHARS)
    for idx in range(end_idx, scan_ceiling):
        if text[idx] in SENTENCE_BOUNDARIES:
            return idx + 1
    return scan_ceiling


def _expand_hit_to_sentence_window(
    text: str, hit_start: int, hit_end: int, context_sentences: int
) -> tuple[int, int]:
    left = _scan_left_sentence_boundary(text, hit_start)
    right = _scan_right_sentence_boundary(text, hit_end)
    for _ in range(context_sentences):
        left = _scan_left_sentence_boundary(text, left)
        right = _scan_right_sentence_boundary(text, right)
    return left, right


def _build_sentence_windows_from_hits(
    text: str, hit_rows: list[dict[str, Any]], context_sentences: int
) -> list[dict[str, Any]]:
    windows: list[dict[str, Any]] = []
    for hit in hit_rows:
        start_char, end_char = _expand_hit_to_sentence_window(
            text, hit["start_char"], hit["end_char"], context_sentences
        )
        windows.append(
            {
                "start_char": start_char,
                "end_char": end_char,
                "hit_offsets": [hit["start_char"]],
                "hit_keywords": [hit["keyword"]],
            }
        )
    return windows


def _newline_offsets(text: str) -> list[int]:
    return [idx for idx, ch in enumerate(text) if ch == "\n"]


def _line_no_for_offset(newline_positions: list[int], offset: int) -> int:
    return bisect_right(newline_positions, offset) + 1


def _merge_char_windows(hit_windows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for window in hit_windows:
        start_char = window["start_char"]
        end_char = window["end_char"]
        hit_offsets = list(window["hit_offsets"])
        hit_keywords = list(window["hit_keywords"])

        if not merged:
            merged.append(
                {
                    "start_char": start_char,
                    "end_char": end_char,
                    "hit_offsets": hit_offsets,
                    "hit_keywords": hit_keywords,
                }
            )
            continue

        prev = merged[-1]
        if start_char <= prev["end_char"] + 1:
            prev["end_char"] = max(prev["end_char"], end_char)
            for offset in hit_offsets:
                if offset not in prev["hit_offsets"]:
                    prev["hit_offsets"].append(offset)
            for keyword in hit_keywords:
                if keyword not in prev["hit_keywords"]:
                    prev["hit_keywords"].append(keyword)
            continue

        merged.append(
            {
                "start_char": start_char,
                "end_char": end_char,
                "hit_offsets": hit_offsets,
                "hit_keywords": hit_keywords,
            }
        )

    for window in merged:
        window["hit_offsets"].sort()

    return merged


def _center_crop_interval(start_char: int, end_char: int, anchor_char: int, budget: int) -> tuple[int, int]:
    interval_len = end_char - start_char
    if budget <= 0:
        return start_char, start_char
    if interval_len <= budget:
        return start_char, end_char

    half = budget // 2
    cropped_start = max(start_char, anchor_char - half)
    cropped_end = cropped_start + budget
    if cropped_end > end_char:
        cropped_end = end_char
        cropped_start = end_char - budget
    if cropped_start < start_char:
        cropped_start = start_char
    return cropped_start, cropped_end


def _build_char_snippets_with_budget(
    text: str,
    merged_windows: list[dict[str, Any]],
    max_total_chars: int,
    newline_positions: list[int] | None = None,
) -> tuple[list[dict[str, Any]], int, bool]:
    snippets: list[dict[str, Any]] = []
    consumed_chars = 0
    truncated = False
    line_map = newline_positions if newline_positions is not None else _newline_offsets(text)

    prioritized_windows = sorted(
        merged_windows,
        key=lambda window: (-len(window["hit_offsets"]), -len(window["hit_keywords"]), window["start_char"]),
    )

    for window in prioritized_windows:
        remaining = max_total_chars - consumed_chars
        if remaining <= 0:
            truncated = True
            break

        start_char = window["start_char"]
        end_char = window["end_char"]
        interval_len = end_char - start_char
        if interval_len > remaining:
            anchor = window["hit_offsets"][len(window["hit_offsets"]) // 2] if window["hit_offsets"] else start_char
            start_char, end_char = _center_crop_interval(start_char, end_char, anchor, remaining)
            truncated = True

        snippets.append(
            {
                "start_char": start_char,
                "end_char": end_char,
                "hit_offsets": [offset for offset in window["hit_offsets"] if start_char <= offset < end_char],
                "hit_line_numbers": sorted(
                    {
                        _line_no_for_offset(line_map, offset)
                        for offset in window["hit_offsets"]
                        if start_char <= offset < end_char
                    }
                ),
                "hit_keywords": window["hit_keywords"],
                "content": text[start_char:end_char],
            }
        )
        consumed_chars += end_char - start_char
        if truncated:
            break

    snippets.sort(key=lambda snippet: snippet["start_char"])
    return snippets, consumed_chars, truncated


def main(arg1: list) -> dict:
    """
    自适应双约束算法：
    1. 性能：每包尽量 10 章。
    2. 安全：总包数严控在 25 以内 。
    """
    # 1. 拼接文本 [cite: 1, 2]
    try:
        full_text = "\n".join([str(p) for p in arg1 if p]) if isinstance(arg1, list) else str(arg1)
    except Exception:
        return {"total_chapters": 0, "data": []}

    # 2. 精准切分 [cite: 10, 16]
    DELIMITER = "|||CHAPTER_START|||"
    raw_chunks = [c.strip() for c in full_text.split(DELIMITER) if c.strip()]
    total = len(raw_chunks)

    if total == 0:
        return {"total_chapters": 0, "data": []}

    # 3. 自适应逻辑：在 10 章/包和 25 总包数之间取最优解
    # 如果 total < 250，batch_size 为 10；如果 > 250，动态增加步长
    batch_size = max(10, math.ceil(total / 25))

    bundled_data = []
    for i in range(0, total, batch_size):
        batch = raw_chunks[i : i + batch_size]
        batch_chapters = []

        for content in batch:
            lines = content.splitlines()
            title = lines[0].strip() if lines else "未命名章节"
            body = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""

            # 40万字符上限保护
            if len(body) > 300000:
                body = body[:300000] + "...(Truncated)"

            batch_chapters.append({"title": title, "content": body})

        bundled_data.append(
            {
                "range": f"CH{i+1}-{min(i+batch_size, total)}",
                "chapters": batch_chapters,
            }
        )

    # 4. 精简返回，只保留核心数据
    return {
        "total_chapters": total,
        "data": bundled_data,
    }


def create_blueprint(
    *,
    storage_root: str,
    parse_json_payload: Callable[[list[str] | None], tuple[dict | None, tuple | None]],
    require_book_id: Callable[[dict | None], tuple[str | None, tuple | None]],
    json_error: Callable[[str, str, int], tuple],
) -> Blueprint:
    bp = Blueprint("tools", __name__)

    @bp.post("/tools/read_chapter")
    def read_chapter():
        payload, err = parse_json_payload(["chapter_index"])
        if err:
            return err

        book_id, book_err = require_book_id(payload)
        if book_err:
            return book_err

        chapter_index = _coerce_int(payload.get("chapter_index"))
        if chapter_index is None or chapter_index < 0:
            return json_error("MISSING_FIELD", "chapter_index must be a non-negative integer", 400)

        paths = ensure_book_layout(book_id, storage_root)
        chapter_path = _resolve_chapter_path(paths["chapters_dir"], chapter_index)
        if not chapter_path:
            return json_error("INVALID_PAYLOAD", "chapter not found", 404)

        with open(chapter_path, "r", encoding="utf-8") as f:
            content = f.read()

        return (
            jsonify(
                {
                    "status": "success",
                    "book_id": book_id,
                    "chapter_index": chapter_index,
                    "file_path": chapter_path,
                    "content": content,
                }
            ),
            200,
        )

    @bp.post("/tools/extract_chapter_highlights")
    def extract_chapter_highlights():
        payload, err = parse_json_payload(["chapter_index", "keywords"])
        if err:
            return err

        book_id, book_err = require_book_id(payload)
        if book_err:
            return book_err

        chapter_index = _coerce_int(payload.get("chapter_index"))
        if chapter_index is None or chapter_index < 0:
            return json_error("MISSING_FIELD", "chapter_index must be a non-negative integer", 400)

        keywords, keywords_err = _normalize_keywords(payload.get("keywords"))
        if keywords_err:
            return json_error("INVALID_PAYLOAD", keywords_err, 400)
        assert keywords is not None

        raw_context_sentences = payload.get("context_sentences")
        if raw_context_sentences is None and "context_lines" in payload:
            raw_context_sentences = payload.get("context_lines")
        context_sentences, context_sentences_err = _normalize_context_sentences(raw_context_sentences)
        if context_sentences_err:
            return json_error("INVALID_PAYLOAD", context_sentences_err, 400)
        assert context_sentences is not None

        paths = ensure_book_layout(book_id, storage_root)
        chapter_path = _resolve_chapter_path(paths["chapters_dir"], chapter_index)
        if not chapter_path:
            return json_error("INVALID_PAYLOAD", "chapter not found", 404)

        with open(chapter_path, "r", encoding="utf-8") as f:
            text = f.read()
        newline_positions = _newline_offsets(text)

        keyword_forms = _build_keyword_forms(keywords)
        hit_rows = _scan_text_keyword_hits(text, keyword_forms)
        if not hit_rows:
            return (
                jsonify(
                    {
                        "status": "success",
                        "book_id": book_id,
                        "chapter_index": chapter_index,
                        "file_path": chapter_path,
                        "keywords": keywords,
                        "context_sentences": context_sentences,
                        "total_chars_in_chapter": len(text),
                        "hit_line_count": 0,
                        "hit_count": 0,
                        "snippet_count": 0,
                        "total_chars": 0,
                        "max_total_chars": MAX_TOTAL_HIGHLIGHT_CHARS,
                        "truncated": False,
                        "snippets": [],
                        "message": "未命中关键词，请调整关键词或扩大上下文。",
                    }
                ),
                200,
            )

        windows = _build_sentence_windows_from_hits(text, hit_rows, context_sentences)
        merged_windows = _merge_char_windows(windows)
        snippets, total_chars, truncated = _build_char_snippets_with_budget(
            text, merged_windows, MAX_TOTAL_HIGHLIGHT_CHARS, newline_positions
        )
        hit_line_count = len({_line_no_for_offset(newline_positions, row["start_char"]) for row in hit_rows})

        return (
            jsonify(
                {
                    "status": "success",
                    "book_id": book_id,
                    "chapter_index": chapter_index,
                    "file_path": chapter_path,
                    "keywords": keywords,
                    "context_sentences": context_sentences,
                    "total_chars_in_chapter": len(text),
                    "hit_line_count": hit_line_count,
                    "hit_count": len(hit_rows),
                    "snippet_count": len(snippets),
                    "total_chars": total_chars,
                    "max_total_chars": MAX_TOTAL_HIGHLIGHT_CHARS,
                    "truncated": truncated,
                    "snippets": snippets,
                }
            ),
            200,
        )

    @bp.post("/tools/search_chapter_index")
    def search_chapter_index():
        payload, err = parse_json_payload(["keyword"])
        if err:
            return err

        book_id, book_err = require_book_id(payload)
        if book_err:
            return book_err

        keyword = payload.get("keyword", "")
        if not isinstance(keyword, str):
            keyword = str(keyword)
        keyword = keyword.strip()
        if not keyword:
            return json_error("MISSING_FIELD", "keyword is required", 400)

        paths = ensure_book_layout(book_id, storage_root)
        chapters_dir = paths["chapters_dir"]
        files = sorted(name for name in os.listdir(chapters_dir) if name.lower().endswith(".md"))

        rows = []
        for name in files:
            abs_path = os.path.join(chapters_dir, name)
            if not os.path.isfile(abs_path):
                continue
            with open(abs_path, "r", encoding="utf-8") as f:
                content = f.read()
            hit_count = content.count(keyword)
            chapter_index = _chapter_index_from_name(name)
            rows.append(
                {
                    "chapter_index": chapter_index,
                    "file_name": name,
                    "count": hit_count,
                }
            )

        return (
            jsonify(
                {
                    "status": "success",
                    "book_id": book_id,
                    "keyword": keyword,
                    "hits": rows,
                }
            ),
            200,
        )

    @bp.post("/tools/validate_chapter_lengths")
    def validate_chapter_lengths():
        payload, err = parse_json_payload()
        if err:
            return err

        book_id, book_err = require_book_id(payload)
        if book_err:
            return book_err

        paths = get_book_paths(book_id, storage_root)
        if not os.path.isdir(paths["book_dir"]):
            return json_error("INVALID_PAYLOAD", "book not found", 404)
        file_path, file_err = _resolve_book_markdown_file(paths["book_dir"], payload.get("file_name"))
        if file_err:
            return json_error("INVALID_PAYLOAD", file_err, 400)
        assert file_path is not None
        if not os.path.exists(file_path):
            return json_error("INVALID_PAYLOAD", "markdown file not found", 404)

        min_chars = _coerce_int(payload.get("min_chars")) or 2200
        target_chars = _coerce_int(payload.get("target_chars")) or 2500
        max_chars = _coerce_int(payload.get("max_chars")) or 3200
        if min_chars <= 0 or target_chars <= 0 or max_chars <= 0:
            return json_error("INVALID_PAYLOAD", "min_chars, target_chars, and max_chars must be positive", 400)
        if min_chars > target_chars:
            return json_error("INVALID_PAYLOAD", "min_chars cannot exceed target_chars", 400)
        if target_chars > max_chars:
            return json_error("INVALID_PAYLOAD", "target_chars cannot exceed max_chars", 400)

        with open(file_path, "r", encoding="utf-8") as f:
            markdown = f.read()

        result = measure_chapter_lengths(
            markdown,
            min_chars=min_chars,
            target_chars=target_chars,
            max_chars=max_chars,
        )
        return (
            jsonify(
                {
                    "status": "success",
                    "book_id": book_id,
                    "file_name": os.path.relpath(file_path, paths["book_dir"]).replace("\\", "/"),
                    **result,
                }
            ),
            200,
        )

    @bp.post("/tools/validate_domain_facts")
    def validate_domain_facts():
        payload, err = parse_json_payload()
        if err:
            return err

        book_id, book_err = require_book_id(payload)
        if book_err:
            return book_err

        paths = get_book_paths(book_id, storage_root)
        if not os.path.isdir(paths["book_dir"]):
            return json_error("INVALID_PAYLOAD", "book not found", 404)

        inline_markdown = payload.get("markdown")
        source = "file"
        file_label = "chapter_draft.md"
        if inline_markdown is not None:
            if not isinstance(inline_markdown, str):
                return json_error("INVALID_PAYLOAD", "markdown must be a string", 400)
            if len(inline_markdown) > MAX_INLINE_DOMAIN_VALIDATION_CHARS:
                return json_error(
                    "INVALID_PAYLOAD",
                    f"markdown cannot exceed {MAX_INLINE_DOMAIN_VALIDATION_CHARS} characters",
                    400,
                )
            markdown = inline_markdown
            source = "inline"
            file_label = "__inline_markdown__"
        else:
            file_path, file_err = _resolve_book_markdown_file(paths["book_dir"], payload.get("file_name"))
            if file_err:
                return json_error("INVALID_PAYLOAD", file_err, 400)
            assert file_path is not None
            if not os.path.exists(file_path):
                return json_error("INVALID_PAYLOAD", "markdown file not found", 404)
            with open(file_path, "r", encoding="utf-8") as f:
                markdown = f.read()
            file_label = os.path.relpath(file_path, paths["book_dir"]).replace("\\", "/")

        rules_path, rules_err = _resolve_book_markdown_file(
            paths["book_dir"],
            payload.get("rules_file") or "domain_rules.md",
        )
        if rules_err:
            return json_error("INVALID_PAYLOAD", f"rules_file: {rules_err}", 400)
        assert rules_path is not None
        if not os.path.exists(rules_path):
            return json_error("INVALID_PAYLOAD", "domain rules file not found", 404)

        with open(rules_path, "r", encoding="utf-8") as f:
            rules_markdown = f.read()

        return (
            jsonify(
                {
                    "status": "success",
                    "book_id": book_id,
                    "source": source,
                    "file_name": file_label,
                    "rules_file": os.path.relpath(rules_path, paths["book_dir"]).replace("\\", "/"),
                    **validate_domain_rules(markdown, rules_markdown),
                }
            ),
            200,
        )

    @bp.post("/tools/generate_style_diagnostics")
    def generate_style_diagnostics_tool():
        payload, err = parse_json_payload()
        if err:
            return err

        book_id, book_err = require_book_id(payload)
        if book_err:
            return book_err

        paths = get_book_paths(book_id, storage_root)
        if not os.path.isdir(paths["book_dir"]):
            return json_error("INVALID_PAYLOAD", "book not found", 404)

        source_count = _coerce_int(payload.get("source_count")) or 8
        if source_count <= 0:
            return json_error("INVALID_PAYLOAD", "source_count must be positive", 400)
        if source_count > 30:
            return json_error("INVALID_PAYLOAD", "source_count cannot exceed 30", 400)

        draft_file = payload.get("draft_file") or "chapter_draft.md"
        _draft_path, draft_err = _resolve_book_markdown_file(paths["book_dir"], draft_file)
        if draft_err:
            return json_error("INVALID_PAYLOAD", f"draft_file: {draft_err}", 400)

        result = generate_style_diagnostics(
            book_dir=Path(paths["book_dir"]),
            source_count=source_count,
            draft_file=draft_file,
            draft_chapters=payload.get("draft_chapters"),
        )
        return jsonify({"book_id": book_id, **result}), 200

    @bp.post("/tools/adaptive_slice")
    def adaptive_slice():
        payload, err = parse_json_payload()
        if err:
            return err

        result = main(payload.get("arg1"))
        return jsonify(result), 200

    return bp
