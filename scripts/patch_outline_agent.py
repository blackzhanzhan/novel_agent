"""Patch the live Dify outline workflow from PostgreSQL.

The Dify PostgreSQL database is the runtime truth for this project. This script
keeps the current outline topology and tool provider bindings intact, then
updates the live and draft outline workflows so explicit outline
initialization/rebuild creates the four outline control artifacts:

- brainstorm.md
- master_outline.md
- arc_outline.md
- chapter_outline.md
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime"

DB_CONTAINER = "docker-db_postgres-1"
DB_NAME = "dify"
APP_ID = "b58303e8-4a67-4327-8f56-ff1dbfc4023e"
EXPECTED_LIVE_WORKFLOW_ID = "a4462c69-d0db-46f6-8f3c-50c5c6d04bbb"
START_NODE_ID = "1776085196214"
TOOL_PROVIDER_ID = "c41fee3b-54dd-4e49-af9b-be30f68f6242"

EXPECTED_MODEL_PROVIDER = "langgenius/deepseek/deepseek"
EXPECTED_MODEL = "deepseek-v4-flash"
EXPECTED_NODE_COUNT = 6
EXPECTED_EDGE_COUNT = 5

DISCUSS_AGENT_TITLE = "DISCUSS_AGENT"
COMMIT_AGENT_TITLE = "COMMIT_AGENT"

DISCUSS_TOOLS = [
    "get_markdown_section",
    "get_markdown_outline",
    "get_archive_range",
    "get_core_archive",
]

COMMIT_TOOLS = [
    "get_markdown_section",
    "get_archive_range",
    "get_markdown_outline",
    "get_core_archive",
    "draft_append_markdown_section",
    "draft_replace_markdown_section",
]

PREPATCH_COMMIT_TOOLS = [
    "get_markdown_section",
    "get_archive_range",
    "get_markdown_outline",
    "get_core_archive",
    "draft_sync_markdown_sections",
]

TOOL_DESCRIPTION_OVERRIDES = {
    "get_markdown_section": "读取指定 Markdown 文件的指定章节内容，用于小范围取证与对齐。",
    "get_markdown_outline": "读取指定 Markdown 文件的标题结构、section_path 与 base_etag，用于安全定位和写入前校验。",
    "get_archive_range": "按范围读取书库归档内容，用于抽样核对摘要、世界观、状态和大纲证据。",
    "get_core_archive": "读取书库核心档案，用于快速取得当前作品的关键上下文。",
    "draft_append_markdown_section": "在 draft/sandbox 分支向指定 Markdown 文件追加一个完整子章节；参数必须扁平，file_name 只能是裸文件名。",
    "draft_replace_markdown_section": "在 draft/sandbox 分支替换指定 Markdown section；content 必须包含目标标题行，base_etag 必须来自最近读取结果。",
}

OUTLINE_FILES = [
    "brainstorm.md",
    "master_outline.md",
    "arc_outline.md",
    "chapter_outline.md",
]

GOOGLE_SEARCH_TOOL_NAME = "google_search"
GOOGLE_SEARCH_PROVIDER_NAME = "langgenius/google/google"
GOOGLE_SEARCH_DESCRIPTION = "一个用于执行 Google SERP 搜索并提取片段和网页的工具。输入应该是一个搜索查询。"

CONTEXT_FILES = [
    "summary.md",
    "world_model.md",
    "status_card.md",
    "style_constraints_for_continuation.md",
]

REAL_EVIDENCE_FILES = [
    *CONTEXT_FILES,
    *OUTLINE_FILES,
    "style_fingerprint.md",
    "style_review.md",
    "chapters/*.md",
]
REAL_EVIDENCE_FILE_LIST = ", ".join(REAL_EVIDENCE_FILES)

OUTLINE_PRODUCTION_CONTROL_PROTOCOL = f"""OUTLINE_PRODUCTION_CONTROL_PROTOCOL：
- 本段是内部执行规约。最终回复不得复述、引用、解释规约原文，也不得把规约名当作证据。
- 最终回复不要叙述工具调用、文件读取过程、重试、缺少 book_id/book_name 的内部恢复，直接给作者能用的结论。
- 所有可沉淀的大纲判断都要归入三类证据模式：
  - SOURCE_FACT：来自真实可读文件的已发生事实、已有设定、状态记录或可复盘摘要。
  - AUTHOR_PROPOSAL：面向后续创作的方案、钩子、节奏、章节卡、爽点与回收顺序；它能指导写作，但不是既成正史。
  - WORLD_MODEL_REQUIRED：会新增或改变世界规则、身份、时间线、硬约束、角色生死状态、因果底层或冲突修复的方案；进入续写或审查硬约束前，要先交给 world_model.md/status_card.md 吸收。
- 遇到作者提出的红线或矛盾请求，用表格回复：请求、判断、证据模式、可用证据、替代路径。被源文件阻断时，判断写 blocked_by_source；改变世界规则的替代路径标 WORLD_MODEL_REQUIRED，其余替代路径标 AUTHOR_PROPOSAL。
- 不要把一个复合请求拆成多行批准项；如果同一请求里有多个不可逆变更，保留一行并说明其中的子项都被阻断。
- 表格只放作者实际提出的请求，不额外添加元说明行、脚注行、合计行。总结放在表格下方。
- 已完结作品初始化可以产出终局弧线回顾卡；继续写作或下一单元设计要产出后续生产卡。后续生产卡默认是 AUTHOR_PROPOSAL 或 WORLD_MODEL_REQUIRED，除非当前源文件已经明确支持。
- NONEXISTENT_EVIDENCE_GUARD：可引用的文件名只有 {REAL_EVIDENCE_FILE_LIST}。记忆里或用户提到但不在清单中的文件，不得作为证据引用；必要时只说“非清单证据已丢弃”。
- RED_LINE_REVERSAL_PROTOCOL：对源文件已经确认的不可逆事实，不能因为作者临时提出而写成 SOURCE_FACT；应标 blocked_by_source，或作为 WORLD_MODEL_REQUIRED 的待确认改写方案。
- 对角色死亡、牺牲代价、身份否认、世界规则封锁、时间线锁定等不可逆事实，只有当前 world_model.md/status_card.md 明确授权时，才能当作已解除；投影、残响、伪装、继承、幻觉、局部代理等可作为替代创意，但不得伪装成原事实反转。
- 作者提出与当前源文件冲突的方案时，要阻断、转入 WORLD_MODEL_REQUIRED，或明确写成 AUTHOR_PROPOSAL；不要把它写成已发生事实。
"""

OUTLINE_IDEATION_PROTOCOL = """OUTLINE_IDEATION_ENGINE_PROTOCOL：
- 适用场景：作者在发散、找灵感、问接下来能发生什么、比较方案，或明确表示暂不保存、暂不落档。
- 目标是当网文创意搭子：给作者可抓取、可修改、可推进的剧情燃料，同时保留源文件纪律。
- 开放式发散时，给 3-5 条候选路线。每条路线包含：路线名、卖点、冲突压力、留存钩子、兑现形态、风险或红线、建议落点、证据模式。
- 建议落点只能指向 brainstorm.md、master_outline.md、arc_outline.md、chapter_outline.md；跨层方案要写主落点和辅助落点。
- 证据模式只能使用 SOURCE_FACT、AUTHOR_PROPOSAL、WORLD_MODEL_REQUIRED。与当前源文件冲突、或需要改变世界规则的路线，不得当成正史。
- 最后给一个“推荐选择”和一个作者可以直接执行的下一步；问题最多问一个。
- 回复面向作者，不叙述内部流程、SQL、协议原文、工具参数或隐藏标记。
- DISCUSS_AGENT 不写文件，也不声称草稿已更新。作者想保存某条路线时，引导其明确说“落档/写入/归档”，交给 COMMIT_AGENT 压缩进大纲。
"""

OUTLINE_SEARCH_REFERENCE_PROTOCOL = """OUTLINE_SEARCH_REFERENCE_PROTOCOL：
- 只有作者明确提出“联网、搜索、查资料、考据、现实资料、行业参考、新闻背景、热梗参考、平台趋势、题材资料、搜索一下”等需求时，DISCUSS_AGENT 才调用 google_search。
- 普通大纲讨论、剧情发散、章节卡设计、世界观整理，默认先用当前书库文件，不主动联网。
- 搜索结果一律标为 EXTERNAL_REFERENCE：它能启发 AUTHOR_PROPOSAL，但不能自动升级为 SOURCE_FACT，也不能覆盖书库里的既有设定。
- 外部资料如果会改变世界规则、人物身份、时间线、硬约束、题材底层设定，必须标 WORLD_MODEL_REQUIRED，等待作者或世界观流程吸收。
- 回复中要把“书内证据”和“外部参考”分开写；不要把搜索摘要包装成书内已经发生的事实。
- 搜索词应保持通用、可考据，不把当前作品私有角色、私有设定当作公共事实去搜索，除非作者明确要求查自己的公开作品资料。
"""

OUTLINE_LANDING_PROTOCOL = """OUTLINE_LANDING_ENGINE_PROTOCOL：
- 适用场景：作者明确要求保存、落档、归档、写入大纲、初始化、重建，或把某个已选想法压进大纲层。
- 目标是把作者意图压缩成可审阅、可回退、可继续编辑的大纲工件，而不是继续开放发散。
- 写入前先形成 landing_plan：来源意图、写入范围、目标文件、证据读取、想法到大纲层映射、世界模型风险、回退风险。
- 想法到大纲层映射要把每个重要想法落到 brainstorm.md、master_outline.md、arc_outline.md、chapter_outline.md 之一，不让成熟想法漂在闲聊文本里。
- 每次写入都要包含“证据模式/生产边界”或同义段落，区分 SOURCE_FACT、AUTHOR_PROPOSAL、WORLD_MODEL_REQUIRED、EXTERNAL_REFERENCE、blocked_by_source。
- chapter_outline.md 要产出可执行章节卡。每张卡包含：章节目标、入场场景、冲突或阻碍、当章兑现、状态变化、伏笔动作、结尾钩子、约束引用、证据模式。
- arc_outline.md 要产出留存阶梯：入场钩子、压力台阶、揭示/兑现顺序、信息缺口、伏笔债、单元尾钩子。
- brainstorm.md 要保留被拒方案、风险区和待决问题，不静默删除作者仍可能回收的灵感。
- master_outline.md 要先保护读者承诺、核心循环和不可违背约束，再加入新的生产方向。
- 改变耐久世界事实的方案只能写为 WORLD_MODEL_REQUIRED，不得提升为 SOURCE_FACT 或硬约束。
- 工具调用后，只汇报哪些大纲文件已更新、每个文件承载了什么生产决定；不叙述原始工具参数。
"""

OUTLINE_TOOL_ARGUMENT_SAFETY_PROTOCOL = """OUTLINE_TOOL_ARGUMENT_SAFETY_PROTOCOL：
- 在每次调用 draft_append_markdown_section 或 draft_replace_markdown_section 前执行。
- Dify 会把工具参数转换为 JSON。工具参数要保持 JSON 安全，不把伪 JSON 当正文塞进参数。
- content 参数中尽量避免半角双引号、反斜杠、代码围栏、JSON 示例、YAML 块和未配对大括号；引用故事名词时优先用中文书名号或直角引号。
- 单次 content 保持紧凑，优先用清晰 Markdown 标题和要点，不把整本设定集塞进一次工具调用。
- 如果计划写入内容过大，先写能证明生产决定的最小可执行段落，把剩余扩写作为后续编辑汇报。
- 最终可见回复不得提到本规约名，也不得展示原始工具参数。
"""

COMMON_PROMPT_MARKERS = [
    "OUTLINE_LAYER_CONTROL_PROTOCOL",
    "OUTLINE_PRODUCTION_CONTROL_PROTOCOL",
    "SOURCE_FACT",
    "AUTHOR_PROPOSAL",
    "WORLD_MODEL_REQUIRED",
    "EXTERNAL_REFERENCE",
    "NONEXISTENT_EVIDENCE_GUARD",
    "RED_LINE_REVERSAL_PROTOCOL",
    "blocked_by_source",
    "初始化大纲",
    "重建大纲",
    "brainstorm.md",
    "master_outline.md",
    "arc_outline.md",
    "chapter_outline.md",
    "summary.md",
    "world_model.md",
    "status_card.md",
    "style_constraints_for_continuation.md",
    "chapter_draft.md",
]

DISCUSS_PROMPT_MARKERS = [
    *COMMON_PROMPT_MARKERS,
    "OUTLINE_IDEATION_ENGINE_PROTOCOL",
    "OUTLINE_SEARCH_REFERENCE_PROTOCOL",
    "google_search",
    "路线名",
    "卖点",
    "冲突压力",
    "留存钩子",
    "兑现形态",
    "建议落点",
    "推荐选择",
]

COMMIT_PROMPT_MARKERS = [
    *COMMON_PROMPT_MARKERS,
    "OUTLINE_LANDING_ENGINE_PROTOCOL",
    "landing_plan",
    "想法到大纲层映射",
    "可执行章节卡",
    "留存阶梯",
    "章节目标",
    "file_name 只能填写裸文件名",
    "draft/sandbox 是后端 Git 分支",
    "OUTLINE_FLAT_WRITE_PROTOCOL",
    "OUTLINE_TOOL_ARGUMENT_SAFETY_PROTOCOL",
]


DISCUSS_QUERY = f"""当前 book_id：{{{{#{START_NODE_ID}.book_id#}}}}
当前书名：{{{{#{START_NODE_ID}.book_name#}}}}
当前目标文件：{{{{#{START_NODE_ID}.active_file#}}}}
作者当前意图：{{{{#sys.query#}}}}

你是大纲讨论代理。请基于当前作品上下文继续讨论，但本节点没有写入权限。

默认先读：
- `summary.md`
- `world_model.md`
- `status_card.md`
- `style_constraints_for_continuation.md`
- 当前目标 outline 文件

{OUTLINE_PRODUCTION_CONTROL_PROTOCOL}
{OUTLINE_IDEATION_PROTOCOL}
{OUTLINE_SEARCH_REFERENCE_PROTOCOL}

如果作者只是发散、比较、追问、判断“该不该进入大纲层”，保持讨论态。
如果作者明确要求“初始化大纲”“重建大纲”“生成四层大纲”“落档/写入/归档”，请说明这属于 COMMIT_AGENT 的写入链路，当前 DISCUSS_AGENT 不写文件。

结尾只问一个关键问题，或给出一个明确的下一步建议。不要输出 hidden JSON，不要宣称已写入草稿。
"""


DISCUSS_INSTRUCTION = f"""# Role: DISCUSS_AGENT
{OUTLINE_IDEATION_PROTOCOL}
{OUTLINE_SEARCH_REFERENCE_PROTOCOL}

你是当前作品的大纲讨论代理，不是归档代理，也不是正文续写器。

OUTLINE_LAYER_CONTROL_PROTOCOL：
- `brainstorm.md` 是卖点试验池：题材卖点、开局钩子、爽点母题、风险区、被拒方案、待决创意。
- `master_outline.md` 是读者承诺契约：长线主欲望、核心循环、终局方向、不可违背约束、期待债、重大兑现计划。
- `arc_outline.md` 是留存单元计划：15-30 章弧线目标、入场钩子、压力阶梯、兑现序列、信息缺口、伏笔、弧尾钩子。
- `chapter_outline.md` 是逐章生产卡组：每章目标、入场场景、冲突阻碍、兑现、状态变化、伏笔动作、结尾钩子、约束引用。

{OUTLINE_PRODUCTION_CONTROL_PROTOCOL}

讨论态职责：
1. 读取 `summary.md`、`world_model.md`、`status_card.md`、`style_constraints_for_continuation.md` 和当前 outline 文件的小范围证据。
2. 帮作者判断哪些内容应该进入 brainstorm/master/arc/chapter 四层中的哪一层。
3. 发现 summary/world/status/style 证据不足时明确说“证据不足”，不要编造成熟大纲。
4. 保持作者主权：未明确要求写入时只讨论，不调用写入工具。
5. 作者要求“下一留存单元”“下一篇章”“续写前大纲”等生产设计时，优先给后续生产卡，并按 SOURCE_FACT / AUTHOR_PROPOSAL / WORLD_MODEL_REQUIRED / EXTERNAL_REFERENCE 标注来源模式。
6. 作者明确要求联网、搜索或现实资料参考时，才调用 google_search；搜索结果只作为 EXTERNAL_REFERENCE。

硬边界：
- DISCUSS_AGENT 只有读取工具，不得声称写入或初始化完成。
- 不写 `chapter_draft.md`。正文续写属于 continuation agent。
- 不写 `summary.md`、`world_model.md`、`status_card.md`、style 文件或 `error_archive.md`。
- 不输出 `<think>`、hidden JSON、工具参数模板或后端内部控制标记。
"""


COMMIT_QUERY = f"""当前 book_id：{{{{#{START_NODE_ID}.book_id#}}}}
{OUTLINE_LANDING_PROTOCOL}
当前书名：{{{{#{START_NODE_ID}.book_name#}}}}
当前打开文件：{{{{#{START_NODE_ID}.active_file#}}}}
作者当前意图：{{{{#sys.query#}}}}

你当前执行的是“大纲归档/初始化/重建”任务，不是继续讨论。

请先判定：
1. 作者是否明确要求写入、初始化、重建、归档或保存大纲。
2. 本轮是单文件归档，还是 OUTLINE_LAYER_CONTROL_PROTOCOL 的四件套初始化/重建。
3. 必须读取哪些上下文文件和当前 outline 文件。
4. 最终只能写哪些 outline 文件。

如果作者说“初始化大纲”“重建大纲”“初始化/重建大纲”“生成四层大纲”，必须生成四份 reviewable draft：
- `brainstorm.md`
- `master_outline.md`
- `arc_outline.md`
- `chapter_outline.md`

{OUTLINE_PRODUCTION_CONTROL_PROTOCOL}
{OUTLINE_TOOL_ARGUMENT_SAFETY_PROTOCOL}

请保持归档态。写入前读取必要证据，写入后用自然语言汇报每个文件的落点和工具返回结果。
"""


COMMIT_INSTRUCTION = f"""# Role: COMMIT_AGENT
{OUTLINE_LANDING_PROTOCOL}

你是当前作品的大纲归档与初始化代理。你的工作是把成熟讨论、作者明确指令，或“初始化/重建大纲”请求，整理成可审阅的 draft/sandbox 草稿。

OUTLINE_LAYER_CONTROL_PROTOCOL：
- `brainstorm.md` = 卖点试验池。记录题材卖点、开局钩子、爽点母题、风险区、被拒方案、待决创意，不把未证实灵感伪装成主线。
- `master_outline.md` = 读者承诺契约。记录长线主欲望、核心循环、终局方向、非谈判约束、期待债、重大兑现计划。
- `arc_outline.md` = 留存单元计划。按 15-30 章弧线组织，必须有入场钩子、压力阶梯、兑现序列、信息缺口、伏笔/回收、弧尾钩子和硬约束。
- `chapter_outline.md` = 逐章生产卡组。每张卡必须包含章节目标、入场场景、冲突/阻碍、当章兑现、状态变化、伏笔动作、结尾钩子、约束引用。

{OUTLINE_PRODUCTION_CONTROL_PROTOCOL}

上下文读取协议：
1. 所有工具调用优先携带 `book_id`；book_id 为空时才使用 book_name。
2. 初始化/重建前必须读取或抽样读取：
   - `summary.md`：先 get_markdown_outline，再用 get_archive_range/get_markdown_section 读取关键段，不要整篇搬运。
   - `world_model.md`：读读者承诺、硬/软约束、冲突发动机、未回收承诺。
   - `status_card.md`：读当前阶段、张力等级、当前驱动、未兑现承诺、主角状态。
   - `style_constraints_for_continuation.md`：读节奏、句式、禁忌、续写约束。
   - 四个现有 outline 文件：取得 outline、section_path 和 base_etag。
3. 每份输出必须显式写出“依据与对齐”：对应到 summary/world/status/style 的证据，而不是凭空生成。

初始化/重建四件套的最低质量线：
1. `brainstorm.md` 至少包含：核心卖点、开局/当前钩子、爽点母题、可试路线、风险区、拒绝清单、待决问题。
2. `master_outline.md` 至少包含：读者承诺、主欲望、核心循环、终局方向、主角推进线、期待债台账、重大兑现顺序、不可违背约束。
3. `arc_outline.md` 至少包含：当前/下一 15-30 章留存单元，入场钩子、压力阶梯、信息差、阶段兑现、伏笔/回收、弧尾钩子、约束引用。
4. `chapter_outline.md` 至少包含：3-8 张可执行章节卡；每卡写清目标、场景入口、冲突/障碍、当章兑现、状态变化、伏笔动作、结尾钩子、引用约束。
5. 每份文件都必须有“证据模式/生产边界”或等价段落，明确区分 SOURCE_FACT、AUTHOR_PROPOSAL、WORLD_MODEL_REQUIRED、EXTERNAL_REFERENCE。不能把 AUTHOR_PROPOSAL、WORLD_MODEL_REQUIRED 或 EXTERNAL_REFERENCE 写成既成事实。

写入工具纪律：
OUTLINE_FLAT_WRITE_PROTOCOL：
1. 只有明确写入/初始化/重建/归档/保存意图时，才能调用 `draft_replace_markdown_section` 或 `draft_append_markdown_section`。
2. `draft/sandbox 是后端 Git 分支`，不是文件路径。`file_name 只能填写裸文件名`，例如 `brainstorm.md`；禁止填写 `draft/sandbox/brainstorm.md` 或任何路径前缀。
3. 初始化/重建四件套时，必须分别调用四次扁平写入工具：`brainstorm.md`、`master_outline.md`、`arc_outline.md`、`chapter_outline.md` 各一次。禁止使用嵌套 `writes` 数组，禁止把多个文件塞进同一次工具调用。
4. 优先使用 `draft_replace_markdown_section` 替换每个文件的根 section；只有追加子区块时才使用 `draft_append_markdown_section`。
5. 每次工具调用的参数必须是一层扁平对象：`book_id`、`file_name`、`section_path`、`content`、`base_etag`、`origin`、`message`。不要构造数组、嵌套 JSON、批量写入参数或工具参数文本。
6. `origin` 必须正好是 `explicit_user_write`。
7. `base_etag` 必须来自最近读取目标文件的 get_markdown_outline/get_markdown_section/get_core_archive。
8. 对只有根标题的模板文件，替换根 section；content 必须保留该文件自己的一级标题。
9. 四份文件没有全部写入成功前，不得宣称初始化/重建完成。工具失败时必须指出失败文件和原因。

硬边界：
- 只能写 `brainstorm.md`、`master_outline.md`、`arc_outline.md`、`chapter_outline.md`。
- 禁止写 `chapter_draft.md`；你只能给 continuation agent 提供可执行章节卡。
- 禁止写 `summary.md`、`world_model.md`、`status_card.md`、`style_guide.md`、`style_fingerprint.md`、`style_review.md`、`style_constraints_for_continuation.md`、`error_archive.md`、`domain_rules.md`。
- 不输出 `<think>`、hidden JSON 或工具参数伪文本；工具调用结束后用可见自然语言汇报。
"""


CLASS_1_NAME = """用户当前仍然希望继续讨论，而不是立即把结果写进文件。

适用情况：
- 用户还在发散、比较、试探、追问。
- 用户想判断某个想法应该下沉到 brainstorm/master/arc/chapter 哪一层。
- 用户要求只读地体验、诊断或设计“下一留存单元”“下一篇章”“某个新篇章方向”等生产方案，但没有要求写入文件。
- 用户说“继续”“沿这个继续”“再深入一点”“换个方向”“重新发散”“先不要落档”。
- 用户只是询问大纲层现状、创作理论、如何优化分层大纲。

边界：
- 该分类进入 `DISCUSS_AGENT`。
- 重点是继续讨论当前问题，而不是生成可写入文件的草稿。
- 只要没有明确要求写入、归档、初始化或重建，都优先视为本分类。
"""


CLASS_2_NAME = """用户当前希望把结果整理为 outline 文件草稿，或明确要求初始化/重建大纲。

适用情况：
- 用户明确要求写入、保存、归档、整理进去、落档。
- 用户要求“初始化大纲”“重建大纲”“初始化/重建大纲”“生成四层大纲”“生成大纲四件套”。
- 用户要求把当前讨论结果写入 brainstorm.md、master_outline.md、arc_outline.md 或 chapter_outline.md。
- 用户希望输出可审阅、可回退、可继续编辑的 draft/sandbox 草稿。
- 用户要求把下一留存单元、下一篇章、续写前生产卡或类似生产卡写入 outline 四件套。

边界：
- 该分类进入 `COMMIT_AGENT`。
- 初始化/重建大纲必须生成四份 outline 草稿：brainstorm.md、master_outline.md、arc_outline.md、chapter_outline.md。
- 只有 outline 四件套可写；不得写 chapter_draft.md 或 world/status/summary/style/error 文件。
"""


COMMIT_INSTRUCTION = COMMIT_INSTRUCTION.replace(
    OUTLINE_PRODUCTION_CONTROL_PROTOCOL,
    OUTLINE_PRODUCTION_CONTROL_PROTOCOL + "\n" + OUTLINE_TOOL_ARGUMENT_SAFETY_PROTOCOL,
    1,
)


def run(args: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=ROOT,
        input=input_text,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )


def psql(args: list[str], *, input_text: str | None = None) -> str:
    docker_args = ["docker", "exec"]
    if input_text is not None:
        docker_args.append("-i")
    docker_args.extend(
        [
            DB_CONTAINER,
            "psql",
            "-U",
            "postgres",
            "-d",
            DB_NAME,
            "-v",
            "ON_ERROR_STOP=1",
            *args,
        ]
    )
    proc = run(docker_args, input_text=input_text)
    if proc.returncode:
        raise RuntimeError(
            "psql failed\n"
            f"COMMAND: {' '.join(a for a in proc.args if a)}\n"
            f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return proc.stdout


def psql_at(sql: str) -> list[str]:
    out = psql(["-A", "-t", "-F", "\t", "-c", sql])
    return [line for line in out.splitlines() if line.strip()]


def dollar_quote(value: str) -> str:
    for tag in ("codex", "codex_outline", "codex_outline2"):
        marker = f"${tag}$"
        if marker not in value:
            return f"{marker}{value}{marker}"
    raise ValueError("Cannot build a safe dollar-quoted SQL string")


def sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def load_provider_tools() -> list[dict[str, Any]]:
    rows = psql_at(
        f"""
        select encode(convert_to(tools_str, 'UTF8'), 'hex')
        from tool_api_providers
        where id = '{TOOL_PROVIDER_ID}'
        """
    )
    if len(rows) != 1:
        raise RuntimeError(f"Expected one ToolProvider row, found {len(rows)}")
    tools_text = bytes.fromhex(rows[0]).decode("utf-8")
    tools = json.loads(tools_text)
    if not isinstance(tools, list):
        raise RuntimeError("ToolProvider tools_str is not a list")
    entries: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            raise RuntimeError("ToolProvider tool entry is not a dict")
        entries.append(tool)
    return entries


def workflow_tool_entry(tool_name: str, provider_tools: list[dict[str, Any]], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    provider_tool = next((item for item in provider_tools if item.get("operation_id") == tool_name), None)
    if provider_tool is None:
        raise RuntimeError(f"Provider missing tool for workflow entry: {tool_name}")
    description = (
        TOOL_DESCRIPTION_OVERRIDES.get(tool_name)
        or provider_tool.get("summary")
        or provider_tool.get("openapi", {}).get("description")
        or tool_name
    )
    entry = deepcopy(existing) if existing is not None else {}
    entry.update(
        {
            "type": "api",
            "enabled": True,
            "tool_name": tool_name,
            "tool_label": tool_name,
            "provider_name": TOOL_PROVIDER_ID,
            "provider_show_name": "LoreGit 后端工具集",
            "tool_description": description,
            "extra": {"description": description},
            "settings": {},
        }
    )
    params: dict[str, dict[str, int]] = {}
    for param in provider_tool.get("parameters", []):
        name = param.get("name")
        if isinstance(name, str):
            params[name] = {"auto": 1}
    entry["parameters"] = params
    return entry


def google_search_tool_entry(existing: dict[str, Any] | None = None) -> dict[str, Any]:
    entry = deepcopy(existing) if existing is not None else {}
    description = (
        entry.get("tool_description")
        or (entry.get("extra") or {}).get("description")
        or GOOGLE_SEARCH_DESCRIPTION
    )
    parameters = entry.get("parameters")
    if not isinstance(parameters, dict) or not parameters:
        parameters = {
            "query": {"auto": 1, "value": None},
            "country_code": {"auto": 1, "value": None},
            "language_code": {"auto": 1, "value": None},
        }
    entry.update(
        {
            "type": "builtin",
            "enabled": True,
            "tool_name": GOOGLE_SEARCH_TOOL_NAME,
            "tool_label": entry.get("tool_label") or "谷歌搜索",
            "provider_name": GOOGLE_SEARCH_PROVIDER_NAME,
            "provider_show_name": entry.get("provider_show_name") or GOOGLE_SEARCH_PROVIDER_NAME,
            "tool_description": description,
            "extra": {"description": description},
            "settings": {
                **(entry.get("settings") if isinstance(entry.get("settings"), dict) else {}),
                "as_agent_tool": {"value": {"type": "constant", "value": True}},
            },
            "parameters": parameters,
        }
    )
    return entry


def google_search_enabled_for_agent(tool: dict[str, Any]) -> bool:
    if tool.get("tool_name") != GOOGLE_SEARCH_TOOL_NAME:
        return False
    settings = tool.get("settings") if isinstance(tool.get("settings"), dict) else {}
    as_agent_tool = settings.get("as_agent_tool") if isinstance(settings.get("as_agent_tool"), dict) else {}
    value = as_agent_tool.get("value")
    if isinstance(value, dict):
        value = value.get("value")
    return (
        tool.get("type") == "builtin"
        and tool.get("enabled") is True
        and tool.get("provider_name") == GOOGLE_SEARCH_PROVIDER_NAME
        and value is True
    )


def load_outline_workflows() -> tuple[str, list[dict[str, Any]]]:
    app_rows = psql_at(
        f"""
        select id::text, workflow_id::text, name, mode
        from apps
        where id = '{APP_ID}'
        """
    )
    if len(app_rows) != 1:
        raise RuntimeError(f"Expected one outline app row, found {len(app_rows)}")
    app_id, live_workflow_id, app_name, app_mode = app_rows[0].split("\t")
    if app_id != APP_ID or live_workflow_id != EXPECTED_LIVE_WORKFLOW_ID:
        raise RuntimeError(f"Unexpected outline app identity: app={app_id}, live_workflow={live_workflow_id}")
    if app_mode != "advanced-chat":
        raise RuntimeError(f"Unexpected outline app mode for {app_name}: {app_mode}")

    rows = psql_at(
        f"""
        select
            w.id::text,
            case when w.id = a.workflow_id then 'live' else w.version end,
            encode(convert_to(w.graph::text, 'UTF8'), 'hex')
        from workflows w
        join apps a on a.id = w.app_id
        where w.app_id = '{APP_ID}'
          and (w.id = a.workflow_id or w.version = 'draft')
        order by case when w.id = a.workflow_id then 0 else 1 end, w.updated_at desc
        """
    )
    if len(rows) != 2:
        raise RuntimeError(f"Expected live and draft outline workflows, found {len(rows)}")

    workflows: list[dict[str, Any]] = []
    for row in rows:
        workflow_id, version, graph_hex = row.split("\t", 2)
        graph_text = bytes.fromhex(graph_hex).decode("utf-8")
        workflows.append({"id": workflow_id, "version": version, "graph_text": graph_text, "graph": json.loads(graph_text)})
    if workflows[0]["id"] != EXPECTED_LIVE_WORKFLOW_ID or workflows[0]["version"] != "live":
        raise RuntimeError("The first outline workflow row is not the expected live workflow")
    if workflows[1]["version"] != "draft":
        raise RuntimeError("The second outline workflow row is not the draft workflow")
    return live_workflow_id, workflows


def start_node(graph: dict[str, Any]) -> dict[str, Any]:
    starts = [node for node in graph.get("nodes", []) if (node.get("data") or {}).get("type") == "start"]
    if len(starts) != 1:
        raise RuntimeError(f"Expected one start node, found {len(starts)}")
    node = starts[0]
    if node.get("id") != START_NODE_ID:
        raise RuntimeError(f"Unexpected start node id: {node.get('id')}")
    return node


def start_variable_names(graph: dict[str, Any]) -> list[str]:
    variables = (start_node(graph).get("data") or {}).get("variables")
    if not isinstance(variables, list):
        raise RuntimeError("Start node variables are not a list")
    names: list[str] = []
    for item in variables:
        if not isinstance(item, dict):
            raise RuntimeError("Start node variable entry is not a dict")
        raw_name = item.get("variable")
        if isinstance(raw_name, str):
            names.append(raw_name)
    return names


def ensure_start_book_id_variable(graph: dict[str, Any]) -> bool:
    node = start_node(graph)
    variables = node.setdefault("data", {}).setdefault("variables", [])
    if not isinstance(variables, list):
        raise RuntimeError("Start node variables are not a list")
    if any(isinstance(item, dict) and item.get("variable") == "book_id" for item in variables):
        return False
    book_id_variable = {
        "hint": "",
        "type": "text-input",
        "label": "book_id",
        "default": "",
        "options": [],
        "required": False,
        "variable": "book_id",
        "placeholder": "",
    }
    insert_at = 0
    for index, item in enumerate(variables):
        if isinstance(item, dict) and item.get("variable") == "book_name":
            insert_at = index + 1
            break
    variables.insert(insert_at, book_id_variable)
    return True


def agent_nodes(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise RuntimeError("Workflow graph is missing nodes or edges arrays")
    if len(nodes) != EXPECTED_NODE_COUNT or len(edges) != EXPECTED_EDGE_COUNT:
        raise RuntimeError(f"Unexpected outline topology: nodes={len(nodes)}, edges={len(edges)}")

    agents: dict[str, dict[str, Any]] = {}
    for node in nodes:
        data = node.get("data") or {}
        if data.get("type") == "agent":
            title = data.get("title")
            if title in agents:
                raise RuntimeError(f"Duplicate agent title: {title}")
            agents[title] = node
    expected = {DISCUSS_AGENT_TITLE, COMMIT_AGENT_TITLE}
    if set(agents) != expected:
        raise RuntimeError(f"Unexpected outline agent titles: {sorted(agents)}")
    return agents


def classifier_node(graph: dict[str, Any]) -> dict[str, Any]:
    classifiers = [node for node in graph.get("nodes", []) if (node.get("data") or {}).get("type") == "question-classifier"]
    if len(classifiers) != 1:
        raise RuntimeError(f"Expected one question-classifier node, found {len(classifiers)}")
    return classifiers[0]


def tool_entries(node: dict[str, Any]) -> list[dict[str, Any]]:
    value = node.get("data", {}).get("agent_parameters", {}).get("tools", {}).get("value", [])
    if not isinstance(value, list):
        raise RuntimeError("Agent tools value is not a list")
    entries: list[dict[str, Any]] = []
    for tool in value:
        if not isinstance(tool, dict):
            raise RuntimeError("Agent tool entry is not a dict")
        entries.append(tool)
    return entries


def tool_names(node: dict[str, Any]) -> list[str]:
    return [tool.get("tool_name") for tool in tool_entries(node)]


def set_agent_prompt(node: dict[str, Any], *, query: str, instruction: str) -> bool:
    changed = False
    params = node.setdefault("data", {}).setdefault("agent_parameters", {})
    if params.setdefault("query", {"type": "constant"}).get("value") != query:
        params["query"] = {"type": "constant", "value": query}
        changed = True
    if params.setdefault("instruction", {"type": "constant"}).get("value") != instruction:
        params["instruction"] = {"type": "constant", "value": instruction}
        changed = True
    return changed


def set_agent_thinking(node: dict[str, Any], enabled: bool) -> bool:
    params = node.setdefault("data", {}).setdefault("agent_parameters", {})
    model = params.setdefault("model", {"type": "constant", "value": {}}).setdefault("value", {})
    completion = model.setdefault("completion_params", {})
    if completion.get("thinking") != enabled:
        completion["thinking"] = enabled
        return True
    return False


def set_max_iterations(node: dict[str, Any], value: int) -> bool:
    params = node.setdefault("data", {}).setdefault("agent_parameters", {})
    if params.get("maximum_iterations", {}).get("value") == value:
        return False
    params["maximum_iterations"] = {"type": "constant", "value": value}
    return True


def set_tools(
    node: dict[str, Any],
    desired_names: list[str],
    source_tools: dict[str, dict[str, Any]],
    provider_tools: list[dict[str, Any]],
    preserve_google_search: bool = False,
) -> bool:
    params = node.setdefault("data", {}).setdefault("agent_parameters", {})
    current_entries = tool_entries(node)
    desired_entries: list[dict[str, Any]] = []
    for tool_name in desired_names:
        current = next((tool for tool in current_entries if tool.get("tool_name") == tool_name), None)
        if current is None:
            current = source_tools.get(tool_name)
        if current is None:
            desired_entries.append(workflow_tool_entry(tool_name, provider_tools))
        else:
            desired_entries.append(workflow_tool_entry(tool_name, provider_tools, current))
    if preserve_google_search:
        google_entry = next((tool for tool in current_entries if tool.get("tool_name") == GOOGLE_SEARCH_TOOL_NAME), None)
        if google_entry is None:
            google_entry = source_tools.get(GOOGLE_SEARCH_TOOL_NAME)
        if not any(tool.get("tool_name") == GOOGLE_SEARCH_TOOL_NAME for tool in desired_entries):
            desired_entries.append(google_search_tool_entry(google_entry))
    if current_entries == desired_entries:
        return False
    params.setdefault("tools", {"type": "constant"})["type"] = "constant"
    params["tools"]["value"] = desired_entries
    return True


def patch_classifier(graph: dict[str, Any]) -> bool:
    node = classifier_node(graph)
    data = node.setdefault("data", {})
    changed = False
    model = data.setdefault("model", {})
    completion = model.setdefault("completion_params", {})
    if completion.get("thinking") is not False or completion.get("temperature") != 0:
        model["completion_params"] = {"thinking": False, "temperature": 0}
        changed = True
    classes = data.setdefault("classes", [])
    if not isinstance(classes, list):
        raise RuntimeError("Question classifier classes are not a list")
    by_id = {item.get("id"): item for item in classes if isinstance(item, dict)}
    if set(by_id) != {"1", "2"}:
        raise RuntimeError(f"Unexpected classifier class ids: {sorted(by_id)}")
    if by_id["1"].get("name") != CLASS_1_NAME:
        by_id["1"]["name"] = CLASS_1_NAME
        changed = True
    if by_id["2"].get("name") != CLASS_2_NAME:
        by_id["2"]["name"] = CLASS_2_NAME
        changed = True
    return changed


def validate_graph(graph: dict[str, Any], *, label: str) -> dict[str, Any]:
    agents = agent_nodes(graph)
    classifier = classifier_node(graph)
    snapshot: dict[str, Any] = {
        "nodes": len(graph["nodes"]),
        "edges": len(graph["edges"]),
        "start_variables": start_variable_names(graph),
        "classifier_sha": sha_text(json.dumps((classifier.get("data") or {}).get("classes"), ensure_ascii=False)),
        "agents": {},
    }
    if label.startswith("after:") and "book_id" not in snapshot["start_variables"]:
        raise RuntimeError(f"{label} start node is missing book_id variable")

    classifier_text = json.dumps(classifier.get("data") or {}, ensure_ascii=False)
    if label.startswith("after:"):
        for marker in ("初始化大纲", "重建大纲", "COMMIT_AGENT", "brainstorm.md", "chapter_outline.md"):
            if marker not in classifier_text:
                raise RuntimeError(f"{label} classifier missing marker: {marker}")

    for title, node in sorted(agents.items()):
        params = node.get("data", {}).get("agent_parameters", {})
        model = (params.get("model") or {}).get("value") or {}
        if model.get("provider") != EXPECTED_MODEL_PROVIDER or model.get("model") != EXPECTED_MODEL:
            raise RuntimeError(f"{label} {title} model changed unexpectedly: {model}")
        tools = tool_names(node)
        if title == DISCUSS_AGENT_TITLE:
            tools_without_search = [tool_name for tool_name in tools if tool_name != GOOGLE_SEARCH_TOOL_NAME]
            if tools_without_search != DISCUSS_TOOLS or tools.count(GOOGLE_SEARCH_TOOL_NAME) > 1:
                raise RuntimeError(f"{label} {title} tools mismatch: {tools}")
            if label.startswith("after:"):
                google_entries = [tool for tool in tool_entries(node) if tool.get("tool_name") == GOOGLE_SEARCH_TOOL_NAME]
                if len(google_entries) != 1 or not google_search_enabled_for_agent(google_entries[0]):
                    raise RuntimeError(f"{label} DISCUSS_AGENT google_search is not enabled as an agent tool")
            expected_tool_options = None
        elif label.startswith("before:"):
            expected_tool_options = [COMMIT_TOOLS, PREPATCH_COMMIT_TOOLS]
        else:
            expected_tool_options = [COMMIT_TOOLS]
        if expected_tool_options is not None and tools not in expected_tool_options:
            raise RuntimeError(f"{label} {title} tools mismatch: {tools}")
        instruction = (params.get("instruction") or {}).get("value")
        query = (params.get("query") or {}).get("value")
        if not isinstance(instruction, str) or not isinstance(query, str):
            raise RuntimeError(f"{label} {title} prompt fields are not strings")
        if label.startswith("after:"):
            completion = model.get("completion_params") or {}
            if completion.get("thinking") is not True:
                raise RuntimeError(f"{label} {title} thinking is not enabled: {completion}")
            if title == DISCUSS_AGENT_TITLE:
                if not instruction.startswith("# Role: DISCUSS_AGENT"):
                    raise RuntimeError(f"{label} DISCUSS_AGENT is not labeled as DISCUSS_AGENT")
                if "# Role: COMMIT_AGENT" in instruction:
                    raise RuntimeError(f"{label} DISCUSS_AGENT still contains COMMIT_AGENT role label")
            required_markers = COMMIT_PROMPT_MARKERS if title == COMMIT_AGENT_TITLE else DISCUSS_PROMPT_MARKERS
            for marker in required_markers:
                if marker not in instruction and marker not in query:
                    raise RuntimeError(f"{label} {title} prompt missing marker: {marker}")
            if title == COMMIT_AGENT_TITLE:
                for marker in ("OUTLINE_FLAT_WRITE_PROTOCOL", "draft_replace_markdown_section", "explicit_user_write", "依据与对齐"):
                    if marker not in instruction and marker not in query:
                        raise RuntimeError(f"{label} COMMIT_AGENT prompt missing marker: {marker}")
        snapshot["agents"][title] = {
            "model_provider": model.get("provider"),
            "model": model.get("model"),
            "completion_params": model.get("completion_params"),
            "tools": tools,
            "has_google_search": GOOGLE_SEARCH_TOOL_NAME in tools,
            "google_search_agent_tool_enabled": any(
                google_search_enabled_for_agent(tool) for tool in tool_entries(node)
            ),
            "instruction_sha": sha_text(instruction),
            "instruction_len": len(instruction),
            "query_sha": sha_text(query),
            "query_len": len(query),
        }
    return snapshot


def collect_source_tools(workflows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    source_tools: dict[str, dict[str, Any]] = {}
    for item in workflows:
        for node in agent_nodes(item["graph"]).values():
            for tool in tool_entries(node):
                source_tools.setdefault(tool.get("tool_name"), tool)
    return source_tools


def patch_graph(
    graph: dict[str, Any],
    provider_tools: list[dict[str, Any]],
    inherited_source_tools: dict[str, dict[str, Any]] | None = None,
) -> bool:
    changed = False
    if ensure_start_book_id_variable(graph):
        changed = True
    agents = agent_nodes(graph)
    source_tools: dict[str, dict[str, Any]] = dict(inherited_source_tools or {})
    for node in agents.values():
        for tool in tool_entries(node):
            source_tools.setdefault(tool.get("tool_name"), tool)

    discuss = agents[DISCUSS_AGENT_TITLE]
    commit = agents[COMMIT_AGENT_TITLE]
    changed = set_agent_prompt(discuss, query=DISCUSS_QUERY, instruction=DISCUSS_INSTRUCTION) or changed
    changed = set_agent_prompt(commit, query=COMMIT_QUERY, instruction=COMMIT_INSTRUCTION) or changed
    changed = set_tools(discuss, DISCUSS_TOOLS, source_tools, provider_tools, preserve_google_search=True) or changed
    changed = set_tools(commit, COMMIT_TOOLS, source_tools, provider_tools) or changed
    changed = set_agent_thinking(discuss, True) or changed
    changed = set_agent_thinking(commit, True) or changed
    changed = set_max_iterations(discuss, 30) or changed
    changed = set_max_iterations(commit, 45) or changed
    changed = patch_classifier(graph) or changed
    return changed


def backup(workflows: list[dict[str, Any]], stamp: str) -> Path:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    out = RUNTIME / f"outline_agent_workflow_backup_{stamp}.json"
    payload = [
        {
            "id": item["id"],
            "version": item["version"],
            "graph_sha": sha_text(item["graph_text"]),
            "graph": item["graph"],
        }
        for item in workflows
    ]
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def update_workflows(workflows: list[dict[str, Any]]) -> None:
    statements = ["begin;"]
    for item in workflows:
        graph_text = json.dumps(item["graph"], ensure_ascii=False, separators=(",", ":"))
        statements.append(
            "update workflows "
            f"set graph = {dollar_quote(graph_text)}, updated_at = now() "
            f"where id = '{item['id']}';"
        )
    statements.append("commit;")
    psql([], input_text="\n".join(statements) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="validate and preview without DB writes")
    args = parser.parse_args()

    provider_tools = load_provider_tools()
    live_workflow_id, workflows = load_outline_workflows()
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup(workflows, stamp)

    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    changed = False
    inherited_source_tools = collect_source_tools(workflows)
    for item in workflows:
        before[item["id"]] = validate_graph(item["graph"], label=f"before:{item['version']}")
        changed = patch_graph(item["graph"], provider_tools, inherited_source_tools) or changed
        after[item["id"]] = validate_graph(item["graph"], label=f"after:{item['version']}")

    if changed and not args.dry_run:
        update_workflows(workflows)

    print(
        json.dumps(
            {
                "app_id": APP_ID,
                "live_workflow_id": live_workflow_id,
                "backup": str(backup_path.relative_to(ROOT)),
                "dry_run": args.dry_run,
                "changed": changed,
                "workflow_ids": [{"id": item["id"], "version": item["version"]} for item in workflows],
                "before": before,
                "after": after,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
