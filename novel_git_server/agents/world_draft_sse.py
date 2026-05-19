"""SSE stream event parsing and Dify stream text extraction for world deduce routes."""

import json
import re
from typing import Any

from agents.archive import _compute_text_etag, _normalize_file_name
from agents.world_draft_dify import _normalize_text

STATUS_CARD_MAX_LINES = 20
JSON_PAYLOAD_MARKER = "[JSON_PAYLOAD_START]"
THINK_BLOCK_START = "<think>"
THINK_BLOCK_END = "</think>"


def _encode_sse_event(event_name: str, payload: dict[str, Any]) -> str:
    data = json.dumps(payload, ensure_ascii=False)
    chunks = [f"event: {event_name}\n"]
    lines = data.splitlines() or [""]
    for line in lines:
        chunks.append(f"data: {line}\n")
    chunks.append("\n")
    return "".join(chunks)


def _extract_stream_text_chunk(stream_event: dict[str, Any]) -> str:
    data = stream_event.get("data")
    if not isinstance(data, dict):
        return ""
    for key in ("answer", "delta", "text", "content"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _nested_get(source: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = source
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _as_non_empty_text(value: Any) -> str:
    return value if isinstance(value, str) and value.strip() else ""


def _first_non_empty_text(values: list[Any]) -> str:
    for value in values:
        text = _as_non_empty_text(value)
        if text:
            return text
    return ""


def _normalize_stream_event_name(stream_event: dict[str, Any]) -> str:
    event_name = _as_non_empty_text(stream_event.get("event"))
    data = stream_event.get("data")
    nested_name = ""
    if isinstance(data, dict):
        nested_name = _as_non_empty_text(data.get("event"))

    if nested_name and (not event_name or event_name == "message"):
        return nested_name
    if event_name:
        return event_name
    if nested_name:
        return nested_name
    return "message"


def _sanitize_node_label(raw_label: str, node_type: str = "") -> str:
    label = _normalize_text(raw_label).strip()
    if not label:
        return ""

    label = re.sub(r"(?i)(started|finished|running|completed)$", "", label)
    label = re.sub(r"[_\-\s]*\d+$", "", label)
    label = re.sub(r"(?i)[_\-\s]*(agent|node)$", "", label)
    label = re.sub(r"[_\-]+", " ", label)
    label = re.sub(r"\s+", " ", label).strip()
    if not label:
        return ""

    normalized_upper = label.upper()
    if normalized_upper == "COMMIT":
        return "草稿写入"
    if normalized_upper == "CLASSIFIER":
        return "问题分类"
    if normalized_upper == "ROUTER":
        return "路由节点"
    if normalized_upper == "READ FILE":
        return "读取文件"
    if normalized_upper == "WRITE FILE":
        return "写入文件"

    if re.fullmatch(r"[A-Z][A-Z0-9 ]+", label):
        label = label.title()

    if node_type == "tool" and not label.endswith("工具"):
        return f"{label}工具"
    return label


def _format_hidden_payload_error(raw_payload: str, exc: json.JSONDecodeError) -> str:
    compact_payload = raw_payload.replace("\n", "\\n")
    snippet = compact_payload[max(0, exc.pos - 28): exc.pos + 28]
    message = f"隐藏 JSON 载荷格式错误：{exc.msg}（第 {exc.lineno} 行，第 {exc.colno} 列）"
    if exc.msg == "Extra data":
        message = (
            f"{message}；marker 之后混入了额外文本，"
            "说明隐藏载荷不是单个 JSON 文档。"
        )
    if snippet:
        message = f"{message}；附近片段：{snippet}"
    return message


def _extract_stream_conversation_id(stream_event: dict[str, Any]) -> str | None:
    data = stream_event.get("data")
    if not isinstance(data, dict):
        return None
    value = _first_non_empty_text(
        [
            data.get("conversation_id"),
            _nested_get(data, ("data", "conversation_id")),
            _nested_get(data, ("message", "conversation_id")),
        ]
    )
    return value or None


def _extract_stream_task_id(stream_event: dict[str, Any]) -> str | None:
    data = stream_event.get("data")
    if not isinstance(data, dict):
        return None
    value = _first_non_empty_text(
        [
            data.get("task_id"),
            _nested_get(data, ("data", "task_id")),
            _nested_get(data, ("message", "task_id")),
        ]
    )
    return value or None


def _extract_workflow_output_text(stream_event: dict[str, Any]) -> str:
    data = stream_event.get("data")
    if not isinstance(data, dict):
        return ""
    return _first_non_empty_text(
        [
            _nested_get(data, ("outputs", "text")),
            _nested_get(data, ("outputs", "answer")),
            _nested_get(data, ("data", "outputs", "text")),
            _nested_get(data, ("data", "outputs", "answer")),
            _nested_get(data, ("workflow_run", "outputs", "text")),
            _nested_get(data, ("workflow_run", "outputs", "answer")),
            _nested_get(data, ("data", "workflow_run", "outputs", "text")),
            _nested_get(data, ("data", "workflow_run", "outputs", "answer")),
        ]
    )


def _extract_workflow_sync_meta(stream_event: dict[str, Any]) -> dict[str, str] | None:
    data = stream_event.get("data")
    if not isinstance(data, dict):
        return None

    sync_status = _first_non_empty_text(
        [
            _nested_get(data, ("outputs", "sync_status")),
            _nested_get(data, ("data", "outputs", "sync_status")),
            _nested_get(data, ("workflow_run", "outputs", "sync_status")),
            _nested_get(data, ("data", "workflow_run", "outputs", "sync_status")),
        ]
    )
    sync_commit_id = _first_non_empty_text(
        [
            _nested_get(data, ("outputs", "sync_commit_id")),
            _nested_get(data, ("data", "outputs", "sync_commit_id")),
            _nested_get(data, ("workflow_run", "outputs", "sync_commit_id")),
            _nested_get(data, ("data", "workflow_run", "outputs", "sync_commit_id")),
        ]
    )
    sync_message = _first_non_empty_text(
        [
            _nested_get(data, ("outputs", "sync_message")),
            _nested_get(data, ("data", "outputs", "sync_message")),
            _nested_get(data, ("workflow_run", "outputs", "sync_message")),
            _nested_get(data, ("data", "workflow_run", "outputs", "sync_message")),
        ]
    )
    sync_result = _first_non_empty_text(
        [
            _nested_get(data, ("outputs", "result")),
            _nested_get(data, ("data", "outputs", "result")),
            _nested_get(data, ("workflow_run", "outputs", "result")),
            _nested_get(data, ("data", "workflow_run", "outputs", "result")),
        ]
    )

    if not any([sync_status, sync_commit_id, sync_message, sync_result]):
        return None
    return {
        "sync_status": sync_status,
        "sync_commit_id": sync_commit_id,
        "sync_message": sync_message,
        "sync_result": sync_result,
    }


def _extract_workflow_failure_message(stream_event: dict[str, Any]) -> str:
    data = stream_event.get("data")
    if not isinstance(data, dict):
        return ""

    status = _first_non_empty_text(
        [
            data.get("status"),
            _nested_get(data, ("data", "status")),
            _nested_get(data, ("workflow_run", "status")),
            _nested_get(data, ("data", "workflow_run", "status")),
        ]
    ).lower()
    if status not in {"failed", "error"}:
        return ""

    error_message = _first_non_empty_text(
        [
            data.get("error"),
            _nested_get(data, ("data", "error")),
            _nested_get(data, ("workflow_run", "error")),
            _nested_get(data, ("data", "workflow_run", "error")),
        ]
    )
    if error_message:
        return f"Dify workflow failed: {error_message}"
    return "Dify workflow failed without explicit error message"


def _is_transient_workflow_failure(message: str) -> bool:
    normalized = _normalize_text(message).lower()
    if not normalized:
        return False
    transient_markers = (
        "got invalid json object",
        "expecting value: line 1 column 1",
        "dify workflow failed without explicit error message",
    )
    return any(marker in normalized for marker in transient_markers)


def _extract_stream_text_candidate(stream_event: dict[str, Any]) -> str:
    data = stream_event.get("data")
    if not isinstance(data, dict):
        return ""
    direct_text = _first_non_empty_text(
        [
            data.get("answer"),
            data.get("delta"),
            data.get("text"),
            data.get("content"),
            _nested_get(data, ("message", "content")),
            _nested_get(data, ("data", "text")),
        ]
    )
    if direct_text:
        return direct_text
    return _extract_workflow_output_text(stream_event)


def _compact_agent_reasoning_text(text: str, event_name: str) -> str:
    normalized = _normalize_text(text).strip()
    if not normalized:
        return ""

    lower_text = normalized.lower()
    looks_like_internal_english_scratchpad = (
        len(normalized) > 240
        or any(
            marker in lower_text
            for marker in (
                "let me",
                "i need",
                "now i",
                "actually,",
                "looking at",
                "check if",
                "go through",
            )
        )
    )
    if not looks_like_internal_english_scratchpad:
        if len(normalized) <= 1200:
            return normalized
        return f"{normalized[:1200].rstrip()}..."

    if any(key in lower_text for key in ("chapter_draft", "chapter outline", "summary", "status card", "world model", "style", "error archive", "key files", "outline")):
        return "正在读取章节草稿、大纲、总结、状态卡、世界模型、文风约束和错误档案。"
    if any(key in lower_text for key in ("validate_chapter_lengths", "under_min", "min_chars", "chapter length")):
        return "正在校验章节篇幅水位，并判断是否构成真实硬约束。"
    if any(key in lower_text for key in ("banana", "b short", "mirage", "inferno", "usp", "glock", "cs:go", "cs2")):
        return "正在复查电竞术语与已知错误档案，确认地图术语和阵营武器是否准确。"
    if any(key in lower_text for key in ("outline", "world", "status", "character", "plot", "style")):
        return "正在逐项核对大纲边界、世界观连续性、状态卡事实、文风约束和错误档案。"
    return "正在整理审核依据，过滤内部草稿，只保留作者可读结论。"


def _looks_like_internal_scratchpad_text(text: str) -> bool:
    normalized = _normalize_text(text).strip()
    if len(normalized) < 32:
        return False
    lower_text = normalized.lower()
    has_self_planning_marker = any(
        marker in lower_text
        for marker in (
            "let me",
            "i need",
            "now i",
            "actually,",
            "looking at",
            "go through",
            "conduct a thorough review",
        )
    )
    if not has_self_planning_marker:
        return False
    has_local_workbench_context = any(
        marker in lower_text
        for marker in (
            "chapter_draft.md",
            "chapter_outline.md",
            "summary.md",
            "status_card.md",
            "world_model.md",
            "style_guide.md",
            "error_archive.md",
            "review dimensions",
            "outline shows",
            "read the detailed content",
        )
    )
    return has_local_workbench_context


def _starts_like_internal_scratchpad_text(text: str) -> bool:
    lower_text = _normalize_text(text).lstrip().lower()
    return lower_text.startswith(("let", "let me", "i need", "now i", "actually", "looking at"))


def _contains_cjk_text(text: str) -> bool:
    return any("一" <= char <= "鿿" for char in text)


def _extract_reasoning_payload(stream_event: dict[str, Any]) -> dict[str, Any] | None:
    event_name = _normalize_stream_event_name(stream_event)
    data = stream_event.get("data")
    if not isinstance(data, dict):
        return None

    reasoning_text = _first_non_empty_text(
        [
            data.get("reasoning_content"),
            data.get("thought"),
            data.get("observation"),
            _nested_get(data, ("data", "reasoning_content")),
            _nested_get(data, ("data", "thought")),
            _nested_get(data, ("data", "observation")),
            _nested_get(data, ("metadata", "reasoning_content")),
            _nested_get(data, ("data", "metadata", "reasoning_content")),
        ]
    )
    if not reasoning_text:
        return None
    reasoning_text = _compact_agent_reasoning_text(reasoning_text, event_name)
    if not reasoning_text:
        return None

    label = "已深度思考"
    if event_name == "agent_thought":
        tool_name = _first_non_empty_text([data.get("tool"), _nested_get(data, ("data", "tool"))])
        if tool_name:
            label = f"工具思考：{tool_name}"
    return {
        "label": label,
        "text": reasoning_text,
        "source_event": event_name,
    }


def _extract_preview_payload(stream_event: dict[str, Any]) -> dict[str, Any] | None:
    event_name = _normalize_stream_event_name(stream_event)
    if event_name != "node_finished":
        return None

    data = stream_event.get("data")
    if not isinstance(data, dict):
        return None

    node_title = _first_non_empty_text(
        [
            data.get("node_title"),
            data.get("title"),
            _nested_get(data, ("data", "title")),
        ]
    )
    node_type = _first_non_empty_text(
        [
            data.get("node_type"),
            data.get("type"),
            _nested_get(data, ("data", "node_type")),
        ]
    ).lower()
    if node_type in {"tool", "code", "python", "script"}:
        return None

    preview_text = _extract_workflow_output_text(stream_event).strip()
    if not preview_text:
        return None
    if JSON_PAYLOAD_MARKER in preview_text:
        return None
    if preview_text.startswith("{") or preview_text.startswith("["):
        return None

    if len(preview_text) > 280:
        preview_text = f"{preview_text[:280].rstrip()}…"

    return {
        "label": _sanitize_node_label(node_title, node_type) or "中间输出",
        "text": preview_text,
        "source_event": event_name,
    }


def _split_text_and_think_blocks(
    chunk: str,
    *,
    in_think_block: bool,
    pending_tail: str,
    start_marker: str = THINK_BLOCK_START,
    end_marker: str = THINK_BLOCK_END,
) -> tuple[list[tuple[str, str]], bool, str]:
    """
    Split a text chunk into visible text vs think text fragments.

    Returns:
    - segments: list of ("text"|"think_stream"|"think_complete", content)
    - next_in_think_block
    - next_pending_tail
    """
    merged = f"{pending_tail}{chunk}"
    if not merged:
        return [], in_think_block, ""

    segments: list[tuple[str, str]] = []
    cursor = 0

    while cursor < len(merged):
        if in_think_block:
            end_index = merged.find(end_marker, cursor)
            if end_index < 0:
                max_hold = min(len(end_marker) - 1, len(merged) - cursor)
                hold_len = 0
                for probe_len in range(max_hold, 0, -1):
                    if merged.endswith(end_marker[:probe_len]):
                        hold_len = probe_len
                        break
                emit_upto = len(merged) - hold_len
                if emit_upto > cursor:
                    segments.append(("think_stream", merged[cursor:emit_upto]))
                return segments, True, merged[emit_upto:]
            if end_index > cursor:
                segments.append(("think_complete", merged[cursor:end_index]))
            else:
                segments.append(("think_complete", ""))
            cursor = end_index + len(end_marker)
            in_think_block = False
            continue

        start_index = merged.find(start_marker, cursor)
        if start_index < 0:
            max_hold = min(len(start_marker) - 1, len(merged) - cursor)
            hold_len = 0
            for probe_len in range(max_hold, 0, -1):
                if merged.endswith(start_marker[:probe_len]):
                    hold_len = probe_len
                    break
            emit_upto = len(merged) - hold_len
            if emit_upto > cursor:
                segments.append(("text", merged[cursor:emit_upto]))
            return segments, False, merged[emit_upto:]

        if start_index > cursor:
            segments.append(("text", merged[cursor:start_index]))
        cursor = start_index + len(start_marker)
        in_think_block = True

    return segments, in_think_block, ""


def _split_visible_stream_text(chunk: str, pending_tail: str, marker: str = JSON_PAYLOAD_MARKER) -> tuple[str, str, str, bool]:
    merged = f"{pending_tail}{chunk}"
    marker_index = merged.find(marker)
    if marker_index >= 0:
        visible_text = merged[:marker_index]
        payload_seed = merged[marker_index + len(marker):]
        return visible_text, "", payload_seed, True

    if not marker:
        return merged, "", "", False

    max_hold_len = min(len(marker) - 1, len(merged))
    hold_len = 0
    for probe_len in range(max_hold_len, 0, -1):
        if merged.endswith(marker[:probe_len]):
            hold_len = probe_len
            break
    if hold_len <= 0:
        return merged, "", "", False
    visible_text = merged[:-hold_len]
    next_pending_tail = merged[-hold_len:]
    return visible_text, next_pending_tail, "", False


def _parse_json_payload(raw_payload: str, writable_targets: set[str]) -> tuple[list[dict[str, str]], str | None]:
    """Compatibility parser for legacy hidden payload writes.
    Parse writes for validation and observability only; backend no longer executes hidden payload writes.
    """
    payload = (raw_payload or "").strip()
    if not payload:
        return [], "隐藏 JSON 载荷格式错误：marker 之后没有收到合法 JSON 文档。"

    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        return [], _format_hidden_payload_error(payload, exc)

    writes = data.get("writes")
    if not isinstance(writes, list) or not writes:
        return [], "writes must be a non-empty array"

    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in writes:
        file_name = _normalize_file_name(entry.get("file_name", ""))
        if not file_name or file_name not in writable_targets:
            continue
        if file_name in seen:
            continue
        seen.add(file_name)
        content = entry.get("content", "")
        if file_name == "status_card.md":
            lines = content.splitlines(keepends=True)
            if len(lines) > STATUS_CARD_MAX_LINES:
                content = "".join(lines[:STATUS_CARD_MAX_LINES])
        entries.append({"file_name": file_name, "content": content})
    if not entries:
        return [], "writes does not include any writable target for current routed agent"
    return entries, None


def _build_stage_event_payload(stream_event: dict[str, Any]) -> dict[str, Any] | None:
    event_name = _normalize_stream_event_name(stream_event)
    data = stream_event.get("data")
    if not isinstance(data, dict):
        data = {}

    node_title = _first_non_empty_text(
        [
            data.get("node_title"),
            data.get("title"),
            _nested_get(data, ("data", "title")),
        ]
    )
    node_type = _first_non_empty_text(
        [
            data.get("node_type"),
            data.get("type"),
            _nested_get(data, ("data", "node_type")),
        ]
    )

    if event_name == "workflow_started":
        return {
            "stage_code": "workflow_started",
            "stage_text": "正在路由: 启动工作流...",
            "source_event": event_name,
        }
    if event_name == "node_started":
        label = _sanitize_node_label(node_title, node_type) or "处理中"
        if node_type == "tool":
            text = f"正在执行: 调用工具 {label}..."
        else:
            text = f"正在执行: 节点 {label}..."
        return {
            "stage_code": "node_started",
            "stage_text": text,
            "source_event": event_name,
            "node_title": label,
            "node_type": node_type,
        }
    if event_name == "tool_call":
        label = _sanitize_node_label(node_title, node_type) or "工具"
        return {
            "stage_code": "tool_call",
            "stage_text": f"正在执行: 调用工具 {label}...",
            "source_event": event_name,
            "node_title": label,
            "node_type": node_type or "tool",
        }
    if event_name == "node_finished":
        label = _sanitize_node_label(node_title, node_type) or "已完成节点"
        return {
            "stage_code": "node_finished",
            "stage_text": f"已完成: {label}",
            "source_event": event_name,
            "node_title": label,
            "node_type": node_type,
        }
    return None
