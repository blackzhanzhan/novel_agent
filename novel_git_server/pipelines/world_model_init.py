"""Two-phase world_model.md initialization from summary.md.

Phase 1 (extract): sends full summary.md to DeepSeek, extracting a structured
7-section world_model.md.  Phase 2 (verify): sends the draft world_model back
with the summary for cross-validation, catching contradictions and omissions.

With DeepSeek's 1M context window, the entire summary (~60K chars) fits easily.
"""

import re
import logging
from queue import Queue

import git as gitmod
from langchain_core.messages import HumanMessage
from utils.model_provider import create_chat_model

from .batch_parser import parse_summary_batches

log = logging.getLogger(__name__)

CONSTRAINT_LIFECYCLE_PROTOCOL = """CONSTRAINT_LIFECYCLE_PROTOCOL (highest priority):
- A creative constraint is not only hard or soft. Preserve lifecycle and applicability scope.
- Lifecycle labels: current-active, historical-only, retired, overridden, disabled, disabled-in-current-scope, conditional, inherited-residue, unresolved, legacy-unclassified.
- Applicability scopes: global, timeline, arc, stage, loop, faction, character-POV, location, rule-system, source-evidence-window.
- In the hard constraints section, include or preserve a `### Constraint Lifecycle Ledger` subsection whenever the source shows changing states, abilities, identities, relationships, timelines, loops, or rule systems.
- Do not flatten source-backed history into current-active reality. A historical fact can remain true while no longer being active.
- Reincarnation, loop, time-reset, regression, infinite-flow, and branch-timeline novels are the strongest same-case: an ability gained in Loop 5 but locked or unavailable in Loop 6 must be historical-only plus disabled-in-current-scope, not current-active.
- Non-loop novels also need this: a sealed ability, dissolved alliance, exposed identity, dead enemy, changed faction, completed promise, or upgraded realm should not remain an active constraint unless the current scope still says so.
- Downstream rule: continuation may write only current-active or explicitly conditional constraints as present-tense story reality; historical-only, retired, disabled, inherited-residue, or unresolved constraints may be used only as memory, debt, trauma, foreshadowing, reader irony, or review risk unless the world/status layer marks them current-active.
"""

CONSTRAINT_LIFECYCLE_LEDGER_TEMPLATE = """### Constraint Lifecycle Ledger

- legacy-unclassified: Existing constraints in this file need lifecycle classification before downstream agents treat them as current-active.
- required_lifecycle_values: current-active; historical-only; retired; overridden; disabled; disabled-in-current-scope; conditional; inherited-residue; unresolved.
- required_scope_values: global; timeline; arc; stage; loop; faction; character-POV; location; rule-system; source-evidence-window.
- downstream_rule: only current-active or explicitly conditional constraints may be used as present-tense story reality.
"""

EXTRACTION_PROMPT = CONSTRAINT_LIFECYCLE_PROTOCOL + "\n\n" + """你是一个世界模型蒸馏引擎。从以下完整阅读档案中提取创作约束，输出一个结构化的 world_model.md。

## 规则：
1. 不要搬运剧情，只提取能约束后续创作的规则和事实
2. 每个条目格式：- **标题**：描述（描述必须说明该约束对后续创作的影响）
3. 相同/重复条目合并为一条
4. 如果多条信息对同一设定有矛盾：
   - 数量型事实（碎片数、人数、血门数等）：以首次完整表述的版本为准
   - 状态型事实（角色生死、物品归属）：以后出现的版本为准
   - 无论哪种情况，每次矛盾消解都必须在「矛盾与风险」section 中留痕，格式为：- **[设定名]数量/状态矛盾**：前文称X，后文称Y，采用[策略]及理由
   - 严禁静默覆盖
5. 每个主 section 下至少要有 5-15 条条目，不要过度精简，要充分提取每个 section 的增量
6. 对力量体系、修行路径、身份机制、世界规则等硬约束要特别详细，不能遗漏

## 输出格式：
以 "# World Model" 开头，严格按以下 7 个 ## 二级标题组织：

1. ## 读者承诺与主轴 — 核心看点、题材契约、长线情绪方向
2. ## 冲突发动机 — 长期/中期/短期冲突、可复用矛盾模板
3. ## 硬约束 — 不可撤销事实、力量/代价规则、禁区、世界规则、修行体系
4. ## 软假设 — 可调整设定、待确认问题、疑似设定
5. ## 未回收承诺 — 伏笔、情感债、必须回收的读者期待
6. ## 矛盾与风险 — 设定矛盾、高风险写法警告、一致性风险
7. ## 下游工作流接口 — 对续写/审核/大纲/文风 agent 的创作指令

末尾添加覆盖表格，列出所有已处理的 Batch Archive 批次。

直接输出 markdown，不要包裹在代码块中。

## 完整阅读档案：
{summary_text}"""

VERIFY_PROMPT = CONSTRAINT_LIFECYCLE_PROTOCOL + "\n\n" + """你是事实校验引擎。以下是已提取的世界模型（初稿）和原始阅读档案。

请逐一检查世界模型中的硬约束条目：
1. 在阅读档案中找到对应的原文依据
2. 如果条目在档案中无依据 → 标记为「待确认」并移入软假设 section
3. 如果条目与档案矛盾 → 在矛盾与风险 section 中添加修正条目，并修正硬约束中的错误
4. 如果档案中有重要事实未被提取 → 在对应 section 补充，标注「校验补充」

同时检查：
- 数量型事实是否与首次出现的表述一致（不盲目采用后文的矛盾数字）
- 角色/物品的当前状态是否与最新剧情一致

输出修正后的完整 world_model.md，不要省略任何已有条目。保留原有的 7 个 ## section 结构。

## 当前世界模型（初稿）：
{world_model}

## 原始阅读档案（节选 — 最后 3 个批次）：
{summary_tail}"""


REQUIRED_SECTIONS = [
    "读者承诺与主轴",
    "冲突发动机",
    "硬约束",
    "软假设",
    "未回收承诺",
    "矛盾与风险",
    "下游工作流接口",
]

STATUS_CARD_REQUIRED_FIELDS = [
    "当前节奏阶段",
    "张力等级",
    "上次满足点位置及类型",
    "建议下个满足点距离",
    "当前驱动焦点",
    "读者预期方向",
    "未兑现承诺 Top3",
    "主角状态",
    "伏笔压力",
]

UNKNOWN_VALUE = "待确认"
STATUS_CARD_REPAIR_COMMIT_MESSAGE = "batch init: initialize status card"


def _build_llm(max_tokens: int = 32768):
    return create_chat_model(max_tokens=max_tokens, purpose="world_model_init")


def _extract_world_model_from_response(text: str) -> str:
    code_block_re = re.compile(r"```(?:markdown|md)?\s*\n(.*?)```", re.DOTALL)
    m = code_block_re.search(text)
    if m:
        candidate = m.group(1).strip()
        if candidate.startswith("# World Model"):
            return candidate

    idx = text.find("# World Model")
    if idx >= 0:
        return text[idx:].strip()

    return text.strip()


def _validate_sections(content: str) -> tuple[bool, list[str]]:
    missing = [s for s in REQUIRED_SECTIONS if f"## {s}" not in content]
    return len(missing) == 0, missing


def _repair_sections(content: str) -> str:
    existing = {l.strip()[3:] for l in content.split("\n") if l.strip().startswith("## ")}
    missing = [s for s in REQUIRED_SECTIONS if s not in existing]
    if not missing:
        return content
    result = content.rstrip() + "\n\n"
    for section in missing:
        result += f"## {section}\n\n（待补充）\n\n"
    return result


def _has_constraint_lifecycle_ledger(content: str) -> bool:
    return (
        "Constraint Lifecycle Ledger" in content
        and "current-active" in content
        and "historical-only" in content
        and "disabled" in content
    )


def _insert_constraint_lifecycle_ledger(content: str) -> str:
    if _has_constraint_lifecycle_ledger(content):
        return content

    hard_heading = f"## {REQUIRED_SECTIONS[2]}"
    hard_idx = content.find(hard_heading)
    if hard_idx < 0:
        return content.rstrip() + "\n\n" + CONSTRAINT_LIFECYCLE_LEDGER_TEMPLATE

    line_end = content.find("\n", hard_idx)
    if line_end < 0:
        line_end = len(content)

    return (
        content[:line_end]
        + "\n\n"
        + CONSTRAINT_LIFECYCLE_LEDGER_TEMPLATE.rstrip()
        + "\n"
        + content[line_end:]
    )


def _replace_coverage_table(content: str, batches: list[dict]) -> str:
    """Replace LLM-generated coverage table with ground truth from summary batches."""
    table_header = "### 覆盖表格"
    table_idx = content.find(table_header)
    if table_idx < 0:
        # No existing table — append
        return content.rstrip() + "\n\n---\n\n" + _build_coverage_table(batches)

    # Find where the table ends (next ## heading or end of content)
    after_header = content[table_idx + len(table_header):]
    # Skip the header line and table separator lines
    next_section = re.search(r"\n## ", after_header)
    if next_section:
        end_idx = table_idx + len(table_header) + next_section.start()
    else:
        end_idx = len(content)

    return content[:table_idx] + _build_coverage_table(batches) + content[end_idx:]


def _build_coverage_table(batches: list[dict]) -> str:
    lines = [
        "### 覆盖表格",
        "",
        "| Batch Archive | 章节范围 | 已处理 |",
        "| --- | --- | --- |",
    ]
    for b in batches:
        cs, ce = b["chapter_start"], b["chapter_end"]
        if cs and ce:
            range_str = f"第{cs}-{ce}章"
        else:
            range_str = b["title"].replace("Batch Archive: ", "")
        lines.append(f"| {b['title']} | {range_str} | ✅ |")
    lines.append(f"\n**总数：{len(batches)}批次**")
    return "\n".join(lines)


def _commit_files(book_dir: str, filepaths: list[str], message: str) -> str | None:
    repo = gitmod.Repo(book_dir)
    paths = [p.replace("\\", "/") for p in filepaths]
    if not paths:
        return None

    status = repo.git.status("--short", "--", *paths)
    if not status.strip():
        return None

    repo.index.add(paths)
    commit = repo.index.commit(message)
    return commit.hexsha


def _commit_file(book_dir: str, filepath: str, message: str) -> None:
    _commit_files(book_dir, [filepath], message)


def _status_card_has_required_fields(content: str) -> bool:
    for field in STATUS_CARD_REQUIRED_FIELDS:
        pattern = rf"{re.escape(field)}\s*[：:]\s*(.+)"
        match = re.search(pattern, content)
        if not match:
            return False
        value = _normalize_status_value(match.group(1).strip())
        if not value or _is_status_category_label(value):
            return False
    return True


def _is_extraction_done(book_dir: str) -> bool:
    """Check if a verified extraction commit already exists."""
    repo = gitmod.Repo(book_dir)
    for commit in repo.iter_commits(max_count=50):
        if "verified full extraction" in commit.message:
            return True
    return False


def _get_summary_tail(summary_path: str, batches: list[dict], n: int = 3) -> str:
    """Extract text from the last n batches of summary."""
    if not batches:
        return ""
    tail_batches = batches[-n:]
    parts = []
    with open(summary_path, "r", encoding="utf-8") as f:
        all_lines = f.readlines()
    for b in tail_batches:
        start = b["start_line"] - 1  # 0-based
        end = b["end_line"]  # exclusive
        parts.append("".join(all_lines[start:end]).strip())
    return "\n\n---\n\n".join(parts)


def _extract_summary_section(text: str, heading: str) -> str:
    pattern = rf"^###\s+{re.escape(heading)}\s*\n(.*?)(?=^###\s+|^##\s+|\Z)"
    match = re.search(pattern, text, re.DOTALL | re.MULTILINE)
    return match.group(1).strip() if match else ""


def _clean_status_value(line: str) -> str:
    line = _normalize_status_value(line)
    if _is_status_category_label(line):
        return UNKNOWN_VALUE
    return line or UNKNOWN_VALUE


def _normalize_status_value(line: str) -> str:
    line = re.sub(r"^\s*(?:[-+]\s+|\*\s+|[0-9]+[.)]\s*|[一二三四五六七八九十]+[、.]\s*)", "", line)
    line = re.sub(r"(\*\*|__)(.*?)\1", r"\2", line)
    line = re.sub(r"(\*|_)(.*?)\1", r"\2", line)
    line = re.sub(r"^[*_]+|[*_]+$", "", line)
    return re.sub(r"\s+", " ", line).strip()


def _is_status_category_label(line: str) -> bool:
    return bool(re.fullmatch(r"[^：:\n]{1,24}[：:]", line.strip()))


def _collect_status_lines(section_text: str, limit: int = 3) -> list[str]:
    lines: list[str] = []
    for raw_line in section_text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("|") or set(stripped) <= {"-", " ", "|"}:
            continue
        value = _clean_status_value(stripped)
        if value != UNKNOWN_VALUE:
            lines.append(value)
        if len(lines) >= limit:
            break
    return lines


def _first_status_line(*section_texts: str, predicate: str | None = None) -> str:
    for section_text in section_texts:
        for line in _collect_status_lines(section_text, limit=20):
            if predicate and predicate not in line:
                continue
            return line
    return UNKNOWN_VALUE


def _batch_range_label(batch: dict) -> str:
    chapter_start = batch.get("chapter_start")
    chapter_end = batch.get("chapter_end")
    if chapter_start and chapter_end:
        return f"CH{chapter_start}-{chapter_end}"
    return str(batch.get("title", UNKNOWN_VALUE)).replace("Batch Archive: ", "") or UNKNOWN_VALUE


def _infer_tension_level(text: str) -> str:
    if not text.strip():
        return UNKNOWN_VALUE

    high_keywords = [
        "决战",
        "危机",
        "追杀",
        "死亡",
        "大战",
        "倒计时",
        "终局",
        "高压",
        "灾难",
        "失控",
        "决裂",
        "反噬",
    ]
    medium_keywords = ["推进", "揭示", "冲突", "压力", "目标", "伏笔", "承诺", "阻力"]

    for keyword in high_keywords:
        if keyword in text:
            return f"高（最新批次出现「{keyword}」压力信号）"
    for keyword in medium_keywords:
        if keyword in text:
            return f"中（最新批次出现「{keyword}」推进信号）"
    return "中（最新批次仍有剧情推进记录）"


def _infer_satisfaction_point(batch: dict, text: str) -> str:
    range_label = _batch_range_label(batch)
    signal_groups = [
        ("真相揭示", ["真相", "揭示", "身份", "答案"]),
        ("承诺回收", ["回收", "兑现", "解决"]),
        ("战斗/能力满足", ["击败", "胜利", "突破", "晋升", "升级"]),
        ("情绪满足", ["团聚", "告白", "释然", "和解"]),
        ("反转满足", ["反转", "逆转", "翻盘"]),
    ]
    for label, keywords in signal_groups:
        if any(keyword in text for keyword in keywords):
            return f"{range_label}：{label}"
    return UNKNOWN_VALUE


def _suggest_next_satisfaction_distance(tension_level: str, pressure: str) -> str:
    if tension_level == UNKNOWN_VALUE and pressure == UNKNOWN_VALUE:
        return UNKNOWN_VALUE
    if tension_level.startswith("高") or pressure.startswith("高"):
        return "1-2章内"
    return "2-4章内"


def _format_top3(values: list[str]) -> str:
    filled = (values + [UNKNOWN_VALUE, UNKNOWN_VALUE, UNKNOWN_VALUE])[:3]
    return "；".join(f"{idx}. {value}" for idx, value in enumerate(filled, start=1))


def _build_status_card(book_dir: str, summary_path: str) -> str:
    """Build a short, complete status_card.md from the latest summary batch."""
    import json

    batches = parse_summary_batches(summary_path)
    if not batches:
        raise ValueError("No summary batches available for status_card.md")

    last_batch = batches[-1]
    with open(summary_path, "r", encoding="utf-8") as f:
        all_lines = f.readlines()
    last_text = "".join(all_lines[last_batch["start_line"] - 1:last_batch["end_line"]])

    # Read metadata for book name
    meta_path = os.path.join(book_dir, "metadata.json")
    book_name = UNKNOWN_VALUE
    if os.path.exists(meta_path):
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        book_name = meta.get("book_name") or UNKNOWN_VALUE

    story_stage = _extract_summary_section(last_text, "故事阶段")
    core_driver = _extract_summary_section(last_text, "核心驱动进度")
    clues = _extract_summary_section(last_text, "线索状态")
    foreshadow = _extract_summary_section(last_text, "伏笔台账")
    promises_section = _extract_summary_section(last_text, "未兑现承诺")
    relationships = _extract_summary_section(last_text, "关系变化")
    constraints = _extract_summary_section(last_text, "本段约束增量")

    combined_latest = "\n".join(
        [story_stage, core_driver, clues, foreshadow, promises_section, relationships, constraints]
    )
    promise_lines = _collect_status_lines(promises_section, limit=3)
    if len(promise_lines) < 3:
        for candidate in _collect_status_lines(foreshadow, limit=3) + _collect_status_lines(clues, limit=3):
            if candidate not in promise_lines:
                promise_lines.append(candidate)
            if len(promise_lines) >= 3:
                break

    current_stage = _first_status_line(story_stage)
    tension_level = _infer_tension_level(combined_latest)
    satisfaction_point = _infer_satisfaction_point(last_batch, combined_latest)
    driver_focus = _first_status_line(core_driver, story_stage)
    reader_expectation = _first_status_line(promises_section, constraints, core_driver)
    protagonist_state = _first_status_line(relationships, story_stage, predicate="林七夜")
    if protagonist_state == UNKNOWN_VALUE:
        protagonist_state = _first_status_line(relationships, story_stage, predicate="主角")
    foreshadow_count = len(_collect_status_lines(foreshadow, limit=20)) + len(_collect_status_lines(clues, limit=20))
    if foreshadow_count >= 3:
        foreshadow_pressure = f"高（最新批次保留{foreshadow_count}条线索/伏笔）"
    elif foreshadow_count > 0:
        foreshadow_pressure = f"中（最新批次保留{foreshadow_count}条线索/伏笔）"
    else:
        foreshadow_pressure = UNKNOWN_VALUE
    next_distance = _suggest_next_satisfaction_distance(tension_level, foreshadow_pressure)

    content_parts = ["# 状态卡片", ""]
    content_parts.append(
        f"> 本书「{book_name}」初始化运行态，由 backend world_model pipeline 依据最新 Batch Archive 自动生成；证据不足写作「待确认」。"
    )
    content_parts.append("")
    content_parts.extend(
        [
            "## 核心运行态",
            "",
            f"- 当前节奏阶段：{current_stage}",
            f"- 张力等级：{tension_level}",
            f"- 上次满足点位置及类型：{satisfaction_point}",
            f"- 建议下个满足点距离：{next_distance}",
            f"- 当前驱动焦点：{driver_focus}",
            f"- 读者预期方向：{reader_expectation}",
            "",
            "## 角色与承诺",
            "",
            f"- 主角状态：{protagonist_state}",
            f"- 未兑现承诺 Top3：{_format_top3(promise_lines)}",
            f"- 伏笔压力：{foreshadow_pressure}",
            "",
            "## 证据锚点",
            "",
            f"- 最新批次：{_batch_range_label(last_batch)}",
            f"- 故事阶段依据：{current_stage}",
            f"- 驱动依据：{driver_focus}",
            f"- 线索/伏笔依据：{foreshadow_pressure}",
        ]
    )

    content = "\n".join(content_parts).strip() + "\n"
    if not _status_card_has_required_fields(content):
        raise ValueError("Generated status_card.md is missing required initialized fields")
    return content


def _populate_status_card(book_dir: str, summary_path: str, *, force: bool = False) -> str | None:
    """Auto-fill status_card.md from latest summary batch data."""
    status_card_path = os.path.join(book_dir, "status_card.md")
    existing = ""
    if os.path.exists(status_card_path):
        with open(status_card_path, "r", encoding="utf-8") as f:
            existing = f.read()

    if existing and not force and _status_card_has_required_fields(existing):
        return None

    content = _build_status_card(book_dir, summary_path)
    if existing == content:
        return None

    with open(status_card_path, "w", encoding="utf-8") as f:
        f.write(content)
    return "status_card.md"


def run_pipeline(
    book_id: str,
    book_dir: str,
    summary_path: str,
    sse_queue: Queue | None = None,
    *,
    force_rebuild: bool = False,
) -> dict:
    """Run two-phase world_model extraction from summary.md.

    Phase 1: Extract world model from full summary.
    Phase 2: Verify extracted facts against summary tail batches.

    Returns dict with completed_batches, failed_batches.
    """
    # Read summary
    with open(summary_path, "r", encoding="utf-8") as f:
        summary_text = f.read()

    batches = parse_summary_batches(summary_path)
    batch_titles = [b["title"] for b in batches]

    if _is_extraction_done(book_dir) and not force_rebuild:
        log.info("Verified extraction already done.")
        try:
            _populate_status_card(book_dir, summary_path, force=False)
            status_commit = _commit_files(
                book_dir,
                ["status_card.md"],
                STATUS_CARD_REPAIR_COMMIT_MESSAGE,
            )
        except Exception as e:
            log.error("Status card repair failed after verified extraction skip: %s", e, exc_info=True)
            if sse_queue:
                sse_queue.put(
                    {
                        "event": "batch_error",
                        "data": {"batch_index": 0, "title": "status_card", "error": str(e)},
                    }
                )
                sse_queue.put({"event": "done", "data": {"completed": 0, "failed": 1, "skipped": True, "force_rebuild": force_rebuild}})
            return {
                "completed_batches": [],
                "failed_batches": [{"error": str(e), "target": "status_card.md"}],
                "skipped": True,
            }

        if sse_queue:
            sse_queue.put(
                {
                    "event": "done",
                    "data": {
                        "completed": 0,
                        "failed": 0,
                        "skipped": True,
                        "status_card_committed": bool(status_commit),
                        "force_rebuild": force_rebuild,
                    },
                }
            )
        return {
            "completed_batches": [],
            "failed_batches": [],
            "skipped": True,
            "status_card_commit": status_commit,
            "force_rebuild": force_rebuild,
        }

    if sse_queue:
        sse_queue.put({"event": "ack", "data": {"total_batches": len(batches), "book_id": book_id}})

    llm = _build_llm(max_tokens=32768)

    # ── Phase 1: Extract ──
    if sse_queue:
        sse_queue.put({"event": "progress", "data": {"batch_index": 0, "total": 2, "title": "extract", "status": "processing"}})

    try:
        prompt = EXTRACTION_PROMPT.format(summary_text=summary_text)
        log.info("Phase 1 extract: prompt %d chars, %d batches", len(prompt), len(batches))

        response = llm.invoke([HumanMessage(content=prompt)])
        content = _extract_world_model_from_response(response.content)

        valid, missing = _validate_sections(content)
        if not valid:
            log.warning("Missing sections: %s, repairing", missing)
            content = _repair_sections(content)

        log.info("Phase 1 done: %d chars", len(content))

    except Exception as e:
        log.error("Phase 1 extraction failed: %s", e)
        if sse_queue:
            sse_queue.put({"event": "batch_error", "data": {"batch_index": 0, "title": "extract", "error": str(e)}})
            sse_queue.put({"event": "done", "data": {"completed": 0, "failed": 1, "force_rebuild": force_rebuild}})
        return {"completed_batches": [], "failed_batches": [{"error": str(e)}]}

    # ── Phase 2: Verify ──
    if sse_queue:
        sse_queue.put({"event": "progress", "data": {"batch_index": 1, "total": 2, "title": "verify", "status": "processing"}})

    try:
        summary_tail = _get_summary_tail(summary_path, batches, n=3)
        verify_prompt = VERIFY_PROMPT.format(world_model=content, summary_tail=summary_tail)
        log.info("Phase 2 verify: prompt %d chars", len(verify_prompt))

        verify_response = llm.invoke([HumanMessage(content=verify_prompt)])
        verified = _extract_world_model_from_response(verify_response.content)

        valid2, missing2 = _validate_sections(verified)
        if not valid2:
            log.warning("Verify phase missing sections: %s, repairing", missing2)
            verified = _repair_sections(verified)

        content = verified
        log.info("Phase 2 done: %d chars", len(content))

    except Exception as e:
        log.warning("Phase 2 verify failed (using phase 1 result): %s", e)
        # Non-fatal: use phase 1 result

    # ── Post-processing: coverage table + status card ──
    content = _insert_constraint_lifecycle_ledger(content)
    content = _replace_coverage_table(content, batches)

    wm_path = os.path.join(book_dir, "world_model.md")
    with open(wm_path, "w", encoding="utf-8") as f:
        f.write(content)

    try:
        _populate_status_card(book_dir, summary_path, force=True)
    except Exception as e:
        log.error("Status card initialization failed: %s", e, exc_info=True)
        if sse_queue:
            sse_queue.put(
                {
                    "event": "batch_error",
                    "data": {"batch_index": 1, "title": "status_card", "error": str(e)},
                }
            )
            sse_queue.put({"event": "done", "data": {"completed": 0, "failed": 1, "force_rebuild": force_rebuild}})
        return {"completed_batches": [], "failed_batches": [{"error": str(e), "target": "status_card.md"}]}

    commit_id = _commit_files(book_dir, ["world_model.md", "status_card.md"], "batch init: verified full extraction")

    log.info(
        "Verified extraction committed: %d chars, %d lines, commit=%s",
        len(content),
        content.count("\n") + 1,
        commit_id or "unchanged",
    )

    if sse_queue:
        sse_queue.put({"event": "batch_done", "data": {"batch_index": 1, "total": 2, "title": "verify"}})
        sse_queue.put({"event": "done", "data": {"completed": len(batches), "failed": 0, "force_rebuild": force_rebuild}})

    return {
        "completed_batches": batch_titles,
        "failed_batches": [],
        "commit_id": commit_id,
        "force_rebuild": force_rebuild,
    }
