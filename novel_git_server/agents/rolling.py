from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from typing import Any, Callable

from flask import Blueprint, jsonify, request

from pipelines.rolling_chapter import build_chapter_context_pack, build_rolling_plan
from utils.book_storage import get_book_paths


def _coerce_batch_size(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 3
    if parsed <= 0:
        return 3
    return min(parsed, 3)


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _file_state(book_dir: str, file_name: str) -> dict[str, Any]:
    path = os.path.abspath(os.path.join(book_dir, file_name))
    exists = os.path.exists(path)
    is_file = os.path.isfile(path)
    is_dir = os.path.isdir(path)
    return {
        "file_name": file_name,
        "exists": exists,
        "kind": "directory" if is_dir else "file" if is_file else "missing",
        "size": os.path.getsize(path) if is_file else 0,
        "entry_count": len(os.listdir(path)) if is_dir else 0,
    }


def _build_outline_card_states(plan: dict[str, Any]) -> list[dict[str, Any]]:
    written_numbers = set(plan.get("written_chapter_numbers") or [])
    pending_review_numbers = set(plan.get("pending_review_chapter_numbers") or [])
    selected_numbers = set(plan.get("selected_card_numbers") or [])
    blocked_numbers = set(plan.get("blocked_card_numbers") or [])
    pending_numbers = set(plan.get("pending_card_numbers") or [])
    states: list[dict[str, Any]] = []
    for card in plan.get("cards") or []:
        if not isinstance(card, dict):
            continue
        number = card.get("number")
        if number in selected_numbers:
            status = "selected"
        elif number in blocked_numbers:
            status = "blocked"
        elif number in pending_numbers:
            status = "pending"
        elif number in written_numbers:
            status = "written"
        elif number in pending_review_numbers:
            status = "pending_review"
        else:
            status = "ignored"
        states.append(
            {
                "number": number,
                "title": card.get("title") or "",
                "status": status,
                "executable": bool(card.get("executable")),
                "missing_fields": card.get("missing_fields") or [],
                "heading_line": card.get("heading_line") or 0,
                "end_line": card.get("end_line") or 0,
            }
        )
    return states


def _build_outline_diagnostics(plan: dict[str, Any], book_dir: str) -> dict[str, Any]:
    outline_state = _file_state(book_dir, "chapter_outline.md")
    outline_card_count = int(plan.get("outline_card_count") or 0)
    executable_card_count = int(plan.get("executable_card_count") or 0)
    detected_but_unparsed = bool(outline_state["exists"] and outline_state["size"] > 0 and outline_card_count == 0)
    return {
        "outline_card_count": outline_card_count,
        "executable_card_count": executable_card_count,
        "detected_but_unparsed": detected_but_unparsed,
        "message": (
            "chapter_outline.md 有内容，但没有识别到可滚动的章节卡；请检查标题或字段格式。"
            if detected_but_unparsed
            else ""
        ),
    }


def _build_workbench_state(plan: dict[str, Any], book_dir: str) -> dict[str, Any]:
    return {
        "status": "ready",
        "requiresPrompt": False,
        "executionKind": "direct_job",
        "default_batch_size": 3,
        "batch_size": plan.get("batch_size"),
        "next_action": plan.get("next_action"),
        "stop_reason": plan.get("stop_reason") or "",
        "written_chapter_numbers": plan.get("written_chapter_numbers") or [],
        "accepted_chapter_numbers": plan.get("accepted_chapter_numbers") or plan.get("written_chapter_numbers") or [],
        "pending_review_chapter_numbers": plan.get("pending_review_chapter_numbers") or [],
        "pending_card_numbers": plan.get("pending_card_numbers") or [],
        "selected_card_numbers": plan.get("selected_card_numbers") or [],
        "blocked_card_numbers": plan.get("blocked_card_numbers") or [],
        "outline_card_states": _build_outline_card_states(plan),
        "outline_diagnostics": _build_outline_diagnostics(plan, book_dir),
        "remaining_executable_after_selected": plan.get("remaining_executable_after_selected") or [],
        "full_batch_available": bool(plan.get("full_batch_available")),
        "replenishment_needed_after_selected_batch": bool(plan.get("replenishment_needed_after_selected_batch")),
        "review_gate_open": bool(plan.get("review_gate_open")),
        "quality_gate_locked": bool(plan.get("quality_gate_locked")),
        "quality_gate_unlocked": bool(plan.get("quality_gate_unlocked")),
        "source_files": {
            "chapter_outline": _file_state(book_dir, "chapter_outline.md"),
            "chapter_draft": _file_state(book_dir, "chapter_draft.md"),
            "chapters": _file_state(book_dir, "chapters"),
        },
        "no_prose_boundary": {
            "state_contains_generated_prose": False,
            "state_mutates_chapter_outline": False,
            "state_writes_chapter_draft": False,
            "continuation_agent_remains_only_chapter_draft_writer": True,
        },
    }


def _brief_text(value: Any, *, limit: int = 220) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _brief_chapter_cards(plan: dict[str, Any]) -> list[dict[str, Any]]:
    selected_numbers = set(plan.get("selected_card_numbers") or [])
    cards: list[dict[str, Any]] = []
    for card in plan.get("selected_cards") or []:
        if not isinstance(card, dict):
            continue
        number = card.get("number")
        if number not in selected_numbers:
            continue
        fields = card.get("fields") if isinstance(card.get("fields"), dict) else {}
        cards.append(
            {
                "number": number,
                "title": _brief_text(card.get("title"), limit=80),
                "goal": _brief_text(fields.get("chapter_goal")),
                "entry_scene": _brief_text(fields.get("entry_scene")),
                "conflict": _brief_text(fields.get("conflict_or_obstacle")),
                "payoff": _brief_text(fields.get("payoff")),
                "state_change": _brief_text(fields.get("state_change")),
                "hook": _brief_text(fields.get("ending_hook")),
                "constraint_refs": _brief_text(fields.get("constraint_refs")),
                "evidence_mode": _brief_text(fields.get("evidence_mode"), limit=120),
            }
        )
    return cards


def _truth_source_list(context_pack: dict[str, Any]) -> list[dict[str, Any]]:
    refs = context_pack.get("truth_source_refs") if isinstance(context_pack.get("truth_source_refs"), dict) else {}
    sources: list[dict[str, Any]] = []
    for name, ref in refs.items():
        if isinstance(ref, dict):
            sources.append(
                {
                    "name": name,
                    "path": ref.get("path") or name,
                    "role": ref.get("role") or "",
                    "exists": bool(ref.get("exists", True)),
                    "contains_prose": False,
                }
            )
        elif isinstance(ref, list):
            sources.append(
                {
                    "name": name,
                    "path": "",
                    "role": "evidence_list",
                    "exists": bool(ref),
                    "contains_prose": False,
                }
            )
    return sources


def _build_author_writing_brief(
    *,
    plan: dict[str, Any],
    context_pack: dict[str, Any],
    generated_at: str,
) -> dict[str, Any]:
    selected_numbers = [
        number for number in plan.get("selected_card_numbers") or []
        if isinstance(number, int)
    ]
    quality_gate = context_pack.get("quality_gate") if isinstance(context_pack.get("quality_gate"), dict) else {}
    style_advisory = context_pack.get("style_advisory") if isinstance(context_pack.get("style_advisory"), dict) else {}
    active_repair = (
        context_pack.get("active_repair_goals")
        if isinstance(context_pack.get("active_repair_goals"), dict)
        else {}
    )
    quality_summary = quality_gate.get("summary") if isinstance(quality_gate.get("summary"), dict) else {}
    style_summary = style_advisory.get("summary") if isinstance(style_advisory.get("summary"), dict) else {}

    return {
        "schema_version": 1,
        "brief_type": "rolling_author_writing_brief",
        "generated_at": generated_at,
        "book_id": plan.get("book_id"),
        "target_file": "chapter_draft.md",
        "route_agent_key": "continuation_agent",
        "batch": {
            "batch_size": plan.get("batch_size"),
            "selected_card_numbers": selected_numbers,
            "full_batch_available": bool(plan.get("full_batch_available")),
            "remaining_executable_after_selected": plan.get("remaining_executable_after_selected") or [],
        },
        "progress_cursor": {
            "accepted_chapter_numbers": plan.get("accepted_chapter_numbers") or [],
            "pending_review_chapter_numbers": plan.get("pending_review_chapter_numbers") or [],
            "pending_card_numbers": plan.get("pending_card_numbers") or [],
            "next_action": plan.get("next_action"),
            "stop_reason": plan.get("stop_reason") or "",
        },
        "chapter_cards": _brief_chapter_cards(plan),
        "writing_contract": {
            "what_to_write": "只执行本轮 selected_card_numbers 对应的逐章大纲卡。",
            "where_to_write": "只允许 continuation Agent 写入 chapter_draft.md。",
            "what_not_to_do": [
                "不要改写 chapter_outline.md、summary.md、world_model.md、status_card.md、domain_rules.md、style 文件或 error_archive.md。",
                "不要自行补造未列入 selected_card_numbers 的新章节卡。",
                "不要把 WORLD_MODEL_REQUIRED 提案当成已确认世界观事实。",
            ],
        },
        "truth_sources": _truth_source_list(context_pack),
        "quality_and_style": {
            "quality_gate_locked": bool(quality_gate.get("locked")),
            "quality_gate_blocks_next_action": bool(quality_gate.get("blocks_next_action")),
            "quality_gate_summary": quality_summary,
            "style_advisory_active": bool(style_advisory.get("active")),
            "style_is_reference_only": bool(style_advisory.get("reference_only", True)),
            "style_summary": style_summary,
            "repair_goals": {
                "protocol": active_repair.get("protocol"),
                "proxy_repair_goals": active_repair.get("proxy_repair_goals") or [],
                "protected_metrics": active_repair.get("protected_metrics") or [],
                "stop_conditions": active_repair.get("stop_conditions") or {},
            },
        },
        "no_prose_boundary": {
            "brief_contains_generated_prose": False,
            "brief_reads_chapter_draft_text": False,
            "brief_writes_files": False,
            "continuation_agent_remains_only_chapter_draft_writer": True,
        },
    }


def _build_continuation_intent(*, plan: dict[str, Any], context_pack: dict[str, Any]) -> str:
    selected_numbers = [
        number for number in plan.get("selected_card_numbers") or []
        if isinstance(number, int)
    ]
    context_json = json.dumps(context_pack, ensure_ascii=False, sort_keys=True)
    selected_label = "、".join(str(number) for number in selected_numbers) or "无"
    batch_size = plan.get("batch_size") or 3
    return (
        "【滚动续写工作台任务】\n"
        "本次任务由前台按钮触发，不是聊天闲聊；请按项目 continuation Agent 的既有工具链执行。\n"
        "你必须自己读取 chapter_draft.md、chapter_outline.md、summary.md、status_card.md、world_model.md、"
        "domain_rules.md、style_constraints_for_continuation.md 与 error_archive.md。\n"
        "只允许把正文写入 chapter_draft.md；不要修改 chapter_outline.md、summary.md、status_card.md、"
        "world_model.md、domain_rules.md、style_constraints_for_continuation.md 或 error_archive.md。\n"
        f"本轮默认批量上限为 {batch_size} 章；本次只写 selected_card_numbers 中列出的章节：{selected_label}。\n"
        "如果 selected_card_numbers 少于三章，只写列出的章节；不要自行补造新的章节卡。\n"
        "写作时以逐章大纲和真相源为边界，文风约束作为参考提示，由你自主模仿最近原文，不要因文风提示卡死调度。\n"
        "写完后保持草稿进入审查工作台；最终回答只给简短状态，不要把整章正文粘贴到回答里。\n\n"
        "chapter_context_pack JSON：\n"
        f"{context_json}"
    )


def create_blueprint(
    *,
    storage_root: str,
    require_book_id: Callable[[dict | None], tuple[str | None, tuple | None]],
    json_error: Callable[[str, str, int], tuple],
) -> Blueprint:
    bp = Blueprint("rolling", __name__)

    @bp.get("/api/rolling/state")
    def rolling_state():
        book_id, book_err = require_book_id()
        if book_err:
            return book_err
        assert book_id is not None

        paths = get_book_paths(book_id, storage_root)
        book_dir = paths["book_dir"]
        if not os.path.isdir(book_dir):
            return json_error("BOOK_NOT_FOUND", "book not found", 404)

        batch_size = _coerce_batch_size(request.args.get("batch_size"))
        review_gate_open = request.args.get("review_gate") != "closed"

        try:
            plan = build_rolling_plan(
                book_id=book_id,
                book_dir=book_dir,
                batch_size=batch_size,
                review_gate_open=review_gate_open,
            )
        except ValueError as exc:
            return json_error("INVALID_PAYLOAD", str(exc), 400)

        return (
            jsonify(
                {
                    "status": "success",
                    "book_id": book_id,
                    "generated_at": _iso_now(),
                    "workbench_state": _build_workbench_state(plan, book_dir),
                    "plan": plan,
                }
            ),
            200,
        )

    @bp.post("/api/rolling/continuation_payload")
    def rolling_continuation_payload():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            payload = {}
        book_id, book_err = require_book_id(payload)
        if book_err:
            return book_err
        assert book_id is not None

        paths = get_book_paths(book_id, storage_root)
        book_dir = paths["book_dir"]
        if not os.path.isdir(book_dir):
            return json_error("BOOK_NOT_FOUND", "book not found", 404)

        batch_size = _coerce_batch_size(payload.get("batch_size"))
        review_gate_open = payload.get("review_gate") != "closed"
        try:
            plan = build_rolling_plan(
                book_id=book_id,
                book_dir=book_dir,
                batch_size=batch_size,
                review_gate_open=review_gate_open,
            )
        except ValueError as exc:
            return json_error("INVALID_PAYLOAD", str(exc), 400)

        if plan.get("next_action") != "continue_existing_cards":
            return (
                jsonify(
                    {
                        "status": "error",
                        "code": "ROLLING_NOT_READY",
                        "message": f"rolling workbench is not ready to continue: {plan.get('next_action')}",
                        "book_id": book_id,
                        "next_action": plan.get("next_action"),
                        "stop_reason": plan.get("stop_reason") or "",
                        "workbench_state": _build_workbench_state(plan, book_dir),
                        "plan": plan,
                    }
                ),
                409,
            )

        generated_at = _iso_now()
        context_pack = build_chapter_context_pack(
            plan=plan,
            book_dir=book_dir,
            generated_at=generated_at,
            pack_id=f"rolling-continuation-{generated_at}",
        )
        author_writing_brief = _build_author_writing_brief(
            plan=plan,
            context_pack=context_pack,
            generated_at=generated_at,
        )
        chapter_number = context_pack.get("chapter_number")
        return (
            jsonify(
                {
                    "status": "success",
                    "book_id": book_id,
                    "generated_at": generated_at,
                    "chapter_number": chapter_number if isinstance(chapter_number, int) else 0,
                    "target_file": "chapter_draft.md",
                    "route_agent_key": "continuation_agent",
                    "file_type": "chapter",
                    "write_scope": "active_file_strict",
                    "dify_user": "loregit-ui-rolling-continuation",
                    "intent": _build_continuation_intent(plan=plan, context_pack=context_pack),
                    "workbench_state": _build_workbench_state(plan, book_dir),
                    "chapter_context_pack": context_pack,
                    "author_writing_brief": author_writing_brief,
                    "no_prose_boundary": {
                        "payload_contains_generated_prose": False,
                        "payload_writes_chapter_draft": False,
                        "continuation_agent_remains_only_chapter_draft_writer": True,
                    },
                    "plan": plan,
                }
            ),
            200,
        )

    return bp
