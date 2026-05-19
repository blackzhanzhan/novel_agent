"""Phase 2: merge all batch deltas into final world_model.md."""

CONSTRAINT_LIFECYCLE_PROTOCOL = """CONSTRAINT_LIFECYCLE_PROTOCOL:
- Preserve constraint lifecycle and applicability scope while merging.
- Lifecycle labels: current-active, historical-only, retired, overridden, disabled, disabled-in-current-scope, conditional, inherited-residue, unresolved, legacy-unclassified.
- Applicability scopes: global, timeline, arc, stage, loop, faction, character-POV, location, rule-system, source-evidence-window.
- Do not flatten older source-backed constraints into current-active reality. If later batches supersede or disable earlier states, keep earlier states as historical-only, retired, overridden, disabled, or inherited-residue.
- Include or preserve `### Constraint Lifecycle Ledger` in the hard constraints section when any merged batch contains changing states, abilities, identities, relationships, timelines, loops, or rule systems.
"""

REQUIRED_SECTIONS = [
    "读者承诺与主轴",
    "冲突发动机",
    "硬约束",
    "软假设",
    "未回收承诺",
    "矛盾与风险",
    "下游工作流接口",
]

MERGE_PROMPT = CONSTRAINT_LIFECYCLE_PROTOCOL + "\n\n" + """你是一个世界模型合成引擎。将以下 {batch_count} 个批次的约束增量合并为一个完整的 world_model.md。

## 增量数据：
{all_deltas_text}

## 输出要求：
1. 以 "# World Model" 开头
2. 必须包含以下 7 个 ## 二级标题，严格按此顺序：
   - ## 读者承诺与主轴
   - ## 冲突发动机
   - ## 硬约束
   - ## 软假设
   - ## 未回收承诺
   - ## 矛盾与风险
   - ## 下游工作流接口
3. 每个 section 下的条目用 - **标题**：描述 格式排列
4. 去重：相同或高度相似的条目合并为一条，保留信息最丰富的版本
5. 矛盾处理：如果多个批次对同一设定有矛盾，以章节范围更大的（更新的）批次为准
6. 在末尾添加覆盖表格，列出全部已处理批次
7. 直接输出 markdown 内容，不要包裹在代码块中"""


def validate_sections(content: str) -> tuple[bool, list[str]]:
    """Check if content contains all 7 required sections.

    Returns (is_valid, missing_sections).
    """
    missing = [s for s in REQUIRED_SECTIONS if f"## {s}" not in content]
    return len(missing) == 0, missing


def format_deltas_for_merge(deltas: list[dict], batch_titles: list[str]) -> str:
    """Format batch deltas into text for merge prompt.

    Each delta is a dict with slot keys and markdown string values.
    """
    from .extract_schema import SLOT_KEYS, SECTION_NAMES_ZH

    parts: list[str] = []
    for i, (delta, title) in enumerate(zip(deltas, batch_titles)):
        parts.append(f"### 批次 {i + 1}: {title}")
        for key in SLOT_KEYS:
            value = delta.get(key, "")
            if value:
                zh = SECTION_NAMES_ZH[key]
                parts.append(f"**{zh}**:\n{value}")
        parts.append("")
    return "\n".join(parts)
