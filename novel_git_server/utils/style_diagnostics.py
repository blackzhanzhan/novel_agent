from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


DIALOGUE_PATTERN = re.compile(r"[“”\"'「」『』]|：")
SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?])")
CHAPTER_HEADING = re.compile(r"^##\s*第?(\d+)章[^\n]*$", re.MULTILINE)
OUTLINE_CARD_HEADING = re.compile(r"^(?:#{1,6}\s+)?章节卡\s*([0-9０-９一二两三四五六七八九十百]+)\s*[：:\-]?\s*(.*?)\s*$")
OUTLINE_FIELD = re.compile(r"^[ \t]*[-*][ \t]*([A-Za-z_]+|[\u4e00-\u9fff]+)[：:][ \t]*(.*)$")
INTERIOR_PATTERN = re.compile(r"想|觉得|意识|知道|明白|判断|怀疑|恐惧|害怕|不安|沉默|错觉|记得|忘记|心|脑|呼吸")
ACTION_PATTERN = re.compile(r"走|跑|站|坐|看|盯|转|伸|抬|按|握|推|拉|打开|关上|低头|回头|停下|靠|穿过|落下")
ENVIRONMENT_PATTERN = re.compile(r"光|灯|影|风|空气|声音|声浪|噪音|气味|温度|寒|热|墙|门|窗|地板|走廊|房间|屏幕|座椅|空间")
EXPOSITION_PATTERN = re.compile(r"因为|所以|因此|规则|流程|计划|安排|解释|说明|分析|数据|结果|意味着|本质|原因|逻辑|结构")
SUSPENSE_PATTERN = re.compile(r"但|可是|然而|忽然|突然|没有|不对|异常|奇怪|裂缝|空白|问题|为什么|仿佛|像是")

METRIC_LABELS = {
    "avg_sentence": "句式呼吸",
    "avg_para": "段落节拍",
    "dialogue_ratio": "对白推进度",
    "interior_density": "内心贴近度",
    "action_density": "动作驱动度",
    "environment_density": "环境压迫感",
    "exposition_density": "设定解释度",
    "suspense_density": "悬念留白度",
}

STYLE_TOLERANCES = {
    "avg_sentence": 0.15,
    "avg_para": 0.20,
    "dialogue_ratio": 0.25,
    "interior_density": 0.30,
    "action_density": 0.35,
    "environment_density": 0.35,
    "exposition_density": 0.35,
    "suspense_density": 0.35,
}
STYLE_HARD_MULTIPLIER = 2.0
STYLE_MAX_WARNINGS_PER_DRAFT = 2
STYLE_REPAIR_MAX_ROUNDS = 2
BRIDGE_PROFILE_QUALITY_THRESHOLDS = {
    "min_scene_bound_paragraph_ratio": 0.65,
    "min_exposition_scene_bound_ratio": 0.85,
    "min_suspense_scene_bound_ratio": 0.75,
    "min_action_or_environment_paragraph_ratio": 0.45,
    "max_exposition_over_hard_ratio": 1.75,
    "max_suspense_over_hard_ratio": 1.15,
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
BRIDGE_CORE_CUES = (
    "因果",
    "代价",
    "反噬",
    "改写",
    "机制",
    "causal",
    "cost",
    "backlash",
    "rewrite",
    "mechanism",
)
BRIDGE_SUPPORT_CUES = (
    "WORLD_MODEL_REQUIRED",
    "解释",
    "说明",
    "规则",
    "逻辑",
    "结构",
    "流程",
    "权柄",
    "权限",
    "bridge",
    "exposition",
    "rule",
    "constraint",
    "system",
)
CHOICE_ARC_TAIL_CUES = (
    "弧尾",
    "兑现",
    "解除",
    "下一个单元",
    "arc-tail",
    "arc tail",
    "resolution",
    "resolve",
)
CHOICE_DECISION_CUES = (
    "抉择",
    "选择",
    "第三条路",
    "放弃",
    "保留",
    "守护",
    "控制指令",
    "choice",
    "third path",
    "sacrifice",
    "command",
)
CHOICE_COST_CUES = (
    "代价",
    "因果",
    "记忆",
    "锁定",
    "控制者",
    "cost",
    "memory",
    "lock",
    "controller",
)

NO_PROSE_REWRITE_CONSTRAINTS = [
    "current_chapter_only",
    "preserve_outline_facts",
    "preserve_world_state",
    "preserve_character_motivation",
    "preserve_result_and_causality",
]

METRIC_REPAIR_ACTIONS = {
    "avg_para": {
        "increase": ["merge_adjacent_micro_paragraphs", "keep_one_action_chain_in_one_paragraph"],
        "decrease": ["split_long_paragraphs_at_decision_beats", "add_breathing_breaks_between_action_and_reaction"],
    },
    "avg_sentence": {
        "increase": ["merge_choppy_sentences", "extend_causal_and_sensory_links"],
        "decrease": ["split_overloaded_sentences", "move_explanations_into_separate_beats"],
    },
    "dialogue_ratio": {
        "increase": ["turn_summary_into_character_exchange", "let_conflict_surface_in_spoken_lines"],
        "decrease": ["replace_q_and_a_with_action_reaction", "move_information_into_space_and_body_cues"],
    },
    "interior_density": {
        "increase": ["add_brief_judgment_beats", "show_pressure_through_character_choice"],
        "decrease": ["externalize_repeated_thoughts", "replace_named_emotion_with_observable_action"],
    },
    "action_density": {
        "increase": ["anchor_information_in_physical_movement", "add_cause_and_effect_stage_business"],
        "decrease": ["merge_redundant_motions", "keep_only_actions_that_change_pressure"],
    },
    "environment_density": {
        "increase": ["add_specific_space_light_sound_cues", "tie_setting_to_character_decision"],
        "decrease": ["delete_atmosphere_only_cues", "keep_setting_details_that_change_choice"],
    },
    "exposition_density": {
        "increase": ["add_only_missing_rule_context", "bind_explanation_to_immediate_cost"],
        "decrease": ["convert_explanation_to_scene_conflict", "replace_abstract_logic_with_concrete_consequence"],
    },
    "suspense_density": {
        "increase": ["leave_one_unresolved_signal", "delay_complete_explanation_until_scene_turn"],
        "decrease": ["resolve_redundant_question_marks", "keep_only_one_open_hook_per_beat"],
    },
}

STYLE_GATE_PROFILES = {
    "opening_continuation": {
        "name": "opening_continuation",
        "target_mode": "rhythm_first_scene_execution",
        "priority_order": [
            "avg_para",
            "avg_sentence",
            "exposition_density",
            "dialogue_ratio",
            "suspense_density",
            "interior_density",
            "environment_density",
            "action_density",
        ],
        "strategy": [
            "stabilize_paragraph_rhythm_before_adding_material",
            "turn_exposition_into_scene_pressure",
            "keep_suspense_to_one_open_signal_per_beat",
        ],
    },
    "standard_continuation": {
        "name": "standard_continuation",
        "target_mode": "scene_balance_and_continuity",
        "priority_order": [
            "avg_para",
            "dialogue_ratio",
            "action_density",
            "environment_density",
            "interior_density",
            "avg_sentence",
            "exposition_density",
            "suspense_density",
        ],
        "strategy": [
            "preserve_existing_scene_causality",
            "balance_dialogue_action_environment_before_polishing",
            "avoid_solving_metric_drift_by_changing_plot_facts",
        ],
    },
    "bridge_exposition_continuation": {
        "name": "bridge_exposition_continuation",
        "target_mode": "causal_bridge_scene_execution",
        "priority_order": [
            "avg_para",
            "exposition_density",
            "avg_sentence",
            "dialogue_ratio",
            "environment_density",
            "interior_density",
            "action_density",
            "suspense_density",
        ],
        "strategy": [
            "preserve_outline_causal_cost_chain",
            "bind_exposition_to_immediate_choice_and_consequence",
            "treat_profile_as_gate_specialization_not_bypass",
        ],
        "tolerances": {
            **STYLE_TOLERANCES,
            "avg_para": 0.90,
            "avg_sentence": 0.30,
            "dialogue_ratio": 0.50,
            "environment_density": 0.45,
            "exposition_density": 0.90,
        },
        "hard_multiplier": 1.2,
        "max_warnings_per_draft": 4,
        "quality_thresholds": BRIDGE_PROFILE_QUALITY_THRESHOLDS,
    },
    "arc_tail_choice_continuation": {
        "name": "arc_tail_choice_continuation",
        "target_mode": "choice_resolution_scene_execution",
        "priority_order": [
            "dialogue_ratio",
            "suspense_density",
            "avg_para",
            "interior_density",
            "action_density",
            "environment_density",
            "avg_sentence",
            "exposition_density",
        ],
        "strategy": [
            "preserve_outline_final_choice_and_cost",
            "allow_dialogue_pressure_when_choice_resolution_is_the_chapter_role",
            "treat_next_unit_hooks_as_tracked_warnings_before_hard_failure",
            "treat_profile_as_gate_specialization_not_bypass",
        ],
        "tolerances": {
            **STYLE_TOLERANCES,
            "avg_para": 1.10,
            "avg_sentence": 0.30,
            "dialogue_ratio": 0.55,
            "suspense_density": 0.45,
            "exposition_density": 0.60,
        },
        "hard_multiplier": 1.6,
        "max_warnings_per_draft": 3,
    },
}


@dataclass(frozen=True)
class StyleMetrics:
    label: str
    chars: int
    paragraphs: int
    avg_para: float
    sentences: int
    avg_sentence: float
    dialogue_ratio: float
    interior_density: float
    action_density: float
    environment_density: float
    exposition_density: float
    suspense_density: float
    profile_quality: dict[str, Any] = field(default_factory=dict)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _strip_markdown_headings(text: str) -> str:
    return re.sub(r"(?m)^#{1,6}\s+.*$", "", text).strip()


def _split_paragraphs(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]


def _non_space_count(text: str) -> int:
    return len(re.findall(r"\S", text))


def _density_per_1000(pattern: re.Pattern[str], text: str, chars: int) -> float:
    if chars <= 0:
        return 0.0
    return round(len(pattern.findall(text)) / chars * 1000, 1)


def _safe_ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _profile_quality_for_body(body: str) -> dict[str, Any]:
    paragraphs = _split_paragraphs(body)
    paragraph_count = len(paragraphs)
    scene_bound_count = 0
    action_or_environment_count = 0
    exposition_count = 0
    exposition_scene_bound_count = 0
    suspense_count = 0
    suspense_scene_bound_count = 0

    for paragraph in paragraphs:
        has_dialogue = bool(DIALOGUE_PATTERN.search(paragraph))
        has_action = bool(ACTION_PATTERN.search(paragraph))
        has_environment = bool(ENVIRONMENT_PATTERN.search(paragraph))
        has_interior = bool(INTERIOR_PATTERN.search(paragraph))
        has_scene_anchor = has_dialogue or has_action or has_environment or has_interior
        has_exposition = bool(EXPOSITION_PATTERN.search(paragraph))
        has_suspense = bool(SUSPENSE_PATTERN.search(paragraph))

        scene_bound_count += int(has_scene_anchor)
        action_or_environment_count += int(has_action or has_environment)
        exposition_count += int(has_exposition)
        exposition_scene_bound_count += int(has_exposition and has_scene_anchor)
        suspense_count += int(has_suspense)
        suspense_scene_bound_count += int(has_suspense and has_scene_anchor)

    return {
        "paragraph_count": paragraph_count,
        "scene_bound_paragraph_count": scene_bound_count,
        "scene_bound_paragraph_ratio": _safe_ratio(scene_bound_count, paragraph_count),
        "action_or_environment_paragraph_count": action_or_environment_count,
        "action_or_environment_paragraph_ratio": _safe_ratio(action_or_environment_count, paragraph_count),
        "exposition_paragraph_count": exposition_count,
        "exposition_scene_bound_count": exposition_scene_bound_count,
        "exposition_scene_bound_ratio": _safe_ratio(exposition_scene_bound_count, exposition_count),
        "suspense_paragraph_count": suspense_count,
        "suspense_scene_bound_count": suspense_scene_bound_count,
        "suspense_scene_bound_ratio": _safe_ratio(suspense_scene_bound_count, suspense_count),
    }


def metric_for(text: str, label: str) -> StyleMetrics:
    body = _strip_markdown_headings(text)
    paragraphs = _split_paragraphs(body)
    sentences = [item.strip() for item in SENTENCE_SPLIT.split(body) if item.strip()]
    chars = _non_space_count(body)
    dialogue_count = sum(1 for paragraph in paragraphs if DIALOGUE_PATTERN.search(paragraph))
    return StyleMetrics(
        label=label,
        chars=chars,
        paragraphs=len(paragraphs),
        avg_para=round(chars / len(paragraphs), 1) if paragraphs else 0.0,
        sentences=len(sentences),
        avg_sentence=round(chars / len(sentences), 1) if sentences else 0.0,
        dialogue_ratio=round(dialogue_count / len(paragraphs), 2) if paragraphs else 0.0,
        interior_density=_density_per_1000(INTERIOR_PATTERN, body, chars),
        action_density=_density_per_1000(ACTION_PATTERN, body, chars),
        environment_density=_density_per_1000(ENVIRONMENT_PATTERN, body, chars),
        exposition_density=_density_per_1000(EXPOSITION_PATTERN, body, chars),
        suspense_density=_density_per_1000(SUSPENSE_PATTERN, body, chars),
        profile_quality=_profile_quality_for_body(body),
    )


def latest_chapter_files(book_dir: Path, count: int) -> list[Path]:
    chapters_dir = book_dir / "chapters"
    if not chapters_dir.exists():
        return []
    return sorted(chapters_dir.glob("*.md"))[-max(0, count):]


def _parse_outline_chapter_number(raw: str) -> int | None:
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


def _split_outline_cards(markdown: str) -> list[tuple[int, int, int, str]]:
    lines = markdown.splitlines()
    headings: list[tuple[int, int, str]] = []
    for index, line in enumerate(lines):
        match = OUTLINE_CARD_HEADING.match(line.strip())
        if not match:
            continue
        number = _parse_outline_chapter_number(match.group(1))
        if number is None:
            continue
        headings.append((index, number, match.group(2).strip()))

    cards: list[tuple[int, int, int, str]] = []
    for index, (start, number, title) in enumerate(headings):
        end = headings[index + 1][0] if index + 1 < len(headings) else len(lines)
        cards.append((number, start + 1, end, title))
    return cards


def _extract_outline_fields(lines: list[str]) -> dict[str, str]:
    fields: dict[str, str] = {}
    active_key: str | None = None
    for line in lines:
        match = OUTLINE_FIELD.match(line)
        if match:
            active_key = match.group(1).strip()
            fields[active_key] = match.group(2).strip()
            continue
        if active_key and line.startswith((" ", "\t")) and line.strip():
            fields[active_key] = f"{fields[active_key]}\n{line.strip()}".strip()
    return fields


def parse_chapter_outline_evidence(markdown: str) -> dict[int, dict[str, Any]]:
    lines = markdown.splitlines()
    evidence: dict[int, dict[str, Any]] = {}
    for number, heading_line, end_line, title in _split_outline_cards(markdown):
        fields = _extract_outline_fields(lines[heading_line:end_line])
        evidence[number] = {
            "number": number,
            "title": title,
            "heading_line": heading_line,
            "end_line": end_line,
            "fields": fields,
        }
    return evidence


def extract_draft_chapters(draft_text: str, chapter_numbers: set[int] | None = None) -> list[tuple[str, str]]:
    matches = list(CHAPTER_HEADING.finditer(draft_text))
    if not matches:
        stripped = draft_text.strip()
        return [("当前草稿", stripped)] if stripped else []
    sections: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        chapter_no = int(match.group(1))
        if chapter_numbers and chapter_no not in chapter_numbers:
            continue
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(draft_text)
        heading = match.group(0).lstrip("#").strip()
        sections.append((heading, draft_text[start:end].strip()))
    return sections


def parse_chapter_numbers(raw_value: Any) -> set[int] | None:
    if raw_value is None or raw_value == "":
        return None
    if isinstance(raw_value, list):
        numbers = raw_value
    else:
        numbers = str(raw_value).replace("，", ",").split(",")
    parsed: set[int] = set()
    for item in numbers:
        try:
            parsed.add(int(str(item).strip()))
        except ValueError:
            continue
    return parsed or None


def _percent(value: float) -> str:
    return f"{value * 100:.0f}%"


def _metric_state(value: float, baseline: float, tolerance: float) -> tuple[str, float]:
    if baseline == 0:
        return "缺少基准", 0.0
    delta = (value - baseline) / baseline
    if delta > tolerance:
        return f"偏高 {delta * 100:.0f}%", delta
    if delta < -tolerance:
        return f"偏低 {abs(delta) * 100:.0f}%", delta
    return "接近", delta


def _band(value: float, tolerance: float) -> str:
    low = round(value * (1 - tolerance), 2)
    high = round(value * (1 + tolerance), 2)
    return f"{low} - {high}"


def _band_values(value: float, tolerance: float) -> dict[str, float]:
    return {
        "low": round(value * (1 - tolerance), 2),
        "high": round(value * (1 + tolerance), 2),
    }


def _repair_direction(delta: float) -> str:
    if delta > 0:
        return "decrease"
    if delta < 0:
        return "increase"
    return "hold"


def _repair_recipe(metric: str, delta: float, baseline_value: float, target_band: dict[str, float]) -> dict[str, Any]:
    direction = _repair_direction(delta)
    return {
        "metric": metric,
        "direction": direction,
        "target_band": target_band,
        "baseline": baseline_value,
        "priority": "none" if direction == "hold" else "required",
        "actions": METRIC_REPAIR_ACTIONS.get(metric, {}).get(direction, []),
        "constraints": NO_PROSE_REWRITE_CONSTRAINTS,
    }


def _opening_metric_couplings(items: list[dict[str, Any]], profile: dict[str, Any]) -> list[dict[str, Any]]:
    if profile["name"] != "opening_continuation":
        return []
    by_metric = {item["metric"]: item for item in items}
    avg_para = by_metric.get("avg_para")
    avg_sentence = by_metric.get("avg_sentence")
    if avg_para is None or avg_sentence is None:
        return []
    return [
        {
            "metrics": ["avg_para", "avg_sentence"],
            "shared_goal": "stabilize_paragraph_rhythm_before_sentence_polishing",
            "split_trigger": "Only split a paragraph beat when the new beat keeps avg_sentence inside its target band.",
            "merge_trigger": "Only merge sentences when the paragraph rhythm keeps avg_para inside its target band.",
            "joint_revalidation": ["avg_para", "avg_sentence"],
            "target_bands": {
                "avg_para": avg_para["target_band"],
                "avg_sentence": avg_sentence["target_band"],
            },
        }
    ]


def _chapter_number_from_label(label: str) -> int | None:
    match = re.search(r"(\d+)", label)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _outline_profile_text(evidence: dict[str, Any] | None) -> str:
    if not evidence:
        return ""
    fields = evidence.get("fields") if isinstance(evidence.get("fields"), dict) else {}
    parts = [str(evidence.get("title") or "")]
    for key in (
        "chapter_goal",
        "conflict_or_obstacle",
        "payoff",
        "state_change",
        "foreshadowing_action",
        "ending_hook",
        "constraint_refs",
        "evidence_mode",
    ):
        parts.append(str(fields.get(key) or ""))
    return "\n".join(parts)


def _arc_tail_choice_profile_match(evidence: dict[str, Any] | None) -> dict[str, Any] | None:
    text = _outline_profile_text(evidence)
    if not text:
        return None
    text_lower = text.lower()
    arc_tail_matches = sorted({cue for cue in CHOICE_ARC_TAIL_CUES if cue.lower() in text_lower})
    decision_matches = sorted({cue for cue in CHOICE_DECISION_CUES if cue.lower() in text_lower})
    cost_matches = sorted({cue for cue in CHOICE_COST_CUES if cue.lower() in text_lower})
    if not arc_tail_matches or len(decision_matches) < 2 or not cost_matches:
        return None
    return {
        "source": "chapter_outline.md",
        "reason": "outline_card_arc_tail_choice_cues",
        "chapter_card_number": evidence.get("number") if evidence else None,
        "matched_arc_tail_cues": arc_tail_matches,
        "matched_decision_cues": decision_matches,
        "matched_cost_cues": cost_matches,
    }


def _bridge_profile_match(evidence: dict[str, Any] | None) -> dict[str, Any] | None:
    text = _outline_profile_text(evidence)
    if not text:
        return None
    text_lower = text.lower()
    core_matches = sorted({cue for cue in BRIDGE_CORE_CUES if cue.lower() in text_lower})
    support_matches = sorted({cue for cue in BRIDGE_SUPPORT_CUES if cue.lower() in text_lower})
    if not core_matches or not (len(core_matches) >= 2 or support_matches):
        return None
    return {
        "source": "chapter_outline.md",
        "reason": "outline_card_bridge_exposition_cues",
        "chapter_card_number": evidence.get("number"),
        "matched_core_cues": core_matches,
        "matched_support_cues": support_matches,
    }


def _profile_tolerances(profile: dict[str, Any]) -> dict[str, float]:
    return {**STYLE_TOLERANCES, **profile.get("tolerances", {})}


def _style_profile_for_draft(
    draft: StyleMetrics,
    chapter_outline_evidence: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    chapter_number = _chapter_number_from_label(draft.label)
    profile_key = "opening_continuation" if chapter_number == 1 else "standard_continuation"
    selection_basis: dict[str, Any] = {
        "source": "chapter_number",
        "reason": "opening_chapter" if chapter_number == 1 else "default_continuation",
    }
    if chapter_number not in {None, 1}:
        evidence = (chapter_outline_evidence or {}).get(chapter_number)
        outline_match = _arc_tail_choice_profile_match(evidence)
        if outline_match:
            profile_key = "arc_tail_choice_continuation"
            selection_basis = outline_match
        else:
            outline_match = _bridge_profile_match(evidence)
        if profile_key == "standard_continuation" and outline_match:
            profile_key = "bridge_exposition_continuation"
            selection_basis = outline_match
    profile = STYLE_GATE_PROFILES[profile_key]
    return {
        "name": profile["name"],
        "target_mode": profile["target_mode"],
        "chapter_number": chapter_number,
        "priority_order": profile["priority_order"],
        "strategy": profile["strategy"],
        "tolerances": _profile_tolerances(profile),
        "hard_multiplier": profile.get("hard_multiplier", STYLE_HARD_MULTIPLIER),
        "max_warnings_per_draft": profile.get("max_warnings_per_draft", STYLE_MAX_WARNINGS_PER_DRAFT),
        "quality_thresholds": profile.get("quality_thresholds", {}),
        "selection_basis": selection_basis,
    }


def _style_gate_item(baseline: StyleMetrics, draft: StyleMetrics, key: str, profile: dict[str, Any]) -> dict[str, Any]:
    label = METRIC_LABELS[key]
    baseline_value = float(getattr(baseline, key))
    value = float(getattr(draft, key))
    tolerance = profile.get("tolerances", STYLE_TOLERANCES).get(key, STYLE_TOLERANCES[key])
    hard_multiplier = profile.get("hard_multiplier", STYLE_HARD_MULTIPLIER)
    hard_tolerance = tolerance * hard_multiplier

    if baseline_value == 0:
        delta = 0.0
        severity = "pass" if value == 0 else "warn"
        status = "缺少可比基准" if value == 0 else "原文基准为 0，草稿出现该特征"
    else:
        delta = (value - baseline_value) / baseline_value
        abs_delta = abs(delta)
        if abs_delta > hard_tolerance:
            severity = "fail"
        elif abs_delta > tolerance:
            severity = "warn"
        else:
            severity = "pass"
        status, _ = _metric_state(value, baseline_value, tolerance)

    target_band = _band_values(baseline_value, tolerance)
    explanation = _review_explanation(label, status)
    repair_recipe = _repair_recipe(key, delta, baseline_value, target_band)
    quality_override = _bridge_quality_override(
        draft=draft,
        key=key,
        profile=profile,
        severity=severity,
        value=value,
        hard_band=_band_values(baseline_value, hard_tolerance),
    )
    if quality_override:
        severity = quality_override["severity"]
    return {
        "metric": key,
        "metric_label": label,
        "value": value,
        "baseline": baseline_value,
        "target_band": target_band,
        "hard_band": _band_values(baseline_value, hard_tolerance),
        "relative_delta": round(delta, 4),
        "status": status,
        "severity": severity,
        "recommendation": explanation,
        "repair_recipe": repair_recipe,
        "quality_override": quality_override,
    }


def _bridge_quality_override(
    *,
    draft: StyleMetrics,
    key: str,
    profile: dict[str, Any],
    severity: str,
    value: float,
    hard_band: dict[str, float],
) -> dict[str, Any] | None:
    if profile.get("name") != "bridge_exposition_continuation":
        return None
    if severity != "fail" or key not in {"exposition_density", "suspense_density"}:
        return None

    thresholds = profile.get("quality_thresholds") or {}
    quality = draft.profile_quality or {}
    hard_high = float(hard_band.get("high") or 0.0)
    over_hard_ratio = round(value / hard_high, 4) if hard_high > 0 else 0.0

    checks = {
        "scene_bound_paragraph_ratio": quality.get("scene_bound_paragraph_ratio", 0.0)
        >= thresholds.get("min_scene_bound_paragraph_ratio", 1.0),
        "action_or_environment_paragraph_ratio": quality.get("action_or_environment_paragraph_ratio", 0.0)
        >= thresholds.get("min_action_or_environment_paragraph_ratio", 1.0),
    }
    if key == "exposition_density":
        checks["exposition_scene_bound_ratio"] = quality.get("exposition_scene_bound_ratio", 0.0) >= thresholds.get(
            "min_exposition_scene_bound_ratio",
            1.0,
        )
        checks["exposition_over_hard_ratio"] = over_hard_ratio <= thresholds.get("max_exposition_over_hard_ratio", 0.0)
    else:
        checks["suspense_scene_bound_ratio"] = quality.get("suspense_scene_bound_ratio", 0.0) >= thresholds.get(
            "min_suspense_scene_bound_ratio",
            1.0,
        )
        checks["suspense_over_hard_ratio"] = over_hard_ratio <= thresholds.get("max_suspense_over_hard_ratio", 0.0)

    if not all(checks.values()):
        return None
    return {
        "status": "downgraded_to_warning",
        "severity": "warn",
        "reason": "bridge_profile_scene_bound_exposition_or_suspense",
        "metric": key,
        "quality": quality,
        "thresholds": thresholds,
        "checks": checks,
        "over_hard_ratio": over_hard_ratio,
    }


def _build_repair_plan(
    fail_items: list[dict[str, Any]],
    warn_items: list[dict[str, Any]],
    profile: dict[str, Any],
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    ordered = [*fail_items, *warn_items]
    priority_rank = {metric: index for index, metric in enumerate(profile["priority_order"])}
    ordered = sorted(
        ordered,
        key=lambda item: (
            0 if item["severity"] == "fail" else 1,
            priority_rank.get(item["metric"], len(priority_rank)),
            -abs(float(item.get("relative_delta", 0.0))),
        ),
    )
    return {
        "status": "not_needed" if not ordered else "required",
        "max_rounds": STYLE_REPAIR_MAX_ROUNDS,
        "rewrite_scope": "current_chapter_only",
        "rewrite_constraints": NO_PROSE_REWRITE_CONSTRAINTS,
        "gate_profile": profile,
        "metric_couplings": _opening_metric_couplings(items, profile),
        "priority_metrics": [
            {
                "metric": item["metric"],
                "metric_label": item["metric_label"],
                "severity": item["severity"],
                "direction": item["repair_recipe"]["direction"],
                "target_band": item["target_band"],
                "hard_band": item["hard_band"],
                "current_value": item["value"],
                "relative_delta": item["relative_delta"],
                "actions": item["repair_recipe"]["actions"],
            }
            for item in ordered
        ],
        "stop_condition": "rerun_length_and_style_gates_after_each_rewrite; stop_after_max_rounds_if_any_priority_metric_remains_failed",
    }


def build_style_gate(
    metrics: list[StyleMetrics],
    chapter_outline_evidence: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not metrics:
        return {
            "status": "not_applicable",
            "overall_pass": False,
            "reason": "暂无原文基准。",
            "baseline": None,
            "drafts": [],
            "tolerances": STYLE_TOLERANCES,
            "hard_multiplier": STYLE_HARD_MULTIPLIER,
            "max_warnings_per_draft": STYLE_MAX_WARNINGS_PER_DRAFT,
        }

    baseline = metrics[0]
    drafts = metrics[1:]
    if not drafts:
        return {
            "status": "baseline_only",
            "overall_pass": True,
            "reason": "已建立原文基准，暂无草稿样本。",
            "baseline": asdict(baseline),
            "drafts": [],
            "tolerances": STYLE_TOLERANCES,
            "hard_multiplier": STYLE_HARD_MULTIPLIER,
            "max_warnings_per_draft": STYLE_MAX_WARNINGS_PER_DRAFT,
        }

    draft_results: list[dict[str, Any]] = []
    for draft in drafts:
        profile = _style_profile_for_draft(draft, chapter_outline_evidence)
        items = [_style_gate_item(baseline, draft, key, profile) for key in METRIC_LABELS]
        fail_items = [item for item in items if item["severity"] == "fail"]
        warn_items = [item for item in items if item["severity"] == "warn"]
        max_warnings = profile.get("max_warnings_per_draft", STYLE_MAX_WARNINGS_PER_DRAFT)
        draft_pass = not fail_items and len(warn_items) <= max_warnings
        draft_results.append(
            {
                "label": draft.label,
                "status": "pass" if draft_pass else "fail",
                "pass": draft_pass,
                "fail_count": len(fail_items),
                "warn_count": len(warn_items),
                "gate_profile": profile,
                "red_flags": [
                    {
                        "metric": item["metric"],
                        "metric_label": item["metric_label"],
                        "status": item["status"],
                        "recommendation": item["recommendation"],
                        "repair_recipe": item["repair_recipe"],
                        "quality_override": item.get("quality_override"),
                    }
                    for item in [*fail_items, *warn_items]
                ],
                "repair_plan": _build_repair_plan(fail_items, warn_items, profile, items),
                "items": items,
            }
        )

    overall_pass = all(item["pass"] for item in draft_results)
    return {
        "status": "pass" if overall_pass else "fail",
        "overall_pass": overall_pass,
        "reason": "全部草稿处于硬门禁内。" if overall_pass else "至少一个草稿章节触发文风漂移门禁。",
        "baseline": asdict(baseline),
        "drafts": draft_results,
        "tolerances": STYLE_TOLERANCES,
        "hard_multiplier": STYLE_HARD_MULTIPLIER,
        "max_warnings_per_draft": STYLE_MAX_WARNINGS_PER_DRAFT,
    }


def _markdown_table(rows: list[StyleMetrics]) -> str:
    lines = [
        "| 样本 | 非空字符 | 段落数 | 句式呼吸 | 段落节拍 | 对白推进度 | 内心贴近度 | 动作驱动度 | 环境压迫感 | 设定解释度 | 悬念留白度 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| {label} | {chars} | {paragraphs} | {avg_sentence} | {avg_para} | "
            "{dialogue_ratio:.2f} | {interior_density} | {action_density} | "
            "{environment_density} | {exposition_density} | {suspense_density} |".format(**asdict(row))
        )
    return "\n".join(lines)


def _baseline_snapshot_lines(baseline: StyleMetrics) -> list[str]:
    return [
        f"- 样本标签：{baseline.label}",
        f"- 非空字符：{baseline.chars}",
        f"- 段落数：{baseline.paragraphs}",
        f"- 句式呼吸：{baseline.avg_sentence}",
        f"- 段落节拍：{baseline.avg_para}",
        f"- 对白推进度：{_percent(baseline.dialogue_ratio)}",
        f"- 内心贴近度：{baseline.interior_density}/千字",
        f"- 动作驱动度：{baseline.action_density}/千字",
        f"- 环境压迫感：{baseline.environment_density}/千字",
        f"- 设定解释度：{baseline.exposition_density}/千字",
        f"- 悬念留白度：{baseline.suspense_density}/千字",
    ]


def _baseline_snapshot_json_block(baseline: StyleMetrics) -> str:
    return "\n".join(
        [
            "## 作者视图基准 JSON",
            "",
            "```json",
            json.dumps(asdict(baseline), ensure_ascii=False, indent=2),
            "```",
        ]
    )


def _review_explanation(name: str, state: str) -> str:
    high = {
        "对白推进度": "人物更依赖说话推进，容易削弱场景、动作和沉默的叙事重量。",
        "句式呼吸": "句子更长，压迫感可能增强，但过高会拖慢阅读。",
        "段落节拍": "段落更重，换气点减少，容易形成大块堆叙。",
        "内心贴近度": "人物判断和心理反应更密，适合高压段，但过高会变成解释情绪。",
        "动作驱动度": "身体动作更密，场面更动，但过高会显得调度忙乱。",
        "环境压迫感": "空间、声音、光线等承托更强，但过高会抢人物戏。",
        "设定解释度": "解释和分析更密，容易从场景滑向说明书。",
        "悬念留白度": "转折和异常感更密，但过高会让节奏焦虑。",
    }
    low = {
        "对白推进度": "人物说话更少，若场景和动作跟不上，信息会显得断裂。",
        "句式呼吸": "句子更短，节奏更快，但可能缺少原文的持续铺压。",
        "段落节拍": "段落更碎，换气更频繁，但可能削弱沉浸感。",
        "内心贴近度": "人物内在判断不足，读者可能只看到事件，看不到压力如何穿过人物。",
        "动作驱动度": "身体动作较少，场景可能停留在概述层。",
        "环境压迫感": "空间和感官承托不足，容易变成信息复述。",
        "设定解释度": "说明负担较轻，通常不是问题，除非读者理解剧情所需信息不足。",
        "悬念留白度": "异常感和信息缺口偏少，章节钩子可能不足。",
    }
    if state.startswith("偏高"):
        return high.get(name, "")
    if state.startswith("偏低"):
        return low.get(name, "")
    return f"{name}与原文近段样本接近。"


def build_style_fingerprint(book_dir: Path, source_count: int, metrics: list[StyleMetrics], source_files: list[Path]) -> str:
    source_label = ", ".join(path.name for path in source_files) if source_files else "无可用原文章节"
    return "\n".join(
        [
            "# 叙事结构指纹",
            "",
            "## 输入样本",
            "",
            f"- 书库：`{book_dir}`",
            f"- 原文采样：最近 {len(source_files)} / 请求 {source_count} 章",
            f"- 原文章节：{source_label}",
            "",
            "## 中文指标表",
            "",
            "指标说明：句式呼吸/段落节拍为平均长度；对白推进度为对话段占比；其余为每千字触发密度。",
            "",
            _markdown_table(metrics),
            "",
            "## 机器可读快照",
            "",
            "```json",
            json.dumps([asdict(row) for row in metrics], ensure_ascii=False, indent=2),
            "```",
            "",
        ]
    )


def _style_gate_markdown(gate: dict[str, Any]) -> str:
    lines = [
        "## 机器门禁摘要",
        "",
        f"- 总体状态：{gate.get('status', 'unknown')}",
        f"- 判定说明：{gate.get('reason', '')}",
        f"- 软偏差上限：每章最多 {gate.get('max_warnings_per_draft', STYLE_MAX_WARNINGS_PER_DRAFT)} 项；硬偏差倍率：{gate.get('hard_multiplier', STYLE_HARD_MULTIPLIER)}。",
        "",
    ]
    for draft in gate.get("drafts", []):
        lines.extend(
            [
                f"### {draft.get('label', '草稿')}",
                "",
                f"- 门禁 profile：{(draft.get('gate_profile') or {}).get('name', 'unknown')}",
                f"- 状态：{draft.get('status')}；硬失败 {draft.get('fail_count', 0)} 项，软警告 {draft.get('warn_count', 0)} 项。",
            ]
        )
        red_flags = draft.get("red_flags") or []
        if red_flags:
            for item in red_flags:
                lines.append(f"- {item['metric_label']}：{item['status']}。{item['recommendation']}")
        else:
            lines.append("- 未触发文风漂移红旗。")
        lines.append("")
    return "\n".join(lines)


def build_style_review(metrics: list[StyleMetrics], source_count: int, gate: dict[str, Any] | None = None) -> str:
    if not metrics:
        return "# 作者可读审查\n\n暂无可审查样本。\n"
    baseline = metrics[0]
    drafts = metrics[1:]
    lines = [
        "# 作者可读审查",
        "",
        "## 原文近段基准",
        "",
        f"- 对照样本：最近 {source_count} 章原文",
        f"- 句式呼吸：{baseline.avg_sentence}",
        f"- 段落节拍：{baseline.avg_para}",
        f"- 对白推进度：{_percent(baseline.dialogue_ratio)}",
        f"- 内心贴近度：{baseline.interior_density}/千字",
        f"- 动作驱动度：{baseline.action_density}/千字",
        f"- 环境压迫感：{baseline.environment_density}/千字",
        f"- 设定解释度：{baseline.exposition_density}/千字",
        f"- 悬念留白度：{baseline.suspense_density}/千字",
        "",
        _baseline_snapshot_json_block(baseline),
        "",
    ]
    if not drafts:
        lines.extend(["## 审查结论", "", "当前没有草稿样本，本轮只建立原文叙事结构基准。", ""])
        return "\n".join(lines)

    gate = gate or build_style_gate(metrics)
    lines.extend([_style_gate_markdown(gate), ""])
    lines.extend(["## 草稿偏差诊断", ""])
    for draft in drafts:
        lines.extend([f"### {draft.label}", ""])
        for key, label in METRIC_LABELS.items():
            value = getattr(draft, key)
            baseline_value = getattr(baseline, key)
            state, _delta = _metric_state(value, baseline_value, STYLE_TOLERANCES[key])
            display = _percent(value) if key == "dialogue_ratio" else str(value)
            suffix = "" if key in {"avg_sentence", "avg_para", "dialogue_ratio"} else "/千字"
            lines.append(f"- **{label}**：{display}{suffix}，相对原文 {state}。{_review_explanation(label, state)}")
        lines.append("")
    lines.extend(
        [
            "## 作者判断入口",
            "",
            "- 若偏差集中在对白推进度和设定解释度，优先要求续写 agent 把信息落回动作、空间和人物误判。",
            "- 若偏差集中在段落节拍，优先拆分自然换气点，不要只做语句润色。",
            "- 若环境压迫感偏高，要检查它是否服务人物选择；若只是气氛堆料，应删减。",
            "- 若悬念留白度偏低，下一章需要保留未解释信息，但不能牺牲当前章节的事件闭合。",
            "",
        ]
    )
    return "\n".join(lines)


def build_continuation_constraints(metrics: list[StyleMetrics]) -> str:
    if not metrics:
        return "# 续写硬约束\n\n暂无原文基准，续写前必须先生成叙事结构指纹。\n"
    baseline = metrics[0]
    return "\n".join(
        [
            "# 续写硬约束",
            "",
            "## 当前基准快照",
            "",
            *_baseline_snapshot_lines(baseline),
            "",
            _baseline_snapshot_json_block(baseline),
            "",
            "## 数值边界",
            "",
            f"- 句式呼吸：目标区间 {_band(baseline.avg_sentence, 0.15)}。",
            f"- 段落节拍：目标区间 {_band(baseline.avg_para, 0.20)}。",
            f"- 对白推进度：目标区间 {_band(baseline.dialogue_ratio, 0.25)}。",
            f"- 内心贴近度：目标区间 {_band(baseline.interior_density, 0.30)} / 千字。",
            f"- 动作驱动度：目标区间 {_band(baseline.action_density, 0.35)} / 千字。",
            f"- 环境压迫感：目标区间 {_band(baseline.environment_density, 0.35)} / 千字。",
            f"- 设定解释度：目标区间 {_band(baseline.exposition_density, 0.35)} / 千字。",
            f"- 悬念留白度：目标区间 {_band(baseline.suspense_density, 0.35)} / 千字。",
            "",
            "## 写作硬约束",
            "",
            "- 每章写完后先自检篇幅，再对照以上指标做一次局部扩写或删改，复验后才能进入下一章。",
            "- 对白只能承担关键冲突和信息转折，不能用连续问答替代场景推进。",
            "- 设定、流程、计划必须落到人物动作、空间压力、判断失误或代价后果上。",
            "- 环境描写必须服务人物选择，不允许每段都堆感官气氛。",
            "- 段落过重时增加自然换气点；段落过碎时合并同一动作链。",
            "- 文风复写只能改变语言质感和叙事节奏，不得改剧情事件、胜负结果、人物动机和章节事实。",
            "- 若机器门禁返回 fail，必须只由续写 Agent 基于原文约束重写或局部替换当前章节；外部助手不得直接改正文。",
            "",
        ]
    )


def generate_style_diagnostics(
    *,
    book_dir: Path,
    source_count: int = 8,
    draft_file: str = "chapter_draft.md",
    draft_chapters: Any = None,
) -> dict[str, Any]:
    safe_source_count = max(1, min(int(source_count or 8), 30))
    source_files = latest_chapter_files(book_dir, safe_source_count)
    source_text = "\n\n".join(_read_text(path) for path in source_files)
    metrics: list[StyleMetrics] = []
    warnings: list[str] = []
    if source_text.strip():
        metrics.append(metric_for(source_text, f"原文近段样本：最近{len(source_files)}章"))
    else:
        warnings.append("未找到可用原文章节，只能返回空基准。")

    draft_path = book_dir / str(draft_file or "chapter_draft.md").replace("\\", "/")
    if draft_path.exists() and draft_path.is_file():
        chapter_numbers = parse_chapter_numbers(draft_chapters)
        for heading, section_text in extract_draft_chapters(_read_text(draft_path), chapter_numbers):
            metrics.append(metric_for(section_text, f"草稿：{heading}"))
    else:
        warnings.append(f"未找到草稿文件：{draft_file or 'chapter_draft.md'}。")

    outline_evidence: dict[int, dict[str, Any]] = {}
    outline_path = book_dir / "chapter_outline.md"
    if outline_path.exists() and outline_path.is_file():
        outline_evidence = parse_chapter_outline_evidence(_read_text(outline_path))

    style_gate = build_style_gate(metrics, chapter_outline_evidence=outline_evidence)
    outputs = {
        "style_fingerprint.md": build_style_fingerprint(book_dir, safe_source_count, metrics, source_files),
        "style_review.md": build_style_review(metrics, safe_source_count, style_gate),
        "style_constraints_for_continuation.md": build_continuation_constraints(metrics),
    }
    return {
        "status": "success",
        "source_count": safe_source_count,
        "source_files": [path.name for path in source_files],
        "draft_file": str(draft_file or "chapter_draft.md"),
        "metrics": [asdict(row) for row in metrics],
        "style_gate": style_gate,
        "warnings": warnings,
        "outputs": outputs,
    }
