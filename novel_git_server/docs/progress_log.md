# 工作进度日志

## 2026-03-09 Markdown Section Indexing (a1-a9)

### 完成的工作
1. Markdown 标题树工具层
- 新增 `novel_git_server/utils/markdown_sections.py`。
- 支持 ATX 标题解析、YAML frontmatter 跳过、fenced code block 忽略。
- 输出 canonical `section_path`，用于重复同级标题去歧义，如 `Rule [2]`。
- 新增 `replace_section` / `append_under_section` / `replay_patch` 工具函数，为 Dify 代码节点后续做局部补丁缝合提供稳定语义。

2. 只读 API 层
- 新增 `GET /books/get_markdown_outline`。
- 新增 `GET /books/get_markdown_section`。
- 两个接口都复用现有 path safety、virtual core file、repo integrity 机制。
- `get_markdown_section` 对空区块显式返回 `content_length: 0`，并对重复 raw path 返回 `409 SECTION_PATH_AMBIGUOUS`。

3. 盲点护栏已编码
- `append_under_section` 按父标题的最后一个后代末尾插入，避免把已有子节点错误吸附到新标题下。
- Frontmatter 会被物理跳过，避免顶端 YAML 干扰标题定位。
- 空标题区块与“读取失败”分离：读取成功但正文为空时，返回 success + `content_length: 0`。
- 并发失败的补丁重放语义已在工具层固定：发生 428 时应重拉最新全文并对最新文本重放同一 patch。

### 测试与验证
- `./novel_git_server/venv/bin/python -m unittest novel_git_server/tests/test_v57_markdown_sections.py novel_git_server/tests/test_v58_markdown_outline_api.py`
- `./novel_git_server/venv/bin/python -m py_compile novel_git_server/agents/archive.py novel_git_server/utils/markdown_sections.py`
- 结果：10/10 通过，编译通过。

### 已知遗留
- `novel_git_server/tests/test_v31_archive.py` 仍然依赖旧时代的隐式 bootstrap 读路径假设；在 repo integrity 改造后会出现 404/428 语义漂移。本轮未修改这套旧测试，避免把“标题树索引”任务和“旧测试对齐”混成一次大改。

### Git 提交记录（本轮）
- `8ca292a` docs: add markdown section indexing checklist
- `afd9fba` feat(backend): add markdown section parsing utilities
- `bdc64ea` feat(api): add markdown outline and section endpoints

### 关键决策
- 不修改后端 `sync_all` 契约，仍然只接受全量 `update|append|prepend`。
- 标题级 patch 的解释与缝合执行权继续放在 Dify Python 节点，不回流到 Flask 写接口。
- 本地仓库不改 `dify_workflows/世界模型agent.yml`；实际工作流节点调整仍需在 Dify UI 中完成。

## 2026-03-09 Dify Incremental Workflow Guide

### 完成的工作
1. 整理了一份面向 live Dify 工作流画布的节点级操作手册：
- 新增 `novel_git_server/docs/dify_markdown_incremental_workflow_guide.md`
- 明确 `INIT_AGENT` 保持整文件初始化，不进入标题树 patch
- 明确 `READ_AGENT` / `ONLINE_AGENT` 的节点职责、工具集、提示词方向、structured output 结构以及 Python code node 执行契约

2. 文档中收口了以下关键口径：
- `world_model.md` 走 `get_markdown_outline -> get_markdown_section -> patch -> stitch -> sync_all`
- `status_card.md` 暂时保持 `full_replace`
- Dify 代码节点必须处理 `428` 后重拉全文并重放 patch 一次
- 回复节点继续显示 Agent 自然语言过程，不显示结构化 patch

### 关键决策
- 将此前对话中分散的说明、节点改法与提示词模板收束为单一 Markdown 文档，方便直接对照 Dify UI 操作。

## 2026-03-09 Dify Copyable Nodes Pack

### 完成的工作
1. 新增 `novel_git_server/docs/dify_incremental_copyable_nodes.md`
- 面向 Dify live 画布，提供可直接复制的节点内容
- 包含 `READ_AGENT` / `ONLINE_AGENT` 系统提示词
- 包含 READ/ONLINE 共用的 extraction `LLM` 提示词与 schema
- 包含 READ/ONLINE 共用的 `后端文件创立` Python code node 完整模板
- 包含输入映射、输出变量约定、回复节点保留策略与最小验收清单

### 关键决策
- 把“节点改法”进一步压缩成可复制的配置块，减少在 Dify UI 手工摘录时的错漏成本。

## 2026-02-14 会话 1

### 完成的工作
1. **Phase 0.2：Frontmatter 解析器**
   - 引入 `re` 和 `yaml` 模块
   - 实现 `parse_frontmatter()` 函数，支持 YAML 头部提取
   - 正则表达式模式：`^---\s*\n(.*?)\n---\s*\n(.*)$`

2. **Phase 0.3：改造 /commit 接口**
   - 移除 JSON 接收逻辑
   - 使用 `request.get_data(as_text=True)` 接收纯文本
   - 从 Frontmatter 提取 `message`, `parent_id` 等元数据
   - 实现双存储策略：
     - `raw_payload`: 完整原文（含 Frontmatter）
     - `markdown_payload`: 剥离后的纯净正文

3. **依赖管理**
   - 更新 `requirements.txt` 添加 `pyyaml>=6.0`
   - 成功安装 `pyyaml-6.0.3`

4. **测试框架搭建**
   - 设计三层测试架构（参考 Anthropic 最佳实践）
   - 创建 `test_harness.py` 自动化测试脚本（5个测试用例）
   - 创建 `feature_checklist.json` 功能完成清单
   - 创建 `dify_test_guide.md` Dify 集成测试指南

### 关键决策
- **协议完全替换**：不再支持 JSON，统一使用 `text/plain`
- **KISS 原则**：使用正则 + yaml 而非第三方库 `python-frontmatter`
- **MVP 策略**：忽略并发锁和过早优化

### 遗留问题
- [ ] 需要重启服务器以应用新代码
- [ ] 需要运行 `test_harness.py` 验证功能
- [ ] 需要用户手动进行 Dify 集成测试

### 下一步计划
1. 用户重启 `git_server.py`
2. 运行自动化测试脚本
3. 根据测试结果修复问题（如有）
4. 更新 `feature_checklist.json` 标记完成项
5. 用户按照 `dify_test_guide.md` 进行 Dify 集成测试

---

## 会话记录模板（供后续使用）

### 2026-XX-XX 会话 N

#### 完成的工作
- 

#### 关键决策
- 

#### 遗留问题
- 

#### 下一步计划
- 

## 2026-02-14 会话 2（Phase 1 专项）

### 目标范围确认
- 按用户要求仅执行 Phase 1，不改动已跑通的 Phase 0 协议链路。
- 保持 Dify -> Flask 的 POST /save_outline + Content-Type: text/plain 兼容。

### 已完成改造（代码）
1. git_server.py：实现 Phase 1 全量能力
- GET /checkout 新增 ?view= 参数分发，支持 world_model / writer / 
eviewer。
- 非法 iew 参数返回 400，无 iew 保持完整快照回传（兼容旧行为）。
- 新增 prune_snapshot() 与章节分段提取逻辑，按视图裁剪上下文。
- 新增 GET /history，仅返回 commit_id/parent_id/message/timestamp，按时间倒序。
- POST /commit 保持“全量快照存储 + parent 链”语义。
- 保持 POST /save_outline text/plain 协议，不破坏现有 Dify 节点配置。

2. 快照模板标准化
- 新增 data/snapshot_template.md。
- 空库 GET /checkout 时回传该模板，确保包含：
  - ## 核心状态档案
  - ## 待回收伏笔
  - ## 章节梗概
  - ## 动态文风指南
  - ## 错误档案
  - ## 最新正文

3. 自动化测试（Phase 1）
- 新增 	ests/test_phase1.py，覆盖 1.1 ~ 1.8：
  - 1.1 全量快照与回滚
  - 1.2 视图层路由/非法 view
  - 1.3 world_model 裁剪
  - 1.4 writer 裁剪（最近两章）
  - 1.5 reviewer 裁剪
  - 1.6 history 输出规范
  - 1.7 默认模板完整性
  - 1.8 端到端闭环（save_outline -> commit0 -> 演化 commit1 -> rollback/view/history）
- 测试结果：8/8 通过（本地运行时间：2026-02-14 12:54:56）。

### 风险处理与兼容性说明
- 之前删除 git_server.py 的动作是为整文件重构准备，不涉及 data/outlines 与数据库内容。
- 当前实现已恢复并增强接口，/save_outline 链路可继续按原 Dify 配置工作。

### Git 记录
- 已初始化本地 Git 仓库。
- 已提交一次代码快照（后端+测试+模板），后续继续按“每次完成一组修改即 commit”执行。

## 2026-02-14 会话 3（Phase 1 收口：World Agent）

### 领取任务（feature_checklist）
- 任务来源：phase_1.1 ~ 1.8，本轮聚焦 1.2/1.3/1.8 的 PRD 哲学对齐。
- 目标：遵循“Dify=前额叶，Flask=海马体，Markdown=神经信号”，后端只做存取和分发，不对 World Model 强制固定结构。

### 本轮代码改动
1. 新增 world_agent.py
- 新增独立世界模型文档机制：data/world_model.md。
- 新增 GET /world_model 与 POST /world_model：World Model Agent 可自由维护 markdown 文本。
- POST /world_model 支持 frontmatter + 正文输入，但 Flask 只剥离并存储正文，不做规则引擎和结构校验。
- prune_snapshot(..., view=world_model) 改为优先返回 world_model.md，避免硬编码章节约束。

2. 更新 git_server.py
- 注册 
egister_world_agent(...)。
- 在 init_db() 中确保 world_model.md 存在。
- GET /checkout?view=world_model 改为读取独立 world model 文档并返回。
- 保留 writer/reviewer 视图裁剪与 POST /commit 全量快照链路。

3. 更新 	ests/test_phase1.py
- 调整 1.3_view_world_model：改测“独立 world_model 文档链路”而非固定章节提取。
- 调整 1.8_data_flow_loop：加入 world model 文档更新并验证读取。
- 新增 	est_19_world_model_doc_endpoints 验证 /world_model GET/POST。

### 测试结果
- python tests/test_phase1.py：9/9 通过。
- python tests/test_outline_unpack.py：2/2 通过。
- 结论：Phase 1 在 PRD 哲学下可用，outlines/world model 两条链路均可独立运行。

### Git 提交记录（本轮）
- 3135b4 feat(world-agent): use standalone world_model markdown with flexible schema
- 35c5c35 feat(server): wire world model document routes and view integration
- 5d49f34 test(phase1): align world model flow with standalone markdown document
- 21faae5 docs(task): update phase1 world-model task notes and timestamps

### 下一步建议（Phase 2 前）
- 将 commit/checkout/history 进一步拆成独立 agent 文件，持续保持“一个 agent 一个文件”架构一致性。

## 2026-02-14 会话 4（协议升级：v2.3 JSON）

### 目标
- 执行 Project Chronos v2.3 协议：所有 POST 端点硬切 `application/json`。
- 保持“单一真相”：写入 `database.json` 的是后端重封装后的 Frontmatter Markdown。
- 取消旧的 text/plain 兼容与 outline JSON 自动解包旁路。

### 本轮代码改动
1. `/commit`（git_server.py）
- 新增统一 JSON 校验：`INVALID_PAYLOAD` / `MISSING_FIELD` / `ACTION_MISMATCH`。
- 请求协议改为 `action=commit + message + content (+parent_id)`。
- 对 `content` 先剥离已有 Frontmatter，再以 JSON 字段重封装并入库。
- 新增 `append_commit()`，统一 commit 元数据封装与哈希入链逻辑。

2. `/save_outline`（outline_agent.py）
- 移除旧的 `final_output/request/body` 自动解包逻辑。
- 改为只接收 `action=save_outline` 的 JSON 请求。
- 执行“剥离旧头->JSON字段重封装->存储”的一致化流程。
- 导出文件名优先级实现为：`JSON.title > content 第一行 > timestamp`。

3. `/world_model`（world_model_agent.py + world_agent.py + git_server.py）
- 新增 `POST /world_model`，协议 `action=update_world_model`。
- 不再读写独立 `world_model.md`。
- world_model 更新会合并进目标快照的 `## 核心状态档案`，并生成新的 commit（可回滚、可追溯）。

4. 自动化测试更新
- `tests/test_phase1.py`：更新为 JSON 协议并覆盖 `/world_model` 合并入链逻辑（9/9）。
- `tests/test_outline_unpack.py`：更新为协议校验与 rewrap 行为测试（4/4）。

### 测试结果
- `novel_git_server/.venv/Scripts/python.exe novel_git_server/tests/test_phase1.py`：9/9 通过。
- `novel_git_server/.venv/Scripts/python.exe novel_git_server/tests/test_outline_unpack.py`：4/4 通过。

### Git 提交记录（本轮）
- `675c537` refactor(commit): hard-cut to application/json with frontmatter rewrap
- `b0e9d84` refactor(save-outline): enforce JSON contract and rewrap markdown payload
- `6c452fd` feat(world-model): add json endpoint that merges core state into snapshot commits
- `cd1c520` test(protocol): update phase1 and outline tests for JSON hard-cut contract

## 2026-02-14 会话 5（World Agent v2.4 主动推演）

### 领取任务（feature_checklist）
- 先创建 `phase_1_patch_v24` 任务组（1.9~1.12），再按开发循环执行。
- 三权分立目标：`current_state`（现状）+ `target_outline`（目标）+ `gap_analysis`（逻辑桥接）。

### 本轮实现
1. 相关逻辑增强（后端）
- `GET /outlines` 新增查询参数：
  - `latest=1`：返回 `latest` 字段，直接给 World Agent 目标剧情入口。
  - `full=1`：返回完整 `content`（不再只看 preview）。
- 目的：支撑 `HTTP_GetOutlines` 节点直接提供“剧情驱动”输入。

2. Dify 指南（v2.4）
- 新增 `docs/dify_world_agent_v2_4.md`。
- 明确节点流：
  - `HTTP_CheckoutWorld`（现状锚点）
  - `HTTP_GetOutlines`（剧情驱动）
  - `Agent_WorldModel_GapPlanner`（差分推演）
  - `Condition_NeedRetrieval` + `Knowledge_Retrieval`
  - `Agent_WorldModel_Synthesizer`
  - `HTTP_UpdateWorld`
- 明确 Agent 输入变量必须同时包含 `{{current_state}}` 与 `{{target_outline}}`。

3. PRD 升级到 v2.4
- 将 World Agent 改为主动推演定义，加入 Active Deduction Flow。
- 明确 `/outlines?latest=1&full=1` 的目标剧情输入语义。
- 保持 JSON 协议与单一真相原则不变。

4. 任务回写
- `feature_checklist.json` 中 `phase_1_patch_v24` 的 1.9~1.12 已标记完成并补充说明。

### 测试结果
- `novel_git_server/.venv/Scripts/python.exe novel_git_server/tests/test_outline_unpack.py`：5/5 通过。
- `novel_git_server/.venv/Scripts/python.exe novel_git_server/tests/test_phase1.py`：9/9 通过。

## 2026-02-15 v3 Atomic Log
- task: v3.2_book_id_strict_validation
- change: added strict `validate_book_id()` in `book_storage.py` with separator/whitespace/charset guards.
- result: invalid ids (`..`, `a/b`, `book?`, whitespace) are rejected by ValueError; valid ids pass.
- verification: `python -m py_compile novel_git_server/book_storage.py` and runtime smoke checks via venv python.
- task: v3.3_request_book_id_guard
- change: rewrote `git_server.py` to v3 app factory with centralized `json_error`, `parse_json_payload`, and `require_book_id` helpers.
- result: v3 route `/books/ping` enforces `book_id` and emits standard error shape.
- verification: `/books/ping` without book_id returns 400; with `book_id=test_book_33` returns 200.
- task: v3.5_add_chapter_endpoint
- change: added `chapter_agent.py` with `POST /books/add_chapter` and wired registration in `git_server.py`.
- result: chapter content is persisted to `storage/{book_id}/chapters/{index}.md`.
- verification: API call returned 200 and file existence check returned true.
- task: v3.6_chapter_filename_policy
- change: chapter filename policy upgraded to `{4-digit}_{title}.md` with title derivation and sanitization.
- result: chapter files are naturally sortable and avoid illegal path characters.
- verification: `POST /books/add_chapter` produced `0012_*.md` style filename and saved successfully.
- task: v3.7_commit_world_state_endpoint
- change: added `world_state_agent.py` with `POST /commit_world_state` using real git init/add/commit/rev-parse on `storage/{book_id}`.
- result: world model updates are committed per book repo with real hash output.
- verification: repeated same payload twice; both returned 200 success and valid commit_id (second call hit nothing-to-commit fallback path).
- task: v3.8_commit_summary_endpoint
- change: added `summary_agent.py` and `POST /books/commit_summary` with per-book git commit flow.
- result: summary updates are persisted and versioned with real commit hash.
- verification: API call returned 200 success with non-empty commit_id.
- task: v3.9_outline_v3_endpoint
- change: rewrote `outline_agent.py` to v3 book-scoped endpoints: `POST /books/save_outline` and `GET /books/outlines`.
- result: outlines are isolated by `book_id` and read from filesystem without database.json.
- verification: save_outline returned 200 success; latest outline query with `full=1` returned content.
- task: v3.10_tool_read_chapter
- change: added `tools_agent.py` with `POST /tools/read_chapter` and registered it in server.
- result: tools API can fetch full chapter content by chapter_index.
- verification: saved chapter index 2 then read it back; response 200 with expected body text.
- task: v3.11_tool_search_chapter_index
- change: added `POST /tools/search_chapter_index` to `tools_agent.py` with file-based keyword counting.
- result: returns per-chapter count list for given keyword under target book.
- verification: sample chapters returned expected counts (2 and 0 for keyword alpha).

## 2026-02-24 会话：Ghost Write 靶向锁死（故障一）

### 目标
- 修复“推演成功但当前文件无 diff”的 Ghost Write 问题。
- 让世界 Agent 写入范围仅限 `world_model.md` / `status_card.md`。
- 在严格模式下强制 `writes[*].file_name == active_file`，防止跨文件写入造成前端视觉幽灵。

### 已完成
1. `world_draft.py`
- 新增写入策略常量与白名单：`WORLD_AGENT_ALLOWED_FILES`、`SYNC_ALL_WRITE_SCOPES`。
- `/api/world/deduce_stream` 入口新增 `active_file` 白名单拦截。
- Dify 输入与 `ack` 事件新增靶向契约字段：`active_file`、`write_scope=active_file_strict`。
- `/api/draft/sync_all` 新增 `write_scope`、`active_file` 校验。
- 增加目标文件集合锁（仅 world/status）与严格靶向锁（strict 模式必须命中 active_file）。

2. `archive.py`
- `WRITE_CONFLICT` 文案改为人工合并导向：明确返回 `draft_file` 后需人工合并再重试。

3. 前端契约同步
- `frontend/src/api/orchestration.ts`：推演请求显式发送 `write_scope=active_file_strict`。
- `frontend/src/api/draft.ts`：补齐 `write_scope/active_file` 的类型契约，避免后续直连漏参。

4. 测试与文档
- `test_v45_draft_sync_all.py`：新增拒绝越权写入、严格靶向拦截、strict 冲突草稿回归用例。
- `test_v46_world_deduce.py`：新增 `ack` 靶向字段断言与非法 `active_file` 拦截用例。
- `openapi_v3_5_1_draft_min.json`：补充 `write_scope`、`active_file` 契约与冲突人工合并说明。

5. Dify Prompt 同步
- `dify_workflows/世界模型agent (1).yml`：要求仅写 world/status，必须携带 strict 契约，冲突时停止重试并提示人工合并。

### 待验证
- 运行回归：
  - `pytest novel_git_server/tests/test_v45_draft_sync_all.py -q`
  - `pytest novel_git_server/tests/test_v46_world_deduce.py -q`
- task: v3.12_checkout_include_composer
- change: added `checkout_agent.py` with `GET /checkout` based on `include`, `last_n`, and optional `commit_id`.
- result: composition is token-driven (no writer/reviewer hardcoding); include parser trims comma-side spaces.
- verification: `include=world_model, summary, chapters` parsed to clean tokens; unknown token returned `400 INVALID_PAYLOAD`; `last_n=1` returned latest chapter chunk.
- task: v3.13_git_history_only
- change: added `history_agent.py` with `GET /books/history` parsing results from `git log` only.
- result: history endpoint no longer depends on database indexes; it reflects real repo timeline.
- verification: after world-state commit, `/books/history` returned total>=1 and expected fields.
- task: v3.4_hard_cut_legacy_routes
- change: added hard-cut guard in `git_server.py` to assert legacy routes are absent from active url map.
- result: legacy endpoints are not registered; no compatibility wrapper path remains.
- verification: `/commit` and `/history` returned 404 while `/books/ping` remained available.
- task: v3.14_remove_database_json_dependency
- change: marked runtime as database-json-free in `git_server.py` (`DATABASE_JSON_RETIRED=True`) and exposed state in `/health`.
- result: server runtime path no longer depends on database.json behavior.
- verification: `/health` returned `database_json: retired`.
- task: v3.15_one_time_migration
- change: added `tools/migrate_v24_to_v30.py` for one-shot v2.4->v3.0 migration into `storage/{book_id}`.
- result: legacy `world_model.md/outlines/chapters` move into scoped book dir; `database.json` archived under `_legacy_archive/...`.
- verification: dry-run execution showed expected move plan and archive target path.
- task: v3.16_test_book_id_required
- change: added `tests/test_v3_validation.py` covering missing and invalid `book_id` cases.
- result: strict guard behavior is verified as 400 with standard error code.
- verification: `python -m unittest novel_git_server.tests.test_v3_validation -v` passed (2 tests).
- task: v3.17_test_checkout_include
- change: added `tests/test_v3_checkout.py` and adjusted temp-path handling to workspace-local `.tmp_tests`.
- result: include trimming and chapter window behavior are now regression-tested.
- verification: `python -m unittest novel_git_server.tests.test_v3_validation novel_git_server.tests.test_v3_checkout -v` passed (4 tests).
- task: v3.18_test_storage_and_git
- change: added `tests/test_v3_storage_git.py` for per-book git auto-init and commit hash verification.
- result: endpoint behavior is validated against real `git rev-parse HEAD` output.
- verification: `python -m unittest novel_git_server.tests.test_v3_storage_git -v` passed.
- task: v3.19_test_migration_no_dbjson
- change: added `tests/test_v3_migration.py` validating one-time migration and post-migration runtime behavior.
- result: migration path confirms `database.json` is archived/removed and checkout still works.
- verification: `python -m unittest novel_git_server.tests.test_v3_migration -v` passed.
- task: v3.20_docs_progress_update
- change: synchronized progress log evidence across completed v3 refactor tasks.
- result: each atomic task now has an explicit log entry with change/result/verification.
- verification: full v3 test suite passed:
  - `novel_git_server.tests.test_v3_validation`
  - `novel_git_server.tests.test_v3_checkout`
  - `novel_git_server.tests.test_v3_storage_git`
  - `novel_git_server.tests.test_v3_migration`
  - total: 6 tests, all passed.
- task: v3.21_checklist_writeback
- change: finalized `feature_checklist.json` with all v3 task statuses set to done and phase marked complete.
- result: checklist now reflects atomic execution history and completion state.
- verification: manual review confirms v3.1~v3.21 all marked done with tested timestamps.
## 2026-02-15 v3 Atomic Log (Deterministic ID)
- task: v3.22_deterministic_book_id_generator
- change: added `generate_deterministic_id(book_name)` to `utils/book_storage.py`.
- detail: normalization (`strip + collapse spaces + lower`), pinyin slug via `pypinyin.lazy_pinyin` with safe fallback, plus md5 short hash suffix.
- detail: output format is `{slug}_{hash8}` and still validated by existing `validate_book_id` guard.
- dependency: added `pypinyin>=0.53.0` to `requirements.txt`.
- verification: static import and function-level smoke checks will be covered in route tests after endpoint wiring.
- task: v3.23_batch_import_optional_book_id_and_self_heal
- change: updated `POST /books/batch_import` in `agents/chapter.py`.
- detail: `book_id` is now optional; route resolves id by priority `book_id` -> `generate_deterministic_id(book_name)`.
- detail: when the resolved `storage/{book_id}` folder is missing, `ensure_book_layout(...)` auto-initializes it (self-healing/revival mode).
- detail: metadata is updated with incoming `book_name` when provided.
- test: extended `tests/test_v31_batch_import.py` with deterministic-id and delete-then-revive scenarios.
- verification: `python -m unittest novel_git_server.tests.test_v31_batch_import -v` passed (4 tests).
- task: v3.24_init_optional_book_id_deterministic_alignment
- change: updated `POST /books/init` in `agents/library.py`.
- detail: `book_name` remains required; if `book_id` is missing, backend now computes deterministic id via `generate_deterministic_id(book_name)`.
- detail: behavior is now aligned with `/books/batch_import` and preserves idempotent same-name initialization.
- test: updated `tests/test_v31_library.py` to cover deterministic id reuse without explicit `book_id`.
- verification: `python -m unittest novel_git_server.tests.test_v31_library novel_git_server.tests.test_v31_batch_import -v` passed (8 tests).
## 2026-02-15 PRD Update
- task: prd_v3_1_antifragile_rewrite
- change: rewrote `prd.md` from v3.0 to v3.1 based on current backend baseline + next-step architecture.
- scope: deterministic ID, self-healing storage, API matrix synced with implemented endpoints, and roadmap for status_card/error_archive/style_guide.
- commit: 64a934c
## 2026-02-15 v3.1 Atomic Log
- task: r0_checklist_seed_v31
- change: wrote R1-R14 refactor tasks into `feature_checklist.json` before coding, per workflow rule.
- detail: set phase `phase_v31_world_refactor` to `in_progress` with all tasks `pending`.
- detail: updated top-level checklist metadata to `prd_version=v3.1` and relaxed addressing rule to `book_id_or_book_name_required`.
- task: r1_contract_freeze
- change: synchronized contract docs for v3.1 addressing + generic archive APIs.
- detail: added explicit addendum in `prd.md` for unified addressing, get_file scope, and origin tag defaults.
- detail: created `novel_git_server/docs/api.md` draft for `/books/get_file` and `/books/update_file` payload/response contract.
- checklist: marked `r1_contract_freeze` as done in `feature_checklist.json`.
- task: r2_add_resolver_helper
- change: added `resolve_book_id(raw_book_id, raw_book_name)` to `utils/book_storage.py`.
- detail: resolution priority is `book_id` first, fallback to deterministic id from `book_name`.
- verification: `python -m py_compile novel_git_server/utils/book_storage.py` passed.
- checklist: marked `r2_add_resolver_helper` as done.
- task: r3_wire_resolver_world_state
- change: `/commit_world_state` now accepts payload without `book_id` and resolves repository by `book_name` via shared resolver.
- detail: route now calls `resolve_book_id(book_id, book_name)` and keeps existing `book_id` compatibility.
- verification: smoke test with Flask test client using `book_name` only returned 200 and generated deterministic `book_id`.
- checklist: marked `r3_wire_resolver_world_state` as done.
- task: r4_wire_resolver_summary
- change: `/books/commit_summary` now supports `book_name` fallback by using shared `resolve_book_id`.
- detail: payload requirement changed to `content` mandatory, while `book_id` remains optional for backward compatibility.
- verification: smoke test with `book_name`-only payload returned 200 and deterministic `book_id`.
- checklist: marked `r4_wire_resolver_summary` as done.
- task: r5_wire_resolver_other_routes
- change: updated centralized `require_book_id` in `app.py` to resolve from `book_id` or `book_name` using shared resolver.
- change: `add_chapter`, `batch_import`, `tools/read_chapter`, and `tools/search_chapter_index` no longer require explicit `book_id` field in payload.
- verification: smoke tests succeeded for add/read/checkout with `book_name` only; history route accepts `book_name` and returns route-level git error instead of field-missing error when repo has no commits.
- checklist: marked `r5_wire_resolver_other_routes` as done.
- task: r6_self_heal_templates_extend
- change: `ensure_book_layout` now auto-creates `status_card.md` and `error_archive.md`.
- detail: added structured markdown templates with guided sections (人物状态, 关系网络, 世界进度, 风险与冲突, 逻辑禁忌, 人设禁忌, 文风禁忌, 用户硬性修正).
- verification: local layout smoke confirmed both files are created during initialization.
- checklist: marked `r6_self_heal_templates_extend` as done.
- task: r7_generic_archive_agent_add
- change: added new blueprint module `agents/archive.py` with `GET /books/get_file` and `POST /books/update_file` base implementation.
- detail: both routes use unified book addressing helper and treat file content as plain text stream.
- verification: `python -m py_compile novel_git_server/agents/archive.py` passed.
- checklist: marked `r7_generic_archive_agent_add` as done.
- task: r8_archive_safety_guard
- change: added strict file path guard in archive API to block traversal and unsafe targets.
- detail: normalized relative paths, rejected absolute/parent escape, blocked `.git` internals, and enforced extension whitelist (`.md`, `.json`).
- verification: `python -m py_compile novel_git_server/agents/archive.py` passed.
- checklist: marked `r8_archive_safety_guard` as done.
- task: r9_atomic_commit_tagging
- change: upgraded `/books/update_file` to atomic write flow with rollback on git failure.
- detail: commit message now auto-prefixes by origin (`ai`/`user`/default system) and stages only target file.
- detail: write path is temp-file -> os.replace -> git add/commit; failures restore previous file content or remove newly created file.
- verification: `python -m py_compile novel_git_server/agents/archive.py` passed.
- checklist: marked `r9_atomic_commit_tagging` as done.
- task: r10_register_archive_blueprint
- change: registered new archive blueprint in app factory and imported `agents.archive`.
- verification: `python -m py_compile novel_git_server/app.py` passed.
- checklist: marked `r10_register_archive_blueprint` as done.
- task: r11_tests_resolver_and_self_heal
- change: added `tests/test_v31_addressing.py` to cover book_name addressing and self-healing recovery.
- coverage: world-state book_name commit, summary book_name commit, and delete-then-recover flow with `status_card.md` + `error_archive.md` recreation.
- verification: `python -m unittest novel_git_server.tests.test_v31_addressing -v` passed (3 tests).
- checklist: marked `r11_tests_resolver_and_self_heal` as done.
- task: r12_tests_archive_api
- change: added `tests/test_v31_archive.py` for generic archive API coverage.
- coverage: origin prefix behavior (`[System_Update]`, `[AI_Update]`, `[User_Edit]`), path traversal rejection, and reading `chapters/*.md` via `get_file`.
- verification: `python -m unittest novel_git_server.tests.test_v31_archive -v` passed (4 tests).
- checklist: marked `r12_tests_archive_api` as done.
- task: r13_docs_sync
- change: synchronized `docs/api.md` to current runtime endpoint behaviors and payload contracts.
- change: appended PRD runtime sync note for archive APIs, unified addressing, and origin commit tag policy.
- checklist: marked `r13_docs_sync` as done.
- task: r14_final_regression
- change: executed v31 regression suite after R1-R13 implementation.
- verification: `python -m unittest` passed for:
  - `test_v31_library`
  - `test_v31_batch_import`
  - `test_v31_adaptive_slice`
  - `test_v31_no_outlines`
  - `test_v31_addressing`
  - `test_v31_archive`
- result: 20 tests passed, 0 failed.
- checklist: marked `r14_final_regression` as done and `phase_v31_world_refactor` as done.

## 2026-02-15 v3.1 Final Polish
- task: r15_style_guide_template_init
- change: extended `ensure_book_layout` to initialize `style_guide.md` and expose `style_guide_path` in returned paths.
- template: added structured modules `# ????`, `# ????`, `# ????` for high-density style guidance.
- verification: `python -m unittest novel_git_server.tests.test_v31_addressing -v` (includes style_guide existence checks) passed.
- checklist: set `r15_style_guide_template_init` done, added r16/r17 as pending.
- task: r16_error_archive_negative_constraints
- change: strengthened default `error_archive.md` with explicit negative constraints for logic/persona/style cold start.
- template_examples:
  - ??????????????????
  - ??????????????????
  - ???AI ?????????????
- verification: `python -m unittest novel_git_server.tests.test_v31_addressing -v` (includes template content assertions) passed.
- checklist: set `r16_error_archive_negative_constraints` to done.
- task: r17_update_file_rollback_visibility
- change: upgraded `/books/update_file` failure path to emit traceback logs on both commit failure and rollback failure.
- change: when rollback itself fails, API now returns `warning` field (e.g. `rollback_failed: ...`) in `GIT_COMMIT_FAILED` response.
- verification: `python -m unittest novel_git_server.tests.test_v31_archive -v` passed (5 tests), including mocked rollback-failure warning case.
- checklist: set `r17_update_file_rollback_visibility` done and closed `phase_v31_world_refactor` as done.

## 2026-02-15 v3.1 Cleanup Atomic Log
- task: c1_archive_legacy_artifacts
- change: created `novel_git_server/legacy_attic/` and moved outdated artifacts there.
- moved_files:
  - `novel_git_server/legacy_attic/tools/cleantxt.py`
  - `novel_git_server/legacy_attic/tools/view_outlines.py`
  - `novel_git_server/legacy_attic/docs/dify_world_agent_v2_4.md`
  - `novel_git_server/legacy_attic/docs/????.md`
- result: active `docs/` and `tools/` now only keep v3.1 runtime-relevant files.
- checklist: added `phase_v31_cleanup` and marked `c1_archive_legacy_artifacts` done.
- task: c2_isolate_legacy_broken_tests
- change: created `novel_git_server/tests/legacy/` and moved syntax-broken legacy suites there:
  - `novel_git_server/tests/legacy/test_phase1.py`
  - `novel_git_server/tests/legacy/test_outline_unpack.py`
- result: active test discovery no longer imports those broken legacy modules.
- verification: `novel_git_server/.venv/Scripts/python.exe -m unittest discover novel_git_server/tests -v` passed (27 tests).
- checklist: set `c2_isolate_legacy_broken_tests` done.
- task: c3_remove_unused_blueprint_args
- change: removed unused `require_book_id` parameter from blueprint factories:
  - `agents/library.py`
  - `agents/summary.py`
  - `agents/world_state.py`
- change: cleaned corresponding `app.py` blueprint registration arguments.
- result: route contract unchanged, factory signatures cleaner with no dead params.
- verification: `novel_git_server/.venv/Scripts/python.exe -m unittest novel_git_server.tests.test_v31_library novel_git_server.tests.test_v31_addressing -v` passed (7 tests).
- checklist: set `c3_remove_unused_blueprint_args` done.
- task: c4_runtime_cleanup_and_regression
- change: removed runtime temp/cache artifacts:
  - `novel_git_server/.tmp_tests`
  - all `__pycache__` / `.pytest_cache` under `novel_git_server`
- verification: `novel_git_server/.venv/Scripts/python.exe -m unittest discover novel_git_server/tests -v` passed (27 tests, 0 failed).
- checklist: set `c4_runtime_cleanup_and_regression` done and closed `phase_v31_cleanup` as done.

## 2026-02-15 v3.1 Smart Resolution Hotfix
- task: prevent "ID of ID" nested hashing when `book_name` accidentally contains an existing `book_id`.
- change: added `smart_resolve_id(user_input, storage_root)` in `utils/book_storage.py` with 3-step resolution:
  1) direct id hit (`storage/{user_input}` exists)
  2) derived deterministic id hit (`storage/{generate_id(user_input)}` exists)
  3) fallback to derived deterministic id for new-book creation
- integration:
  - `resolve_book_id(..., storage_root)` now uses `smart_resolve_id` for `book_name` path
  - `app.py` require_book_id passes current `STORAGE_ROOT`
  - `agents/world_state.py` and `agents/summary.py` pass `storage_root` into `resolve_book_id`
  - `agents/library.py` `/books/init` now uses `smart_resolve_id` (instead of direct deterministic generation) when `book_id` is absent
- verification:
  - added tests in `tests/test_v31_library.py` and `tests/test_v31_addressing.py` for existing-id reuse via `book_name`
  - `python -m unittest discover novel_git_server/tests -v` passed (29 tests, 0 failed)

## 2026-02-18 Archive Hotfix Atomic Log (Empty-Commit Guard + Atomic Rollback Restore)
- task: a1_archive_atomic_write_restore
- change: restored atomic file-write workflow in `agents/archive.py` using temp file + `os.replace`, with rollback on failure.
- detail: update path now snapshots prior file state and restores previous content (or removes new file) when git stage/commit fails.
- verification: `python3 -m py_compile novel_git_server/agents/archive.py` passed.

- task: a2_archive_empty_commit_guard
- change: added no-change guard before commit in `update_file` via `git status --porcelain -- <target_file>`.
- detail: if no staged change exists for target file, endpoint returns success with message `No changes detected, file is already up to date.`
- detail: added `is_nothing_to_commit_error` fallback handling to keep no-change requests idempotent.
- verification: `python3 -m py_compile novel_git_server/agents/archive.py` passed.

- task: a3_archive_path_scoped_git_commit
- change: constrained archive git operations to target file only.
- detail: `git add` updated to `git add -- <normalized_rel_path>`.
- detail: `git commit` updated to `git commit -m <msg> -- <normalized_rel_path>`.
- verification: path-scoped behavior covered by subsequent regression run.

- task: a4_archive_regression_tests_sync
- change: updated `tests/test_v31_archive.py`.
- coverage:
  - added no-change short-circuit test to assert no additional commit is produced.
  - restored rollback warning coverage for commit failure + rollback failure path.

- task: a5_archive_hotfix_regression_run
- verification:
  - `python3 -m unittest novel_git_server.tests.test_v31_archive -v` passed (6 tests).
  - `python3 -m unittest novel_git_server.tests.test_v3_checkout -v` passed (2 tests).
- result: no regressions detected for archive/update_file and checkout integration.

## 2026-02-19 Archive Range Read Optimization Atomic Log
- task: a1_archive_range_contract_and_limits
- change: seeded `phase_v32_archive_range_read_optimization` in checklist with explicit endpoint contract and task pipeline.
- detail: contract frozen as 1-based inclusive range read with required `file_name/start_line/end_line` and shared `book_id|book_name` resolution.
- detail: added backend hard cap `max_lines=500` to prevent accidental huge line-window pulls and token explosion.
- checklist: set phase to `in_progress`, a1 to `in_progress`, and queued a2-a7 as `pending`.

- task: a2_archive_range_backend_helpers
- change: added line-window parsing helpers to `agents/archive.py` before route injection.
- detail: introduced `MAX_ARCHIVE_RANGE_LINES = 500` hard cap.
- detail: `_parse_positive_line_number(...)` now validates required positive integer line arguments.
- detail: `_validate_line_window(...)` now rejects `end_line < start_line` and any window larger than 500 lines.
- verification: `python3 -m py_compile novel_git_server/agents/archive.py` passed.

- task: a3_archive_range_route_injection
- change: injected `GET /books/get_archive_range` into `agents/archive.py`.
- detail: route reuses `_resolve_target_file(...)` and existing `book_id|book_name` addressing for path-safe file resolution.
- detail: response now returns `content` plus range metadata (`start_line`, `end_line`, `returned_end_line`, `line_count`, `total_lines`, `max_lines`).
- detail: route enforces 1-based positive lines and keeps `.git`/path-traversal defenses via shared validator.
- verification: `python3 -m py_compile novel_git_server/agents/archive.py` passed.

- task: a4_archive_range_tests_sync
- change: extended `tests/test_v31_archive.py` with range-read endpoint coverage.
- coverage:
  - UTF-8 line-slice correctness (`summary.md` lines 2-3).
  - invalid window guard (`end_line < start_line` -> 400).
  - max-lines hard cap guard (`1..501` -> 400, message contains `max_lines=500`).
  - path traversal rejection for `../escape.md`.
- verification: `python3 -m py_compile novel_git_server/tests/test_v31_archive.py` passed.

- task: a5_archive_range_contract_doc
- change: added `docs/archive_range_contract.md` for the new endpoint contract.
- detail: documented required params, 1-based inclusive semantics, and path safety constraints.
- detail: documented backend hard cap `max_lines=500` and corresponding error semantics.

- task: a6_archive_range_regression_run
- verification:
  - `python3 -m unittest novel_git_server.tests.test_v31_archive -v` failed in system interpreter (`ModuleNotFoundError: flask`).
  - `./novel_git_server/.venv_linux/bin/python -m unittest novel_git_server.tests.test_v31_archive -v` passed (10 tests).
- result: new `get_archive_range` tests passed and existing archive route behavior remained green.

- task: a7_archive_range_log_and_close
- change: completed atomic logging for a1-a6 and closed checklist statuses for phase v32.
- result: backend now supports path-safe line-range reads with hard cap `max_lines=500` for token-efficient agent calls.

## 2026-02-19 Archive Range Doc & Semantic Hardening Atomic Log
- task: a1_v33_contract_and_semantic_plan
- change: seeded `phase_v33_archive_range_doc_semantic_hardening` with atomic tasks for doc unification and error semantic optimization.
- detail: declared `docs/api.md` as single source of truth for range-read contract.
- detail: froze max-lines error requirement to include requested line count and split-read guidance for agent auto-correction.

- task: a2_v33_doc_merge_and_cleanup
- change: merged range contract documentation into `docs/api.md` under Generic Archive APIs.
- change: removed temporary contract file `docs/archive_range_contract.md` to enforce single-source documentation.
- detail: used targeted staging to avoid mixing unrelated pre-existing edits in `docs/api.md`.

- task: a3_v33_agent_friendly_error_semantics
- change: upgraded max-lines validation message in `agents/archive.py` for `GET /books/get_archive_range`.
- detail: over-limit response now includes requested count and explicit split-read guidance:
  - `请求行数（X行）超过上限（500行），请通过多次分段读取实现。`
- verification: `python3 -m py_compile novel_git_server/agents/archive.py` passed.

- task: a4_v33_tests_and_regression
- change: updated max-lines test assertion in `tests/test_v31_archive.py` to match exact actionable message.
- verification:
  - `python3 -m py_compile novel_git_server/tests/test_v31_archive.py` passed.
  - `./novel_git_server/.venv_linux/bin/python -m unittest novel_git_server.tests.test_v31_archive -v` passed (10 tests).

- task: a5_v33_log_and_close
- change: finalized v33 atomic logs and checklist closure for doc single-source and semantic hardening.
- result: range API documentation is now centralized in `docs/api.md`, and over-limit errors are agent-actionable.

## 2026-02-19 Chapter Highlights Fast Extract Atomic Log
- task: a1_v34_contract_freeze
- change: seeded `phase_v34_chapter_highlights_fast_extract` with atomic tasks for fast keyword highlight extraction.
- detail: contract frozen with `book_name/book_id + chapter_index + keywords + context_lines(optional)` and pure Python matching.
- detail: compression budget baseline fixed at `MAX_TOTAL_CHARS=1000`.

- task: a2_v34_validation_helpers
- change: added validation helpers in `agents/tools.py` for highlight endpoint payload normalization.
- detail: introduced keyword dedup/count guards and context_lines default/max constraints.
- detail: added fast-path constants including `MAX_TOTAL_HIGHLIGHT_CHARS = 1000`.
- verification: `python3 -m py_compile novel_git_server/agents/tools.py` passed.

- task: a3_v34_highlight_match_engine
- change: implemented pure Python keyword hit scan and context window generation in `agents/tools.py`.
- detail: added `line.casefold()` based matching with per-line matched keyword capture.
- detail: converted hits into context windows with start/end line bounds.
- verification: `python3 -m py_compile novel_git_server/agents/tools.py` passed.

- task: a4_v34_window_merge_and_budget
- change: added merge and budget pipeline in `agents/tools.py` for highlight windows.
- detail: overlapping/adjacent windows now coalesce into single snippets with deduped hit lines/keywords.
- detail: snippet rendering now enforces `MAX_TOTAL_HIGHLIGHT_CHARS = 1000` with truncation flag.
- verification: `python3 -m py_compile novel_git_server/agents/tools.py` passed.

- task: a5_v34_route_injection
- change: injected `POST /tools/extract_chapter_highlights` into tools blueprint.
- detail: route now resolves chapter by `book_id|book_name + chapter_index`, scans keyword hits, merges windows, and returns compressed snippets.
- detail: no-hit path returns success with empty snippets and agent guidance message; hit path returns line metadata and truncation stats.
- verification: `python3 -m py_compile novel_git_server/agents/tools.py` passed.

- task: a6_v34_tests_sync
- change: added `tests/test_v31_highlights.py` for new fast extraction endpoint.
- coverage:
  - hit extraction with line metadata
  - adjacent-window merge behavior
  - no-hit success response
  - `MAX_TOTAL_HIGHLIGHT_CHARS = 1000` truncation
  - payload validation failures
- verification:
  - `./novel_git_server/.venv_linux/bin/python -m unittest novel_git_server.tests.test_v31_highlights -v` passed (5 tests).
  - `./novel_git_server/.venv_linux/bin/python -m unittest novel_git_server.tests.test_v31_archive -v` passed (10 tests).

- task: a7_v34_perf_benchmark
- change: executed local latency benchmark via Flask test client for `/tools/extract_chapter_highlights`.
- dataset:
  - chapter size: 160 lines (~4k+ chars)
  - keywords: 3 (`高利贷`, `流浪汉`, `大满贯`)
  - context_lines: 2
  - iterations: 300 (after 20 warmups)
- result:
  - p50: `1.425 ms`
  - p95: `2.099 ms`
  - p99: `2.742 ms`
  - min/max: `1.207 ms` / `3.773 ms`
- note: last response payload remained compressed (`total_chars=396`, `snippet_count=2`).

- task: a8_v34_docs_and_close
- change: synced `docs/api.md` with `/tools/extract_chapter_highlights` request/response contract and hard limits.
- detail: documented keywords/context constraints, window merge behavior, and `max_total_chars=1000` budget semantics.
- result: v34 phase completed with code, tests, benchmark, and docs all aligned.

## 2026-02-19 Hybrid Radar + Append File Atomic Log
- task: a1_v35_contract_freeze
- change: seeded `phase_v35_highlight_hybrid_radar_and_append_file` with atomic implementation tasks.
- detail: contract now explicitly targets absolute-index extraction, `context_sentences` semantics, and 200-char boundary fallback.
- detail: acceptance includes single-line/no-newline tail-keyword benchmark and new `/books/append_file` API contract.

- task: a2_v35_absolute_index_hit_engine
- change: replaced legacy line-hit scanner with absolute index keyword hit engine in `agents/tools.py`.
- detail: keyword hits are now extracted directly from full text via `str.find` on `casefold` text.
- detail: output hit records carry `start_char/end_char` offsets and deterministic dedupe ordering.
- verification: `python3 -m py_compile novel_git_server/agents/tools.py` passed.

- task: a3_v35_sentence_boundary_expansion
- change: added sentence-window expansion helpers in `agents/tools.py` based on absolute hit offsets.
- detail: boundary scan now uses `。！？\\n` and `MAX_SENTENCE_BOUNDARY_SCAN_CHARS = 200`.
- detail: when punctuation is absent within scan range, expansion falls back to fixed-width char windows.
- verification: `python3 -m py_compile novel_git_server/agents/tools.py` passed.

- task: a4_v35_interval_merge_and_center_crop
- change: replaced line-window merge with char-range merge in `agents/tools.py`.
- detail: overlapping/adjacent hit ranges now merge using absolute char offsets and deduped hit offsets.
- detail: budget clipping now uses anchor-centered crop (`_center_crop_interval`) to preserve keyword core context.
- verification: `python3 -m py_compile novel_git_server/agents/tools.py` passed.

- task: a5_v35_extract_route_semantics_upgrade
- change: rewired `/tools/extract_chapter_highlights` to hybrid radar pipeline and `context_sentences` semantics.
- detail: route now reads full chapter text as raw string and extracts snippets using absolute char ranges.
- detail: response includes char offsets, hit offsets, hit line numbers, and chapter-level char stats.
- detail: backward compatibility retained for payload key `context_lines` as alias fallback.
- verification: `python3 -m py_compile novel_git_server/agents/tools.py` passed.

- task: a6_v35_highlight_tests_rewrite
- change: rewrote `tests/test_v31_highlights.py` for hybrid radar behavior.
- coverage:
  - single-line/no-newline tail keyword extraction
  - sentence window merge behavior under `context_sentences`
  - anchor-centered truncation under 1000-char budget
  - payload validation failures
- verification:
  - `./novel_git_server/.venv_linux/bin/python -m unittest novel_git_server.tests.test_v31_highlights -v` passed (6 tests).
  - `python3 -m py_compile novel_git_server/tests/test_v31_highlights.py` passed.

- task: a7_v35_append_file_route
- change: added `POST /books/append_file` in `agents/archive.py`.
- detail: append route now supports atomic temp-write replace, path-scoped git add/commit, and rollback on failure.
- detail: response includes `appended_chars`, `new_size`, and `commit_id`; empty append short-circuits as success.
- verification: `python3 -m py_compile novel_git_server/agents/archive.py` passed.

- task: a8_v35_append_file_tests
- change: added append-file tests in `tests/test_v31_archive.py` for success path, empty append short-circuit, and path traversal rejection.
- detail: success case verifies content persistence + commit count increment + commit metadata fields.
- detail: empty append case verifies no new commit and explicit unchanged response contract.
- detail: traversal case verifies `INVALID_PAYLOAD` protection remains effective for append route.
- verification:
  - `python3 -m py_compile novel_git_server/tests/test_v31_archive.py` passed.
  - `./novel_git_server/.venv_linux/bin/python -m unittest novel_git_server.tests.test_v31_archive -v` passed (13 tests).

- task: a9_v35_perf_benchmark_tail_hit
- change: executed dedicated latency benchmark for `/tools/extract_chapter_highlights` under single-line/no-newline long chapter with keyword near text tail.
- benchmark setup:
  - runner: Flask `test_client` in-process benchmark script (`.venv_linux/bin/python`)
  - iterations: `500` after `30` warmups
  - chapter shape: single line, `12073` chars, target keyword at end segment
  - keywords payload: 3 items (1 tail hit + 2 miss) with `context_sentences=2`
- result:
  - p50: `1.698 ms`
  - p95: `2.257 ms`
  - p99: `2.621 ms`
  - min/max: `1.482 ms` / `5.589 ms`
- validation:
  - returned `snippet_count=1`, `snippet_start_char=11400`, `snippet_end_char=12073`
  - `snippet_has_keyword=True`, proving tail keyword context survives extraction and budget clipping.

- task: a10_v35_docs_and_close
- change: synced `docs/api.md` to v35 runtime contract.
- detail:
  - upgraded `/tools/extract_chapter_highlights` docs to `context_sentences` + absolute char-range snippet schema
  - documented sentence-boundary expansion + 200-char fallback and `max_total_chars=1000` budget
  - added `POST /books/append_file` request/response contract and short-circuit semantics
- verification:
  - `./novel_git_server/.venv_linux/bin/python -m unittest novel_git_server.tests.test_v31_highlights -v` passed (6 tests).
  - `./novel_git_server/.venv_linux/bin/python -m unittest novel_git_server.tests.test_v31_archive -v` passed (13 tests).
- result: v35 phase completed with hybrid radar extraction, append-file incremental write, tests, benchmark, and docs fully aligned.

## 2026-02-20 Archive Write Conflict Guard Atomic Log
- task: a1_v36_contract_freeze
- change: froze optimistic-locking contract for archive writes.
- detail: core files (`world_model.md`, `summary.md`, `status_card.md`, `style_guide.md`, `error_archive.md`) require `base_etag`.
- detail: non-core files (e.g. `chapters/*.md`) remain compatibility mode with optional `base_etag`.

- task: a2_v36_etag_helpers + a3_v36_read_etag_surface
- change: added etag helper stack and surfaced etag in read APIs.
- detail:
  - introduced `_compute_text_etag` / `_compute_file_etag` in `agents/archive.py`
  - `GET /books/get_file` now returns `etag` and `ETag` response header
  - `GET /books/get_archive_range` now returns `etag` of full file and `ETag` response header

- task: a4_v36_short_critical_lock + a5_v36_conflict_draft_fallback
- change: added per-file short critical section locks and conflict draft persistence.
- detail:
  - introduced `_path_lock` backed by `fcntl.flock` and repo-local `.locks/`
  - introduced `_save_conflict_draft` to persist stale write payloads under `conflicts/`
  - introduced `WRITE_CONFLICT (409)` response with `base_etag/current_etag/draft_file`

- task: a6_v36_update_file_guard + a7_v36_append_file_guard
- change: enforced optimistic locking in both write routes.
- detail:
  - `POST /books/update_file` and `POST /books/append_file` now parse `base_etag`
  - core-file writes missing `base_etag` return `PRECONDITION_REQUIRED (428)`
  - stale etag writes return `WRITE_CONFLICT (409)` and emit `.ai_conflict_draft.md`
  - success payload now includes updated `etag`

- task: a8_v36_gitignore_hardening
- change: hardened nested repo ignore rules in `utils/book_storage.py`.
- detail:
  - `BOOK_GITIGNORE` now includes `.locks/` and `conflicts/`
  - existing `.gitignore` files are now patched to include missing required entries

- task: a9_v36_archive_tests_conflict + a10_v36_checkout_test_sync
- change: expanded regression tests for new conflict control contract.
- detail:
  - `tests/test_v31_archive.py` added coverage for etag headers, 428 precondition, 409 conflict+draft fallback
  - `tests/test_v3_checkout.py` updated to seed `base_etag` for `status_card.md` update

- task: a11_v36_docs_sync + a12_v36_regression_close
- change: synchronized `docs/api.md` with etag/precondition/conflict semantics and closed targeted regressions.
- verification:
  - `python3 -m py_compile novel_git_server/agents/archive.py novel_git_server/utils/book_storage.py novel_git_server/tests/test_v31_archive.py novel_git_server/tests/test_v3_checkout.py` passed
  - `./novel_git_server/.venv_linux/bin/python -m unittest novel_git_server.tests.test_v31_archive -v` passed (19 tests)
  - `./novel_git_server/.venv_linux/bin/python -m unittest novel_git_server.tests.test_v3_checkout -v` passed (2 tests)
  - `./novel_git_server/.venv_linux/bin/python -m unittest novel_git_server.tests.test_v31_library -v` passed (7 tests)
- result: archive write path now defends human/agent dirty-write races with optimistic locking, lock-protected commit critical section, and conflict draft preservation fallback.

## 2026-02-20 Prepend File Head-Injection Atomic Log
- task: a1_v37_prepend_route_contract
- change: added `POST /books/prepend_file` in `agents/archive.py`.
- detail: payload contract mirrors append route with `file_name`, `prepend_content`, optional `base_etag/message/origin`.

- task: a2_v37_prepend_edge_short_circuit
- change: added whitespace short-circuit guard for prepend writes.
- detail: when `prepend_content` is empty or whitespace-only, route returns success and skips write/git commit.

- task: a3_v37_prepend_lock_and_etag_guard
- change: reused optimistic-lock stack for prepend path.
- detail: prepend route now reuses `_normalize_base_etag`, `_path_lock`, core-file `428 PRECONDITION_REQUIRED`, and stale `409 WRITE_CONFLICT`.
- detail: conflict path persists `.ai_conflict_draft.md` through existing `_save_conflict_draft`.

- task: a4_v37_prepend_atomic_write
- change: implemented prepend atomic write + git pipeline.
- detail:
  - if current file is empty: `new_content = prepend_content`
  - if current file has content: `new_content = prepend_content + "\\n\\n" + current_content`
  - disk write remains atomic (`tempfile` + `os.replace`) and git commit remains path-scoped.

- task: a5_v37_docs_sync
- change: updated `docs/api.md` with `POST /books/prepend_file` contract and behavior notes.
- detail: documented edge-case short-circuit and etag/lock/conflict semantics.

- task: a6_v37_tests_prepend_regression
- change: extended `tests/test_v31_archive.py` with prepend regression coverage.
- coverage:
  - head injection correctness for `world_model.md`
  - stale etag conflict for prepend with draft fallback path assertion
  - whitespace prepend short-circuit with no new commit assertion
- verification:
  - `python3 -m py_compile novel_git_server/agents/archive.py novel_git_server/tests/test_v31_archive.py` passed
  - `./novel_git_server/.venv_linux/bin/python -m unittest novel_git_server.tests.test_v31_archive -v` passed (21 tests)

## 2026-02-20 Cold Archive Reader Atomic Log
- task: a1_v38_task_intake_and_contract_lock
- change: locked v38 scope to additive development only.
- detail: explicitly kept existing `GET /books/get_file` and `GET /books/get_archive_range` contracts untouched.
- detail: cold reader scope fixed to chapter-like files with strict filename filtering and core-file blacklist.

- task: a2_v38_filename_and_path_guard
- change: added dedicated cold-archive safety helpers in `agents/archive.py`.
- detail:
  - introduced `MAX_COLD_ARCHIVE_RANGE_LINES = 100`
  - introduced allowlist patterns: `chapter_*.md` and `^\\d+.*\\.md$`
  - hard-blocked `summary.md`, `world_model.md`, `status_card.md` in cold channel
  - added resolver that only targets `storage/{book_id}/chapters/` with root fallback
  - traversal / `.git` internal access remains blocked

- task: a3_v38_cold_range_route + a4_v38_line_window_cap_and_eof_smoothing
- change: added `GET /books/get_cold_archive_range`.
- detail:
  - input: `book_id|book_name`, `file_name`, `start_line`, `end_line`
  - read-only response excludes `etag`/`ETag`
  - if request window exceeds 100 lines, server auto-truncates and returns warning `message`
  - if `end_line` exceeds EOF, server clips to file tail and returns success

- task: a5_v38_tests_success_and_safety + a6_v38_tests_cap_and_eof
- change: extended `tests/test_v31_archive.py` with cold-reader regressions.
- coverage:
  - chapters directory read path + root fallback path
  - core-file blacklist rejection
  - filename regex rejection
  - traversal rejection
  - >100 line request truncation with warning
  - EOF smoothing behavior
  - no ETag exposure for cold-reader responses

- task: a7_v38_docs_api_sync + a8_v38_targeted_regression
- change: synced `docs/api.md` with new endpoint contract and executed targeted regressions.
- verification:
  - `./novel_git_server/.venv_linux/bin/python -m unittest tests.test_v31_archive -v` passed (27 tests)

## 2026-02-20 Cold Archive Prefix-Hit Atomic Log
- task: a1_v39_contract_lock
- change: locked scope to minimal modification, only touching cold archive resolver and response enrichment.
- detail: existing `GET /books/get_file` and `GET /books/get_archive_range` contracts remain unchanged.

- task: a2_v39_numeric_extract_helper
- change: added chapter-index extraction helper in `agents/archive.py`.
- detail:
  - extracts first numeric token from incoming `file_name`
  - normalizes to zero-padded 4-digit key (e.g. `95.md` -> `0095`, `chapter95` -> `0095`, `095` -> `0095`)

- task: a3_v39_prefix_scan_resolver
- change: added prefix-scan fallback for exact-match miss in cold resolver.
- detail:
  - resolver now scans `storage/{book_id}/chapters/` for files starting with `<index4>_`
  - keeps deterministic match order via sorted directory traversal
  - still preserves blacklist, traversal, and `.git` internals blocking

- task: a4_v39_route_response_real_name
- change: extended `GET /books/get_cold_archive_range` success payload with `real_file_name`.
- detail: payload now reports actual matched physical filename so Agent can cache canonical target.

- task: a5_v39_tests_prefix_hit + a6_v39_tests_no_number_and_safety
- change: extended `tests/test_v31_archive.py` coverage.
- coverage:
  - added prefix fallback hit assertions for `95.md`, `chapter95`, `095`
  - added `real_file_name` assertions on cold-reader success payloads
  - existing blacklist/traversal/invalid-name guards remain covered and passing

- task: a7_v39_docs_and_schema_sync
- change: updated `docs/api.md` for exact->prefix fallback order and response field `real_file_name`.
- detail: documented numeric normalization and chapters prefix matching rule.

- task: a8_v39_regression_and_close
- verification:
  - `./novel_git_server/.venv_linux/bin/python -m unittest tests.test_v31_archive -v` passed (28 tests)

## 2026-02-21 Frontend Handover Protocol Atomic Log
- task: a1_v40_scope_lock
- change: locked handover scope to frontend delivery handoff + flask-dify integration chain + atomic SOP extraction.
- detail: output target fixed to docs directory and aligned with existing checklist/progress governance.

- task: a2_v40_handover_doc
- change: created `docs/handover_protocol.md`.
- detail:
  - consolidated topology (`frontend -> flask -> dify`)
  - documented single-file closed loop for `world_model.md` with ETag precondition writeback
  - documented multi-flow routing strategy and YAML export governance for `dify_workflows/*.yml`
  - recorded canonical filename contract (`style_guide.md` instead of `style_card.md`)
  - codified repository atomic development SOP (audit -> checklist -> approval -> atomic commit -> progress writeback)

- task: a3_v40_progress_log_writeback
- change: appended this v40 delivery record as auditable handover evidence.

## 2026-02-21 OpenAPI Toolset Alignment Atomic Log
- task: a1_v41_scope_lock
- change: locked scope to contract-level alignment only; no runtime Flask behavior changes.
- detail: target artifact is a Dify-ready OpenAPI JSON synced to implemented backend endpoints.

- task: a2_v41_openapi_spec_doc
- change: created `docs/openapi_v3_4_4_aligned.json`.
- detail:
  - aligned core archive reads with runtime ETag semantics
  - aligned cold archive radar with numeric prefix auto-targeting and `real_file_name`
  - aligned highlight endpoint options (`context_sentences` + compatibility alias `context_lines`)
  - aligned write endpoints with core-file optimistic-lock semantics and `428/409` conflict/precondition responses
  - included `style_guide.md` and `error_archive.md` in core archive enum to avoid frontend naming drift
- verification:
  - `python3 -m json.tool docs/openapi_v3_4_4_aligned.json` passed

## 2026-02-21 OpenAPI Description Localization Atomic Log
- task: a1_v42_scope_lock
- change: locked scope to localization only on `docs/openapi_v3_4_4_aligned.json`.
- detail: no endpoint schema shape changes, no backend runtime behavior changes.

- task: a2_v42_translate_descriptions
- change: translated all OpenAPI `description` fields to Chinese.
- detail:
  - localized info-level, operation-level, parameter-level, response-level, and schema field descriptions
  - preserved technical identifiers (e.g. `base_etag`, `WRITE_CONFLICT`) where necessary for tool clarity
- verification:
  - `python3 -m json.tool docs/openapi_v3_4_4_aligned.json` passed

## 2026-02-21 OpenAPI Chinese Wording Polish Atomic Log
- task: a1_v43_scope_lock
- change: locked scope to wording polish only for OpenAPI description text.
- detail: no contract shape changes, no runtime API behavior impact.

- task: a2_v43_polish_apply
- change: refined remaining English-centered description wording to Chinese expression.
- detail:
  - localized phrases containing `WRITE_CONFLICT`/`Git` explanatory text into Chinese wording
  - localized alias description wording for context parameter
- verification:
  - `python3 -m json.tool docs/openapi_v3_4_4_aligned.json` passed
  - `rg -n '"description"\\s*:\\s*"[A-Za-z]' docs/openapi_v3_4_4_aligned.json` returned no matches

## 2026-02-21 World Draft Branching Atomic Log
- task: a1_v44_scope_and_checklist_writeback
- change: created v44 atomic checklist before code modifications.
- detail: scope locked to `/api/world/sync`, `/api/world/rollback`, `/api/world/confirm` plus tests/docs/progress synchronization.

- task: a2_v44_add_gitpython_dependency
- change: added `GitPython>=3.1.43` to `requirements.txt`.
- detail: branch orchestration implementation targets `git.Repo` and keeps dependency explicit in project manifest.

- task: a3_v44_world_draft_blueprint + a4_v44_world_draft_rollback_confirm
- change: added `agents/world_draft.py` with draft-branch lifecycle APIs.
- detail:
  - `POST /api/world/sync`: bootstrap draft branch (`draft/world_model`) from mainline (`main` first, fallback `master`), commit human markdown, call `call_dify_api` placeholder, commit AI markdown.
  - `POST /api/world/rollback`: hard reset draft branch to target commit hash and return rolled-back content.
  - `POST /api/world/confirm`: checkout mainline, merge draft branch, then delete draft branch.
  - added repo-level `.locks/world_draft.lock` via `fcntl.flock` to guard branch/index critical section.

- task: a5_v44_app_blueprint_registration
- change: registered `world_draft` blueprint in `app.py`.
- detail: new APIs are reachable under `/api/world/*` without touching existing route contracts.

- task: a6_v44_world_draft_tests + a7_v44_regression_run
- change: added `tests/test_v44_world_draft.py`.
- coverage:
  - sync creates draft branch and writes AI result.
  - rollback restores target draft commit content.
  - confirm merges into mainline and deletes `draft/world_model`.
- verification:
  - `env PYTHONPATH=/usr/lib/python3/dist-packages ./novel_git_server/.venv_linux/bin/python -m unittest novel_git_server.tests.test_v44_world_draft -v` passed (3 tests)
  - `env PYTHONPATH=/usr/lib/python3/dist-packages ./novel_git_server/.venv_linux/bin/python -m unittest novel_git_server.tests.test_v31_addressing -v` passed (4 tests)

- task: a8_v44_api_docs_sync
- change: updated `docs/api.md` with `/api/world/sync|rollback|confirm` contracts and response examples.

## 2026-02-22 Unified Draft Sandbox (v45) Atomic Log
- task: a1_v45_scope_lock
- change: added v45 phase checklist and locked scope to unified draft sandbox implementation.
- detail: scope includes `/api/draft/sync_all`, `/api/draft/rollback`, `/api/draft/confirm`, branch rename, compatibility aliases, tests, and minimal OpenAPI artifact.

- task: a2_v45_branch_namespace_refactor + a3_v45_sync_all_contract + a4_v45_etag_preflight + a5_v45_atomic_multifile_write + a6_v45_single_commit_transaction + a7_v45_route_namespace_converge + a8_v45_backward_alias
- change: rewrote `agents/world_draft.py` to implement unified draft sandbox flow.
- detail:
  - canonical branch changed to `draft/sandbox`; legacy `draft/world_model` auto-migrates on first touch.
  - added `POST /api/draft/sync_all` with `writes[]` contract (`update|append|prepend`) and duplicate-path guard.
  - added full ETag preflight before writes; core files require `base_etag` and return `428` when absent.
  - stale ETag returns `409 WRITE_CONFLICT` with persisted draft file via existing conflict helper.
  - multi-file write uses `tempfile + os.replace` and rollback restoration for all already-written files on failure.
  - one sync_all batch produces one commit on draft branch (`git add -- <paths>`, `git commit ... -- <paths>`).
  - canonical rollback/confirm routes moved to `/api/draft/rollback` and `/api/draft/confirm`.
  - kept `/api/world/sync|rollback|confirm` as deprecated aliases with warning field.
  - legacy `/api/world/sync` now auto-resolves current `world_model` etag for backward compatibility.

- task: a9_v45_regression_tests
- change: added `tests/test_v45_draft_sync_all.py` and updated `tests/test_v44_world_draft.py` expectations.
- verification:
  - `PYTHONPATH=venv/Lib/site-packages python3 -m unittest tests.test_v45_draft_sync_all -v` passed (3 tests)
  - `PYTHONPATH=venv/Lib/site-packages python3 -m unittest tests.test_v44_world_draft -v` passed (3 tests)
  - `PYTHONPATH=venv/Lib/site-packages python3 -m unittest tests.test_v31_addressing -v` passed (4 tests)

- task: a10_v45_openapi_draft_only
- change: created `docs/openapi_v3_5_1_draft_min.json` containing only three core draft endpoints.
- verification:
  - `python3 -m json.tool docs/openapi_v3_5_1_draft_min.json` passed.

## 2026-02-23 Dify Real-Link Orchestration (v46) Atomic Log
- task: a10_v46_timeout_guard
- change: updated `frontend/src/api/client.ts` with API timeout control.
- detail:
  - introduced default timeout (`VITE_API_TIMEOUT_MS`) and long deduction timeout (`VITE_DEDUCTION_TIMEOUT_MS`).
  - `/api/world/deduce` now uses extended timeout window to avoid premature abort during model reasoning.
  - timeout now raises protocol-level `ApiError(504, REQUEST_TIMEOUT)`.

- task: a11_v46_rollback_payload
- change: updated `frontend/src/api/draft.ts` rollback call contract.
- detail:
  - `rollbackDraft` now requires `commitHash` and sends `{\"commit_hash\": ...}` body.

- task: a12_v46_rollback_binding
- change: updated `frontend/src/App.tsx` rollback flow.
- detail:
  - rollback action now binds to `store.draftCommitId`.
  - missing commit hash now short-circuits to safe refresh path (reset sandbox + reload mainline).

- task: a13_v46_proxy_env
- change: updated `frontend/vite.config.ts`.
- detail:
  - proxy target moved to `VITE_FLASK_ORIGIN` (default `http://127.0.0.1:8000`).

- task: a14_v46_front_env_template
- change: created `frontend/.env.example`.
- detail:
  - added `VITE_FLASK_ORIGIN`, `VITE_API_TIMEOUT_MS`, `VITE_DEDUCTION_TIMEOUT_MS`.

- task: a15_v46_world_deduce_tests
- change: added `novel_git_server/tests/test_v46_world_deduce.py`.
- coverage:
  - mock-deduce success path returns `answer` + `conversation_id`.
  - required-field validation (`active_file`) returns `400 MISSING_FIELD`.
  - missing Dify key path returns `502 DIFY_API_FAILED`.
- verification:
  - `PYTHONPATH=venv/Lib/site-packages python3 -m unittest tests.test_v46_world_deduce -v` passed.

- task: a16_v46_rollback_contract_test
- change: updated `novel_git_server/tests/test_v45_draft_sync_all.py`.
- coverage:
  - added `test_draft_rollback_requires_commit_hash`.
- verification:
  - `PYTHONPATH=venv/Lib/site-packages python3 -m unittest tests.test_v45_draft_sync_all -v` passed.

- task: a17_v46_api_doc
- change: updated `novel_git_server/docs/api.md`.
- detail:
  - route index now includes `/api/world/deduce` and draft endpoints.
  - added dedicated `/api/world/deduce` contract and error example.

- task: a18_v46_handover_sync
- change: updated `novel_git_server/docs/handover_protocol.md`.
- detail:
  - added v46 real-link rules for `world/deduce`, timeout policy, and rollback `commit_hash` requirement.

- task: v46_postfix_frontend_types
- change: fixed frontend env typing and Vite config typing after a10/a13 integration.
- detail:
  - refactored `frontend/vite.config.ts` to `loadEnv(...)` pattern (removed `process` typing dependency).
  - added `frontend/src/vite-env.d.ts` for `import.meta.env` typing.
- verification:
  - `cd frontend && npm run -s build` passed.

## 2026-02-23 Streaming Chat Refactor (v47) Atomic Log
- task: a1_v47_dify_stream_client
- change: updated `novel_git_server/utils/dify_client.py`.
- detail:
  - added `chat_messages_stream(...)` with UTF-8 POST payload and SSE frame parsing.
  - added reusable payload builder and SSE packet parser helpers.

- task: a2_v47_world_draft_sse_helpers
- change: updated `novel_git_server/agents/world_draft.py`.
- detail:
  - added SSE encoder, draft-branch snapshot helpers, stream text extraction, and unified diff preview builder.

- task: a3_v47_world_deduce_stream_route
- change: updated `novel_git_server/agents/world_draft.py`.
- detail:
  - added `POST /api/world/deduce_stream` returning `text/event-stream`.
  - emits `ack -> delta* -> draft_ready? -> done` and `error` on failure.
  - preserves existing draft write boundary (`/api/draft/sync_all`), only observes draft changes and emits attachment data.
- verification:
  - `python3 -m py_compile novel_git_server/agents/world_draft.py` passed.

- task: a4_v47_api_md_stream_contract
- change: updated `novel_git_server/docs/api.md`.
- detail:
  - documented `/api/world/deduce_stream` payload and SSE event contract.

- task: a5_v47_openapi_stream_contract
- change: updated `novel_git_server/docs/openapi_v3_4_4_aligned.json`.
- detail:
  - added `/api/world/deduce_stream` OpenAPI schema and `text/event-stream` response description.
- verification:
  - `python3 -m json.tool novel_git_server/docs/openapi_v3_4_4_aligned.json` passed.

- task: a6_v47_store_types
- change: updated `frontend/src/types/store.d.ts`.
- detail:
  - introduced chat message model, diff attachment model, and streaming store action signatures.

- task: a7_v47_store_actions
- change: updated `frontend/src/store/index.ts`.
- detail:
  - added user/assistant message lifecycle methods, delta append, error settle, and diff attachment binding.

- task: a8_v47_sse_front_client
- change: added `frontend/src/api/sse.ts`.
- detail:
  - implemented `fetch + ReadableStream` POST-SSE parser with timeout guard and protocol-level error conversion.

- task: a9_v47_stream_orchestration
- change: updated `frontend/src/api/orchestration.ts`.
- detail:
  - added `runDeductionStream(...)` with `ack/delta/draft_ready/done/error` callback dispatch.

- task: a10_v47_chat_panel
- change: added `frontend/src/components/ChatPanel.tsx`.
- detail:
  - added right-side conversational container and auto-scroll behavior.

- task: a11_v47_chat_bubble
- change: added `frontend/src/components/ChatMessageBubble.tsx`.
- detail:
  - added role-aware chat bubbles with inline draft action controls.

- task: a12_v47_diff_card
- change: added `frontend/src/components/DiffSnippetCard.tsx`.
- detail:
  - added collapsible local-diff preview card for `draft_ready` attachments.

- task: a13_v47_prompt_unfreeze
- change: updated `frontend/src/components/CommandPrompt.tsx`.
- detail:
  - switched from full disable to submit-only disable; typing remains available during THINKING.

- task: a14_v47_app_stream_switch
- change: updated `frontend/src/App.tsx`.
- detail:
  - replaced blocking `runDeduction` flow with streaming `runDeductionStream`.
  - replaced right global diff panel with `ChatPanel`.
  - moved confirm/rollback trigger point into assistant message context.

- task: a15_v47_layout_rebalance
- change: updated `frontend/src/layouts/AppLayout.tsx`.
- detail:
  - rebalanced panel widths for chat-first right column.

- task: a16_v47_actionbar_legacy
- change: updated `frontend/src/components/ActionBar.tsx`.
- detail:
  - downgraded global action bar to legacy fallback mode for compatibility.

- task: a17_v47_chat_theme
- change: updated `frontend/src/index.css`.
- detail:
  - added stream caret animation and chat scrollbar theme primitives.

- task: a18_v47_progress_sync
- change: updated `novel_git_server/docs/progress_log.md`.
- detail:
  - synchronized full v47 atomic execution trace.

## 2026-02-23 Cursor UX Alignment (v48) Atomic Log
- task: a1_v48_api_stage_contract
- change: updated `novel_git_server/docs/api.md`.
- detail:
  - extended `/api/world/deduce_stream` contract with `stage` event semantics.
  - documented fallback behavior: if no delta but `workflow_finished.outputs.text` exists, backend emits one final `delta`.

- task: a2_v48_openapi_stage_contract
- change: updated `novel_git_server/docs/openapi_v3_4_4_aligned.json`.
- detail:
  - aligned deduce_stream description with event order `ack -> stage* -> delta* -> draft_ready? -> done`.
  - explicitly documented `stage` event and fallback delta semantics.
- verification:
  - `python3 -m json.tool novel_git_server/docs/openapi_v3_4_4_aligned.json` passed.

- task: a3_v48_backend_event_helpers
- change: updated `novel_git_server/agents/world_draft.py`.
- detail:
  - added Dify stream normalization helpers (`event` normalization, nested text extraction, workflow outputs extraction, stage payload builder).

- task: a4_v48_backend_stage_emit
- change: updated `novel_git_server/agents/world_draft.py`.
- detail:
  - added `stage` event emission for workflow/node/tool progress signals.
  - stage payload now includes readable text + source metadata.

- task: a5_v48_backend_delta_fallback_guard
- change: updated `novel_git_server/agents/world_draft.py`.
- detail:
  - implemented strict fallback gate: emit fallback delta only when **no delta has ever been emitted** and event is `workflow_finished`.
  - guarded against duplicate text emission with dedicated fallback flag.
- verification:
  - `python3 -m py_compile novel_git_server/agents/world_draft.py` passed.

- task: a6_v48_front_types_stage
- change: updated `frontend/src/types/store.d.ts`.
- detail:
  - introduced `StageProgress` model and per-message `stageProgress` field.
  - extended store action signatures for stage updates.

- task: a7_v48_front_store_stage
- change: updated `frontend/src/store/index.ts`.
- detail:
  - added `setAssistantStageProgress` action.
  - stage info clears automatically when first delta arrives or message completes/fails.

- task: a8_v48_front_orchestration_stage
- change: updated `frontend/src/api/orchestration.ts`.
- detail:
  - added `onStage` callback path for streamed `stage` events.

- task: a9_v48_front_app_stage_bind
- change: updated `frontend/src/App.tsx`.
- detail:
  - bound `stage` event payload to assistant message state in stream handler.

- task: a10_v48_front_bubble_stage_ui
- change: updated `frontend/src/components/ChatMessageBubble.tsx`.
- detail:
  - added Cursor-style subtle progress line (`[⚙️ ...]`) with low-contrast pulse indicator.
  - ensured stage line yields to normal text stream once delta content starts.

- task: a11_v48_front_panel_stability
- change: updated `frontend/src/components/ChatPanel.tsx`.
- detail:
  - applied dedicated scrollbar class to keep progress messages readable in continuous streams.

- task: a12_v48_progress_sync
- change: updated `novel_git_server/docs/progress_log.md`.
- detail:
  - synchronized full v48 atomic execution trace.

## 2026-02-23 Stream Continuity Hotfix (v49) Atomic Log
- task: a1_v49_backend_stream_event_normalization_fix
- change: updated `novel_git_server/agents/world_draft.py`.
- detail:
  - fixed Dify stream event normalization: when outer event is generic `message`, backend now correctly promotes `data.event` (`workflow_started`, `node_started`, `workflow_finished`, etc.).
  - restored stage progress emission path that was previously silenced by mis-normalized event names.
  - expanded workflow fallback extraction to support `workflow_finished.data.outputs.answer` in addition to `.text`, preventing empty assistant bubbles when only answer output is returned.

- task: a2_v49_stream_regression_tests
- change: updated `novel_git_server/tests/test_v46_world_deduce.py`.
- detail:
  - added regression test to ensure nested Dify `message + data.event` is translated into frontend `stage` events.
  - added regression test to ensure fallback delta is emitted from `workflow_finished.data.outputs.answer` when no prior delta exists.
- verification:
  - `./novel_git_server/venv/bin/python -m unittest novel_git_server/tests/test_v46_world_deduce.py` passed.
  - `./novel_git_server/venv/bin/python -m py_compile novel_git_server/agents/world_draft.py novel_git_server/tests/test_v46_world_deduce.py` passed.

## 2026-02-23 Frontend Done-Answer Fallback Hotfix (v50) Atomic Log
- task: a1_v50_front_store_done_answer_hydration
- change: updated `frontend/src/store/index.ts`.
- detail:
  - extended assistant finalize path to hydrate message text from `done.answer` when no prior delta text exists.
  - keeps existing delta-first behavior unchanged; fallback only activates on empty message text.

- task: a2_v50_front_app_done_answer_wiring
- change: updated `frontend/src/App.tsx`.
- detail:
  - wired stream `onDone` payload `answer` into `finishAssistantMessage(...)`.
  - prevents blank assistant bubbles for non-tokenized Dify responses.
- verification:
  - `cd frontend && npm run -s build` passed.

## 2026-02-23 Stage Trace UX Refinement (v51) Atomic Log
- task: a1_v51_types_stage_trace_list
- change: updated `frontend/src/types/store.d.ts`.
- detail:
  - added `stageEvents: StageProgress[]` to `ChatMessage` for rendering real execution trace.

- task: a2_v51_store_stage_trace_persistence
- change: updated `frontend/src/store/index.ts`.
- detail:
  - initialized `stageEvents` for both user/assistant messages.
  - stage updates now append deduplicated trace entries (rolling window) instead of keeping only transient single-line status.

- task: a3_v51_bubble_real_trace_render
- change: updated `frontend/src/components/ChatMessageBubble.tsx`.
- detail:
  - removed fake radar-style animated stage line.
  - replaced with compact real trace list showing actual stage/tool events from backend stream.
- verification:
  - `cd frontend && npm run -s build` passed.

## 2026-02-24 Fault3 Context Routing Rollout (in progress)
- task: a1_a6_front_context_switch_foundation
- change:
  - updated `frontend/src/types/store.d.ts`
  - updated `frontend/src/store/index.ts`
  - added `frontend/src/components/FileExplorer.tsx`
  - updated `frontend/src/App.tsx`
- detail:
  - introduced `FileType`/`HotFileItem` contracts.
  - added per-file conversation isolation store (`conversationByFile`) and transactional `setActiveFile`.
  - added left-side file explorer.
  - added navigation guard: block file switch when `fsm != IDLE` or unresolved draft exists.
  - made file switch force refresh mainline content + `base_etag`.

- task: a7_a10_front_backend_file_tree
- change:
  - added `frontend/src/config/hotFiles.ts`
  - added `frontend/src/lib/fileType.ts`
  - updated `frontend/src/api/checkout.ts`
  - updated `novel_git_server/agents/archive.py`
- detail:
  - added default hot file manifest and deterministic file_type resolver.
  - added frontend `fetchHotFiles()`.
  - added backend `GET /books/list_hot_files` endpoint returning core files + chapters list.

- task: a11_a16_backend_guard_and_route
- change:
  - updated `novel_git_server/agents/world_draft.py`
  - updated `novel_git_server/app.py`
- detail:
  - split read/write allowlists for `active_file`.
  - allowed read scope active files in deduce stream (`summary.md`, `chapters/*.md`, plus core/style/error files).
  - enforced `active_file <-> file_type` consistency.
  - hard-blocked write attempts when active file is read-only scope.
  - added file_type-based Dify route map config in app.
  - surfaced routing metadata (`file_type`, `routed_agent`) in SSE `ack`.

## 2026-02-25 Git Workspace + DAG Visualization (v52) Atomic Log
- task: a1_frontend_core_deps_lock
- change:
  - updated `frontend/package.json`
  - updated `frontend/package-lock.json`
  - updated `frontend/node_modules/.package-lock.json`
- detail:
  - added `@headless-tree/react` + `@headless-tree/core`.
  - added `react-resizable-panels`.
  - added `@xyflow/react`.

- task: a2_filetree_domain_model
- change:
  - added `frontend/src/lib/fileTree.ts`
- detail:
  - introduced deterministic tree model builder for `hotFiles -> tree nodes`.
  - added stable ids for group/folder/file nodes to support tree state consistency.

- task: a3_filetree_headless_render + a6_view_toggle_entry
- change:
  - updated `frontend/src/components/FileExplorer.tsx`
- detail:
  - migrated explorer rendering to `@headless-tree/react` with fold/unfold behavior.
  - added top-level `编辑视图 / Git 视图` toggle at explorer header.

- task: a4_scrollbar_tailwind_unify
- change:
  - updated `frontend/src/index.css`
  - updated `frontend/src/components/ChatPanel.tsx`
- detail:
  - introduced `@layer utilities` scrollbar utility class `app-scrollbar` with global dark tokens.
  - aligned chat/file-tree scrollbar visuals to unified console style.

- task: a5_workbench_mode_state
- change:
  - updated `frontend/src/types/store.d.ts`
  - updated `frontend/src/store/index.ts`
- detail:
  - added global state for `workbenchMode` and git graph session fields.
  - added actions for graph loading/error/data/selection updates.

- task: a7_layout_dual_mode_shell + a8_resizable_editor_layout + a9_resizable_persistence
- change:
  - updated `frontend/src/layouts/AppLayout.tsx`
  - updated `frontend/src/components/MainlineView.tsx`
  - updated `frontend/src/components/ChatPanel.tsx`
- detail:
  - replaced fixed columns with `react-resizable-panels` group/panel/separator layout.
  - added dual workbench shell (`editor` / `git_graph`) and persistent panel layout ids.
  - added `min-h-0` + `overflow-hidden/overflow-y-auto` guards to prevent flex overflow panel breakage.

- task: a10_git_graph_api_contract + a11_git_graph_backend_impl
- change:
  - updated `novel_git_server/agents/history.py`
  - updated `novel_git_server/docs/api.md`
  - updated `novel_git_server/docs/openapi_v3_5_1_draft_min.json`
- detail:
  - added `GET /books/git_graph` endpoint returning full DAG rows (`parent_ids[]`, `refs[]`).
  - preserved legacy `/books/history` compatibility by retaining `parent_id` and adding `parent_ids`.

- task: a12_git_graph_backend_tests
- change:
  - added `novel_git_server/tests/test_v52_git_graph.py`
- detail:
  - covered fresh repo graph shape, merge multi-parent graph, and history compatibility fields.

- task: a13_git_graph_front_dataflow + a14_git_graph_xyflow_render + a15_git_graph_minimal_inspector
- change:
  - added `frontend/src/api/history.ts`
  - added `frontend/src/components/GitGraphView.tsx`
  - updated `frontend/src/App.tsx`
- detail:
  - wired frontend graph fetch pipeline from `/books/git_graph` into global store.
  - rendered interactive DAG canvas with `@xyflow/react` in dedicated `git_graph` mode workspace.
  - implemented phase-1 minimal inspector: node click logs to console and shows basic commit message panel.
  - enforced mode-switch guard: block entering `git_graph` when draft decision is pending.

- task: a16_handover_progress_writeback
- change:
  - updated `novel_git_server/docs/handover_protocol.md`
  - updated `novel_git_server/docs/progress_log.md`
- detail:
  - documented workbench mode switch rules and git DAG contract in handover baseline.

- verification:
  - `cd frontend && npm run -s build` passed.
  - `./novel_git_server/venv/bin/python -m unittest novel_git_server/tests/test_v52_git_graph.py` passed.
  - `./novel_git_server/venv/bin/python -m py_compile novel_git_server/agents/history.py novel_git_server/tests/test_v52_git_graph.py` passed.

## 2026-02-25 Hidden Payload Stealth Intercept (v54) Atomic Log
- task: a1_backend_payload_primitives
- change:
  - updated `novel_git_server/agents/world_draft.py`
- detail:
  - added hidden payload marker constant `[FILE_PAYLOAD_START]`.
  - added `<file name="...">...</file>` parser with writable-file whitelist and duplicate guard.
  - added stream chunk splitter helper for marker detection.

- task: a2_backend_stream_gate
- change:
  - updated `novel_git_server/agents/world_draft.py`
- detail:
  - introduced stealth stream state machine (`is_payload_mode`, `pending_marker_tail`, hidden buffer).
  - enforced cross-chunk marker protection: partial marker prefixes are held until next chunk confirmation.
  - marker后文本不再透传前端，仅写入后端隐藏缓存。

- task: a3_backend_payload_validation
- change:
  - updated `novel_git_server/agents/world_draft.py`
- detail:
  - when marker appears, backend now requires valid `<file>` payload.
  - marker present but payload missing/invalid now returns `FILE_PAYLOAD_INVALID` and aborts stream.

- task: a4_backend_sync_bridge_with_etag
- change:
  - updated `novel_git_server/agents/world_draft.py`
- detail:
  - bridged parsed hidden files to existing `_sync_all_from_payload(...)` transaction path.
  - added ETag injection guard: backend resolves per-file current base etag and injects into writes before sync.
  - emits `git_sync_success` SSE event after successful transaction commit.

- task: a5_backend_done_guard
- change:
  - updated `novel_git_server/agents/world_draft.py`
- detail:
  - added `done.git_sync_applied` and `done.git_sync_commit_id` for explicit frontend sequencing guard.

- task: a6_backend_regression_tests
- change:
  - updated `novel_git_server/tests/test_v46_world_deduce.py`
- detail:
  - added tests for hidden payload successful sync, cross-chunk marker non-leak, marker-without-file hard failure, and legacy no-marker compatibility.

- task: a7_front_sse_contract
- change:
  - updated `frontend/src/api/orchestration.ts`
- detail:
  - added `onGitSyncSuccess` callback and `git_sync_success` event dispatch branch.

- task: a8_front_flush_on_done
- change:
  - updated `frontend/src/App.tsx`
- detail:
  - implemented onDone-after-sync flush strategy: collect `git_sync_success`, then run `flushAllStore()` and reload mainline/git views after stream completion.
  - preserves anti-race behavior by avoiding mid-stream reset.

- task: a9_docs_sync
- change:
  - updated `novel_git_server/docs/api.md`
  - updated `novel_git_server/docs/openapi_v3_4_4_aligned.json`
  - updated `novel_git_server/docs/progress_log.md`
- detail:
  - documented hidden payload intercept contract, new SSE event `git_sync_success`, and updated `done` payload fields.

- verification:
  - `python3 -m py_compile novel_git_server/agents/world_draft.py` passed.
  - `./novel_git_server/venv/bin/python -m unittest novel_git_server/tests/test_v46_world_deduce.py` passed.
  - `python3 -m json.tool novel_git_server/docs/openapi_v3_4_4_aligned.json` passed.
  - `cd frontend && npm run -s build` passed.

## 2026-02-25 合并分支功能（Git Merge）原子组
> **开发者：Antigravity**

### 目标
为 Git 控制台新增 Merge Branch 功能：任意本地分支 → 当前分支合并，正确区分 fast_forward / merge_commit / up_to_date 三种结果，含冲突自动中止与全量前端 UI。

### 原子任务执行记录

- task: **b1** feat(git-console): add POST /books/git_merge *(Antigravity)*
- change: `agents/git_console.py` 注入 `books_git_merge` 端点（120 行）
- detail:
  - **P0**：先 `git diff --diff-filter=U` 取冲突文件列表存内存，再 `git merge --abort`
  - **P1**：`--no-ff` 自动注入默认 commit message，防止 git 拉起编辑器挂起进程
  - **P2**：stdout+stderr 合并检测，兼容英文 `Already up to date` 与中文 `已经是最新的`
  - **FF 判定**：`new_HEAD == target_commit`（parent_count 在 source 含 merge commit 时误判）
- verification: `python -m py_compile agents/git_console.py` passed
- commit: f16108a

- task: **b1-patch + b2** fix+test: 多语言 up_to_date 检测 + 4 merge 测试 *(Antigravity)*
- root cause: 中文 locale 下 git 输出 `已经是最新的。`，英文字符串匹配永远无法命中
- change: `agents/git_console.py` 补丁；`tests/test_v53_git_console.py` 追加 4 用例
  - `test_git_merge_fast_forward`：HEAD == source tip
  - `test_git_merge_no_ff_no_hang`：5 秒内返回，产生 merge commit
  - `test_git_merge_conflict_aborted_with_file_list`：409 + conflicted_files + 工作区干净
  - `test_git_merge_already_up_to_date`：同 commit 分支 → merge_type=="up_to_date"
- verification: **10/10 passed**
- commit: 83d08dc

- task: **f1–f4** feat(frontend): merge branch UI + API *(Antigravity)*
- change:
  - `api/gitConsole.ts` (f1)：`mergeGitBranch` 函数，返回 merge_type 三元选
  - `api/client.ts` (f2)：409 MERGE_CONFLICT 先于 WRITE_CONFLICT 拦截，透传 conflictedFiles[]
  - `components/GitBranchPanel.tsx` (f3)：Merge Branch 区块（选源分支 / --no-ff / 冲突文件列表）
  - `App.tsx` (f4)：`handleGitMerge`，up_to_date→info / ff→success / conflict→error+CustomEvent
- verification: `npm run build` passed
- commit: 6a5ef8a

- task: **d1** docs: progress_log 记录 *(Antigravity)*
- commit: d6b6bc0

### 成果汇总
| 指标 | 值 |
|---|---|
| 后端新端点 | `POST /books/git_merge` |
| 测试 | 10/10（含 4 个新用例）|
| 前端改动 | 4 文件 |
| 提交 | f16108a / 83d08dc / 6a5ef8a / d6b6bc0 |
| bug 修正 | P0 时序 / P1 挂起 / P2 up_to_date / FF 误判 |

---

## 2026-02-25 FILE_PAYLOAD_INVALID 终极修复
> **开发者：Antigravity**

### 背景
Read Agent / World Agent 在 `</file>` 标签后输出任何中文收尾语时，后端报 FILE_PAYLOAD_INVALID 并中止写入。LLM 的天性决定 Prompt 层无法 100% 约束，须从后端根治。

### 原子任务执行记录

- task: **p1** 尾部容错 *(Antigravity)*
- change: `agents/world_draft.py` — `_parse_hidden_file_payload`
  - 将 `</file>` 之后的 `tail.strip()` 硬报错改为 warning 日志后忽略
  - `<file>` 块**之间**有杂文仍报错（保留结构严格性）
- verification: 14/14 passed
- commit: 4ce4b50

- task: **p2** 纯提取模式（终极修复）*(Antigravity)*
- root cause: p1 只修复尾部；LLM 在多 file 块**之间**同样会加"好的，接下来是……"等过渡语，仍会触发报错
- change: 重写 `_parse_hidden_file_payload` 为 Extraction Mode
  - 删除所有结构校验（between-block / trailing text）
  - 改为纯 `FILE_TAG_PATTERN.finditer(payload)` 提取：忽略 file 块周围的一切散文
  - 保留：白名单校验 / status_card.md 20 行 GC 截断
  - 函数体从 41 行缩至 22 行
- verification: **22/22 passed**（test_v46_world_deduce + test_v45_draft_sync_all）
- commit: e135985

### 成果汇总
| 指标 | 值 |
|---|---|
| 修复文件 | `agents/world_draft.py` |
| 免疫场景 | 标签前散文 / 块间过渡语 / 标签后收尾语 |
| 提交 | 4ce4b50 / e135985 |
| 回归 | 22/22 passed |

## 2026-02-26: Refactoring Dify Payload Pipeline & Handover Notes

- **Goal**: Decouple the World Deduce Agent's XML output formatting into a dedicated JSON schema node on Dify, making the backend a pure JSON receiver.
- **Completed Changes**:
  - Rewrote `world_draft.py`'s `_parse_hidden_file_payload` to `_parse_json_payload`.
  - Replaced `FILE_PAYLOAD_MARKER` with `JSON_PAYLOAD_MARKER` (`[JSON_PAYLOAD_START]`).
  - Removed all strict XML regex matching and stream-blocking errors for payload extraction.
  - Successfully updated and passed all 22 regression tests in `test_v46_world_deduce.py` and `test_v45_draft_sync_all.py` (Commit `e7b17fb`).
- **Current Experiment & Roadblock**:
  - Attempted to bypass the SSE hidden payload mechanism entirely by having a Dify Python Code Node directly send `POST /api/draft/sync_all` requests to the Flask backend.
  - The Dify container (Docker) can successfully reach the host's Flask server via `172.19.0.1:8000`.
  - **The Blocker**: The request is rejected by `archive.py` with `428 PRECONDITION_REQUIRED: base_etag is required for core archive file: world_model.md`.
  - **Context**: The `draft/sync_all` API rigidly enforces optimistic locking (ETag) for core files to prevent lost updates, but the Dify Python node does not have access to the current `base_etag` of the files it wants to write to.
- **Handover for Next Engineer**:
  - The architectural decouple is partially successful on the backend (it accepts pure JSON), but the direct API call approach from Dify is blocked by the ETag requirement.
  - **Potential Solutions to Evaluate**:
    1. **Rollback to SSE Injection (Recommended)**: Revert to having Dify output `[JSON_PAYLOAD_START]` followed by the JSON in the stream. The existing backend interceptor (`_parse_json_payload`) is already equipped to handle this, automatically fetches the required `base_etag` (`_resolve_hidden_payload_base_etag`), and executes `draft_sync_all` elegantly.
    2. **Modify Dify Workflow**: Before the Python Sync node runs, add an HTTP node to `GET /api/books/get_file` to fetch the current `etag`, then pass it as `base_etag` into the Sync node's payload.
    3. **Relax Backend Validation**: (High Risk) Allow `sync_all` to accept a `force` flag or bypass ETag checks for AI origin. Not recommended due to conflict risks.
  - Signed off: Antigravity.

## 2026-02-26 Bright Route Refactor (a1-a12)

- task: a1_protocol_freeze
- change:
  - added `novel_git_server/docs/world_deduce_v2_protocol.md`
- detail:
  - froze bright-route contract: Flask stream masks payload only; Dify owns extraction + sync execution.
  - fixed JSON marker contract `[JSON_PAYLOAD_START]`, ETag/428 retry rules, and frontend refresh closure conditions.
- commit: `f628ae8`

- task: a2_locator_conflict_guard
- change:
  - updated `novel_git_server/app.py`
  - updated `novel_git_server/utils/book_storage.py`
- detail:
  - introduced strict locator conflict detection; mixed `book_id` + `book_name` mismatch now returns `409 BOOK_LOCATOR_CONFLICT`.
- commit: `8b4f3a1`

- task: a3_a5_backend_dark_route_demotion
- change:
  - updated `novel_git_server/agents/world_draft.py`
- detail:
  - removed backend hidden-payload write execution path.
  - preserved marker masking and cross-chunk leakage protection.
  - marker present but invalid JSON payload now emits `JSON_PAYLOAD_INVALID` and aborts stream.
  - `done` event upgraded with `write_confirmed` + `hidden_payload_detected` + `hidden_payload_valid`.
- commit: `8581e29`

- task: a6_marker_migration
- change:
  - updated `dify_workflows/世界模型agent.yml`
- detail:
  - migrated workflow prompt markers from `[FILE_PAYLOAD_START]` to `[JSON_PAYLOAD_START]`.
- commit: `fb279a8`

- task: a7_a9_dify_executor_hardening
- change:
  - updated `dify_workflows/世界模型agent.yml`
  - updated `novel_git_server/agents/world_draft.py`
- detail:
  - repurposed three workflow code nodes as extraction+execution nodes (no graph rewiring required).
  - code-node executor now: parses hidden JSON, validates write whitelist, enforces payload size guard, trims status_card to 15 lines, fetches `base_etag`, calls `/api/draft/sync_all`, and retries once on `428` with `100-300ms` jitter.
  - answer nodes now render `visible_text` from code node outputs, preventing hidden payload leak.
  - backend now forwards `book_id` into Dify inputs and extracts workflow `sync_status/sync_commit_id/sync_message/result` from streamed outputs.
- commit: `47671da`

- task: a10_frontend_done_gate
- change:
  - updated `frontend/src/App.tsx`
- detail:
  - refresh now gated on `done.write_confirmed` (with backward fallback).
  - removed hard dependency on `git_sync_success` event.
  - if hidden payload exists but `sync_status != success`, frontend emits explicit error toast instead of silent refresh.
- commit: `b61aa3f`

- task: a11_regression_tests
- change:
  - updated `novel_git_server/tests/test_v46_world_deduce.py`
- detail:
  - aligned tests to bright-route behavior (no backend `git_sync_success`).
  - added coverage for `JSON_PAYLOAD_INVALID` on marker-without-payload.
  - added coverage for workflow sync-meta -> `done.write_confirmed` bridging.
  - added coverage for `BOOK_LOCATOR_CONFLICT`.
- commit: `5bb6332`

- task: a12_handover_progress_sync
- change:
  - updated `novel_git_server/docs/handover_protocol.md`
  - updated `novel_git_server/docs/progress_log.md`
- detail:
  - synced locator conflict semantics and deduce_stream role demotion in handover baseline.

- verification:
  - `python3 -m py_compile novel_git_server/app.py novel_git_server/utils/book_storage.py` passed.
  - `python3 -m py_compile novel_git_server/agents/world_draft.py` passed.
  - `./novel_git_server/venv/bin/python -m unittest novel_git_server/tests/test_v46_world_deduce.py` passed (16/16).
  - `cd frontend && npm run -s build` passed.
  - `python3 - <<'PY' ... yaml.safe_load('dify_workflows/世界模型agent.yml') ... PY` passed.


## 2026-03-09 Repo Integrity Repair (a1-a15)

- task: a1_a6_backend_read_virtualization
- change:
  - updated `novel_git_server/utils/git_utils.py`
  - updated `novel_git_server/utils/book_storage.py`
  - updated `novel_git_server/agents/archive.py`
  - updated `novel_git_server/agents/git_console.py`
  - updated `novel_git_server/agents/history.py`
  - updated `novel_git_server/agents/checkout.py`
  - updated `novel_git_server/agents/library.py`
  - updated `novel_git_server/app.py`
- detail:
  - split pure path resolution from explicit layout materialization.
  - added repo integrity probe, virtual core-file reads, side-effect-free Git/history reads, and explicit `POST /books/repair_layout`.
  - `/books/init` now performs an explicit repaired bootstrap instead of relying on GET auto-creation.
- commit: `d6a731e`

- task: a7_a9_world_draft_blockers
- change:
  - updated `novel_git_server/agents/world_draft.py`
- detail:
  - blocked `deduce`, `deduce_stream`, legacy sync, draft confirm, and draft rollback when repo layout is incomplete.
  - preserved virtual read semantics for active-file resolution while forcing explicit repair before AI execution.
- commit: `f4fed66`

- task: a10_a13_frontend_integrity_guard
- change:
  - updated `frontend/src/App.tsx`
  - updated `frontend/src/api/checkout.ts`
  - updated `frontend/src/types/store.d.ts`
  - updated `frontend/src/components/FileExplorer.tsx`
- detail:
  - added repo-integrity polling, repair action, missing-file/virtual-file state, Git freeze placeholders, and left-panel repair banner.
  - editor / AI / Git now respect `needsRepair` and stop before entering broken write flows.
- commit: `6e29fe9`

- task: a14_backend_regressions
- change:
  - added `novel_git_server/tests/test_v56_repo_integrity.py`
- detail:
  - covered metadata-only rollback -> virtual read, hot-file virtualization, Git GET non-mutation, explicit repair, and deduce-stream blocking.
- commit: `dbf260e`

- task: a15_docs_sync
- change:
  - updated `novel_git_server/docs/checklist_repo_integrity_repair.md`
  - updated `novel_git_server/docs/progress_log.md`
- verification:
  - `python3 -m py_compile novel_git_server/agents/world_draft.py` passed.
  - `./novel_git_server/venv/bin/python -m unittest novel_git_server/tests/test_v56_repo_integrity.py` passed (5/5).
  - `cd frontend && npm run -s build` passed.
- 2026-04-23
  - markdown write migration:
    - `POST /api/draft/sync_markdown_sections` became the new primary Markdown write path.
    - hidden `[JSON_PAYLOAD_START]` is now compatibility-only and should no longer be treated as the recommended Dify write strategy.
    - cross-file review detection now follows routed writable files rather than only `active_file`.
