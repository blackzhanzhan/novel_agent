"""Patch live Dify continuation runtime.

The Dify PostgreSQL database is the runtime truth for this project. This script
exposes the LoreGit continuation gates and patches the live/draft continuation
workflow without changing endpoint ports, workflow topology, or model identity.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime"
OPENAPI_PATH = ROOT / "novel_git_server" / "docs" / "openapi_v3_5_1_draft_min.json"

DB_CONTAINER = "docker-db_postgres-1"
DB_NAME = "dify"
TOOL_PROVIDER_ID = "c41fee3b-54dd-4e49-af9b-be30f68f6242"
APP_ID = "089d589b-09a5-42b9-864b-ccac331bb8f8"
EXPECTED_LIVE_WORKFLOW_ID = "a11bafc7-4495-4b9f-8925-041f259f87e9"
EXPECTED_MODEL_PROVIDER = "langgenius/deepseek/deepseek"
EXPECTED_MODEL = "deepseek-v4-flash"
EXPECTED_NODE_COUNT = 3
EXPECTED_EDGE_COUNT = 2
START_NODE_ID = "1777261774474"
AGENT_TITLE = "CONTINUATION_AGENT"

VALIDATE_CHAPTER_LENGTHS = "validate_chapter_lengths"
GENERATE_STYLE_DIAGNOSTICS = "generate_style_diagnostics"
REQUIRED_PROVIDER_OPERATIONS = (
    VALIDATE_CHAPTER_LENGTHS,
    GENERATE_STYLE_DIAGNOSTICS,
)
OPERATION_PATHS = {
    VALIDATE_CHAPTER_LENGTHS: ("post", "/tools/validate_chapter_lengths"),
    GENERATE_STYLE_DIAGNOSTICS: ("post", "/tools/generate_style_diagnostics"),
}
ENDPOINT_RE = re.compile(r"host\.docker\.internal:(\d+)")

CONTINUATION_TOOLS = [
    "get_markdown_outline",
    "get_markdown_section",
    "get_archive_range",
    "get_core_archive",
    "draft_append_markdown_section",
    "draft_replace_markdown_section",
    "validate_chapter_lengths",
    "generate_style_diagnostics",
]

TOOL_DESCRIPTION_OVERRIDES = {
    "get_markdown_outline": "读取指定 Markdown 文件的标题结构、section_path 与 base_etag，用于安全定位章节和写入前校验。",
    "get_markdown_section": "读取指定 Markdown 文件的局部章节内容，用于小范围取证、对齐和修订前确认。",
    "get_archive_range": "按范围读取书库归档内容，用于抽样核对摘要、原文样本、世界观、状态和大纲证据。",
    "get_core_archive": "读取书库核心档案，用于快速取得当前作品的关键上下文；大文件只在必要时兜底使用。",
    "draft_append_markdown_section": "在 draft/sandbox 分支向指定 Markdown 文件追加完整子章节；参数必须扁平，file_name 只能是裸文件名。",
    "draft_replace_markdown_section": "在 draft/sandbox 分支替换指定 Markdown section；content 必须包含目标标题行，base_etag 必须来自最近读取结果。",
    "validate_chapter_lengths": "只读统计 chapter_draft.md 中各章节篇幅，返回非空白字符数、目标线、缺口和状态；不写文件。",
    "generate_style_diagnostics": "只读生成文风诊断与打磨提示，把结果作为作者参考的 style_advisory；不写文件，不充当调度硬门。",
}

PROMPT_MARKERS = [
    "CONTINUATION_PRODUCTION_LAYER_PROTOCOL",
    "CHAPTER_CARD_EXECUTION_PROTOCOL",
    "LENGTH_GATE_PROTOCOL",
    "LENGTH_REPAIR_STYLE_PRIORITY_PROTOCOL",
    "BRIDGE_DENSITY_REPAIR_PROTOCOL",
    "SOURCE_FACT",
    "AUTHOR_PROPOSAL",
    "WORLD_MODEL_REQUIRED",
    "style_constraints_for_continuation.md",
    "style_guide.md",
    "source_text_imitation_reference",
    "style_advisory",
    "STYLE_ADVISORY_PROTOCOL",
    "AUTHOR_STYLE_REVISION_PROTOCOL",
    "validate_chapter_lengths",
    "generate_style_diagnostics",
    "author_revision_owner",
    "locks_scheduler=false",
    "style_files_imitation_reference",
    "latest_source_text",
    "style_gate_not_scheduler_lock",
    "style_advisory_diagnostics",
    "four_density_failure",
    "STYLE_METRIC_DELTA_PROTOCOL",
    "style_metric_delta",
    "proxy_repair_goals",
    "protected_metrics",
    "protected_metric_regressions",
    "block_blind_expansion",
    "average_paragraph_chars_must_decrease",
    "no_merge_split_beats",
    "environment_cue_clusters_must_decrease",
    "delete_atmosphere_only_cues",
    "length_or_size_recovery_regressed_protected_metric",
    "CHAPTER_CONTEXT_PACK_PROTOCOL",
    "chapter_context_pack",
    "decision_chain",
    "non_negotiable_facts",
    "truth_source_refs",
    "pack_reads_chapter_draft_text",
    "pack_is_hidden_canon",
    "continuation_agent_remains_only_chapter_draft_writer",
    "WRITE_LOOP_BUDGET_PROTOCOL",
    "AI_WRITE_LOOP_GUARD",
    "six_recent_repair_like",
    "立即停止",
    "PARAGRAPH_ENVIRONMENT_REPAIR_DELTA",
    "paragraph_count_must_increase",
    "no_merge_back_into_bulk_paragraphs",
    "environment_cue_budget",
    "environment_terms_must_decrease",
    "no_environment_padding",
    "no_q_and_a_padding",
    "scene_bound_micro_beats",
    "style_gate",
    "red_flags",
    "chapter_outline.md",
    "chapter_draft.md",
    "draft_append_markdown_section",
    "draft_replace_markdown_section",
    "file_name 只能填写裸文件名",
    "draft/sandbox 是后端 Git 分支",
    "2200",
    "2500",
    "3200",
]

CONTINUATION_QUERY = f"""当前 book_id：{{{{#{START_NODE_ID}.book_id#}}}}
当前书名：{{{{#{START_NODE_ID}.book_name#}}}}
当前目标文件：{{{{#{START_NODE_ID}.active_file#}}}}
作者当前指令：{{{{#sys.query#}}}}

你是续写 Agent，当前执行的是章节正文生产任务。默认目标文件永远是 `chapter_draft.md`。

必须先读取并对齐：
- `chapter_outline.md`：本轮唯一章卡执行来源。
- `arc_outline.md`、`master_outline.md`、`brainstorm.md`：只作为留存单元、读者承诺和创意边界参考。
- `summary.md`：原文事实、最近剧情和可追溯的原文样本线索。
- `world_model.md`、`status_card.md`、`domain_rules.md`：世界硬约束、当前状态和领域规则。
- `style_constraints_for_continuation.md`、`style_guide.md`：style_files_imitation_reference，作为节奏、句式、禁忌和可复用文风提示，不是硬门禁。
- `get_archive_range` / `get_core_archive` 可读到的 latest_source_text：source_text_imitation_reference，只模仿叙述节奏、场景进入方式和信息释放方式，不照搬原文句子。
- `error_archive.md`：必须规避的已知错误。

CONTINUATION_PRODUCTION_LAYER_PROTOCOL:
- 这段协议只用于内部执行，不要在最终回复中引用、复述或暴露协议名。
- 你的职责是把 `chapter_outline.md` 中可执行的章卡压成正文，不负责改大纲、改世界模型、改状态卡、改文风文件、改 summary 或改错误档案。
- 本轮只允许写 `chapter_draft.md`。任何写入工具的 file_name 只能填写裸文件名 `chapter_draft.md`；`draft/sandbox` 是后端 Git 分支，不是路径，禁止写成 `draft/sandbox/chapter_draft.md`。
- 正文内容里不要写 SOURCE_FACT / AUTHOR_PROPOSAL / WORLD_MODEL_REQUIRED 标签；这些标签只用于判断大纲证据模式和最终阻塞说明。

CHAPTER_CARD_EXECUTION_PROTOCOL:
- 从 `chapter_outline.md` 选择作者请求的章卡；如果作者没有指定，选择下一组最靠前、尚未写入 `chapter_draft.md` 的 1-3 张可执行章卡。
- 一张可执行章卡至少应能提供：chapter_goal、entry_scene、conflict_or_obstacle、payoff、state_change、foreshadowing_action、ending_hook、constraint_refs、evidence_mode。字段名可为中文，但语义必须对应。
- SOURCE_FACT 可以作为已发生事实或硬背景使用；AUTHOR_PROPOSAL 可以作为下一步生产设计使用；WORLD_MODEL_REQUIRED 不能当成已生效正史，除非 `world_model.md` 或 `status_card.md` 已明确吸收并确认。
- 如果章卡缺失、只有空模板、或关键设定仍是 WORLD_MODEL_REQUIRED，停止写入并说明需要先修 outline/world/status，而不是硬写正文。
- 每章输出必须是完整 Markdown 章节块，推荐标题形态：`## 第X章 标题`。章节正文要包含场景推进、人物行动、对话/反应、冲突升级、当章兑现、状态变化和结尾钩子，不要只写摘要。

DRAFT_WRITE_PROTOCOL:
- 写入前必须用 `get_markdown_outline` 读取 `chapter_draft.md` 以取得 base_etag；新书没有实体文件时也要使用工具返回的虚拟草稿 etag。
- 初次写入时，用 `draft_append_markdown_section` 追加到根章节 `续写草稿` 下；已有章节需要扩写或修正时，用 `draft_replace_markdown_section` 替换对应章节块。
- 写入工具参数必须是一层扁平结构：book_id 或 book_name、file_name、section_path、content、base_etag、origin、message。origin 必须是 `explicit_user_write`。
- 工具调用失败、etag 冲突或目标章节路径不明确时，不要假装完成；先报告失败位置。

LENGTH_GATE_PROTOCOL:
- 每写入一章后立刻调用 `validate_chapter_lengths`，参数使用 book_id、file_name=`chapter_draft.md`、min_chars=2200、target_chars=2500、max_chars=3200。
- 篇幅统计以工具返回的 non_whitespace_chars 为准，不相信自我估算。
- 如果当前章低于 min_chars，必须只扩写当前章，用 `draft_replace_markdown_section` 原地补足，再次调用 `validate_chapter_lengths` 复验；通过后才能进入下一章。
- 不要三章全部写完后再统一补救。当前章未过长度门时，不能宣布本轮完成。

LENGTH_REPAIR_STYLE_PRIORITY_PROTOCOL:
- 当作者要求文风修订或参考建议导致当前章低于 min_chars 时，补足篇幅仍要保留最新 style_advisory_diagnostics 和 source_text_imitation_reference 的模仿意图。
- 补足篇幅前先参考 `style_gate.drafts[].repair_plan.priority_metrics`。如果 `exposition_density` 或 `suspense_density` 被标红，禁止用解释、世界规则分析、重复提问、预言或新悬念灌水。
- 优先用具体场面节拍补足：行动、观察、身体反应、空间压迫、战术选择、即时后果，以及会改变压力的对白。
- 每次补足篇幅后都要重新调用 `validate_chapter_lengths` 和 `generate_style_diagnostics`；篇幅不足仍是硬门，style_advisory 的 fail/warn 只报告为建议，不能单独阻塞下一章。

WRITE_LOOP_BUDGET_PROTOCOL:
- 写入工具可能在 `chapter_draft.md` 当前修复窗口内已有 six_recent_repair_like 个 `[AI_Update]` 类提交时返回 `AI_WRITE_LOOP_GUARD`。
- 任何写入工具返回 `AI_WRITE_LOOP_GUARD` 时，立即停止。不要在同一轮继续尝试更小修改、补字数、收尾微调、替换 section_path 或再次替换。
- 停止报告里说明当前章节、已知的最新长度门和 style_advisory 状态，以及仍然存在的写入循环硬原因。触发该守卫后不要继续写后续待写章卡。
- 该守卫表示盲目扩写或反复局部修补已经失败。下一步只能是有边界的修复计划、审查桥接，或滚动门允许的人类解锁，而不是继续写正文。

BRIDGE_DENSITY_REPAIR_PROTOCOL:
- 如果 `repair_plan.gate_profile.name` 是 `bridge_exposition_continuation`，且 `avg_para`、`dialogue_ratio`、`environment_density`、`exposition_density` 中至少两项标红，把这次可选修订视为 `four_density_failure`，而不是普通润色。
- 作者要求修订时，顺序必须稳定：先在物理决策转折处分拆或压缩长段落，再减少问答式对白轮次，再删除只提供气氛的空间、光线、声音提示，最后把抽象规则解释改成可观察后果。
- 在 `four_density_failure` 下，补足篇幅不能使用 `no_environment_padding`、`no_q_and_a_padding` 或规则解释式灌水；除非该节拍会直接改变战术状态，否则不要新增景物压迫、对白交换、准入规则复述、世界规则分析、标签或抽象逻辑。
- 允许的补足方式只限 `scene_bound_micro_beats`：身体反应、物件操作、必要空间移动、即时后果、沉默决断，或会改变压力的行动。每个新增节拍都要保持或降低对白、环境、解释密度。
- 每次作者要求的改写或补足篇幅后，都要重跑长度校验和文风诊断。若达到 `max_rounds` 后四项密度仍有标红，停止可选文风修订循环并报告剩余指标；这个报告本身不能作为调度锁。

PARAGRAPH_ENVIRONMENT_REPAIR_DELTA:
- 当剩余 style_advisory 标红为 `avg_para` 和 `environment_density`，或前一次修复补足了长度却让 `avg_para` 变差时，使用这个建议增量。
- `paragraph_count_must_increase`：写入前先读取当前章，按可见空行分段估算段落数。替换稿要在决策、反应、后果转折处增加段落断点，让段落数上升；除非当前章已经落入 `avg_para` 硬区间。
- `no_merge_back_into_bulk_paragraphs`：句子润色时不要把刚拆开的节拍重新合并成大段。若合并句子会重造大段，就保留段落断点，只顺滑局部句子。
- `environment_cue_budget`：只保留会改变选择、阻碍移动、暴露规则或制造即时战术压力的环境提示。重复传递同一信息的光线、声音、沉默、走廊、房间、影子、空气、压迫等气氛提示要删除。
- `environment_terms_must_decrease`：替换后章节里的重复环境提示簇应少于替换前。`environment_density` 失败时，不要用景物压迫来补字数。
- 若此增量下仍需补足篇幅，优先添加非环境微节拍：身体反应、物件操作、沉默决断、后果确认，或不引入新气氛词的角色站位。

STYLE_METRIC_DELTA_PROTOCOL:
- 当滚动层、审查包或作者提示提供 `style_metric_delta` 时，把它视为建议性修复证据；它不是调度锁，不是正文，也不授权编辑 `chapter_draft.md` 之外的任何文件。
- 作者要求改写前先读取 `style_metric_delta.proxy_repair_goals`。每个目标中的 `metric`、`direction`、`target_band`、`hard_band`、`current_value`、`proxy_targets`、`proxy_state`、`actions` 都是具体提示，不能用泛泛润色替代。
- `paragraph_count_must_increase`、`average_paragraph_chars_must_decrease`、`no_merge_split_beats` 是 style_advisory 提示：修订时分拆决策、反应、后果节拍，但不能把指标通过或失败当成改变剧情事实的许可。
- `environment_cue_clusters_must_decrease` 和 `delete_atmosphere_only_cues` 是 style_advisory 提示：删除重复的光线、声音、沉默、走廊、房间、影子、空气和压迫提示；除非该提示会改变选择、阻碍移动、暴露规则或制造即时战术压力。
- `protected_metrics` 和 `protected_metric_regressions` 是面向作者的护栏。若出现 `length_or_size_recovery_regressed_protected_metric`，把它视为避免同类灌水模式的警告；这些诊断不要求 style_gate 通过才能进入下一章，也不能自行锁住调度。
- 如果 `stop_conditions.block_blind_expansion` 为真，把它视为反对盲目扩写和灌水的警告。它可以停止可选文风修订循环，但在剧情、长度、世界观硬门都通过时，不能阻止继续下一章。

CHAPTER_CONTEXT_PACK_PROTOCOL:
- 当滚动层、审查包或作者提示提供 `chapter_context_pack` 或 `CHAPTER_CONTEXT_PACK_PROTOCOL` 时，先把它作为当前章执行简报，再选择或改写章节。
- 该包是派生证据，不是生成正文，不是隐藏正史，不是隐藏大纲，也不是人类批准。它永远不授权编辑 `chapter_draft.md` 之外的任何文件。
- 先对齐 `chapter_context_pack.chapter_number`、`targeting.next_action`、`targeting.blocked_next_action` 与 `chapter_card.number`。如果该包指向被阻塞的当前章，先修复当前章，再写待写章卡。
- 使用 `chapter_context_pack.chapter_card.fields` 和 `decision_chain` 保留谁想要什么、障碍、必需状态变化、兑现点和结尾钩子。不要用最近正文惯性或新编剧情路线替代它们。
- 把 `non_negotiable_facts` 和 `truth_source_refs` 当作来源引用证据。若包内出现 `WORLD_MODEL_REQUIRED` 且未被 `world_model.md` 或 `status_card.md` 确认，不要在正文里把它提升为 SOURCE_FACT。
- 如果包内有 `active_repair_goals.style_metric_delta`，按 `STYLE_METRIC_DELTA_PROTOCOL` 使用：proxy 目标、保护指标和停止条件都是当前修复的 style_advisory 证据，不是隐藏正史或调度锁。
- 尊重该包的 no-prose 边界。若 `pack_reads_chapter_draft_text=false`、`pack_contains_generated_prose=false`、`pack_is_hidden_canon=false` 或 `continuation_agent_remains_only_chapter_draft_writer=true`，不要把包当成可粘贴文本；它只能用于选择、约束和验证当前章节。

STYLE_ADVISORY_PROTOCOL:
- 每章通过长度门后，立刻调用 `generate_style_diagnostics`，参数使用 book_id、source_count=12、draft_file=`chapter_draft.md`、draft_chapters=当前章号。
- 工具返回的 `style_gate.status`、`style_gate.drafts[].red_flags`、`style_gate.drafts[].repair_plan` 是 style_advisory_diagnostics：author_revision_owner=human_author，locks_scheduler=false。
- style_advisory fail/warn 只说明“作者可怎样改得更像原文或更合口味”，并满足 style_gate_not_scheduler_lock；只要长度、章卡、世界、状态和因果链硬边界通过，就可以继续下一章。
- 生成新章节时，同时看 style_files_imitation_reference 和 latest_source_text：模仿原文的场景开合、信息释放、对白占比和段落呼吸；不要机械追指标，不要照搬原文句子。
- 最终回复要把文风结果称为 style_advisory，报告 red_flags 和可选打磨提示，不要把 style_advisory 说成硬阻塞。

AUTHOR_STYLE_REVISION_PROTOCOL:
- 只有当作者明确要求“润色/打磨/修一下这一章文风”时，才用 `style_gate.drafts[0].repair_plan` 或 `style_metric_delta` 原地替换当前章。
- 可选文风修改只能改语言质感、段落节拍、对白/动作/环境/解释比例和叙事呼吸；不得改剧情事件、胜负结果、人物动机、状态变化、章节事实、世界状态或因果链。
- 修订后必须重新调用 `validate_chapter_lengths`；如果低于 2200 字符，长度门仍是硬门，必须先补足当前章。
- 外部助手不得直接写/改正文；所有正文变化只能由本 continuation 工作流通过写入工具产生。

- 最终回复只报告：写入章节、`chapter_draft.md`、每章 non_whitespace_chars/status、style_advisory 状态与可选提示、仍阻塞的硬问题。不要输出工具参数、隐藏 JSON 或协议名。
"""

CONTINUATION_INSTRUCTION = """# Role: CONTINUATION_AGENT

你是当前作品的正文生产层，负责把 `chapter_outline.md` 的逐章生产卡写成可审阅的 `chapter_draft.md`。你不是大纲 Agent、不是世界模型 Agent、不是文风初始化 Agent，也不是审核 Agent。

CONTINUATION_PRODUCTION_LAYER_PROTOCOL:
1. 只写 `chapter_draft.md`。禁止写入 summary.md、world_model.md、status_card.md、domain_rules.md、style_guide.md、style_constraints_for_continuation.md、error_archive.md、brainstorm.md、master_outline.md、arc_outline.md、chapter_outline.md。
2. file_name 只能填写裸文件名 `chapter_draft.md`；draft/sandbox 是后端 Git 分支，不是路径。
3. 续写内容必须从章卡落地成正文场景：动作、感官、对话、人物选择、矛盾推进、当章兑现、状态变化、结尾钩子都要有。
4. 不得把工具报告、长度统计、SOURCE_FACT / AUTHOR_PROPOSAL / WORLD_MODEL_REQUIRED 标签写进正文。

上下文读取顺序：
- 先读 `chapter_outline.md`，确定本轮章卡和 section_path。
- 再读 `arc_outline.md`、`master_outline.md`、`brainstorm.md`，校准留存单元、读者承诺和创意边界。
- 再读 `summary.md`、`world_model.md`、`status_card.md`、`domain_rules.md`，校准原文事实、世界硬约束、当前状态、领域规则。
- 最后读 `style_constraints_for_continuation.md` 和 `style_guide.md`，它们是 style_files_imitation_reference，只校准节奏、句式、禁忌和可复用文风提示；必要时用 `get_archive_range` / `get_core_archive` 读取 latest_source_text 作为 source_text_imitation_reference；读 `error_archive.md` 规避历史错误。

CHAPTER_CARD_EXECUTION_PROTOCOL:
1. 作者指定章节时执行指定章卡；未指定时执行 `chapter_outline.md` 中最靠前且尚未出现在 `chapter_draft.md` 的 1-3 张章卡。
2. 章卡必须能支撑真实正文。如果只有空模板、只有主题口号、缺少 entry_scene / conflict_or_obstacle / payoff / state_change / ending_hook 的等价信息，则停止并要求先修大纲。
3. SOURCE_FACT 是源文本事实；AUTHOR_PROPOSAL 是可落地的生产方案；WORLD_MODEL_REQUIRED 是世界模型待确认事项。WORLD_MODEL_REQUIRED 不能直接写成已发生事实或硬设定。
4. 如果章卡中有 WORLD_MODEL_REQUIRED，而 world_model.md/status_card.md 没有确认它，正文只能绕开该点或停止；不能替作者偷偷转正。
5. 每章必须按章卡完成：开场入场、冲突受阻、当章兑现、状态变化、伏笔动作、尾钩。

DRAFT_WRITE_PROTOCOL:
1. 写入前读取 `chapter_draft.md` 的 markdown outline，拿到 base_etag。即使实体文件尚不存在，虚拟草稿也会提供 etag。
2. 初次写章节，用 `draft_append_markdown_section` 追加到 section_path=`续写草稿`；content 以 `## 第X章 标题` 开头。
3. 扩写或修正某章，用 `draft_replace_markdown_section` 替换该章 section_path。不要替换整份文件，除非草稿只有该章且路径明确。
4. 每次写入的 origin 必须为 `explicit_user_write`，message 简短说明本次续写章节。
5. 写入工具返回冲突、失败或路径不明确时，立即停下并报告，不要继续虚构后续状态。

LENGTH_GATE_PROTOCOL:
1. 每章写入成功后，必须调用 `validate_chapter_lengths` 校验 `chapter_draft.md`，固定参数：min_chars=2200、target_chars=2500、max_chars=3200。
2. 只信 validate_chapter_lengths 返回的 non_whitespace_chars、under_min、status 或等价字段。
3. 如果当前章 under_min 或低于 2200，必须只扩写当前章，使用 `draft_replace_markdown_section` 原地补足，再复验。
4. 当前章通过长度门之后，才可以写下一章。
5. 最终回复必须列出每章的标题、non_whitespace_chars、status；若有 under_min 或校验失败，不得宣称任务完成。

LENGTH_REPAIR_STYLE_PRIORITY_PROTOCOL:
1. 当作者要求文风修订或参考建议导致当前章低于 min_chars 时，补足篇幅仍要保留最新 style_advisory_diagnostics 和 source_text_imitation_reference 的模仿意图。
2. 补足篇幅前先参考 `style_gate.drafts[].repair_plan.priority_metrics`。如果 `exposition_density` 或 `suspense_density` 被标红，禁止用解释、世界规则分析、重复提问、预言或新悬念灌水。
3. 优先用具体场面节拍补足：行动、观察、身体反应、空间压迫、战术选择、即时后果，以及会改变压力的对白。
4. 每次补足篇幅后都要重新调用 `validate_chapter_lengths` 和 `generate_style_diagnostics`；篇幅不足仍是硬门，style_advisory 的 fail/warn 只报告为建议，不能单独阻塞下一章。

BRIDGE_DENSITY_REPAIR_PROTOCOL:
1. 如果 `repair_plan.gate_profile.name` 是 `bridge_exposition_continuation`，且 `avg_para`、`dialogue_ratio`、`environment_density`、`exposition_density` 中至少两项标红，把这次可选修订视为 `four_density_failure`，而不是普通润色。
2. 作者要求修订时，顺序必须稳定：先在物理决策转折处分拆或压缩长段落，再减少问答式对白轮次，再删除只提供气氛的空间、光线、声音提示，最后把抽象规则解释改成可观察后果。
3. 在 `four_density_failure` 下，补足篇幅不能使用 `no_environment_padding`、`no_q_and_a_padding` 或规则解释式灌水；除非该节拍会直接改变战术状态，否则不要新增景物压迫、对白交换、准入规则复述、世界规则分析、标签或抽象逻辑。
4. 允许的补足方式只限 `scene_bound_micro_beats`：身体反应、物件操作、必要空间移动、即时后果、沉默决断，或会改变压力的行动。每个新增节拍都要保持或降低对白、环境、解释密度。
5. 每次作者要求的改写或补足篇幅后，都要重跑长度校验和文风诊断。若达到 `max_rounds` 后四项密度仍有标红，停止可选文风修订循环并报告剩余指标；这个报告本身不能作为调度锁。

PARAGRAPH_ENVIRONMENT_REPAIR_DELTA:
1. 当剩余 style_advisory 标红为 `avg_para` 和 `environment_density`，或前一次修复补足了长度却让 `avg_para` 变差时，使用这个建议增量。
2. `paragraph_count_must_increase`：写入前先读取当前章，按可见空行分段估算段落数。替换稿要在决策、反应、后果转折处增加段落断点，让段落数上升；除非当前章已经落入 `avg_para` 硬区间。
3. `no_merge_back_into_bulk_paragraphs`：句子润色时不要把刚拆开的节拍重新合并成大段。若合并句子会重造大段，就保留段落断点，只顺滑局部句子。
4. `environment_cue_budget`：只保留会改变选择、阻碍移动、暴露规则或制造即时战术压力的环境提示。重复传递同一信息的光线、声音、沉默、走廊、房间、影子、空气、压迫等气氛提示要删除。
5. `environment_terms_must_decrease`：替换后章节里的重复环境提示簇应少于替换前。`environment_density` 失败时，不要用景物压迫来补字数。
6. 若此增量下仍需补足篇幅，优先添加非环境微节拍：身体反应、物件操作、沉默决断、后果确认，或不引入新气氛词的角色站位。

STYLE_METRIC_DELTA_PROTOCOL:
1. 当滚动层、审查包或作者提示提供 `style_metric_delta` 时，把它视为建议性修复证据；它不是调度锁，不是正文，也不授权编辑 `chapter_draft.md` 之外的任何文件。
2. 作者要求改写前先读取 `style_metric_delta.proxy_repair_goals`。每个目标中的 `metric`、`direction`、`target_band`、`hard_band`、`current_value`、`proxy_targets`、`proxy_state`、`actions` 都是具体提示，不能用泛泛润色替代。
3. `paragraph_count_must_increase`、`average_paragraph_chars_must_decrease`、`no_merge_split_beats` 是 style_advisory 提示：修订时分拆决策、反应、后果节拍，但不能把指标通过或失败当成改变剧情事实的许可。
4. `environment_cue_clusters_must_decrease` 和 `delete_atmosphere_only_cues` 是 style_advisory 提示：删除重复的光线、声音、沉默、走廊、房间、影子、空气和压迫提示；除非该提示会改变选择、阻碍移动、暴露规则或制造即时战术压力。
5. `protected_metrics` 和 `protected_metric_regressions` 是面向作者的护栏。若出现 `length_or_size_recovery_regressed_protected_metric`，把它视为避免同类灌水模式的警告；这些诊断不要求 style_gate 通过才能进入下一章，也不能自行锁住调度。
6. 如果 `stop_conditions.block_blind_expansion` 为真，把它视为反对盲目扩写和灌水的警告。它可以停止可选文风修订循环，但在剧情、长度、世界观硬门都通过时，不能阻止继续下一章。

CHAPTER_CONTEXT_PACK_PROTOCOL:
1. 当滚动层、审查包或作者提示提供 `chapter_context_pack` 或 `CHAPTER_CONTEXT_PACK_PROTOCOL` 时，先把它作为当前章执行简报，再选择或改写章节。
2. 该包是派生证据，不是生成正文，不是隐藏正史，不是隐藏大纲，也不是人类批准。它永远不授权编辑 `chapter_draft.md` 之外的任何文件。
3. 先对齐 `chapter_context_pack.chapter_number`、`targeting.next_action`、`targeting.blocked_next_action` 与 `chapter_card.number`。如果该包指向被阻塞的当前章，先修复当前章，再写待写章卡。
4. 使用 `chapter_context_pack.chapter_card.fields` 和 `decision_chain` 保留谁想要什么、障碍、必需状态变化、兑现点和结尾钩子。不要用最近正文惯性或新编剧情路线替代它们。
5. 把 `non_negotiable_facts` 和 `truth_source_refs` 当作来源引用证据。若包内出现 `WORLD_MODEL_REQUIRED` 且未被 `world_model.md` 或 `status_card.md` 确认，不要在正文里把它提升为 SOURCE_FACT。
6. 如果包内有 `active_repair_goals.style_metric_delta`，按 `STYLE_METRIC_DELTA_PROTOCOL` 使用：proxy 目标、保护指标和停止条件都是当前修复的 style_advisory 证据，不是隐藏正史或调度锁。
7. 尊重该包的 no-prose 边界。若 `pack_reads_chapter_draft_text=false`、`pack_contains_generated_prose=false`、`pack_is_hidden_canon=false` 或 `continuation_agent_remains_only_chapter_draft_writer=true`，不要把包当成可粘贴文本；它只能用于选择、约束和验证当前章节。

STYLE_ADVISORY_PROTOCOL:
1. 当前章通过长度门后，必须调用 `generate_style_diagnostics`，固定参数：source_count=12、draft_file=`chapter_draft.md`、draft_chapters=当前章号。
2. 工具返回的 `style_gate.status`、`style_gate.drafts[].red_flags`、`style_gate.drafts[].repair_plan` 是 style_advisory_diagnostics：author_revision_owner=human_author，locks_scheduler=false。
3. style_advisory fail/warn 只说明“作者可怎样改得更像原文或更合口味”，并满足 style_gate_not_scheduler_lock；只要长度、章卡、世界、状态和因果链硬边界通过，就可以继续下一章。
4. 生成新章节时，同时看 style_files_imitation_reference 和 latest_source_text：模仿原文的场景开合、信息释放、对白占比和段落呼吸；不要机械追指标，不要照搬原文句子。
5. 最终回复要把文风结果称为 style_advisory，报告 red_flags 和可选打磨提示，不要把 style_advisory 说成硬阻塞。

AUTHOR_STYLE_REVISION_PROTOCOL:
1. 只有当作者明确要求“润色/打磨/修一下这一章文风”时，才用 `style_gate.drafts[0].repair_plan` 或 `style_metric_delta` 原地替换当前章。
2. 可选文风修改只能改语言质感、段落节拍、对白/动作/环境/解释比例和叙事呼吸；不得改剧情事件、胜负结果、人物动机、状态变化、章节事实、世界状态或因果链。
3. 如果 `repair_plan.metric_couplings` 非空，开篇章节可把 `avg_para` 与 `avg_sentence` 作为一组 advisory 指标：先按 shared_goal 稳定段落节拍，再按 split_trigger / merge_trigger 处理局部拆分合并，最后复验。
4. 修订后必须重新调用 `validate_chapter_lengths`；如果低于 2200 字符，长度门仍是硬门，必须先补足当前章。
5. 外部助手不得直接写/改正文；所有正文变化必须由本 continuation 工作流调用写入工具产生。

输出纪律：
- 最终回复用作者能读懂的短报告，不要展示工具参数、SQL、隐藏 JSON、协议名或内部推理。
- 只说明更新了 `chapter_draft.md`，写了哪些章，长度门和 style_advisory 结果如何，以及是否存在需要 world/outline/status 先处理的硬阻塞。
"""


def run(args: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=ROOT,
        input=input_text,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
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
            f"COMMAND: {' '.join(str(a) for a in proc.args if a)}\n"
            f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return proc.stdout


def psql_at(sql: str) -> list[str]:
    out = psql(["-A", "-t", "-F", "\t", "-c", sql])
    return [line for line in out.splitlines() if line.strip()]


def dollar_quote(value: str) -> str:
    for tag in ("codex", "codex_continuation", "codex_continuation2"):
        marker = f"${tag}$"
        if marker not in value:
            return f"{marker}{value}{marker}"
    raise ValueError("Cannot build a safe dollar-quoted SQL string")


def sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def endpoint_ports(*texts: str) -> list[int]:
    return sorted({int(match.group(1)) for text in texts for match in ENDPOINT_RE.finditer(text)})


def load_openapi() -> dict[str, Any]:
    openapi = json.loads(OPENAPI_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(openapi, dict):
        raise RuntimeError("Local OpenAPI is not a JSON object")
    return openapi


def operation_from_openapi(openapi: dict[str, Any], operation_id: str) -> tuple[str, str, dict[str, Any]]:
    method, path = OPERATION_PATHS[operation_id]
    try:
        operation = openapi["paths"][path][method]
    except KeyError as exc:
        raise RuntimeError(f"Local OpenAPI missing {operation_id} at {method.upper()} {path}") from exc
    return method, path, deepcopy(operation)


def load_provider(provider_id: str) -> dict[str, Any]:
    rows = psql_at(
        f"""
        select
            encode(convert_to(schema, 'UTF8'), 'hex'),
            encode(convert_to(tools_str, 'UTF8'), 'hex'),
            name,
            schema_type_str
        from tool_api_providers
        where id = '{provider_id}'
        """
    )
    if len(rows) != 1:
        raise RuntimeError(f"Expected one ToolProvider row for {provider_id}, found {len(rows)}")
    schema_hex, tools_hex, name, schema_type = rows[0].split("\t", 3)
    schema_text = bytes.fromhex(schema_hex).decode("utf-8-sig")
    tools_text = bytes.fromhex(tools_hex).decode("utf-8-sig")
    schema = json.loads(schema_text)
    tools = json.loads(tools_text)
    if not isinstance(schema, dict):
        raise RuntimeError("ToolProvider schema is not a JSON object")
    if not isinstance(tools, list):
        raise RuntimeError("ToolProvider tools_str is not a JSON array")
    return {
        "id": provider_id,
        "name": name,
        "schema_type_str": schema_type,
        "schema_text": schema_text,
        "tools_text": tools_text,
        "schema": schema,
        "tools": tools,
    }


def server_base(schema: dict[str, Any], tools: list[Any]) -> str:
    servers = schema.get("servers")
    if isinstance(servers, list):
        for server in servers:
            if isinstance(server, dict) and isinstance(server.get("url"), str) and server["url"].strip():
                return server["url"].rstrip("/")
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        raw = tool.get("server_url")
        if isinstance(raw, str) and "/" in raw:
            return raw.rsplit("/", 1)[0].rstrip("/")
    return "http://host.docker.internal:8000"


def request_schema(operation: dict[str, Any]) -> tuple[dict[str, Any], set[str]]:
    body = operation.get("requestBody")
    if not isinstance(body, dict):
        return {}, set()
    content = body.get("content")
    if not isinstance(content, dict):
        return {}, set()
    app_json = content.get("application/json")
    if not isinstance(app_json, dict):
        return {}, set()
    schema = app_json.get("schema")
    if not isinstance(schema, dict):
        return {}, set()
    props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    required = schema.get("required")
    return props, set(required if isinstance(required, list) else [])


def dify_type(openapi_type: Any) -> str:
    if openapi_type in {"integer", "number"}:
        return "number"
    if openapi_type == "array":
        return "array"
    if openapi_type == "boolean":
        return "boolean"
    return "string"


def parameter_entry(name: str, schema: dict[str, Any], *, required: bool) -> dict[str, Any]:
    description = schema.get("description") if isinstance(schema.get("description"), str) else ""
    return {
        "name": name,
        "label": {"en_US": name, "zh_Hans": name, "pt_BR": name, "ja_JP": name},
        "placeholder": {"en_US": description, "zh_Hans": description, "pt_BR": description, "ja_JP": description},
        "scope": None,
        "auto_generate": None,
        "template": None,
        "required": required,
        "default": schema.get("default") if "default" in schema else None,
        "min": schema.get("minimum"),
        "max": schema.get("maximum"),
        "precision": None,
        "options": [],
        "type": dify_type(schema.get("type")),
        "human_description": {"en_US": description, "zh_Hans": description, "pt_BR": description, "ja_JP": description},
        "form": "llm",
        "llm_description": description,
        "input_schema": None,
    }


def build_tool_entry(operation_id: str, openapi: dict[str, Any], base_url: str) -> dict[str, Any]:
    method, path, operation = operation_from_openapi(openapi, operation_id)
    description = TOOL_DESCRIPTION_OVERRIDES.get(operation_id) or operation.get("description") or operation.get("summary") or operation_id
    operation["summary"] = description
    operation["description"] = description
    parameters: list[dict[str, Any]] = []
    props, required = request_schema(operation)
    for name, schema in props.items():
        if isinstance(schema, dict):
            parameters.append(parameter_entry(name, schema, required=name in required))
    return {
        "server_url": f"{base_url}{path}",
        "method": method,
        "summary": description,
        "operation_id": operation_id,
        "parameters": parameters,
        "author": "",
        "icon": None,
        "openapi": operation,
        "output_schema": {},
    }


def tool_operation_ids(tools: list[Any]) -> list[str | None]:
    return [tool.get("operation_id") if isinstance(tool, dict) else None for tool in tools]


def without_required_provider_operations(operation_ids: list[str | None]) -> list[str | None]:
    required = set(REQUIRED_PROVIDER_OPERATIONS)
    return [operation_id for operation_id in operation_ids if operation_id not in required]


def schema_operation_ids(schema: dict[str, Any]) -> list[str | None]:
    operation_ids: list[str | None] = []
    paths = schema.get("paths")
    if not isinstance(paths, dict):
        return operation_ids
    for path in sorted(paths):
        path_item = paths[path]
        if not isinstance(path_item, dict):
            continue
        for method in sorted(path_item):
            operation = path_item[method]
            if isinstance(operation, dict):
                operation_ids.append(operation.get("operationId") or operation.get("operation_id"))
    return operation_ids


def patch_provider(provider: dict[str, Any], openapi: dict[str, Any]) -> bool:
    changed = False
    schema = provider["schema"]
    tools = provider["tools"]
    base_url = server_base(schema, tools)
    before_tool_ops = tool_operation_ids(tools)

    paths = schema.setdefault("paths", {})
    if not isinstance(paths, dict):
        raise RuntimeError("ToolProvider schema.paths is not an object")

    for operation_id in REQUIRED_PROVIDER_OPERATIONS:
        method, path, operation = operation_from_openapi(openapi, operation_id)
        description = TOOL_DESCRIPTION_OVERRIDES.get(operation_id)
        if description:
            operation["summary"] = description
            operation["description"] = description
        path_item = paths.setdefault(path, {})
        if not isinstance(path_item, dict):
            raise RuntimeError(f"ToolProvider schema path is not an object: {path}")
        if path_item.get(method) != operation:
            path_item[method] = operation
            changed = True

        desired_tool = build_tool_entry(operation_id, openapi, base_url)
        tool_index = next(
            (index for index, tool in enumerate(tools) if isinstance(tool, dict) and tool.get("operation_id") == operation_id),
            None,
        )
        if tool_index is None:
            tools.append(desired_tool)
            changed = True
        elif tools[tool_index] != desired_tool:
            tools[tool_index] = desired_tool
            changed = True

    after_tool_ops = tool_operation_ids(tools)
    if without_required_provider_operations(before_tool_ops) != without_required_provider_operations(after_tool_ops):
        raise RuntimeError("Existing ToolProvider operation order changed")
    for operation_id in REQUIRED_PROVIDER_OPERATIONS:
        if after_tool_ops.count(operation_id) != 1:
            raise RuntimeError(f"Expected exactly one {operation_id} operation")
    return changed


def validate_provider(provider: dict[str, Any], *, before: dict[str, Any] | None = None) -> dict[str, Any]:
    schema_text = json.dumps(provider["schema"], ensure_ascii=False, separators=(",", ":"))
    tools_text = json.dumps(provider["tools"], ensure_ascii=False, separators=(",", ":"))
    tool_ops = tool_operation_ids(provider["tools"])
    schema_ops = schema_operation_ids(provider["schema"])
    for operation_id in REQUIRED_PROVIDER_OPERATIONS:
        if operation_id not in tool_ops:
            raise RuntimeError(f"ToolProvider tools_str missing {operation_id}")
        if operation_id not in schema_ops:
            raise RuntimeError(f"ToolProvider schema missing {operation_id}")
    if before is not None:
        before_tool_ops = tool_operation_ids(before["tools"])
        if without_required_provider_operations(before_tool_ops) != without_required_provider_operations(tool_ops):
            raise RuntimeError("Existing ToolProvider operation order changed after patch")
        for operation_id in REQUIRED_PROVIDER_OPERATIONS:
            if tool_ops.count(operation_id) != 1:
                raise RuntimeError(f"Expected exactly one {operation_id} operation after patch")
        if endpoint_ports(before["schema_text"], before["tools_text"]) != endpoint_ports(schema_text, tools_text):
            raise RuntimeError("ToolProvider endpoint ports changed during operation patch")
    return {
        "tool_count": len(provider["tools"]),
        "tool_operation_ids": tool_ops,
        "schema_operation_ids": schema_ops,
        "endpoint_ports": endpoint_ports(schema_text, tools_text),
        "schema_sha": sha_text(schema_text),
        "tools_sha": sha_text(tools_text),
    }


def load_continuation_workflows() -> tuple[str, list[dict[str, Any]]]:
    app_rows = psql_at(
        f"""
        select id::text, workflow_id::text, name, mode
        from apps
        where id = '{APP_ID}'
        """
    )
    if len(app_rows) != 1:
        raise RuntimeError(f"Expected one continuation app row, found {len(app_rows)}")
    app_id, live_workflow_id, app_name, app_mode = app_rows[0].split("\t")
    if app_id != APP_ID or live_workflow_id != EXPECTED_LIVE_WORKFLOW_ID:
        raise RuntimeError(f"Unexpected continuation app identity: app={app_id}, live_workflow={live_workflow_id}")
    if app_mode != "advanced-chat":
        raise RuntimeError(f"Unexpected continuation app mode for {app_name}: {app_mode}")

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
        raise RuntimeError(f"Expected at least live and draft continuation workflows, found {len(rows)}")

    workflows: list[dict[str, Any]] = []
    for row in rows:
        workflow_id, version, graph_hex = row.split("\t", 2)
        graph_text = bytes.fromhex(graph_hex).decode("utf-8-sig")
        workflows.append({"id": workflow_id, "version": version, "graph_text": graph_text, "graph": json.loads(graph_text)})
    if workflows[0]["id"] != EXPECTED_LIVE_WORKFLOW_ID or workflows[0]["version"] != "live":
        raise RuntimeError("The first continuation workflow row is not the expected live workflow")
    if not any(item["version"] == "draft" for item in workflows):
        raise RuntimeError("Continuation workflow rows do not include a draft workflow")
    return live_workflow_id, workflows


def start_node(graph: dict[str, Any]) -> dict[str, Any]:
    starts = [node for node in graph.get("nodes", []) if (node.get("data") or {}).get("type") == "start"]
    if len(starts) != 1:
        raise RuntimeError(f"Expected one start node, found {len(starts)}")
    node = starts[0]
    if node.get("id") != START_NODE_ID:
        raise RuntimeError(f"Unexpected start node id: {node.get('id')}")
    return node


def continuation_agent_node(graph: dict[str, Any]) -> dict[str, Any]:
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise RuntimeError("Workflow graph is missing nodes or edges arrays")
    if len(nodes) != EXPECTED_NODE_COUNT or len(edges) != EXPECTED_EDGE_COUNT:
        raise RuntimeError(f"Unexpected continuation topology: nodes={len(nodes)}, edges={len(edges)}")
    agents = [node for node in nodes if (node.get("data") or {}).get("type") == "agent"]
    if len(agents) != 1:
        raise RuntimeError(f"Expected one continuation agent node, found {len(agents)}")
    title = (agents[0].get("data") or {}).get("title")
    if title != AGENT_TITLE:
        raise RuntimeError(f"Unexpected continuation agent title: {title}")
    return agents[0]


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


def ensure_start_variables(
    graph: dict[str, Any],
    *,
    add_book_id: bool = True,
    enforce_active_file: bool = True,
) -> bool:
    node = start_node(graph)
    variables = node.setdefault("data", {}).setdefault("variables", [])
    if not isinstance(variables, list):
        raise RuntimeError("Start node variables are not a list")

    changed = False
    if add_book_id and not any(isinstance(item, dict) and item.get("variable") == "book_id" for item in variables):
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
        changed = True

    for item in variables:
        if not isinstance(item, dict):
            continue
        if item.get("variable") == "book_name":
            if item.get("hint") != "当前书名或项目名。由前端桥接传入；Dify 手测时按当前书库填写。":
                item["hint"] = "当前书名或项目名。由前端桥接传入；Dify 手测时按当前书库填写。"
                changed = True
            if item.get("placeholder") != "填写当前书名或项目名":
                item["placeholder"] = "填写当前书名或项目名"
                changed = True
        if item.get("variable") == "book_id":
            if item.get("hint") != "当前书库标识。由前端桥接传入；Dify 手测时按当前书库填写。":
                item["hint"] = "当前书库标识。由前端桥接传入；Dify 手测时按当前书库填写。"
                changed = True
            if item.get("placeholder") != "填写当前书库标识":
                item["placeholder"] = "填写当前书库标识"
                changed = True
        if item.get("variable") == "active_file":
            if enforce_active_file and item.get("default") != "chapter_draft.md":
                item["default"] = "chapter_draft.md"
                changed = True
            if enforce_active_file and item.get("required") is not True:
                item["required"] = True
                changed = True
            if item.get("hint") != "当前目标文件。续写链路固定为 chapter_draft.md。":
                item["hint"] = "当前目标文件。续写链路固定为 chapter_draft.md。"
                changed = True
            if item.get("placeholder") != "chapter_draft.md":
                item["placeholder"] = "chapter_draft.md"
                changed = True
    return changed


def agent_tool_entries(node: dict[str, Any]) -> list[dict[str, Any]]:
    value = node.get("data", {}).get("agent_parameters", {}).get("tools", {}).get("value", [])
    if not isinstance(value, list):
        raise RuntimeError("Continuation agent tools value is not a list")
    entries: list[dict[str, Any]] = []
    for tool in value:
        if not isinstance(tool, dict):
            raise RuntimeError("Continuation agent tool entry is not a dict")
        entries.append(tool)
    return entries


def agent_tool_names(node: dict[str, Any]) -> list[str]:
    return [tool.get("tool_name") for tool in agent_tool_entries(node)]


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


def set_agent_prompt(node: dict[str, Any]) -> bool:
    changed = False
    params = node.setdefault("data", {}).setdefault("agent_parameters", {})
    if params.setdefault("query", {"type": "constant"}).get("value") != CONTINUATION_QUERY:
        params["query"] = {"type": "constant", "value": CONTINUATION_QUERY}
        changed = True
    if params.setdefault("instruction", {"type": "constant"}).get("value") != CONTINUATION_INSTRUCTION:
        params["instruction"] = {"type": "constant", "value": CONTINUATION_INSTRUCTION}
        changed = True
    return changed


def set_agent_tools(node: dict[str, Any], provider_tools: list[dict[str, Any]]) -> bool:
    params = node.setdefault("data", {}).setdefault("agent_parameters", {})
    current_entries = agent_tool_entries(node)
    existing_by_name = {tool.get("tool_name"): tool for tool in current_entries}
    desired_entries = [
        workflow_tool_entry(tool_name, provider_tools, existing_by_name.get(tool_name))
        for tool_name in CONTINUATION_TOOLS
    ]
    if current_entries == desired_entries:
        return False
    params.setdefault("tools", {"type": "constant"})["type"] = "constant"
    params["tools"]["value"] = desired_entries
    return True


def set_existing_agent_tool_descriptions(node: dict[str, Any]) -> bool:
    changed = False
    for entry in agent_tool_entries(node):
        tool_name = entry.get("tool_name")
        if not isinstance(tool_name, str):
            continue
        description = TOOL_DESCRIPTION_OVERRIDES.get(tool_name)
        if description is None:
            continue
        if entry.get("provider_show_name") != "LoreGit 后端工具集":
            entry["provider_show_name"] = "LoreGit 后端工具集"
            changed = True
        if entry.get("tool_description") != description:
            entry["tool_description"] = description
            changed = True
        extra = entry.setdefault("extra", {})
        if isinstance(extra, dict) and extra.get("description") != description:
            extra["description"] = description
            changed = True
    return changed


def set_max_iterations(node: dict[str, Any], value: int = 45) -> bool:
    params = node.setdefault("data", {}).setdefault("agent_parameters", {})
    if params.get("maximum_iterations", {}).get("value") == value:
        return False
    params["maximum_iterations"] = {"type": "constant", "value": value}
    return True


def validate_workflow(
    graph: dict[str, Any],
    *,
    label: str,
    enforce_after_contract: bool = False,
) -> dict[str, Any]:
    agent = continuation_agent_node(graph)
    params = agent.get("data", {}).get("agent_parameters", {})
    model = (params.get("model") or {}).get("value") or {}
    if model.get("provider") != EXPECTED_MODEL_PROVIDER or model.get("model") != EXPECTED_MODEL:
        raise RuntimeError(f"{label} continuation model changed unexpectedly: {model}")
    instruction = (params.get("instruction") or {}).get("value")
    query = (params.get("query") or {}).get("value")
    if not isinstance(instruction, str) or not isinstance(query, str):
        raise RuntimeError(f"{label} continuation prompt fields are not strings")
    tools = agent_tool_names(agent)
    snapshot = {
        "nodes": len(graph.get("nodes", [])),
        "edges": len(graph.get("edges", [])),
        "start_variables": start_variable_names(graph),
        "model_provider": model.get("provider"),
        "model": model.get("model"),
        "completion_params": model.get("completion_params"),
        "maximum_iterations": params.get("maximum_iterations", {}).get("value"),
        "tools": tools,
        "instruction_sha": sha_text(instruction),
        "instruction_len": len(instruction),
        "query_sha": sha_text(query),
        "query_len": len(query),
    }
    if enforce_after_contract:
        if "book_id" not in snapshot["start_variables"]:
            raise RuntimeError(f"{label} start node is missing book_id variable")
        if tools != CONTINUATION_TOOLS:
            raise RuntimeError(f"{label} continuation tools mismatch: {tools}")
        if snapshot["maximum_iterations"] != 45:
            raise RuntimeError(f"{label} continuation maximum_iterations is not 45")
        combined = f"{instruction}\n{query}"
        for marker in PROMPT_MARKERS:
            if marker not in combined:
                raise RuntimeError(f"{label} continuation prompt missing marker: {marker}")
    return snapshot


def patch_workflow(graph: dict[str, Any], provider_tools: list[dict[str, Any]], *, full_runtime_patch: bool) -> bool:
    changed = False
    if ensure_start_variables(graph, add_book_id=full_runtime_patch, enforce_active_file=full_runtime_patch):
        changed = True
    agent = continuation_agent_node(graph)
    if full_runtime_patch:
        changed = set_agent_prompt(agent) or changed
        changed = set_agent_tools(agent, provider_tools) or changed
        changed = set_max_iterations(agent, 45) or changed
    else:
        changed = set_existing_agent_tool_descriptions(agent) or changed
    return changed


def backup(provider: dict[str, Any], workflows: list[dict[str, Any]], stamp: str) -> Path:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    out = RUNTIME / f"continuation_agent_provider_workflow_backup_{stamp}.json"
    payload = {
        "tool_provider": {
            "id": provider["id"],
            "name": provider["name"],
            "schema_type_str": provider["schema_type_str"],
            "schema_sha": sha_text(provider["schema_text"]),
            "tools_sha": sha_text(provider["tools_text"]),
            "endpoint_ports": endpoint_ports(provider["schema_text"], provider["tools_text"]),
            "schema": provider["schema"],
            "tools": provider["tools"],
        },
        "workflows": [
            {
                "id": item["id"],
                "version": item["version"],
                "graph_sha": sha_text(item["graph_text"]),
                "graph": item["graph"],
            }
            for item in workflows
        ],
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def update_provider(provider: dict[str, Any]) -> None:
    schema_text = json.dumps(provider["schema"], ensure_ascii=False, separators=(",", ":"))
    tools_text = json.dumps(provider["tools"], ensure_ascii=False, separators=(",", ":"))
    sql = (
        "begin;\n"
        "update tool_api_providers set "
        f"schema = {dollar_quote(schema_text)}, "
        f"tools_str = {dollar_quote(tools_text)}, "
        "updated_at = now() "
        f"where id = '{provider['id']}';\n"
        "commit;\n"
    )
    psql([], input_text=sql)


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


def write_marker(stamp: str, payload: dict[str, Any]) -> Path:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    out = RUNTIME / f"continuation_agent_provider_workflow_marker_{stamp}.txt"
    lines = [
        f"provider_id={payload['provider_id']}",
        f"app_id={payload['app_id']}",
        f"live_workflow_id={payload['live_workflow_id']}",
        f"dry_run={payload['dry_run']}",
        f"changed={payload['changed']}",
        f"provider_changed={payload['provider_changed']}",
        f"workflow_changed={payload['workflow_changed']}",
        f"tool_count_before={payload['before_provider']['tool_count']}",
        f"tool_count_after={payload['after_provider']['tool_count']}",
        f"has_validate_chapter_lengths={VALIDATE_CHAPTER_LENGTHS in payload['after_provider']['tool_operation_ids']}",
        f"has_generate_style_diagnostics={GENERATE_STYLE_DIAGNOSTICS in payload['after_provider']['tool_operation_ids']}",
        f"endpoint_ports_before={','.join(str(port) for port in payload['before_provider']['endpoint_ports'])}",
        f"endpoint_ports_after={','.join(str(port) for port in payload['after_provider']['endpoint_ports'])}",
        f"live_workflow_tools={','.join(str(tool) for tool in payload['after_workflows'][payload['live_workflow_id']]['tools'])}",
        f"live_start_variables={','.join(payload['after_workflows'][payload['live_workflow_id']]['start_variables'])}",
        f"live_maximum_iterations={payload['after_workflows'][payload['live_workflow_id']]['maximum_iterations']}",
        f"backup={payload['backup']}",
    ]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="validate and preview without DB writes")
    parser.add_argument("--provider-id", default=TOOL_PROVIDER_ID)
    args = parser.parse_args()

    openapi = load_openapi()
    provider = load_provider(args.provider_id)
    live_workflow_id, workflows = load_continuation_workflows()
    before_snapshot = deepcopy(provider)
    workflow_snapshots = deepcopy(workflows)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup(before_snapshot, workflow_snapshots, stamp)

    before_provider = {
        "tool_count": len(before_snapshot["tools"]),
        "tool_operation_ids": tool_operation_ids(before_snapshot["tools"]),
        "schema_operation_ids": schema_operation_ids(before_snapshot["schema"]),
        "endpoint_ports": endpoint_ports(before_snapshot["schema_text"], before_snapshot["tools_text"]),
        "schema_sha": sha_text(before_snapshot["schema_text"]),
        "tools_sha": sha_text(before_snapshot["tools_text"]),
    }
    before_workflows: dict[str, Any] = {}
    after_workflows: dict[str, Any] = {}

    provider_changed = patch_provider(provider, openapi)
    after_provider = validate_provider(provider, before=before_snapshot)

    workflow_changed = False
    for item in workflows:
        before_workflows[item["id"]] = validate_workflow(item["graph"], label=f"before:{item['version']}")
        full_runtime_patch = item["version"] in {"live", "draft"}
        workflow_changed = patch_workflow(item["graph"], provider["tools"], full_runtime_patch=full_runtime_patch) or workflow_changed
        after_workflows[item["id"]] = validate_workflow(
            item["graph"],
            label=f"after:{item['version']}",
            enforce_after_contract=full_runtime_patch,
        )

    changed = provider_changed or workflow_changed
    if changed and not args.dry_run:
        if provider_changed:
            update_provider(provider)
        if workflow_changed:
            update_workflows(workflows)

    payload = {
        "provider_id": args.provider_id,
        "app_id": APP_ID,
        "live_workflow_id": live_workflow_id,
        "backup": str(backup_path.relative_to(ROOT)),
        "dry_run": args.dry_run,
        "changed": changed,
        "provider_changed": provider_changed,
        "workflow_changed": workflow_changed,
        "workflow_ids": [{"id": item["id"], "version": item["version"]} for item in workflows],
        "before_provider": before_provider,
        "after_provider": after_provider,
        "before_workflows": before_workflows,
        "after_workflows": after_workflows,
    }
    marker_path = write_marker(stamp, payload)
    payload["marker"] = str(marker_path.relative_to(ROOT))
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
