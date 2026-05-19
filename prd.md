# PRD: Project Chronos v3.1 (Antifragile Edition)

## 0. 文档信息
- 版本：`v3.1`
- 日期：`2026-02-24`
- 适用范围：`novel_git_server` 当前代码基线 + 下一阶段演进蓝图
- 设计总纲：`Lazy Backend + Structured Memory + Self-Healing Storage`
- 当前状态：`MVP 持续集成中（SSE + Draft Sandbox 已上线，闭环体验待完善）`

---

## 1. 顶层目标：数字编辑部 (Digital Editorial Department)
构建一个可长期运行、可回溯、可并行推演的多 Agent 小说生产系统，核心解决：
- 长文本遗忘
- 角色 OOC（性格与行为漂移）
- 上下文窗口成本失控
- AI 文风油腻与表达同质化

核心方法论：
- 正向约束：`world_model` / `style_guide` / `summary`
- 负向约束：`error_archive`（错因归档）
- 版本分身：每本书独立 Git 宇宙，支持平行世界推演与回滚

---

## 2. 架构哲学与职责边界

### 2.1 组件职责
| 组件 | 隐喻 | 职责 |
|---|---|---|
| Dify Agent 集群 | 核心总编室 | 决策、推演、写作、审查、工具编排 |
| Flask Server | 加工厂 + 仓库 | IO、持久化、版本归档、自愈初始化；不做语义裁决 |
| Python Heavy Node / Tools | 重载货运车 | 处理大文本切分、批处理，缓解 Dify 侧超时 |
| Nested Git | 平行宇宙观测器 | 每本书独立版本线、分支与回滚能力 |
| 文件系统 | 记忆宫殿 | 文件即数据库，目录即索引 |

### 2.2 “后端躺平”与“后端自愈”的平衡
后端禁止：
- 代替 Agent 做剧情冲突裁决
- 代替 Agent 做语义合并推理
- 代替 Agent 做复杂 RAG 过滤策略

后端必须：
- 做确定性 ID 生成（防随机漂移）
- 做缺失目录/文件自愈初始化（防手动删库后崩溃）
- 做高吞吐 IO 与 Git 原子归档

---

## 3. 存储协议 v3.1（多书隔离 + 嵌套 Git）

### 3.1 目录结构
```text
novel_git_server/
└── storage/
    ├── {book_id}/
    │   ├── .git/
    │   ├── metadata.json
    │   ├── world_model.md
    │   ├── summary.md
    │   ├── chapters/
    │   │   ├── 0001_xxx.md
    │   │   ├── 0002_xxx.md
    │   │   └── ...
    │   ├── status_card.md      # v3.1 规划
    │   ├── error_archive.md      # v3.1 规划
    │   └── style_guide.md        # v3.1 规划
    └── snapshot_template.md
```

### 3.2 单一真相原则 (Single Truth)
- 真相来源：`storage/{book_id}/` 文件内容 + 该目录 `.git` 历史。
- 不维护中心化剧情数据库；`database.json` 彻底退役。

### 3.3 书籍 ID 策略（Deterministic ID）
当调用方未显式提供 `book_id` 时，由后端根据 `book_name` 生成：
1. 归一化：`strip + collapse spaces + lower`
2. 拼音化：`pypinyin.lazy_pinyin`（失败时回退安全字符清洗）
3. Hash 后缀：`md5(normalized_name)[:8]`
4. 输出格式：`{slug}_{hash8}`

例如：`三体 -> santi_xxxxxxxx`（示例）

### 3.4 自愈机制 (Self-Healing)
所有关键写接口在写入前必须调用 `ensure_book_layout(book_id, ...)`：
- 目录不存在则自动创建
- `.git` 不存在则自动初始化
- `world_model.md` / `summary.md` / `chapters/` 缺失则补齐
- `metadata.json` 按需更新

---

## 4. 记忆模型：三维约束矩阵

| 记忆类型 | 载体 | 作用 | 状态 |
|---|---|---|---|
| 冷记忆 | `chapters/*.md` | 原始叙事素材库（风格、事实、细节） | 已实现 |
| 静态热记忆 | `world_model.md` | 世界百科：地理、势力、规则、设定 | 已实现 |
| 动态热记忆 | `status_card.md` | 运行时状态：位置、关系、近期事件、目标 | 规划中 |
| 负向记忆 | `error_archive.md` | 用户纠错与禁忌规则档案 | 规划中 |
| 风格约束 | `style_guide.md` | 句式、节奏、词频、情感阈值 | 规划中 |

说明：
- `world_model.md` 与 `summary.md` 允许全量覆盖，不做后端语义 merge。
- 复杂冲突（如生死/时空矛盾）由 Agent 在 Dify 工作流中解决。

---

## 5. API 协议与接口清单（代码对齐）

### 5.1 通用协议
- `Content-Type: application/json`
- UTF-8 JSON 输出，`ensure_ascii=False`
- 错误统一结构：
```json
{"status": "error", "code": "...", "message": "..."}
```

### 5.2 已实现接口（v3.1 基线）

#### Library
1. `POST /books/init`
- 入参：`book_name`（必填），`book_id`（可选）
- 行为：未传 `book_id` 时自动生成确定性 ID；初始化书籍目录与元数据

2. `GET /books/search?query=...`
- 行为：遍历 `storage/*/metadata.json`，模糊匹配 `book_name/book_id`

#### Chapter
3. `POST /books/add_chapter`
- 入参：`book_id`, `chapter_index`, `content`, `title?`
- 行为：写入 `chapters/{4位序号}_{安全标题}.md`

4. `POST /books/batch_import`
- 入参：`content`（string 或 list），`book_id?`, `book_name?`
- 行为：按 `|||CHAPTER_START|||` 切分，批量落盘；未传 `book_id` 时走确定性 ID

#### World / Summary Commit
5. `POST /commit_world_state`
- 入参：`book_id`, `content`, `message?`
- 行为：覆盖写 `world_model.md`，`git add . && git commit`

6. `POST /books/commit_summary`
- 入参：`book_id`, `content`, `message?`
- 行为：覆盖写 `summary.md`，`git add . && git commit`

#### Checkout / History
7. `GET /checkout`
- Query：`book_id`（必填），`include?`，`last_n?`，`commit_id?`
- `include` 默认：`world_model,summary,chapters`
- 行为：按 include 组合输出 markdown 视图

8. `GET /books/history?book_id=...`
- 行为：返回该书 Git 历史（commit_id/parent_id/timestamp/message）

#### Tools
9. `POST /tools/read_chapter`
- 入参：`book_id`, `chapter_index`
- 行为：返回目标章节全文

10. `POST /tools/search_chapter_index`
- 入参：`book_id`, `keyword`
- 行为：返回每章关键词命中数

11. `POST /tools/adaptive_slice`
- 入参：`arg1`
- 行为：执行自适应切片算法（与 Dify Python 节点兼容）

#### Health
12. `GET /health`
13. `GET /books/ping?book_id=...`

### 5.3 规划接口（状态卡片 Markdown 化）
14. `POST /books/update_file`
- 入参：`book_id`, `file_name`, `content`
- 行为：把目标文件当作纯文本流覆盖写入，不做 JSON 结构解析。
- 说明：`status_card.md` 由该接口统一维护。

15. `GET /books/get_file`
- Query：`book_id`, `file_name`
- 行为：原样读取目标文件文本并返回。
- 说明：后端不解析文件内部结构，保持“躺平档案员”原则。

---

## 6. Agent 军团作战手册（v3.1）

### Agent 1：总结/归档 Agent（已上线）
- 输入：原始文本
- 流程：`/tools/adaptive_slice` -> `/books/batch_import` -> `/books/commit_summary`
- 输出：冷记忆与摘要归档

### Agent 2：世界 Agent（进行中）
- 输入：`checkout(include=world_model,summary,chapters)` + 最新剧情目标
- 任务：维护 `world_model.md`，后续扩展 `status_card.md`
- 输出：`/commit_world_state`

### Agent 3：文风 Agent（规划）
- 输入：`chapters/*`
- 输出：`style_guide.md`

### Agent 4：大纲 Agent（规划）
- 输入：`summary + status_card.md + 用户意图 + 现有 outline 文件`
- 输出：分层规划 Markdown 文件（按阶段写入）
  - `brainstorm.md`
  - `master_outline.md`
  - `arc_outline.md`
  - `chapter_outline.md`
- 规划阶段建议：
  1. 头脑风暴：发散主题、卖点、路线候选
  2. 大方向 / 大伏笔确定：收束总纲、终局、长期伏笔
  3. 篇章内容确定：将总纲拆为卷/篇/阶段目标
  4. 逐章节大纲确定：生成可被续写 Agent 消费的章节执行清单

### Agent 5：续写 Agent（规划）
- 输入：`world_model + status_card.md + style_guide + error_archive + chapter_outline.md`
- 输出：新增章节草稿

### Agent 6：审查 Agent（规划）
- 输入：续写结果 + `chapter_outline.md` + 历史上下文
- 输出：问题清单 + `error_archive.md` 更新建议

### Agent 7：历史/回滚控制 Agent（规划）
- 输入：用户“平行宇宙”意图
- 输出：分支、回滚、对照试验流程（当前先通过 git 命令实现）

### Agent 4-6 宏观闭环（规划）

`大纲 Agent -> 续写 Agent -> 审查 Agent` 不是一次性串行链路，而是一个受作者主权控制的长期闭环：

1. 大纲 Agent 先产出当前层级的规划文件，并最终收束到 `chapter_outline.md`
2. 续写 Agent 读取当前待执行的章节大纲，生成章节草稿
3. 审查 Agent 对照章节大纲、热记忆、冷记忆与负向约束进行审查
4. 若审查未通过，草稿返回续写 Agent 重写
5. 若审查通过，作者决定是否将该章纳入正史
6. 仅当当前章节大纲池已消费完，或作者意图发生改变时，再重新唤起大纲 Agent 生成新的不同层级大纲

关键原则：
- 大纲不是一次性回复文本，而是可被逐步消费的文件化任务集
- 续写 Agent 的直接上游是“当前章节大纲”，不是自由聊天上下文
- 审查 Agent 是生产闸门，而不是可有可无的附属节点
- 大纲 Agent 只在“章节任务耗尽”或“作者改意图”时重新进入

### Agent 4-6 微观循环（人工门控）

章节级生产必须采用人工门控微循环，而不是自动无限自迭代：

```text
章节大纲已确定
-> 续写 Agent 产出草稿
-> 审查 Agent 给出审查结果
-> 作者决定：
   - 再来一轮（返回续写 Agent）
   - 通过入正史
   - 回退草稿
   - 改大纲并重新规划
```

说明：
- 审查 Agent 不能自动触发无限重写
- “是否继续重写”与“是否入正史”都必须由作者决定
- 这样可以防止无限死循环，并保持作者对节奏、质量阈值和成本投入的主权
- 该机制与本项目“文件即真相、Git 可回退、低成本纠偏”的哲学一致

---

## 7. Dify 协同规范（关键）
- Dify 负责“思考与决策”，Flask 负责“归档与提取”。
- 对于大文本处理，优先调用 `/tools/adaptive_slice` 和 `/books/batch_import`，避免 Dify 节点超时。
- World Agent 最小输入建议：
  - `current_state`：`/checkout?include=world_model,summary,chapters&last_n=3`
  - `target_outline`：上游变量或外部剧情输入
- 冲突判定（地点矛盾、人物状态冲突）由 Agent 处理，后端不裁决。

---

## 8. 反脆弱机制（Antifragile）
1. 同名幂等：确定性 ID 降低随机漂移和重复建库。
2. 删库可复活：目录缺失时自动重建，不阻断流水线。
3. 原子可追溯：每次关键写入都可通过 Git 查证。
4. 错误可沉淀：通过 `error_archive.md` 将用户反馈沉淀为长期约束。
5. 平行宇宙：通过分支试写与对照回滚实现“低风险创新”。

---

## 9. 开发里程碑（更新）

### 已完成
- 多书隔离与每书独立 Git
- 确定性 ID（可选 book_id）
- 批量导入与切片工具
- checkout/include 视图拼装
- history/git 日志查询

### 下一阶段（MVP）
- `status_card.md` 的定义、读写接口、Agent 提示词接入
- `error_archive.md` 审查闭环
- 分支/回滚 API（或标准化脚本封装）
- 文风约束 `style_guide.md`

建议排期：
- 2.16 - 2.22：世界 + 文风 + 大纲核心链路
- 2.23 - 2.28：续写 + 审查闭环 + 回滚演示

---

## 10. 验收标准
- 相同 `book_name` 在未提供 `book_id` 时稳定映射到同一 ID
- 手动删除 `storage/{book_id}` 后，后续写请求可自动恢复
- `world_model.md` / `summary.md` / `chapters/` 均可独立提交并可追溯
- 所有核心接口均返回统一 JSON 结构，错误码可读
- Dify 可仅依赖 HTTP 完成“导入 -> 推演 -> 写作 -> 审查”的主链路

---

> 协议声明：Project Chronos v3.1 以“文件即数据库、Git 即时间线、Agent 即决策核心”为基本法；后端负责可靠性，Agent 负责创造性。


## 11. v3.1 Contract Addendum (R1 Freeze)
- Unified addressing: all book-scoped APIs MUST accept `book_id` OR `book_name`.
- Resolution priority: `book_id` first; if absent, backend computes deterministic id from `book_name`.
- Generic archive read scope for `GET /books/get_file`: allow all `.md` and `.json` files under `storage/{book_id}/`, including `chapters/*.md`.
- Generic archive write for `POST /books/update_file`: treat payload content as opaque text stream, no semantic parsing.
- Commit origin tag policy:
  - `origin=ai` -> `[AI_Update]`
  - `origin=user` -> `[User_Edit]`
  - default/unknown -> `[System_Update]`

## 12. Runtime Sync Note (R13)
- `/books/get_file` and `/books/update_file` are now part of runtime API set.
- Archive APIs support unified addressing (`book_id` or `book_name`) and treat content as opaque text.
- `update_file` commit prefix defaults to `[System_Update]` and supports `[AI_Update]` / `[User_Edit]` by `origin`.
- `get_file` supports reading `chapters/*.md` plus other `.md/.json` files under each book root.

## 13. Git 提交记录增补（v34-v36）
基于最近一轮提交回顾（`813586a -> ef1b237`），新增能力如下：

### 13.1 冷档案“高光提取”能力升级（v34/v35）
- 新增并强化接口：`POST /tools/extract_chapter_highlights`
- 核心能力：
  - 从按行扫描升级为“绝对字符索引”匹配，适配“整章单行无换行”文本。
  - 上下文语义从 `context_lines` 升级为 `context_sentences`（保留兼容别名）。
  - 采用句边界扩展（`。！？\n`）+ 200 字符兜底扫描。
  - 命中区间支持合并与“以命中点为中心”预算裁剪，避免首段截断黑洞。
- 预算防线：`max_total_chars=1000`，响应返回 `truncated` 与 char-range 元数据。
- 性能基准（本地 test client）：单行长文本 + 尾部关键词场景 `p95=2.257ms`。

### 13.2 归档读写接口扩展（v35）
- 新增接口：`POST /books/append_file`
  - 支持增量写入，原子落盘（tempfile + `os.replace`）与路径级 Git 提交。
  - 返回 `appended_chars/new_size/commit_id`。
- 新增接口：`GET /books/get_archive_range`
  - 支持按行窗口读取（`start_line/end_line`）。
  - 后端强制上限 `max_lines=500`，超限返回可被 Agent 理解的纠错提示。

### 13.3 Git 历史去噪与隔离强化
- 修复 metadata 垃圾提交：
  - `metadata.json` 仅在结构字段实质变化时写入与提交。
  - 消除“只因 updated_at 刷新而产生提交”的噪声。
- 提交隔离策略：
  - 写接口统一采用路径级 `git add -- <file>` 与 `git commit -- <file>`。
  - 禁止全局暂存导致跨进程“劫持提交”。

### 13.4 人机协同防脏写机制（v36）
为 `world_model.md / summary.md / status_card.md / style_guide.md / error_archive.md`
引入强防冲突策略：
- 乐观锁（主防线）：
  - 读接口 `GET /books/get_file`、`GET /books/get_archive_range` 返回 `etag`（body + `ETag` 头）。
  - 写接口 `POST /books/update_file`、`POST /books/append_file` 对核心文件强制要求 `base_etag`。
  - 缺失 `base_etag` 返回 `428 PRECONDITION_REQUIRED`；过期返回 `409 WRITE_CONFLICT`。
- 短临界区锁（并发防线）：
  - 写入“校验 -> 写盘 -> Git 提交”全过程使用 `fcntl.flock` 文件锁。
  - 锁文件位于每书仓库 `.locks/`。
- 冲突草稿兜底（保全防线）：
  - 发生冲突时自动保存 AI 输入到 `conflicts/*.ai_conflict_draft.md`。
  - `409` 响应返回 `draft_file` 路径，确保内容不丢失。
- 兼容策略：
  - 章节文件（如 `chapters/*.md`）暂时维持 `base_etag` 可选模式，兼容续写流水线。

### 13.5 仓库卫生规则补齐
- 每书仓库 `.gitignore` 现强制包含：
  - `.locks/`
  - `conflicts/`
- 适用于新仓库与既有仓库（自动补齐缺失条目）。

## 14. 开发进度看板（截至 2026-02-24）

### 14.1 已完成（后端能力）
- 核心归档并发防线：`ETag` 乐观锁 + `fcntl.flock` 短临界区锁 + `409` 冲突草稿兜底。
- 核心写接口统一：`/books/update_file`、`/books/append_file`、`/books/prepend_file` 支持原子写盘与路径级 Git 提交。
- 精准读取能力：
  - `/books/get_archive_range`（单次上限 500 行）
  - `/books/get_cold_archive_range`（冷档案自动寻的 + 单次上限 100 行）
- 冷档案语义雷达：`/tools/extract_chapter_highlights` 已升级为绝对索引 + 句边界膨胀算法。
- 统一草稿沙盒：`/api/draft/sync_all`、`/api/draft/confirm`、`/api/draft/rollback` 已落地。
- 世界推演流式通道：`/api/world/deduce_stream` 已输出 `ack/stage/delta/draft_ready/error/done` 事件，默认超时已提升到 10 分钟。

### 14.2 已完成（前端能力）
- 右侧已从“全局 Diff 固定面板”重构为 Chat-first 流式面板。
- SSE 事件已接入状态机，支持 `stage` 进度行展示与 `delta` 文本流渲染。
- 已支持 `done.answer` 兜底（当无 `delta` 时避免空气泡）。
- 已支持局部 `DiffSnippetCard` 内联挂载与草稿动作按钮（Confirm / Rollback）。
- 运行中保持输入可用：推演期间仅禁用 Run，不冻结主编辑区交互。

### 14.3 已验证结果（联调层）
- Flask <-> Dify <-> 前端链路已打通，SSE 可稳定收到 `ack` 与 `done`，并可在有效写入时收到 `draft_ready`。
- `/api/draft/sync_all` 在具备 GitPython 环境后可成功提交并返回 `commit_id`。
- Dify 工作流工具调用路径已进入可调试状态，关键失败可通过后端日志与 SSE `error` 事件追踪。

### 14.4 当前缺口（影响 MVP 完成度）
- **Ghost Write 风险**：尚未把“当前激活文件”强制锁为唯一写入目标，仍可能出现 Agent 写到其他文件导致当前 Diff 缺失。
- **Confirm 闭环不足**：确认后缺少统一成功提示、状态复位可视化与主线重载反馈，用户感知存在“黑洞”。
- **多文件路由缺口**：前端仍缺文件树与 file_type 隐式路由；后端尚未完成按文件类型动态切换 Dify 工作流配置。

### 14.5 下一阶段里程碑（MVP 收口）
1. 强制写入靶向：将 `active_file` 作为后端硬约束，禁止偏航写入。
2. Confirm/Rollback 闭环：补齐前端事务化反馈（toast + fsm reset + reload）。
3. 引入 File Explorer：支持核心档案/章节切换并透传 `file_type`。
4. 动态工作流路由：`/api/world/deduce_stream` 按 `file_type` 选择对应 Dify App 配置。
5. 验收标准升级：以“Cursor 级交互体验”作为最终验收门槛（流式可见、可裁决、可回溯）。
