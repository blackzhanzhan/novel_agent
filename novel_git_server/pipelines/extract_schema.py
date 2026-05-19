"""Phase 1: per-batch constraint extraction schema and prompt."""

SECTIONS = [
    ("reader_promise", "读者承诺与主轴"),
    ("conflict_engine", "冲突发动机"),
    ("hard_constraints", "硬约束"),
    ("soft_assumptions", "软假设"),
    ("unrecovered_promises", "未回收承诺"),
    ("contradictions_risks", "矛盾与风险"),
    ("downstream_interface", "下游工作流接口"),
]

SLOT_KEYS = [key for key, _ in SECTIONS]

SECTION_NAMES_ZH = {key: zh for key, zh in SECTIONS}

EXTRACT_PROMPT = """你是一个世界模型约束提取器。从以下批次摘要中提取创作约束增量。

## 批次摘要 ({batch_title}):
{batch_text}

## 输出格式：
严格输出 JSON 对象，包含以下 7 个字段。每个字段的值为该批次在该维度的增量（markdown 片段），无增量则为空字符串。

{{
  "reader_promise": "核心看点/题材契约/长线情绪变化，用 - **标题**：描述 格式",
  "conflict_engine": "新的长期/中期冲突、可复用矛盾模板",
  "hard_constraints": "新的不可撤销事实、力量/代价规则、禁区",
  "soft_assumptions": "新的可调整设定、待确认问题",
  "unrecovered_promises": "新伏笔、情感债、必须回收的读者期待",
  "contradictions_risks": "新发现的设定矛盾、高风险写法警告",
  "downstream_interface": "对续写/审核/大纲/文风 agent 的增量指令"
}}

## 提取规则：
1. 只提取能约束后续创作的规则和事实，不要搬运剧情
2. 每个条目格式：- **标题**：描述（描述中说明该约束对后续创作的影响）
3. 如果该维度无增量，输出空字符串 ""
4. 直接输出 JSON，不要包裹在 ```json 代码块中"""
