from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from pathlib import Path
from typing import Any

from utils.chapter_length import split_chapter_spans


CARD_HEADING_PATTERNS = (
    re.compile(
        r"^(?:#{1,6}[ \t]+)?章节卡[ \t]*([0-9０-９一二三四五六七八九十百]+)[：:\s-]*(.*?)[ \t]*#*[ \t]*$"
    ),
    re.compile(
        r"^(?:#{1,6}[ \t]+)?CH[ \t]*([0-9０-９]+)[ \t]*(?:[—–-]|：|:)?[ \t]*(.*?)[ \t]*#*[ \t]*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:#{1,6}[ \t]+)?第[ \t]*([0-9０-９一二三四五六七八九十百]+)[ \t]*章[ \t]*(?:[—–-]|：|:)?[ \t]*(.*?)[ \t]*#*[ \t]*$"
    ),
)
FIELD_RE = re.compile(r"^[ \t]*[-*][ \t]*(?:\*\*)?([A-Za-z_]+|[\u4e00-\u9fffA-Za-z_/（）()]+)(?:\*\*)?[：:][ \t]*(.*)$")
BOLD_FIELD_RE = re.compile(r"^[ \t]*(?:[-*][ \t]*)?\*\*([^*：:]+)\*\*[：:][ \t]*(.*)$")
CHAPTER_NUMBER_RE = re.compile(r"第([0-9０-９一二三四五六七八九十百]+)章")
FENCE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})")

EXECUTABLE_CARD_FIELDS = frozenset(
    {
        "chapter_goal",
        "entry_scene",
        "conflict_or_obstacle",
        "payoff",
        "state_change",
        "foreshadowing_action",
        "ending_hook",
    }
)

FIELD_KEY_ALIASES = {
    "章节目标": "chapter_goal",
    "目标": "chapter_goal",
    "入场场景": "entry_scene",
    "开场场景": "entry_scene",
    "冲突/阻碍": "conflict_or_obstacle",
    "冲突阻碍": "conflict_or_obstacle",
    "冲突": "conflict_or_obstacle",
    "阻碍": "conflict_or_obstacle",
    "当章兑现": "payoff",
    "兑现": "payoff",
    "章节兑现": "payoff",
    "状态变化": "state_change",
    "伏笔动作": "foreshadowing_action",
    "伏笔": "foreshadowing_action",
    "结尾钩子": "ending_hook",
    "尾钩": "ending_hook",
    "钩子": "ending_hook",
    "约束引用": "constraint_refs",
    "约束": "constraint_refs",
    "证据模式": "evidence_mode",
    "证据": "evidence_mode",
}

STYLE_GATE_METRICS = (
    "avg_sentence",
    "avg_para",
    "dialogue_ratio",
    "interior_density",
    "action_density",
    "environment_density",
    "exposition_density",
    "suspense_density",
)
SEVERITY_SCORE = {"pass": 0, "warn": 1, "fail": 2}
STYLE_METRIC_DELTA_PROTOCOL = "STYLE_METRIC_DELTA_PROTOCOL"
STYLE_ADVISORY_ROLE = "style_advisory"
CHAPTER_CONTEXT_PACK_PROTOCOL = "CHAPTER_CONTEXT_PACK_PROTOCOL"
CHAPTER_CONTEXT_SOURCE_FILES = (
    "chapter_outline.md",
    "world_model.md",
    "status_card.md",
    "domain_rules.md",
    "summary.md",
    "style_constraints_for_continuation.md",
    "error_archive.md",
)
CHAPTER_CONTEXT_CARD_FIELDS = (
    "chapter_goal",
    "entry_scene",
    "conflict_or_obstacle",
    "payoff",
    "state_change",
    "foreshadowing_action",
    "ending_hook",
    "constraint_refs",
    "evidence_mode",
)
STYLE_METRIC_PROXY_TARGETS = {
    "avg_para": {
        "decrease": [
            "paragraph_count_must_increase",
            "average_paragraph_chars_must_decrease",
            "no_merge_split_beats",
        ],
        "increase": [
            "merge_choppy_micro_paragraphs",
            "keep_action_chain_in_one_paragraph",
        ],
        "hold": ["keep_paragraph_count_and_average_para_inside_target_band"],
    },
    "avg_sentence": {
        "decrease": ["split_overloaded_sentences", "move_explanations_into_separate_beats"],
        "increase": ["merge_choppy_sentences", "extend_causal_and_sensory_links"],
        "hold": ["keep_sentence_breath_inside_target_band"],
    },
    "dialogue_ratio": {
        "decrease": ["dialogue_paragraph_ratio_must_decrease", "replace_q_and_a_with_action_reaction"],
        "increase": ["dialogue_paragraph_ratio_must_increase", "surface_conflict_in_spoken_lines"],
        "hold": ["keep_dialogue_paragraph_ratio_inside_target_band"],
    },
    "interior_density": {
        "decrease": ["repeated_thought_clusters_must_decrease", "externalize_repeated_judgment"],
        "increase": ["brief_judgment_beats_must_increase", "show_pressure_through_character_choice"],
        "hold": ["keep_interior_density_inside_target_band"],
    },
    "action_density": {
        "decrease": ["redundant_motion_clusters_must_decrease", "keep_only_pressure_changing_actions"],
        "increase": ["physical_movement_beats_must_increase", "anchor_information_in_stage_business"],
        "hold": ["keep_action_density_inside_target_band"],
    },
    "environment_density": {
        "decrease": ["environment_cue_clusters_must_decrease", "delete_atmosphere_only_cues"],
        "increase": ["choice_changing_environment_cues_must_increase", "tie_setting_to_decision"],
        "hold": ["keep_environment_density_inside_target_band"],
    },
    "exposition_density": {
        "decrease": ["explanation_trigger_clusters_must_decrease", "convert_exposition_to_consequence"],
        "increase": ["missing_rule_context_must_increase", "bind_explanation_to_immediate_cost"],
        "hold": ["keep_exposition_density_inside_target_band"],
    },
    "suspense_density": {
        "decrease": ["unresolved_signal_clusters_must_decrease", "resolve_redundant_question_marks"],
        "increase": ["unresolved_signal_count_must_increase", "place_one_open_hook_per_scene_turn"],
        "hold": ["keep_suspense_density_inside_target_band"],
    },
}

FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")
CHINESE_DIGITS = {
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


@dataclass(frozen=True)
class ChapterCard:
    number: int
    title: str
    heading_line: int
    end_line: int
    fields: dict[str, str]
    executable: bool
    missing_fields: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "title": self.title,
            "heading_line": self.heading_line,
            "end_line": self.end_line,
            "fields": self.fields,
            "executable": self.executable,
            "missing_fields": list(self.missing_fields),
        }


@dataclass(frozen=True)
class WrittenChapter:
    number: int
    title: str
    heading_line: int
    end_line: int
    source: str = "chapter_draft.md"

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "title": self.title,
            "heading_line": self.heading_line,
            "end_line": self.end_line,
            "source": self.source,
        }


def parse_chapter_number(raw: str) -> int | None:
    value = str(raw or "").strip().translate(FULLWIDTH_DIGITS)
    if not value:
        return None
    if value.isdigit():
        return int(value)
    if value in CHINESE_DIGITS:
        return CHINESE_DIGITS[value]
    if value == "十":
        return 10
    if "十" in value:
        left, _, right = value.partition("十")
        tens = CHINESE_DIGITS.get(left, 1) if left else 1
        ones = CHINESE_DIGITS.get(right, 0) if right else 0
        return tens * 10 + ones
    if value.endswith("百"):
        left = value[:-1]
        return CHINESE_DIGITS.get(left, 1) * 100 if not left or left in CHINESE_DIGITS else None
    return None


def _split_lines(markdown: str) -> list[str]:
    return markdown.splitlines(keepends=True)


def _strip_line_ending(line: str) -> str:
    if line.endswith("\r\n"):
        return line[:-2]
    if line.endswith("\n") or line.endswith("\r"):
        return line[:-1]
    return line


def _chapter_card_headings(markdown: str) -> list[tuple[int, int, str]]:
    headings: list[tuple[int, int, str]] = []
    in_fence = False
    active_fence_char = ""
    active_fence_len = 0
    for line_number, raw_line in enumerate(_split_lines(markdown), start=1):
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
        match = None
        for pattern in CARD_HEADING_PATTERNS:
            match = pattern.match(line.strip())
            if match:
                break
        if not match:
            continue
        number = parse_chapter_number(match.group(1))
        if number is None:
            continue
        headings.append((line_number, number, match.group(2).strip()))
    return headings


def _canonical_field_key(raw_key: str) -> str:
    key = str(raw_key or "").strip()
    if key in EXECUTABLE_CARD_FIELDS or key in CHAPTER_CONTEXT_CARD_FIELDS:
        return key
    compact_key = re.sub(r"[\s　]+", "", key)
    return FIELD_KEY_ALIASES.get(compact_key, key)


def _extract_fields(lines: list[str]) -> dict[str, str]:
    fields: dict[str, str] = {}
    active_key: str | None = None
    for raw_line in lines:
        line = _strip_line_ending(raw_line)
        match = BOLD_FIELD_RE.match(line) or FIELD_RE.match(line)
        if match:
            active_key = _canonical_field_key(match.group(1))
            fields[active_key] = match.group(2).strip()
            continue
        if active_key and line.startswith((" ", "\t")) and line.strip():
            fields[active_key] = f"{fields[active_key]}\n{line.strip()}".strip()
    return fields


def parse_chapter_cards(markdown: str) -> list[ChapterCard]:
    lines = _split_lines(markdown)
    headings = _chapter_card_headings(markdown)
    cards: list[ChapterCard] = []
    for index, (heading_line, number, title) in enumerate(headings):
        next_heading_line = headings[index + 1][0] if index + 1 < len(headings) else len(lines) + 1
        end_line = next_heading_line - 1
        fields = _extract_fields(lines[heading_line:end_line])
        missing = tuple(sorted(EXECUTABLE_CARD_FIELDS - set(fields)))
        cards.append(
            ChapterCard(
                number=number,
                title=title,
                heading_line=heading_line,
                end_line=end_line,
                fields=fields,
                executable=not missing,
                missing_fields=missing,
            )
        )
    return cards


def parse_written_chapters(markdown: str) -> list[WrittenChapter]:
    chapters: list[WrittenChapter] = []
    for span in split_chapter_spans(markdown):
        match = CHAPTER_NUMBER_RE.search(span.title)
        if not match:
            continue
        number = parse_chapter_number(match.group(1))
        if number is None:
            continue
        chapters.append(
            WrittenChapter(
                number=number,
                title=span.title,
                heading_line=span.heading_line,
                end_line=span.end_line,
                source="chapter_draft.md",
            )
        )
    return chapters


def _chapter_number_from_archive_name(path: Path) -> int | None:
    match = re.match(r"^([0-9]{1,6})(?:_|\.|$)", path.name)
    if not match:
        return None
    return int(match.group(1))


def _archive_title_from_path(path: Path, content: str, number: int) -> str:
    spans = split_chapter_spans(content)
    if spans:
        return spans[0].title
    for line in content.splitlines():
        text = line.strip().lstrip("#").strip()
        if text:
            return text
    stem = path.stem
    prefix = f"{number:04d}_"
    if stem.startswith(prefix):
        return stem[len(prefix):].replace("_", " ")
    return stem


def parse_archived_chapters(book_dir: str | Path) -> list[WrittenChapter]:
    chapters_dir = Path(book_dir) / "chapters"
    if not chapters_dir.is_dir():
        return []
    by_number: dict[int, WrittenChapter] = {}
    for path in sorted(chapters_dir.glob("*.md")):
        number = _chapter_number_from_archive_name(path)
        if number is None or number in by_number:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            content = ""
        title = _archive_title_from_path(path, content, number)
        by_number[number] = WrittenChapter(
            number=number,
            title=title,
            heading_line=1,
            end_line=max(1, len(content.splitlines())),
            source=f"chapters/{path.name}",
        )
    return [by_number[number] for number in sorted(by_number)]


def _style_gate_metric_names(items: list[dict[str, Any]], severity: str) -> list[str]:
    names: list[str] = []
    for item in items:
        if item.get("severity") != severity:
            continue
        metric = item.get("metric")
        if isinstance(metric, str) and metric:
            names.append(metric)
    return names


def summarize_style_gate_artifact(style_artifact: dict[str, Any], draft_index: int = 0) -> dict[str, Any]:
    """Build the rolling-loop summary from the current style diagnostics schema."""
    style_gate = style_artifact.get("style_gate") if isinstance(style_artifact, dict) else None
    if not isinstance(style_gate, dict):
        style_gate = style_artifact if isinstance(style_artifact, dict) else {}

    drafts = style_gate.get("drafts") if isinstance(style_gate.get("drafts"), list) else []
    draft = drafts[draft_index] if 0 <= draft_index < len(drafts) and isinstance(drafts[draft_index], dict) else {}
    repair_plan = draft.get("repair_plan") if isinstance(draft.get("repair_plan"), dict) else {}
    profile = draft.get("gate_profile") if isinstance(draft.get("gate_profile"), dict) else {}
    if not profile and isinstance(repair_plan.get("gate_profile"), dict):
        profile = repair_plan["gate_profile"]

    items = draft.get("items") if isinstance(draft.get("items"), list) else []
    fail_metrics = _style_gate_metric_names(items, "fail")
    warn_metrics = _style_gate_metric_names(items, "warn")
    if not fail_metrics and not warn_metrics:
        priority_metrics = repair_plan.get("priority_metrics") if isinstance(repair_plan.get("priority_metrics"), list) else []
        fail_metrics = _style_gate_metric_names(priority_metrics, "fail")
        warn_metrics = _style_gate_metric_names(priority_metrics, "warn")

    metrics = style_artifact.get("metrics") if isinstance(style_artifact, dict) and isinstance(style_artifact.get("metrics"), list) else []
    metric_snapshot = (
        metrics[draft_index + 1]
        if 0 <= draft_index + 1 < len(metrics) and isinstance(metrics[draft_index + 1], dict)
        else {}
    )
    quality_overrides = {
        item["metric"]: item["quality_override"]
        for item in items
        if isinstance(item, dict) and item.get("metric") and item.get("quality_override")
    }

    return {
        "status": draft.get("status") or style_gate.get("status"),
        "overall_pass": draft.get("pass") if "pass" in draft else style_gate.get("overall_pass"),
        "gate_role": STYLE_ADVISORY_ROLE,
        "advisory": True,
        "locks_scheduler": False,
        "author_revision_owner": "human_author",
        "continuation_reference_only": True,
        "profile_name": profile.get("name"),
        "target_mode": profile.get("target_mode"),
        "fail_count": draft.get("fail_count", len(fail_metrics)),
        "warn_count": draft.get("warn_count", len(warn_metrics)),
        "fail_metrics": fail_metrics,
        "warn_metrics": warn_metrics,
        "repair_plan_status": repair_plan.get("status"),
        "priority_metrics": repair_plan.get("priority_metrics") if isinstance(repair_plan.get("priority_metrics"), list) else [],
        "profile_quality": metric_snapshot.get("profile_quality"),
        "quality_overrides": quality_overrides or None,
    }


def _style_gate_draft(style_artifact: dict[str, Any], draft_index: int = 0) -> dict[str, Any]:
    style_gate = style_artifact.get("style_gate") if isinstance(style_artifact, dict) else None
    if not isinstance(style_gate, dict):
        return {}
    drafts = style_gate.get("drafts") if isinstance(style_gate.get("drafts"), list) else []
    if 0 <= draft_index < len(drafts) and isinstance(drafts[draft_index], dict):
        return drafts[draft_index]
    return {}


def _style_gate_item_map(style_artifact: dict[str, Any], draft_index: int = 0) -> dict[str, dict[str, Any]]:
    draft = _style_gate_draft(style_artifact, draft_index)
    items = draft.get("items") if isinstance(draft.get("items"), list) else []
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        metric = item.get("metric")
        if isinstance(metric, str) and metric:
            result[metric] = item
    return result


def _repair_direction_map(style_artifact: dict[str, Any], draft_index: int = 0) -> dict[str, str]:
    draft = _style_gate_draft(style_artifact, draft_index)
    repair_plan = draft.get("repair_plan") if isinstance(draft.get("repair_plan"), dict) else {}
    priorities = repair_plan.get("priority_metrics") if isinstance(repair_plan.get("priority_metrics"), list) else []
    result: dict[str, str] = {}
    for item in priorities:
        if not isinstance(item, dict):
            continue
        metric = item.get("metric")
        direction = item.get("direction")
        if isinstance(metric, str) and isinstance(direction, str):
            result[metric] = direction
    return result


def _metric_value(item: dict[str, Any]) -> float | None:
    value = item.get("value", item.get("current_value"))
    return value if isinstance(value, (int, float)) else None


def _metric_improved(before_value: float | None, after_value: float | None, direction: str) -> bool | None:
    if before_value is None or after_value is None or not direction:
        return None
    if direction == "decrease":
        return after_value < before_value
    if direction == "increase":
        return after_value > before_value
    if direction == "hold":
        return after_value == before_value
    return None


def _draft_metric_snapshot(style_artifact: dict[str, Any], draft_index: int = 0) -> dict[str, Any]:
    metrics = style_artifact.get("metrics") if isinstance(style_artifact, dict) else None
    if not isinstance(metrics, list):
        return {}
    index = draft_index + 1
    if 0 <= index < len(metrics) and isinstance(metrics[index], dict):
        return metrics[index]
    return {}


def _repair_direction_from_item(item: dict[str, Any]) -> str:
    recipe = item.get("repair_recipe") if isinstance(item.get("repair_recipe"), dict) else {}
    direction = recipe.get("direction")
    return direction if isinstance(direction, str) else ""


def _metric_proxy_state(metric: str, before_snapshot: dict[str, Any], after_snapshot: dict[str, Any]) -> dict[str, Any]:
    if metric == "avg_para":
        before_paragraphs = before_snapshot.get("paragraphs")
        after_paragraphs = after_snapshot.get("paragraphs")
        return {
            "before_paragraphs": before_paragraphs if isinstance(before_paragraphs, (int, float)) else None,
            "after_paragraphs": after_paragraphs if isinstance(after_paragraphs, (int, float)) else None,
            "paragraph_delta": (after_paragraphs - before_paragraphs)
            if isinstance(before_paragraphs, (int, float)) and isinstance(after_paragraphs, (int, float))
            else None,
            "before_chars": before_snapshot.get("chars") if isinstance(before_snapshot.get("chars"), (int, float)) else None,
            "after_chars": after_snapshot.get("chars") if isinstance(after_snapshot.get("chars"), (int, float)) else None,
        }
    if metric in {
        "environment_density",
        "exposition_density",
        "suspense_density",
        "action_density",
        "interior_density",
    }:
        quality_key = {
            "environment_density": "action_or_environment_paragraph_count",
            "exposition_density": "exposition_paragraph_count",
            "suspense_density": "suspense_paragraph_count",
        }.get(metric)
        before_quality = before_snapshot.get("profile_quality") if isinstance(before_snapshot.get("profile_quality"), dict) else {}
        after_quality = after_snapshot.get("profile_quality") if isinstance(after_snapshot.get("profile_quality"), dict) else {}
        result = {
            "before_density": before_snapshot.get(metric) if isinstance(before_snapshot.get(metric), (int, float)) else None,
            "after_density": after_snapshot.get(metric) if isinstance(after_snapshot.get(metric), (int, float)) else None,
        }
        if quality_key:
            result.update(
                {
                    f"before_{quality_key}": before_quality.get(quality_key),
                    f"after_{quality_key}": after_quality.get(quality_key),
                    f"{quality_key}_delta": (
                        after_quality.get(quality_key) - before_quality.get(quality_key)
                        if isinstance(before_quality.get(quality_key), (int, float))
                        and isinstance(after_quality.get(quality_key), (int, float))
                        else None
                    ),
                }
            )
        return result
    if metric == "dialogue_ratio":
        return {
            "before_dialogue_ratio": before_snapshot.get("dialogue_ratio")
            if isinstance(before_snapshot.get("dialogue_ratio"), (int, float))
            else None,
            "after_dialogue_ratio": after_snapshot.get("dialogue_ratio")
            if isinstance(after_snapshot.get("dialogue_ratio"), (int, float))
            else None,
        }
    return {}


def _metric_proxy_targets(metric: str, direction: str) -> list[str]:
    targets = STYLE_METRIC_PROXY_TARGETS.get(metric, {})
    values = targets.get(direction) or targets.get("hold") or []
    return list(values)


def _style_metric_delta_contract(
    *,
    before_summary: dict[str, Any],
    after_summary: dict[str, Any],
    metric_deltas: list[dict[str, Any]],
    before_snapshot: dict[str, Any],
    after_snapshot: dict[str, Any],
    before_items: dict[str, dict[str, Any]],
    after_items: dict[str, dict[str, Any]],
    before_directions: dict[str, str],
    after_directions: dict[str, str],
    added_hard_failures: list[str],
    before_score: int,
    after_score: int,
) -> dict[str, Any]:
    before_attention = set(before_summary.get("fail_metrics") or []) | set(before_summary.get("warn_metrics") or [])
    before_attention |= set(before_directions)
    after_attention = set(after_summary.get("fail_metrics") or []) | set(after_summary.get("warn_metrics") or [])

    protected_metrics: list[dict[str, Any]] = []
    protected_regressions: list[str] = []
    for item in metric_deltas:
        metric = item.get("metric")
        if not isinstance(metric, str) or metric not in before_attention:
            continue
        direction = item.get("repair_direction") or before_directions.get(metric) or _repair_direction_from_item(before_items.get(metric, {}))
        regressed = item.get("improved_toward_repair_direction") is False
        if regressed:
            protected_regressions.append(metric)
        protected_metrics.append(
            {
                "metric": metric,
                "required_direction": direction,
                "before_value": item.get("before_value"),
                "after_value": item.get("after_value"),
                "regressed": regressed,
                "reason": "metric_was_failed_warned_or_targeted_before_repair",
            }
        )

    proxy_repair_goals: list[dict[str, Any]] = []
    for metric in STYLE_GATE_METRICS:
        if metric not in after_attention and metric not in protected_regressions:
            continue
        after_item = after_items.get(metric, {})
        direction = after_directions.get(metric) or _repair_direction_from_item(after_item)
        if not direction:
            direction = "hold" if metric not in after_attention else "decrease"
        proxy_repair_goals.append(
            {
                "metric": metric,
                "severity": after_item.get("severity"),
                "direction": direction,
                "target_band": after_item.get("target_band"),
                "hard_band": after_item.get("hard_band"),
                "current_value": _metric_value(after_item),
                "proxy_targets": _metric_proxy_targets(metric, direction),
                "proxy_state": _metric_proxy_state(metric, before_snapshot, after_snapshot),
                "actions": (
                    after_item.get("repair_recipe", {}).get("actions")
                    if isinstance(after_item.get("repair_recipe"), dict)
                    else []
                ),
            }
        )

    before_chars = before_snapshot.get("chars")
    after_chars = after_snapshot.get("chars")
    size_recovered_with_regression = (
        bool(protected_regressions)
        and isinstance(before_chars, (int, float))
        and isinstance(after_chars, (int, float))
        and after_chars > before_chars
    )
    reasons: list[str] = []
    if added_hard_failures:
        reasons.append("added_hard_failures")
    if after_score > before_score:
        reasons.append("failure_score_worsened")
    if protected_regressions:
        reasons.append("protected_metric_regressed")
    if size_recovered_with_regression:
        reasons.append("length_or_size_recovery_regressed_protected_metric")
    if after_summary.get("overall_pass") is False or after_summary.get("status") == "fail":
        reasons.append("style_gate_still_failed")

    return {
        "protocol": STYLE_METRIC_DELTA_PROTOCOL,
        "schema_version": 1,
        "profile_name": after_summary.get("profile_name") or before_summary.get("profile_name"),
        "repair_required": after_summary.get("overall_pass") is False or after_summary.get("status") == "fail",
        "advisory": True,
        "locks_scheduler": False,
        "author_revision_owner": "human_author",
        "proxy_repair_goals": proxy_repair_goals,
        "protected_metrics": protected_metrics,
        "protected_metric_regressions": protected_regressions,
        "stop_conditions": {
            "block_next_chapter": False,
            "scheduler_lock": False,
            "block_blind_expansion": bool(reasons),
            "reasons": reasons,
            "added_hard_failures": added_hard_failures,
            "failure_score_worsened": after_score > before_score,
            "length_or_size_recovery_regressed_protected_metric": size_recovered_with_regression,
        },
        "no_prose_boundary": {
            "delta_contains_chapter_prose": False,
            "continuation_agent_remains_only_chapter_draft_writer": True,
            "rolling_orchestrator_must_not_rewrite_prose": True,
        },
    }


def _gate_failure_score(summary: dict[str, Any]) -> int:
    return len(summary.get("fail_metrics") or []) * 100 + len(summary.get("warn_metrics") or []) * 10


def build_style_repair_delta(
    before_artifact: dict[str, Any],
    after_artifact: dict[str, Any],
    draft_index: int = 0,
) -> dict[str, Any]:
    before_summary = summarize_style_gate_artifact(before_artifact, draft_index)
    after_summary = summarize_style_gate_artifact(after_artifact, draft_index)
    before_failures = set(before_summary.get("fail_metrics") or [])
    after_failures = set(after_summary.get("fail_metrics") or [])
    before_warnings = set(before_summary.get("warn_metrics") or [])
    after_warnings = set(after_summary.get("warn_metrics") or [])
    before_items = _style_gate_item_map(before_artifact, draft_index)
    after_items = _style_gate_item_map(after_artifact, draft_index)
    directions = _repair_direction_map(before_artifact, draft_index)
    after_directions = _repair_direction_map(after_artifact, draft_index)
    before_snapshot = _draft_metric_snapshot(before_artifact, draft_index)
    after_snapshot = _draft_metric_snapshot(after_artifact, draft_index)

    metric_deltas: list[dict[str, Any]] = []
    for metric in STYLE_GATE_METRICS:
        before_item = before_items.get(metric, {})
        after_item = after_items.get(metric, {})
        before_value = _metric_value(before_item)
        after_value = _metric_value(after_item)
        direction = directions.get(metric, "")
        metric_deltas.append(
            {
                "metric": metric,
                "before_severity": before_item.get("severity"),
                "after_severity": after_item.get("severity"),
                "before_value": before_value,
                "after_value": after_value,
                "value_delta": round(after_value - before_value, 4)
                if before_value is not None and after_value is not None
                else None,
                "repair_direction": direction,
                "next_repair_direction": after_directions.get(metric, _repair_direction_from_item(after_item)),
                "improved_toward_repair_direction": _metric_improved(before_value, after_value, direction),
                "severity_delta": SEVERITY_SCORE.get(str(after_item.get("severity")), 0)
                - SEVERITY_SCORE.get(str(before_item.get("severity")), 0),
            }
        )

    before_score = _gate_failure_score(before_summary)
    after_score = _gate_failure_score(after_summary)
    added_hard_failures = sorted(after_failures - before_failures)
    resolved_hard_failures = sorted(before_failures - after_failures)
    persistent_hard_failures = sorted(before_failures & after_failures)
    verdict = "accepted"
    if after_summary.get("overall_pass") is False or after_summary.get("status") == "fail":
        verdict = "blocked"
    if added_hard_failures or after_score > before_score:
        verdict = "regressed"

    return {
        "status": "success",
        "verdict": verdict,
        "before": before_summary,
        "after": after_summary,
        "score": {
            "before_failure_score": before_score,
            "after_failure_score": after_score,
            "delta": after_score - before_score,
        },
        "hard_failures": {
            "added": added_hard_failures,
            "resolved": resolved_hard_failures,
            "persistent": persistent_hard_failures,
        },
        "warnings": {
            "added": sorted(after_warnings - before_warnings),
            "resolved": sorted(before_warnings - after_warnings),
            "persistent": sorted(before_warnings & after_warnings),
        },
        "metric_deltas": metric_deltas,
        "style_metric_delta": _style_metric_delta_contract(
            before_summary=before_summary,
            after_summary=after_summary,
            metric_deltas=metric_deltas,
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            before_items=before_items,
            after_items=after_items,
            before_directions=directions,
            after_directions=after_directions,
            added_hard_failures=added_hard_failures,
            before_score=before_score,
            after_score=after_score,
        ),
        "acceptance": {
            "no_added_hard_failures": not added_hard_failures,
            "failure_score_not_worse": after_score <= before_score,
            "style_gate_passed": after_summary.get("overall_pass") is True or after_summary.get("status") == "pass",
        },
    }


def _compact_priority_metric(item: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in ("metric", "severity", "direction", "current_value", "target_band", "hard_band"):
        if key in item:
            result[key] = item[key]
    return result


def _compact_quality_gate_summary(summary: dict[str, Any]) -> dict[str, Any]:
    priority_metrics = summary.get("priority_metrics") if isinstance(summary.get("priority_metrics"), list) else []
    result: dict[str, Any] = {
        "status": summary.get("status"),
        "overall_pass": summary.get("overall_pass"),
        "gate_role": summary.get("gate_role"),
        "advisory": summary.get("advisory"),
        "locks_scheduler": summary.get("locks_scheduler"),
        "author_revision_owner": summary.get("author_revision_owner"),
        "continuation_reference_only": summary.get("continuation_reference_only"),
        "profile_name": summary.get("profile_name"),
        "target_mode": summary.get("target_mode"),
        "fail_count": summary.get("fail_count"),
        "warn_count": summary.get("warn_count"),
        "fail_metrics": list(summary.get("fail_metrics") or []),
        "warn_metrics": list(summary.get("warn_metrics") or []),
        "repair_plan_status": summary.get("repair_plan_status"),
        "priority_metrics": [
            _compact_priority_metric(item)
            for item in priority_metrics
            if isinstance(item, dict)
        ],
    }
    if summary.get("profile_quality") is not None:
        result["profile_quality"] = summary.get("profile_quality")
    if summary.get("quality_overrides") is not None:
        result["quality_overrides"] = summary.get("quality_overrides")
    return result


def _compact_metric_delta(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "metric": item.get("metric"),
        "before_severity": item.get("before_severity"),
        "after_severity": item.get("after_severity"),
        "before_value": item.get("before_value"),
        "after_value": item.get("after_value"),
        "value_delta": item.get("value_delta"),
        "repair_direction": item.get("repair_direction"),
        "next_repair_direction": item.get("next_repair_direction"),
        "improved_toward_repair_direction": item.get("improved_toward_repair_direction"),
        "severity_delta": item.get("severity_delta"),
    }


def _compact_repair_delta(delta: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(delta, dict) or not delta:
        return {}
    metric_deltas = delta.get("metric_deltas") if isinstance(delta.get("metric_deltas"), list) else []
    return {
        "status": delta.get("status"),
        "verdict": delta.get("verdict"),
        "score": delta.get("score") if isinstance(delta.get("score"), dict) else {},
        "hard_failures": delta.get("hard_failures") if isinstance(delta.get("hard_failures"), dict) else {},
        "warnings": delta.get("warnings") if isinstance(delta.get("warnings"), dict) else {},
        "acceptance": delta.get("acceptance") if isinstance(delta.get("acceptance"), dict) else {},
        "style_metric_delta": delta.get("style_metric_delta") if isinstance(delta.get("style_metric_delta"), dict) else {},
        "metric_deltas": [
            _compact_metric_delta(item)
            for item in metric_deltas
            if isinstance(item, dict)
        ],
        "before_source": delta.get("before_source"),
        "after_source": delta.get("after_source"),
    }


def _file_ref(path: Path, root: Path) -> dict[str, Any]:
    exists = path.exists()
    try:
        rel = str(path.relative_to(root))
    except ValueError:
        rel = str(path)
    ref: dict[str, Any] = {
        "path": rel,
        "exists": exists,
    }
    if exists:
        data = path.read_bytes()
        ref.update(
            {
                "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
            }
        )
    return ref


def _chapter_number_from_text(value: Any) -> int | None:
    text = str(value or "")
    if not text:
        return None
    for pattern in (r"(?i)\bchapter[_\-\s]?([0-9]+)(?![0-9])", r"(?i)\bch[_\-\s]?([0-9]+)(?![0-9])", r"第\s*([0-9]+)\s*章"):
        match = re.search(pattern, text)
        if match:
            return int(match.group(1))
    return None


def _target_chapter_number(plan: dict[str, Any]) -> int | None:
    quality_gate_summary = plan.get("quality_gate_summary") if isinstance(plan.get("quality_gate_summary"), dict) else {}
    for key in ("chapter_number", "target_chapter_number"):
        value = quality_gate_summary.get(key)
        if isinstance(value, int):
            return value
    if plan.get("next_action") == "await_quality_gate":
        for key in ("quality_gate_reason", "quality_gate_source", "stop_reason"):
            number = _chapter_number_from_text(plan.get(key))
            if number is not None:
                return number
        reviewed = _chapter_number_for_review(plan)
        if reviewed is not None:
            return reviewed
    selected = plan.get("selected_card_numbers") if isinstance(plan.get("selected_card_numbers"), list) else []
    selected_ints = [number for number in selected if isinstance(number, int)]
    if selected_ints:
        return min(selected_ints)
    pending = plan.get("pending_card_numbers") if isinstance(plan.get("pending_card_numbers"), list) else []
    pending_ints = [number for number in pending if isinstance(number, int)]
    if pending_ints:
        return min(pending_ints)
    return _chapter_number_for_review(plan)


def _find_card(plan: dict[str, Any], chapter_number: int | None) -> dict[str, Any]:
    if chapter_number is None:
        return {}
    cards = plan.get("cards") if isinstance(plan.get("cards"), list) else []
    for card in cards:
        if isinstance(card, dict) and card.get("number") == chapter_number:
            return card
    return {}


def _card_execution_brief(card: dict[str, Any]) -> dict[str, Any]:
    fields = card.get("fields") if isinstance(card.get("fields"), dict) else {}
    return {
        "number": card.get("number"),
        "title": card.get("title"),
        "heading_line": card.get("heading_line"),
        "end_line": card.get("end_line"),
        "executable": bool(card.get("executable")),
        "missing_fields": list(card.get("missing_fields") or []),
        "fields": {
            key: fields.get(key, "")
            for key in CHAPTER_CONTEXT_CARD_FIELDS
            if fields.get(key) is not None
        },
    }


def _decision_chain_from_card(card: dict[str, Any]) -> dict[str, Any]:
    fields = card.get("fields") if isinstance(card.get("fields"), dict) else {}
    return {
        "who_wants_what": fields.get("chapter_goal", ""),
        "entry_pressure": fields.get("entry_scene", ""),
        "obstacle": fields.get("conflict_or_obstacle", ""),
        "required_state_change": fields.get("state_change", ""),
        "payoff": fields.get("payoff", ""),
        "ending_hook": fields.get("ending_hook", ""),
    }


def _constraint_markers(card: dict[str, Any]) -> dict[str, Any]:
    fields = card.get("fields") if isinstance(card.get("fields"), dict) else {}
    texts = [
        str(fields.get("constraint_refs") or ""),
        str(fields.get("evidence_mode") or ""),
    ]
    unresolved = sorted({marker for text in texts for marker in re.findall(r"WORLD_MODEL_REQUIRED", text)})
    source_facts = sorted({marker for text in texts for marker in re.findall(r"SOURCE_FACT", text)})
    return {
        "constraint_refs": fields.get("constraint_refs", ""),
        "evidence_mode": fields.get("evidence_mode", ""),
        "unresolved_world_model_required_count": len(unresolved),
        "source_fact_marker_count": len(source_facts),
        "forbidden_promotions": [
            "WORLD_MODEL_REQUIRED_must_not_be_promoted_to_source_fact_inside_context_pack"
        ]
        if unresolved
        else [],
    }


def _active_repair_goals(repair_delta: dict[str, Any] | None) -> dict[str, Any]:
    compact = _compact_repair_delta(repair_delta if isinstance(repair_delta, dict) else {})
    style_metric_delta = compact.get("style_metric_delta") if isinstance(compact.get("style_metric_delta"), dict) else {}
    return {
        "repair_delta": compact,
        "protocol": style_metric_delta.get("protocol"),
        "advisory": style_metric_delta.get("advisory"),
        "locks_scheduler": style_metric_delta.get("locks_scheduler"),
        "author_revision_owner": style_metric_delta.get("author_revision_owner"),
        "proxy_repair_goals": style_metric_delta.get("proxy_repair_goals") or [],
        "protected_metrics": style_metric_delta.get("protected_metrics") or [],
        "protected_metric_regressions": style_metric_delta.get("protected_metric_regressions") or [],
        "stop_conditions": style_metric_delta.get("stop_conditions") if isinstance(style_metric_delta.get("stop_conditions"), dict) else {},
    }


def build_chapter_context_pack(
    *,
    plan: dict[str, Any],
    book_dir: str | Path,
    repair_delta: dict[str, Any] | None = None,
    generated_at: str = "",
    pack_id: str = "",
    gate_artifacts: list[str] | None = None,
) -> dict[str, Any]:
    """Build a derived current-chapter execution brief without reading or emitting draft prose."""
    root = Path(book_dir)
    chapter_number = _target_chapter_number(plan)
    card = _find_card(plan, chapter_number)
    quality_gate_summary = plan.get("quality_gate_summary") if isinstance(plan.get("quality_gate_summary"), dict) else {}
    style_advisory_summary = (
        plan.get("style_advisory_summary")
        if isinstance(plan.get("style_advisory_summary"), dict)
        else {}
    )
    source_refs = {
        name: _file_ref(root / name, root)
        for name in CHAPTER_CONTEXT_SOURCE_FILES
    }
    if gate_artifacts:
        source_refs["gate_artifacts"] = [
            {"path": str(path), "role": "quality_gate_or_style_advisory_evidence"}
            for path in gate_artifacts
            if str(path).strip()
        ]
    if plan.get("quality_gate_source"):
        source_refs["quality_gate_source"] = {
            "path": plan.get("quality_gate_source"),
            "role": "style_advisory_source" if plan.get("style_advisory_active") else "active_quality_gate_source",
        }

    return {
        "schema_version": 1,
        "protocol": CHAPTER_CONTEXT_PACK_PROTOCOL,
        "pack_id": pack_id,
        "generated_at": generated_at,
        "status": "success",
        "book_id": plan.get("book_id"),
        "chapter_number": chapter_number,
        "targeting": {
            "next_action": plan.get("next_action"),
            "blocked_next_action": plan.get("blocked_next_action"),
            "quality_gate_locked": bool(plan.get("quality_gate_locked")),
            "quality_gate_reason": plan.get("quality_gate_reason"),
            "quality_gate_source": plan.get("quality_gate_source"),
            "selected_card_numbers": list(plan.get("selected_card_numbers") or []),
            "pending_card_numbers": list(plan.get("pending_card_numbers") or []),
            "written_chapter_numbers": list(plan.get("written_chapter_numbers") or []),
        },
        "chapter_card": _card_execution_brief(card),
        "decision_chain": _decision_chain_from_card(card),
        "non_negotiable_facts": _constraint_markers(card),
        "truth_source_refs": source_refs,
        "quality_gate": {
            "summary": _compact_quality_gate_summary(quality_gate_summary),
            "locked": bool(plan.get("quality_gate_locked")),
            "blocks_next_action": plan.get("next_action") == "await_quality_gate",
        },
        "style_advisory": {
            "active": bool(plan.get("style_advisory_active")),
            "summary": _compact_quality_gate_summary(style_advisory_summary),
            "reference_only": True,
            "blocks_next_action": False,
            "revision_owner": "human_author",
        },
        "active_repair_goals": _active_repair_goals(repair_delta if repair_delta is not None else plan.get("repair_delta")),
        "continuation_route": {
            "agent_key": "continuation_agent",
            "target_file": "chapter_draft.md",
            "write_scope": "active_file_strict",
            "context_protocol": CHAPTER_CONTEXT_PACK_PROTOCOL,
        },
        "no_prose_boundary": {
            "pack_contains_generated_prose": False,
            "pack_reads_chapter_draft_text": False,
            "pack_replaces_outline": False,
            "pack_is_hidden_canon": False,
            "pack_is_human_approval": False,
            "continuation_agent_remains_only_chapter_draft_writer": True,
            "rolling_orchestrator_must_not_rewrite_prose": True,
        },
    }


def _chapter_number_for_review(plan: dict[str, Any]) -> int | None:
    numbers: list[Any] = []
    pending_numbers = plan.get("pending_review_chapter_numbers")
    if isinstance(pending_numbers, list):
        numbers.extend(pending_numbers)
    written_numbers = plan.get("written_chapter_numbers")
    if isinstance(written_numbers, list):
        numbers.extend(written_numbers)
    int_numbers = [number for number in numbers if isinstance(number, int)]
    return max(int_numbers) if int_numbers else None


def build_human_unlock_artifact(
    *,
    plan: dict[str, Any],
    human_actor: str,
    reason: str,
    decision: str = "approve_override",
    generated_at: str = "",
    artifact_id: str = "",
    review_packet_id: str = "",
) -> dict[str, Any]:
    """Build a bound human unlock artifact without touching prose or book files."""
    chapter_number = _chapter_number_for_review(plan)
    return {
        "schema_version": 1,
        "artifact_type": "rolling_human_unlock",
        "artifact_id": artifact_id,
        "generated_at": generated_at,
        "status": "active",
        "decision": decision,
        "human_actor": human_actor,
        "reason": reason,
        "book_id": plan.get("book_id"),
        "chapter_number": chapter_number,
        "quality_gate_source": plan.get("quality_gate_source"),
        "blocked_next_action": plan.get("blocked_next_action"),
        "quality_gate_reason": plan.get("quality_gate_reason"),
        "review_packet_id": review_packet_id,
        "review_recommendation_can_unlock": False,
        "no_prose_boundary": {
            "codex_must_not_generate_or_edit_prose": True,
            "artifact_contains_chapter_prose": False,
            "artifact_contains_outline_card_fields": False,
        },
    }


def evaluate_human_unlock(plan: dict[str, Any], human_unlock: dict[str, Any] | None) -> dict[str, Any]:
    """Return whether a human unlock artifact releases the plan's blocked action."""
    if plan.get("next_action") != "await_quality_gate" or not plan.get("blocked_next_action"):
        return {
            "status": "not_required",
            "accepted": False,
            "reasons": ["quality_gate_is_not_blocking_a_structural_action"],
        }
    if not isinstance(human_unlock, dict) or not human_unlock:
        return {
            "status": "missing",
            "accepted": False,
            "reasons": ["missing_human_unlock_artifact"],
        }

    reasons: list[str] = []
    if human_unlock.get("artifact_type") != "rolling_human_unlock":
        reasons.append("artifact_type_must_be_rolling_human_unlock")
    if human_unlock.get("status") != "active":
        reasons.append("status_must_be_active")
    if human_unlock.get("decision") != "approve_override":
        reasons.append("decision_must_be_approve_override")
    if not str(human_unlock.get("human_actor") or "").strip():
        reasons.append("human_actor_is_required")
    if not str(human_unlock.get("reason") or "").strip():
        reasons.append("reason_is_required")

    bindings = {
        "book_id": plan.get("book_id"),
        "chapter_number": _chapter_number_for_review(plan),
        "quality_gate_source": plan.get("quality_gate_source"),
        "blocked_next_action": plan.get("blocked_next_action"),
    }
    for key, expected in bindings.items():
        if expected in ("", None):
            reasons.append(f"{key}_missing")
            continue
        if human_unlock.get(key) != expected:
            reasons.append(f"{key}_mismatch")

    return {
        "status": "accepted" if not reasons else "rejected",
        "accepted": not reasons,
        "reasons": reasons,
        "artifact_id": human_unlock.get("artifact_id"),
        "decision": human_unlock.get("decision"),
        "human_actor": human_unlock.get("human_actor"),
        "bound": bindings,
    }


def build_review_packet(
    *,
    plan: dict[str, Any],
    repair_delta: dict[str, Any] | None = None,
    book_repo: dict[str, Any] | None = None,
    generated_at: str = "",
    packet_id: str = "",
) -> dict[str, Any]:
    """Build a no-prose packet for routing a rolling quality gate block to review."""
    blocked_next_action = plan.get("blocked_next_action") or ""
    quality_gate_summary = (
        plan.get("quality_gate_summary")
        if isinstance(plan.get("quality_gate_summary"), dict)
        else {}
    )
    effective_repair_delta = repair_delta if repair_delta is not None else plan.get("repair_delta")
    style_advisory_summary = (
        plan.get("style_advisory_summary")
        if isinstance(plan.get("style_advisory_summary"), dict)
        else {}
    )
    requires_human_unlock = (
        plan.get("next_action") == "await_quality_gate"
        and bool(blocked_next_action)
        and bool(plan.get("quality_gate_locked"))
    )

    return {
        "schema_version": 1,
        "status": "success",
        "packet_type": "rolling_quality_gate_review_packet",
        "packet_id": packet_id,
        "generated_at": generated_at,
        "book_id": plan.get("book_id"),
        "chapter_number": _chapter_number_for_review(plan),
        "cursor": {
            "batch_size": plan.get("batch_size"),
            "written_chapter_numbers": list(plan.get("written_chapter_numbers") or []),
            "pending_card_numbers": list(plan.get("pending_card_numbers") or []),
            "selected_card_numbers": list(plan.get("selected_card_numbers") or []),
            "outline_card_count": plan.get("outline_card_count"),
            "executable_card_count": plan.get("executable_card_count"),
            "written_chapter_count": plan.get("written_chapter_count"),
            "full_batch_available": plan.get("full_batch_available"),
            "replenishment_needed_after_selected_batch": plan.get("replenishment_needed_after_selected_batch"),
        },
        "gate": {
            "next_action": plan.get("next_action"),
            "blocked_next_action": blocked_next_action,
            "stop_reason": plan.get("stop_reason"),
            "quality_gate_locked": bool(plan.get("quality_gate_locked")),
            "quality_gate_reason": plan.get("quality_gate_reason"),
            "quality_gate_source": plan.get("quality_gate_source"),
            "quality_gate_summary": _compact_quality_gate_summary(quality_gate_summary),
        },
        "review_scope": {
            "hard_checks": [
                "plot_continuity",
                "world_status_consistency",
                "causal_chain",
                "chapter_card_fulfillment",
                "unresolved_world_model_required",
            ],
            "advisory_inputs": [
                "style_advisory_summary",
                "style_metric_delta",
            ],
            "style_is_scheduler_advisory_only": True,
            "review_agent_focus": "story_conflict_and_consistency",
        },
        "style_advisory": {
            "active": bool(plan.get("style_advisory_active")),
            "summary": _compact_quality_gate_summary(style_advisory_summary),
            "can_block_scheduler": False,
            "revision_owner": "human_author",
        },
        "repair_delta": _compact_repair_delta(effective_repair_delta if isinstance(effective_repair_delta, dict) else {}),
        "review_route": {
            "agent_key": "review_agent",
            "target_file": "chapter_draft.md",
            "read_context_files": [
                "chapter_draft.md",
                "chapter_outline.md",
                "arc_outline.md",
                "master_outline.md",
                "summary.md",
                "status_card.md",
                "world_model.md",
                "style_guide.md",
                "style_constraints_for_continuation.md",
                "error_archive.md",
                "domain_rules.md",
            ],
            "writable_files": ["error_archive.md"],
            "forbidden_write_files": ["chapter_draft.md"],
            "recommendation_only": True,
        },
        "required_recommendation_options": [
            "approve_story_continuity",
            "request_continuation_repair",
            "request_world_status_repair",
            "request_outline_replan",
            "block_story_conflict",
        ],
        "unlock_policy": {
            "requires_explicit_human_unlock": requires_human_unlock,
            "review_recommendation_can_unlock": False,
            "unlock_must_bind": [
                "book_id",
                "chapter_number",
                "quality_gate_source",
                "blocked_next_action",
            ],
        },
        "book_repo": book_repo or {},
        "no_prose_boundary": {
            "codex_must_not_generate_or_edit_prose": True,
            "packet_omits_chapter_draft_text": True,
            "packet_omits_outline_card_fields": True,
            "prose_owner": "continuation_agent",
            "review_owner": "review_agent",
            "human_unlock_owner": "human",
        },
    }


def build_rolling_plan(
    *,
    book_id: str,
    book_dir: str | Path,
    batch_size: int = 3,
    review_gate_open: bool = True,
    quality_gate_locked: bool = False,
    quality_gate_reason: str = "",
    quality_gate_source: str = "",
    quality_gate_summary: dict[str, Any] | None = None,
    human_unlock: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    root = Path(book_dir)
    outline_path = root / "chapter_outline.md"
    draft_path = root / "chapter_draft.md"
    outline_markdown = outline_path.read_text(encoding="utf-8") if outline_path.exists() else ""
    draft_markdown = draft_path.read_text(encoding="utf-8") if draft_path.exists() else "# 续写草稿\n\n"

    cards = parse_chapter_cards(outline_markdown)
    accepted = parse_archived_chapters(root)
    accepted_numbers = {chapter.number for chapter in accepted}
    draft_written = parse_written_chapters(draft_markdown)
    pending_review = [chapter for chapter in draft_written if chapter.number not in accepted_numbers]
    pending_review_numbers = {chapter.number for chapter in pending_review}
    consumed_numbers = accepted_numbers | pending_review_numbers
    pending_cards = [card for card in cards if card.number not in consumed_numbers]
    blocked_cards = [card for card in pending_cards if not card.executable]
    executable_pending = [card for card in pending_cards if card.executable]
    selected = executable_pending[:batch_size]

    if not review_gate_open:
        next_action = "await_human_review"
        stop_reason = "human_review_gate_closed"
    elif blocked_cards and (not selected or blocked_cards[0].number < selected[0].number):
        next_action = "repair_outline_cards"
        stop_reason = "next_pending_card_is_not_executable"
    elif selected:
        next_action = "continue_existing_cards"
        stop_reason = ""
    else:
        next_action = "replenish_outline"
        stop_reason = "no_executable_pending_cards"

    effective_quality_gate_summary = quality_gate_summary or {}
    style_advisory_active = effective_quality_gate_summary.get("gate_role") == STYLE_ADVISORY_ROLE
    effective_quality_gate_locked = bool(quality_gate_locked) and not style_advisory_active
    blocked_next_action = ""
    quality_gate_unlocked = False
    human_unlock_evaluation: dict[str, Any] = {}
    if review_gate_open and effective_quality_gate_locked:
        blocked_next_action = next_action
        next_action = "await_quality_gate"
        stop_reason = quality_gate_reason or "quality_gate_locked"
        provisional_plan = {
            "book_id": book_id,
            "quality_gate_source": quality_gate_source,
            "quality_gate_reason": quality_gate_reason,
            "next_action": next_action,
            "blocked_next_action": blocked_next_action,
            "written_chapter_numbers": sorted(accepted_numbers),
            "pending_review_chapter_numbers": sorted(pending_review_numbers),
        }
        human_unlock_evaluation = evaluate_human_unlock(provisional_plan, human_unlock)
        if human_unlock_evaluation.get("accepted"):
            next_action = blocked_next_action
            stop_reason = "human_unlock_accepted"
            quality_gate_unlocked = True

    selected_numbers = [card.number for card in selected]
    remaining_after_selected = [
        card.number for card in executable_pending if card.number not in set(selected_numbers)
    ]

    return {
        "status": "success",
        "book_id": book_id,
        "book_dir": str(root),
        "batch_size": batch_size,
        "review_gate_open": review_gate_open,
        "quality_gate_locked": effective_quality_gate_locked,
        "quality_gate_unlocked": quality_gate_unlocked,
        "quality_gate_reason": quality_gate_reason,
        "quality_gate_source": quality_gate_source,
        "quality_gate_summary": effective_quality_gate_summary,
        "style_advisory_active": style_advisory_active,
        "style_advisory_summary": effective_quality_gate_summary if style_advisory_active else {},
        "human_unlock_evaluation": human_unlock_evaluation,
        "next_action": next_action,
        "blocked_next_action": blocked_next_action,
        "stop_reason": stop_reason,
        "outline_card_count": len(cards),
        "executable_card_count": sum(1 for card in cards if card.executable),
        "written_chapter_count": len(accepted),
        "written_chapter_numbers": sorted(accepted_numbers),
        "accepted_chapter_count": len(accepted),
        "accepted_chapter_numbers": sorted(accepted_numbers),
        "pending_review_chapter_count": len(pending_review),
        "pending_review_chapter_numbers": sorted(pending_review_numbers),
        "pending_card_numbers": [card.number for card in pending_cards],
        "blocked_card_numbers": [card.number for card in blocked_cards],
        "selected_card_numbers": selected_numbers,
        "remaining_executable_after_selected": remaining_after_selected,
        "full_batch_available": len(selected) == batch_size,
        "replenishment_needed_after_selected_batch": bool(selected) and not remaining_after_selected,
        "cards": [card.to_dict() for card in cards],
        "written_chapters": [chapter.to_dict() for chapter in accepted],
        "accepted_chapters": [chapter.to_dict() for chapter in accepted],
        "pending_review_chapters": [chapter.to_dict() for chapter in pending_review],
        "selected_cards": [card.to_dict() for card in selected],
    }
