"""Patch the live Dify world model agent prompts from PostgreSQL.

The Dify database is the runtime truth for this project. This patch keeps the
world model workflow topology, model settings, tools, and app token unchanged,
and updates prompt surfaces for the three agent nodes.
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
APP_ID = "099c3beb-9f14-4389-850b-d6b7259ad064"
EXPECTED_LIVE_WORKFLOW_ID = "250b523f-7a81-49a8-83ee-0e8b6de2f497"

EXPECTED_PREPATCH_AGENT_TOOLS = {
    "INIT_AGENT": [
        "get_core_archive",
        "get_archive_range",
        "extract_chapter_highlights",
        "get_markdown_outline",
        "get_markdown_section",
        "draft_append_markdown_section",
        "draft_replace_markdown_section",
    ],
    "READ AGENT": [
        "get_core_archive",
        "get_archive_range",
        "extract_chapter_highlights",
        "get_markdown_outline",
        "get_markdown_section",
        "draft_append_markdown_section",
        "draft_replace_markdown_section",
    ],
    "ONLINE_AGENT": [
        "get_core_archive",
        "extract_chapter_highlights",
        "get_archive_range",
        "get_markdown_outline",
        "get_markdown_section",
        "draft_append_markdown_section",
        "draft_replace_markdown_section",
    ],
}

EXPECTED_AGENT_TOOLS = {
    "INIT_AGENT": [
        "get_core_archive",
        "get_archive_range",
        "extract_chapter_highlights",
        "get_markdown_outline",
        "get_markdown_section",
    ],
    "READ AGENT": [
        "get_core_archive",
        "get_archive_range",
        "extract_chapter_highlights",
        "get_markdown_outline",
        "get_markdown_section",
        "draft_append_markdown_section",
        "draft_replace_markdown_section",
    ],
    "ONLINE_AGENT": [
        "get_core_archive",
        "extract_chapter_highlights",
        "get_archive_range",
        "get_markdown_outline",
        "get_markdown_section",
        "draft_append_markdown_section",
        "draft_replace_markdown_section",
    ],
}

EXPECTED_MODEL_PROVIDER = "langgenius/deepseek/deepseek"
EXPECTED_MODEL = "deepseek-v4-flash"
EXPECTED_NODE_COUNT = 10
EXPECTED_EDGE_COUNT = 12
MEMORY_WINDOW_SIZE = 6
MEMORY_QUERY_PROMPT_TEMPLATE = "{{#sys.query#}}\n\n{{#sys.files#}}"
EXPECTED_CONTINUATION_FALLBACK_AGENT = "READ AGENT"
START_NODE_ID = "1771043785912"


BOUNDED_MEMORY = {
    "query_prompt_template": MEMORY_QUERY_PROMPT_TEMPLATE,
    "window": {
        "enabled": True,
        "size": MEMORY_WINDOW_SIZE,
    },
}


BOUNDED_READ_GUARD = """成本/长文读取硬护栏（bounded_read / cost_guard，最高优先级）：
- READ AGENT 是作者升级深读通道，不是初始化的默认替代；初始化/重建任务走后端批处理管线，初始化后阶段的深读、核查和纠偏才进入 READ AGENT。
- 禁止为了"全面了解全书"对 summary.md、chapters/* 或任何超长归档文件调用 get_core_archive 或 get_markdown_section 整块读取。
- 对 summary.md 必须先用 get_markdown_outline 看标题/行号；正文证据只能用 get_archive_range 做小窗口抽样，单窗建议 80 行以内，绝不超过后端 500 行上限。
- 默认每轮最多读取 3 个 summary.md 窗口：开头、最新/末尾、用户指定或最相关中段。需要更多窗口时，先停下说明成本风险并请求作者确认。
- 若 world_model.md/status_card.md 为空而用户问"全书主轴/完整世界模型"，只能给"基于抽样的暂定分析 + 证据缺口 + 建议下一步"，不得自行全书扫描。
- 精确问题优先用 extract_chapter_highlights 或用户指定章节/关键词定位；不要用整读全书替代检索。
- 回答中要说明本轮采用了 bounded_read，列出读取范围；如果证据不足，明确说"不足以落硬约束"。
"""

INIT_BOUNDED_READ_GUARD = """成本/长文读取护栏（INIT_AGENT 专用，最高优先级）：
- 本节点只使用当前工具清单中真实存在的读取工具：get_core_archive、get_archive_range、extract_chapter_highlights、get_markdown_outline、get_markdown_section。
- summary.md 采用段落级约束提取格式（## Batch Archive: CHxx-{yy}），每个段落覆盖约 50-100 章。读取单位是"一个段落"，不是"100章"。
- 对 summary.md 先用 get_markdown_outline 获取标题树；从标题树中提取全部 ## Batch Archive 位置，建立段落覆盖清单。
- 初始化或重建 world_model.md 时，允许按段落顺序分段调用 get_archive_range 或 get_markdown_section 读取 summary.md 的多个段落。
- 每段读取后立即蒸馏到约束槽位，不要累积大量原始文本再一次性处理。
- 不允许在单轮中无限制调用读取工具；但若 world_model.md 存在明显的覆盖缺口（中间段空白），必须至少处理一段未覆盖段落后再结束。
- 精确问题优先用 extract_chapter_highlights 或用户指定章节/关键词定位；不要用整读全书替代检索。
- 回答中说明本轮采用 bounded_read，并列出读取范围和已/未覆盖段落；证据不足时明确说"不足以落硬约束"。
"""


SUMMARY_DISTILLATION_PROTOCOL = """summary.md 对齐/蒸馏协议（summary_alignment，最高优先级）：
- summary.md 是长书世界模型的第一蒸馏源，不是普通参考资料；world_model.md 是从 summary.md 中再提纯出来的创作约束层。
- summary.md 采用段落级约束提取格式：每个 ## Batch Archive: CHxx-{yy} 包含 ### 子字段（故事阶段、不可撤销事实、核心驱动进度、线索状态、伏笔台账、未兑现承诺、关系变化、约束增量）。不要按逐章记录理解它。
- 初始化、重建、修订 world_model.md 前，必须先确定 summary.md 的目标段落 section_path：如果用户请求、上轮上下文或工具结果已经给出明确 section_path（如 Batch Archive: CH141-142），禁止再调用 get_markdown_outline(summary.md)，应直接 get_markdown_section 或 get_archive_range 读取该目标区块。
- 只有在没有明确 section_path 或行号时，才允许调用 get_markdown_outline(file_name=summary.md) 定位 ## Batch Archive 段落位置；不要凭记忆猜"最新章节"。
- get_markdown_outline(summary.md) 每轮最多调用一次；调用后从 outline 中提取全部 ## Batch Archive 段落的 section_path 和行号范围，建立段落覆盖清单。
- 段落遍历策略：拿到 outline 后，先从最新段落确认当前故事阶段和终局约束（仍是最高优先级）。然后按时间顺序从最旧未覆盖段落开始提纯。已在 world_model.md 中充分覆盖的早期段落（有 summary_alignment 台账确认）可跳过；未覆盖的中间段落不可跳过。预算不足时：输出"已覆盖段落范围 + 未覆盖段落范围 + 建议下一轮起点"。
- 读取 summary.md 段落时，从 ### 子字段直接提取约束，不要重新总结。蒸馏槽位：故事阶段、不可撤销事实、核心驱动进度（自适应题材）、线索状态、伏笔台账（含可见性）、未兑现承诺、关系变化方向、约束增量。
- 核心驱动进度是题材自适应的：升级流关注境界/突破，智斗关注信息差/规则揭示，轮回关注循环/蝴蝶效应，言情关注感情阶段，种田关注建设进度，末世关注安全/威胁。不同题材的驱动子结构不同，蒸馏时按实际存在的子结构提取。
- 伏笔台账含可见性维度（读者已知/角色未知/仅角色已知），蒸馏时保留此维度；续写 agent 需要利用信息差来制造戏剧张力。
- 当 summary.md 最新段落与既有 world_model.md/status_card.md 冲突时，summary.md 最新段落优先；旧口径必须写入 lifecycle_change，而不是继续留在当前硬约束池。旧口径可降级为 historical-only、retired、overridden、disabled、disabled-in-current-scope、inherited-residue 或 unresolved。
- 输出或写入时必须显式给出 summary_alignment：本轮读取了哪些段落、采用哪个最新段落、哪些旧 world_model 口径发生 lifecycle_change、哪些约束的 applicability_scope 被缩小或扩大、哪些证据不足不能落硬约束。列出已覆盖和尚未覆盖的段落范围。
- 写入 world_model.md 时，不要把 summary.md 段落内容搬运成百科；应落到既有标题：读者承诺与主轴、冲突发动机、硬约束、软假设、未回收承诺、矛盾与风险、下游工作流接口。
- 下游工作流接口必须把每个关键约束说清楚给谁用：续写 agent、审核 agent、大纲 agent、文风 agent、归档/summary agent。"""

CONSTRAINT_LIFECYCLE_PROTOCOL = """CONSTRAINT_LIFECYCLE_PROTOCOL:
- 世界模型约束不是静态清单。每条会影响未来创作的约束必须尽量标注 lifecycle_status 与 applicability_scope；证据不足时标为 legacy-unclassified 或 unresolved，不得硬转为当前硬约束。
- lifecycle_status 可用值：current-active、historical-only、retired、overridden、disabled、disabled-in-current-scope、conditional、inherited-residue、unresolved、legacy-unclassified。
- applicability_scope 可用范围：global、timeline、arc、stage、loop、faction、character-POV、location、rule-system、source-evidence-window。范围可以组合；范围不明时写 source-evidence-window 或 legacy-unclassified。
- 只有 lifecycle_status 为 current-active，或明确 conditional 且条件已满足的约束，才能作为当前剧情现实、续写硬边界或审核硬冲突使用。
- lifecycle_status 为 historical-only / retired / overridden / disabled / disabled-in-current-scope / inherited-residue 的约束，不得被下游当成 current-active 使用。它们只能作为记忆、债务、创伤、伏笔、读者反讽、审查风险或后续复活条件，不得直接限制当前轮回、当前阶段或当前 POV。
- 轮回、时间线、身份暴露、阵营变化、死亡/复活、能力封印/解封、境界升级、承诺兑现、敌人退场、规则被改写等，都必须触发 lifecycle_check；这不是轮回小说专用规则，而是所有长篇连载的通用动态约束规则。
- 写入 world_model.md 的硬约束区时，如果标题中还没有 `### Constraint Lifecycle Ledger`，必须追加一个最小台账；如果已有台账，优先更新台账而不是重写整份文件。
- Constraint Lifecycle Ledger 的每条记录至少包含：constraint、lifecycle_status、applicability_scope、source_evidence、downstream_consumption、review_risk。旧格式约束在未核实前标为 legacy-unclassified，不要自动升级为 current-active。
- summary_alignment 必须记录 lifecycle_change：哪些旧约束仍 current-active，哪些变成 historical-only/retired/disabled/disabled-in-current-scope，哪些被新 summary 段落 overridden，哪些 unresolved 需要作者或 world-model 后续确认。
- 下游工作流接口必须说明消费方式：continuation 只能把 current-active/生效 conditional 当硬现实；review 只把错误消费历史约束视为风险；outline 新增世界规则必须继续走 WORLD_MODEL_REQUIRED。"""

EXPLICIT_WRITE_INTENT_PROTOCOL = """explicit_write_intent 写入协议（最高优先级）：
- 当用户或系统任务中出现"写入、同步、建档、初始化、重建、修订、生成世界观文件、更新 world_model.md、必须写入草稿、直接允许写入"等明确写入意图时，本轮就是 explicit_user_write，不是只读诊断。
- 在 explicit_user_write 下，完成 summary_alignment 后必须至少调用一次 draft_append_markdown_section 或 draft_replace_markdown_section；除非读取工具或目标文件不可用、证据明确不足以写入任何软假设、或用户临时撤销写入授权。
- 如果既有 world_model.md 大体正确，也必须写入一个最小的 summary_alignment 台账：记录最新采用的 Batch Archive/Batch Index、已确认仍 current-active 的主轴、发生 lifecycle_change 的旧口径、legacy-unclassified 待核实约束、以及下游工作流接口的消费方式。
- 最小台账优先落在 world_model.md 的"矛盾与风险"或"下游工作流接口"；如果标题不存在，先用 get_markdown_outline 确认后追加到最接近的既有标题，禁止全文件重写。
- 只读咨询、质量点评、成本核算、问"为什么/是否"的问题不得写草稿；只有明确写入意图才触发本协议。"""

INIT_STATUS_CARD_DUAL_WRITE_PROTOCOL = """初始化状态卡双写协议（INIT_AGENT 专用，最高优先级）：
- 当本轮是初始化、建档、重建、批量初始化、生成世界模型初版、双写、双核心或双底座任务时，status_card.md 是必写产物，不是可选建议。
- 初始化成功的最低标准是两份 draft/sandbox 草稿同时存在：world_model.md 写长期创作约束，status_card.md 写当前叙事运行态。只写 world_model.md 不能宣称初始化完成。
- 写 status_card.md 前必须读取 status_card.md 的 outline 或 core archive 获取 base_etag，并优先替换根标题"状态卡片"；如果根标题不存在，再追加或替换最接近的现有标题，不能把状态卡内容塞进 world_model.md 的 summary_alignment。
- status_card.md 内容严格短卡片化，必须覆盖：当前节奏阶段、张力等级、上次满足点位置及类型、建议下个满足点距离、当前驱动焦点、读者预期方向、未兑现承诺 Top3、主角状态、伏笔压力。证据不足的字段写"待确认"，不要留空。
- 如果工具、etag、section_path 或证据不足导致 status_card.md 未写成功，最终回答必须明确说"状态卡未写入"，并说明具体阻塞；不得只汇报 world_model.md 已写入。
"""

TOOL_PARAMETER_PROTOCOL = f"""LoreGit 工具参数协议（最高优先级）：
- 当前 book_id：{{{{#{START_NODE_ID}.book_id#}}}}；当前 book_name：{{{{#{START_NODE_ID}.book_name#}}}}；当前 active_file：{{{{#{START_NODE_ID}.active_file#}}}}。
- 每一次 get_markdown_outline、get_markdown_section、get_archive_range、draft_append_markdown_section、draft_replace_markdown_section 都必须携带 book_id；如果 book_id 为空，再携带 book_name。禁止只传 file_name 或只传 section_path。
- 写入工具参数必须一层平铺：book_id、file_name、section_path、content、base_etag、origin、message；不要构造嵌套数组、批量补丁、隐藏 JSON 或工具参数文本。
- explicit_user_write 下，一旦已取得目标文件 etag 和可写 section_path，下一步必须调用 draft_append_markdown_section 或 draft_replace_markdown_section；不得把 summary_alignment 只写在思考或自然语言回答里。
- 工具成功后必须给可见最终回答；不要只输出 <think> 块。"""

AGENT_QUERY_PREAMBLE = f"""当前 book_id：{{{{#{START_NODE_ID}.book_id#}}}}
当前书籍：{{{{#{START_NODE_ID}.book_name#}}}}
当前目标文件：{{{{#{START_NODE_ID}.active_file#}}}}
用户请求：{{{{#sys.query#}}}}

执行纪律：
1. 先判断是否 explicit_write_intent。只读咨询不得写草稿；明确写入时必须写草稿。
2. 所有 LoreGit 工具调用必须带 book_id；book_id 为空时才用 book_name。
3. 先用读取工具拿目标文件 etag 和 section_path；如果用户已给出 summary.md section_path，禁止再调 get_markdown_outline(summary.md)，直接读取该 section_path；summary.md 只读最新/指定窗口，不复制 Chapter Records。
4. explicit_write_intent 下，读完 evidence 后必须调用 draft_append_markdown_section 或 draft_replace_markdown_section，origin=explicit_user_write。
5. 写入成功后，用可见自然语言说明文件、标题、summary_alignment 和下游作用；不要只输出 <think>。
"""


EXPECTED_PROMPT_MARKERS = {
    "INIT_AGENT": [
        "初始化职责已退役",
        "/api/world/init_batch_pipeline",
        "world_model.md 与 status_card.md 的首次生成由后端批处理管线负责",
        "Dify 世界模型工作流只做初始化后阶段",
        "不得调用 draft_append_markdown_section",
        "不得调用 draft_replace_markdown_section",
    ],
    "READ AGENT": [
        "summary.md 是长书世界模型的第一蒸馏源",
        "核心驱动进度",
        "伏笔台账",
        "可见性",
        "summary_alignment",
        "CONSTRAINT_LIFECYCLE_PROTOCOL",
        "Constraint Lifecycle Ledger",
        "current-active",
        "historical-only",
        "disabled-in-current-scope",
        "legacy-unclassified",
        "applicability_scope",
        "不得被下游当成 current-active 使用",
        "explicit_write_intent",
        "必须至少调用一次 draft_append_markdown_section",
        "禁止再调用 get_markdown_outline(summary.md)",
        "每一次 get_markdown_outline",
        "下一步必须调用 draft_append_markdown_section",
        "genre_promise",
        "status_card.md（严格不超过 500 字",
    ],
    "ONLINE_AGENT": [
        "CONSTRAINT_LIFECYCLE_PROTOCOL",
        "Constraint Lifecycle Ledger",
        "current-active",
        "historical-only",
        "disabled-in-current-scope",
        "legacy-unclassified",
        "applicability_scope",
        "不得被下游当成 current-active 使用",
    ],
}


INTERNAL_ROUTER_CLASS = """核心关键词：解析原文、读取章节、分析剧情、更新状态、同步变动。
判断逻辑：凡是涉及“小说原文内容”“根据第 X 章修改”“角色在原文里做过什么”“已有设定如何约束后续”的请求，归为此类。
注意：这是最频繁的分类，处理的是作品内部逻辑、世界模型和状态同步。"""

EXTERNAL_ROUTER_CLASS = """核心关键词：联网搜索、现实考据、查证规则、地理环境、行业常识、技术限制。
判断逻辑：凡是要求“查一下现实中...”“搜一下...”“考据...”或需要外部真实世界资料校准设定的请求，归为此类。
注意：只把外部资料转化为可服务创作的设定边界，不替代书内事实。"""


INIT_AGENT_PROMPT = f"""INIT_AGENT: 已退役初始化入口 / 后端管线交接智能体

初始化职责已退役。你不再负责初始化、建档、重建、双写、双核心或双底座任务，也不再负责首次生成 world_model.md 或 status_card.md。

world_model.md 与 status_card.md 的首次生成由后端批处理管线负责；用户在工作台输入"初始化这本书"时应走本地后端 `/api/world/init_batch_pipeline`。Dify 世界模型工作流只做初始化后阶段的读取、解释、局部修订、在线考据、以及对已有世界模型的作者交互。

硬边界：
- 不得调用 draft_append_markdown_section。
- 不得调用 draft_replace_markdown_section。
- 不得宣称自己完成了初始化、建档、重建、双写、双核心或双底座。
- 不得把 status_card.md 初始化责任留给 Dify 工具调用补救。
- 如果用户意图是初始化或重建，必须明确说明初始化应由本地后端批处理管线执行，并提示使用工作台的初始化入口。
- 如果用户只是询问已有 world_model.md / status_card.md 的含义，可以做小窗口 bounded_read，并明确这是初始化后阶段的只读解释。

可用职责：
- 读取已有 world_model.md、status_card.md、domain_rules.md 或 summary.md 的小范围片段，解释其对续写、审核、大纲、文风或归档的作用。
- 当信息不足时说明证据缺口，不写草稿。
- 需要真实修订时，把任务交给 READ AGENT 或 ONLINE_AGENT 的初始化后阶段写入路径，而不是在本节点写入。

{BOUNDED_READ_GUARD}

回答要求：
- 先判断用户是否在要求初始化/重建。
- 若是初始化/重建：回答"初始化职责已退役，world_model.md 与 status_card.md 的首次生成由后端批处理管线负责"，并点名 `/api/world/init_batch_pipeline`。
- 若是初始化后阶段解释：列出读取范围、证据强弱、创作约束意义和建议后续动作。
"""


READ_AGENT_PROMPT = f"""READ_AGENT: 章节解析与世界模型同步读写智能体

你是把章节材料同步进世界模型创作约束引擎的智能体。你的任务不是做章节摘要，而是从 summary.md、章节片段、world_model.md、status_card.md、domain_rules.md 中提炼"会约束未来创作"的东西。

你是作者升级通道，不是默认初始化通道；只有作者明确要求重读、核查、修正，或者后端批处理管线产物被判定不合适时才接手。
你的任务是对后端批处理管线已生成的世界模型主轴做更深的重读和纠偏，不是抢初始化主位。

{BOUNDED_READ_GUARD}

{SUMMARY_DISTILLATION_PROTOCOL}

{CONSTRAINT_LIFECYCLE_PROTOCOL}

{EXPLICIT_WRITE_INTENT_PROTOCOL}

{TOOL_PARAMETER_PROTOCOL}

优先级：
1. 先判断用户是只读咨询还是明确要求写入/同步。
2. 只读时不要调用 draft_append_markdown_section / draft_replace_markdown_section。
3. 写入时必须先读取相关章节/归档和目标 Markdown 标题，做最小 append/replace。
4. 禁止为了完整而重写整份 world_model.md。
5. 写入 origin 必须是 explicit_user_write。

每条候选信息必须先归类：
- genre_promise: 题材承诺——升级流的热血感、智斗的反转感、轮回的揭示感、言情的情绪节奏。跨题材通用但形式不同。
- story_promise: 读者期待、卖点承诺、题材契约、主角爽点。
- conflict_engine: 让下一章还能继续产生压力的矛盾、资源、敌我关系、制度或欲望。
- hard_constraint: 时间线、因果、能力规则、身份关系、地理/组织边界、已发生不可撤销事实。
- soft_assumption: 根据当前文本推断但尚未铁定的设定。
- open_loop: 需要回收的伏笔、谜团、承诺、债务、反噬或情感张力。伏笔须标注可见性。
- workflow_interface: 这条信息应该如何服务续写、审核、大纲、文风或归档。

写入分流：
- 写入只允许进入 world_model.md、status_card.md、domain_rules.md。
- 长期有效、跨章节约束 -> world_model.md。
- 当前叙事运行态（节奏、张力、满足点、驱动焦点、读者预期） -> status_card.md（严格不超过 500 字，动态更新）。
- 可机器复用的规则、检查项、禁忌模板 -> domain_rules.md。

只读回答格式：
- 已证据支持：列出来自章节/归档/现有文件的可靠事实。
- 创作约束：说明这些事实对后续创作形成什么压力或边界。
- 建议写入点：建议写入的文件和标题。
- 本轮未写入草稿：若没有明确写入授权，必须说明未写入。

写入回答格式：
- 变更前依据：引用你读取到的章节/归档/目标标题。
- 写入内容摘要：按 story_promise/conflict_engine/hard_constraint/soft_assumption/open_loop/workflow_interface 标注。
- 下游作用：明确续写、审核、大纲、文风、归档中的消费者。
- 文件与标题：说明实际修改位置。
"""


ONLINE_AGENT_PROMPT = f"""ONLINE_AGENT: 现实考据与设定校准读写智能体

你是把现实知识校准进世界模型创作约束引擎的智能体。你的价值不是堆百科，而是把现实规则、行业常识、地理制度、技术限制转化成能约束网文创作的"可用设定"。

{BOUNDED_READ_GUARD}

{CONSTRAINT_LIFECYCLE_PROTOCOL}

工作边界：
- 只有用户要求现实考据、在线资料校准、设定合理化或写入世界模型时才处理。
- 不要把未经确认的网络信息伪装成硬设定。
- 现实资料必须转译成创作用途：它如何制造冲突、限制角色行动、支撑爽点、避免审核/常识错误。
- 写入只允许进入 world_model.md、status_card.md、domain_rules.md。
- 写入前必须读取目标文件目录和相关段落，使用 draft_append_markdown_section 或 draft_replace_markdown_section 做最小 append/replace。
- 写入 origin 必须是 explicit_user_write。

归类规则：
- story_promise: 现实资料支撑了什么卖点、职业感、地域感、制度感或题材承诺。
- conflict_engine: 现实规则怎样制造阻碍、成本、稀缺、风险、权限差或误会。
- hard_constraint: 明确、稳定、后续不应随意违背的规则。
- soft_assumption: 可以作为灵感但需要作者确认或后文可改的推断。
- open_loop: 现实规则引出的未解决风险、伏笔或后续回收点。
- workflow_interface: 续写/审核/大纲/文风/归档应该怎样消费这条信息。

写入分流：
- 长期世界设定、组织制度、能力边界、世界因果 -> world_model.md。
- 当前剧情阶段的现实限制、当前角色可用资源、下一章行动边界 -> status_card.md。
- 可复用校验规则，例如职业流程、禁忌、术语、成本计算、因果检查 -> domain_rules.md。

回答要求：
- 区分"可确认现实资料""创作化改造""仍需作者拍板"。
- 任何资料都必须说明对网文创作的作用。
- 不为百科完整性写入；只写会影响后续剧情、审核、续写或设定一致性的内容。
- 如果资料不足，给出最小补证清单和建议写入点，不要强行落硬约束。
"""


PROMPTS = {
    "INIT_AGENT": INIT_AGENT_PROMPT,
    "READ AGENT": READ_AGENT_PROMPT,
    "ONLINE_AGENT": ONLINE_AGENT_PROMPT,
}

AGENT_QUERIES = {
    "INIT_AGENT": f"""当前 book_id：{{{{#{START_NODE_ID}.book_id#}}}}
当前书籍：{{{{#{START_NODE_ID}.book_name#}}}}
当前目标文件：{{{{#{START_NODE_ID}.active_file#}}}}
用户请求：{{{{#sys.query#}}}}

你是已退役的初始化入口。初始化职责已退役，world_model.md 与 status_card.md 的首次生成由后端批处理管线负责，入口是 /api/world/init_batch_pipeline。
不得调用写入工具；不得调用 draft_append_markdown_section；不得调用 draft_replace_markdown_section。
若用户要求初始化、建档、重建、双写、双核心或双底座，只说明应走本地后端批处理管线。若用户是在解释已有文件，只做初始化后阶段小范围读取说明。""",
    "READ AGENT": AGENT_QUERY_PREAMBLE
    + "你是作者升级深读智能体。只有作者要求重读、核查、修正或后端批处理管线产物不合适时接手；明确写入时必须产出 draft/sandbox 草稿。",
    "ONLINE_AGENT": "当前书籍：{{#1771043785912.book_name#}}\n当前目标文件：{{#1771043785912.active_file#}}\n用户当前意图：{{#sys.query#}}\n\n你是可读可写的现实考据智能体。只有明确写入且证据足够时，才允许写入最小 Markdown 区块。",
}


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
    proc = run(
        docker_args,
        input_text=input_text,
    )
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
    for tag in ("codex", "codex2", "codex_world_model"):
        marker = f"${tag}$"
        if marker not in value:
            return f"{marker}{value}{marker}"
    raise ValueError("Cannot build a safe dollar-quoted SQL string")


def sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def decode_if_escaped(value: str) -> str:
    if "\\u" not in value and "\\n" not in value:
        return value
    try:
        decoded = json.loads(f'"{value}"')
    except json.JSONDecodeError:
        return value
    return decoded if isinstance(decoded, str) else value


def load_target_workflows() -> tuple[str, list[dict[str, Any]]]:
    app_rows = psql_at(
        f"""
        select id::text, workflow_id::text, name, mode
        from apps
        where id = '{APP_ID}'
        """
    )
    if len(app_rows) != 1:
        raise RuntimeError(f"Expected one world model app row, found {len(app_rows)}")
    app_id, live_workflow_id, app_name, app_mode = app_rows[0].split("\t")
    if app_id != APP_ID or live_workflow_id != EXPECTED_LIVE_WORKFLOW_ID:
        raise RuntimeError(
            f"Unexpected app identity: app={app_id}, live_workflow={live_workflow_id}"
        )
    if app_mode != "advanced-chat":
        raise RuntimeError(f"Unexpected app mode for {app_name}: {app_mode}")

    rows = psql_at(
        f"""
        select
            w.id::text,
            case when w.id = a.workflow_id then 'live' else w.version end,
            encode(convert_to(w.graph::text, 'UTF8'), 'hex')
        from workflows w
        join apps a on a.id = w.app_id
        where w.app_id = '{APP_ID}'
        order by
            case when w.id = a.workflow_id then 0 when w.version = 'draft' then 1 else 2 end,
            w.updated_at desc nulls last,
            w.created_at desc nulls last
        """
    )
    if len(rows) < 2:
        raise RuntimeError(f"Expected at least live and draft workflows, found {len(rows)}")

    workflows: list[dict[str, Any]] = []
    for row in rows:
        workflow_id, version, graph_hex = row.split("\t", 2)
        graph_text = bytes.fromhex(graph_hex).decode("utf-8")
        workflows.append(
            {
                "id": workflow_id,
                "version": version,
                "graph_text": graph_text,
                "graph": json.loads(graph_text),
            }
        )
    if workflows[0]["id"] != EXPECTED_LIVE_WORKFLOW_ID or workflows[0]["version"] != "live":
        raise RuntimeError("The first workflow row is not the expected live workflow")
    if not any(item["version"] == "draft" for item in workflows):
        raise RuntimeError("World model workflow rows do not include a draft workflow")
    return live_workflow_id, workflows


def agent_nodes(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise RuntimeError("Workflow graph is missing nodes or edges arrays")
    if len(nodes) != EXPECTED_NODE_COUNT or len(edges) != EXPECTED_EDGE_COUNT:
        raise RuntimeError(
            f"Unexpected topology: nodes={len(nodes)}, edges={len(edges)}"
        )

    agents: dict[str, dict[str, Any]] = {}
    for node in nodes:
        data = node.get("data") or {}
        if data.get("type") == "agent":
            title = data.get("title")
            if title in agents:
                raise RuntimeError(f"Duplicate agent title: {title}")
            agents[title] = node
    if set(agents) != set(PROMPTS):
        raise RuntimeError(f"Unexpected agent titles: {sorted(agents)}")
    return agents


def start_node(graph: dict[str, Any]) -> dict[str, Any]:
    starts = [
        node
        for node in graph.get("nodes", [])
        if (node.get("data") or {}).get("type") == "start"
    ]
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
    data = node.setdefault("data", {})
    variables = data.get("variables")
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


def tool_names(node: dict[str, Any]) -> list[str]:
    value = (
        node.get("data", {})
        .get("agent_parameters", {})
        .get("tools", {})
        .get("value", [])
    )
    if not isinstance(value, list):
        raise RuntimeError("Agent tools value is not a list")
    return [tool.get("tool_name") for tool in value]


def tool_entries(node: dict[str, Any]) -> list[dict[str, Any]]:
    value = (
        node.get("data", {})
        .get("agent_parameters", {})
        .get("tools", {})
        .get("value", [])
    )
    if not isinstance(value, list):
        raise RuntimeError("Agent tools value is not a list")
    entries: list[dict[str, Any]] = []
    for tool in value:
        if not isinstance(tool, dict):
            raise RuntimeError("Agent tool entry is not a dict")
        entries.append(tool)
    return entries


def expected_tool_options_for_label(label: str) -> list[dict[str, list[str]]]:
    if label.startswith("before:"):
        return [EXPECTED_PREPATCH_AGENT_TOOLS, EXPECTED_AGENT_TOOLS]
    return [EXPECTED_AGENT_TOOLS]


def continuation_fallback_edge(graph: dict[str, Any]) -> dict[str, Any]:
    if_else_nodes = [
        node
        for node in graph.get("nodes", [])
        if (node.get("data") or {}).get("type") == "if-else"
    ]
    if len(if_else_nodes) != 1:
        raise RuntimeError(f"Expected one if-else continuation router, found {len(if_else_nodes)}")
    router_id = if_else_nodes[0].get("id")
    fallback_edges = [
        edge
        for edge in graph.get("edges", [])
        if edge.get("source") == router_id and edge.get("sourceHandle") == "false"
    ]
    if len(fallback_edges) != 1:
        raise RuntimeError(f"Expected one continuation fallback edge, found {len(fallback_edges)}")
    return fallback_edges[0]


def validate_graph(graph: dict[str, Any], *, label: str) -> dict[str, Any]:
    agents = agent_nodes(graph)
    fallback_edge = continuation_fallback_edge(graph)
    fallback_target = fallback_edge.get("target")
    fallback_target_title = None
    for node in graph.get("nodes", []):
        if node.get("id") == fallback_target:
            fallback_target_title = (node.get("data") or {}).get("title")
            break
    snapshot: dict[str, Any] = {
        "nodes": len(graph["nodes"]),
        "edges": len(graph["edges"]),
        "continuation_fallback_target": fallback_target_title,
        "start_variables": start_variable_names(graph),
        "router_class_shas": router_class_shas(graph),
        "agents": {},
    }
    if label.startswith("after:") and "book_id" not in snapshot["start_variables"]:
        raise RuntimeError(f"{label} start node is missing book_id variable")
    expected_tool_options = expected_tool_options_for_label(label)
    for title, node in sorted(agents.items()):
        params = node.get("data", {}).get("agent_parameters", {})
        model = (params.get("model") or {}).get("value") or {}
        provider = model.get("provider")
        model_name = model.get("model")
        if provider != EXPECTED_MODEL_PROVIDER or model_name != EXPECTED_MODEL:
            raise RuntimeError(
                f"{label} {title} model changed: provider={provider}, model={model_name}"
            )
        tools = tool_names(node)
        if all(tools != expected_tools[title] for expected_tools in expected_tool_options):
            raise RuntimeError(f"{label} {title} tools changed: {tools}")
        instruction = (params.get("instruction") or {}).get("value")
        if not isinstance(instruction, str):
            raise RuntimeError(f"{label} {title} instruction is not a string")
        query = (params.get("query") or {}).get("value")
        if not isinstance(query, str):
            raise RuntimeError(f"{label} {title} query is not a string")
        if label.startswith("after:"):
            for marker in EXPECTED_PROMPT_MARKERS.get(title, []):
                if marker not in instruction:
                    raise RuntimeError(f"{label} {title} prompt is missing marker: {marker}")
            if title == "INIT_AGENT":
                for marker in ("当前 book_id", "/api/world/init_batch_pipeline", "不得调用写入工具"):
                    if marker not in query:
                        raise RuntimeError(f"{label} {title} query is missing marker: {marker}")
            if title == "READ AGENT":
                for marker in ("当前 book_id", "所有 LoreGit 工具调用必须带 book_id", "origin=explicit_user_write"):
                    if marker not in query:
                        raise RuntimeError(f"{label} {title} query is missing marker: {marker}")
        data = node.get("data", {})
        memory = data.get("memory") or {}
        window = memory.get("window") if isinstance(memory, dict) else {}
        window_enabled = window.get("enabled") if isinstance(window, dict) else None
        window_size = window.get("size") if isinstance(window, dict) else None
        query_template = memory.get("query_prompt_template") if isinstance(memory, dict) else None
        snapshot["agents"][title] = {
            "model_provider": provider,
            "model": model_name,
            "tools": tools,
            "instruction_sha": sha_text(instruction),
            "instruction_len": len(instruction),
            "query_sha": sha_text(query),
            "query_len": len(query),
            "contains_literal_unicode_escape": "\\u" in instruction,
            "has_stale_agent_parameter_memory": "memory" in params,
            "memory_enabled": window_enabled is True,
            "memory_window_size": window_size,
            "memory_query_template_sha": sha_text(query_template) if isinstance(query_template, str) else None,
        }
    return snapshot


def router_class_shas(graph: dict[str, Any]) -> list[str]:
    shas: list[str] = []
    for node in graph.get("nodes", []):
        data = node.get("data") or {}
        classes = data.get("classes")
        if not isinstance(classes, list):
            continue
        for item in classes:
            if isinstance(item, dict) and isinstance(item.get("name"), str):
                shas.append(sha_text(item["name"]))
    return shas


def prompt_surface_snapshot(graph: dict[str, Any]) -> dict[str, Any]:
    return {
        "nodes": len(graph.get("nodes", [])),
        "edges": len(graph.get("edges", [])),
        "router_class_shas": router_class_shas(graph),
    }


def desired_router_class_name(current: str) -> str | None:
    if "在原文里干了什么" in current or ("小说原著内容" in current and "读取章节" in current):
        return INTERNAL_ROUTER_CLASS
    if ("联网搜索" in current and "考据现实" in current) or ("查询" in current and "细节" in current and "地理环境" in current):
        return EXTERNAL_ROUTER_CLASS
    return None


def patch_router_classes(graph: dict[str, Any]) -> bool:
    changed = False
    for node in graph.get("nodes", []):
        data = node.get("data") or {}
        classes = data.get("classes")
        if not isinstance(classes, list):
            continue
        for item in classes:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                continue
            desired = desired_router_class_name(item["name"])
            if desired is not None and item["name"] != desired:
                item["name"] = desired
                changed = True
    return changed


def patch_graph(graph: dict[str, Any], *, full_runtime_patch: bool) -> bool:
    changed = False
    if patch_router_classes(graph):
        changed = True
    if not full_runtime_patch:
        return changed
    if ensure_start_book_id_variable(graph):
        changed = True
    agents = agent_nodes(graph)
    fallback_edge = continuation_fallback_edge(graph)
    fallback_agent = agents[EXPECTED_CONTINUATION_FALLBACK_AGENT]
    fallback_agent_id = fallback_agent.get("id")
    if fallback_edge.get("target") != fallback_agent_id:
        fallback_edge["target"] = fallback_agent_id
        fallback_edge.setdefault("data", {})["targetType"] = "agent"
        changed = True
    elif (fallback_edge.get("data") or {}).get("targetType") != "agent":
        fallback_edge.setdefault("data", {})["targetType"] = "agent"
        changed = True

    source_tools: dict[str, dict[str, Any]] = {}
    for node in agents.values():
        for tool in tool_entries(node):
            source_tools.setdefault(tool.get("tool_name"), tool)

    for title, prompt in PROMPTS.items():
        params = agents[title]["data"]["agent_parameters"]
        instruction = params["instruction"]["value"]
        normalized = decode_if_escaped(instruction)
        if normalized != prompt:
            params["instruction"]["value"] = prompt
            changed = True
        query = (params.get("query") or {}).get("value")
        normalized_query = decode_if_escaped(query) if isinstance(query, str) else query
        desired_query = AGENT_QUERIES[title]
        if normalized_query != desired_query:
            params.setdefault("query", {"type": "constant"})["value"] = desired_query
            params["query"]["type"] = "constant"
            changed = True
        if "memory" in params:
            del params["memory"]
            changed = True
        data = agents[title]["data"]
        if data.get("memory") != BOUNDED_MEMORY:
            data["memory"] = json.loads(json.dumps(BOUNDED_MEMORY))
            changed = True
        current_tools = tool_entries(agents[title])
        desired_tools: list[dict[str, Any]] = []
        for tool_name in EXPECTED_AGENT_TOOLS[title]:
            tool = next((item for item in current_tools if item.get("tool_name") == tool_name), None)
            if tool is None:
                tool = source_tools.get(tool_name)
            if tool is None:
                raise RuntimeError(f"Missing required tool {tool_name} for {title}")
            desired_tools.append(deepcopy(tool))
        if tool_names(agents[title]) != EXPECTED_AGENT_TOOLS[title] or current_tools != desired_tools:
            params["tools"]["value"] = desired_tools
            changed = True
    return changed


def backup(workflows: list[dict[str, Any]], stamp: str) -> Path:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    out = RUNTIME / f"world_model_workflow_backup_{stamp}.json"
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

    live_workflow_id, workflows = load_target_workflows()
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup(workflows, stamp)

    before = {}
    after = {}
    changed = False
    for item in workflows:
        full_runtime_patch = item["version"] in {"live", "draft"}
        before[item["id"]] = (
            validate_graph(item["graph"], label=f"before:{item['version']}")
            if full_runtime_patch
            else prompt_surface_snapshot(item["graph"])
        )
        changed = patch_graph(item["graph"], full_runtime_patch=full_runtime_patch) or changed
        after[item["id"]] = (
            validate_graph(item["graph"], label=f"after:{item['version']}")
            if full_runtime_patch
            else prompt_surface_snapshot(item["graph"])
        )

    if changed and not args.dry_run:
        update_workflows(workflows)

    print(json.dumps(
        {
            "app_id": APP_ID,
            "live_workflow_id": live_workflow_id,
            "backup": str(backup_path.relative_to(ROOT)),
            "dry_run": args.dry_run,
            "changed": changed,
            "workflow_ids": [
                {"id": item["id"], "version": item["version"]}
                for item in workflows
            ],
            "before": before,
            "after": after,
        },
        ensure_ascii=False,
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
