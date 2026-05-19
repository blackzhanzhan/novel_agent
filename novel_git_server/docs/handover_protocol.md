# LoreGit 交接协议（Frontend + Flask + Dify）

## 1. 文档目的
本协议用于前端、后端、Dify 三方协作时的唯一对接基线，目标是“同一轮 AI 推演的所有改动同生共死、可审计、可回滚”。

本协议同时覆盖：
- 前端 IDE 交互层
- Flask API 层
- Dify Workflow DSL（YAML）层
- 原子开发与提交流程

---

## 2. 产品哲学（不变）
以下原则是硬约束，不因接口重构而改变：

1. 单一真相源（Single Source of Truth）
- 落盘文件与 Git 历史是唯一事实来源。

2. 人类主权（Human-in-the-Loop Finality）
- AI 只能提交草稿，不得直接确权主线。
- 最终确权只允许人类触发。

3. 因果原子性（Unified Causal Sandbox）
- 同一轮推演中的多文件变更必须在同一草稿事务中提交。
- 禁止“世界观在草稿，状态卡在主线”的状态撕裂。

4. 并发安全（Optimistic Lock + Conflict Draft）
- 核心文件写入必须携带 `base_etag`。
- 版本冲突必须返回 409，并保留冲突草稿文件。

---

## 3. 运行时事实基线（v45 / v3.5.1-draft）

### 3.1 主链路接口（当前生效）
- `GET /books/get_file`
- `GET /books/list_hot_files`
- `GET /books/get_archive_range`
- `GET /books/get_cold_archive_range`
- `POST /api/world/deduce_stream`
- `POST /api/draft/sync_all`
- `POST /api/draft/rollback`
- `POST /api/draft/confirm`

### 3.1.1 v46 前端真实连线补丁（必须遵守）
1. 前端推演入口固定为 `POST /api/world/deduce_stream`
- 请求体最低要求：`intent` + `active_file` + `file_type`。
- 建议透传：`conversation_id`（用于 Dify 会话续写）。
- `conversation_id` 必须按文件隔离存储（`conversationByFile[file_name]`），切换文件后禁止沿用上一文件会话。

2. 网络链路固定为 `Frontend -> Flask -> Dify (/chat-messages)`
- 前端不得直连 Dify。
- Dify 的工具回调再进入 Flask 的 `POST /api/draft/sync_all` 完成写入事务。

3. 超时策略
- `world/deduce` 必须使用长超时（建议 `>= 60s`）。
- 普通读取接口使用短超时，避免阻塞 UI。

4. 回滚契约升级
- `POST /api/draft/rollback` 请求体必须包含 `commit_hash`。
- 前端必须从状态机中的 `draft_commit_id` 取值，不得空调用。

### 3.1.2 Published-Only Runtime Truth（当前生效）
1. 后端只调用 Dify **已发布版本**
- Flask 通过 `DIFY_*_API_KEY` + `DIFY_*_BASE_URL` 调用 published `/v1/chat-messages`。
- `/develop` 画布仅用于人工调试，不是后端运行时真相。

2. 本地 `dify_workflows/*.yml` 仅作导出与手工编排参考
- 仓库内 YAML 不直接决定后端实际命中的 workflow 版本。
- 运行时真相是：后端注册表 + Dify 发布态 app/key 配置。

3. 后端保持单入口，内部按注册表切换 workflow
- 继续复用 `POST /api/world/deduce` 与 `POST /api/world/deduce_stream`。
- 路由依据是 `active_file + file_type`，由后端注册表决定命中哪个 published workflow。
- 当前至少存在：
  - `routed_agent = world_model`
  - `routed_agent = style_guide`

### 3.2 兼容接口（可用但非主链路）
- `POST /books/update_file`
- `POST /books/append_file`
- `POST /books/prepend_file`
- `POST /api/world/sync|rollback|confirm`（deprecated 别名）

约束：
- AI 协同主流程必须使用 `api/draft/*`。
- `books/*` 写接口会在当前分支提交，不得作为 AI 主事务写入入口。

### 3.3 核心文件集合（需 ETag）
- `world_model.md`
- `summary.md`
- `status_card.md`
- `style_guide.md`
- `error_archive.md`

---

## 4. 术语与判定规则（无歧义）

1. `book_id` / `book_name` 寻址规则
- 后端规则是：`book_id` 优先，`book_name` 次之。
- 若同时传入且语义冲突，后端返回 `409 BOOK_LOCATOR_CONFLICT`（不再静默兜底）。
- 前端约束：同一请求只传一个字段，避免误寻址。

2. `book_name` 智能解析规则（后端已实现）
- 直命中已存在 `book_id` 目录 -> 直接用该 id。
- 否则按书名生成确定性 id，若目录存在则复用。
- 都不存在则返回新确定性 id（用于初始化）。

3. 草稿分支规则
- 统一分支名：`draft/sandbox`。
- 旧分支 `draft/world_model` 若存在，会在流程中迁移到新分支。

---

## 5. API 职责矩阵

| 接口 | 作用 | 是否影响主线 | 是否需要 ETag | 典型调用方 |
| --- | --- | --- | --- | --- |
| `GET /books/get_file` | 读取核心文件全文 + `etag` | 否 | 返回 `etag` | 前端/编排层 |
| `GET /books/list_hot_files` | 返回热记忆文件树（核心文件+章节） | 否 | 否 | 前端 |
| `GET /books/get_archive_range` | 核心文件按行读取（上限 500 行） | 否 | 返回 `etag` | 前端/编排层 |
| `GET /books/get_cold_archive_range` | 冷档案章节按行读取（上限 100 行） | 否 | 不返回 `etag` | 前端/编排层 |
| `POST /api/world/deduce_stream` | 流式推演入口（SSE，负责可见文本流与暗门 payload 屏蔽） | 否（仅编排，不执行写入） | 读取侧使用 | 前端 |
| `POST /api/draft/sync_all` | 草稿分支多文件原子写入 + 单次提交 | 否（仅草稿） | 核心文件必须 | Flask 编排层 / Dify 工具调用 |
| `POST /api/draft/rollback` | 草稿回滚到指定提交 | 否（仅草稿） | 否 | 人类触发 |
| `POST /api/draft/confirm` | 草稿合并入主线并删除草稿分支 | 是（确权动作） | 否 | 人类触发 |
| `GET /books/git_graph` | 返回完整 commit DAG（含 `parent_ids[]` 与 `refs[]`） | 否 | 否 | 前端 Git 视图 |
| `POST /books/update|append|prepend_file` | 直接文件写入并提交 | 是（当前分支） | 核心文件必须 | 仅兼容场景 |

---

## 6. Dify DSL 审计结论（基于仓库 YAML 实际内容）

审计文件：
- `dify_workflows/世界模型agent.yml`
- `dify_workflows/文风学习agent.yml`
- `dify_workflows/读书存档agent.yml`

Dify 工作台入口（需在本机登录态访问）：
- `http://localhost/app/35799878-737d-4dc4-b9d0-0d961936d345/develop`

### 6.1 世界模型 Agent（可对齐草稿哲学）
关键事实：
- start 节点显式包含：`book_name`、`chapter_index`。
- tools 节点已接入：
  - `get_core_archive`
  - `get_cold_archive_range`
  - `extract_chapter_highlights`
  - `draft_sync_all`
  - `draft_rollback`
  - `draft_confirm`

结论：
- 该 workflow 已具备“草稿沙盒闭环”所需工具集合。

### 6.2 文风学习 Agent（已纳入后端路由）
关键事实：
- 后端运行时已为 `style_guide.md + file_type=style` 预留独立 published workflow 路由。
- 该 workflow 使用独立 agent registry 条目，不再与世界模型 workflow 共用同一 routed_agent 标识。
- 本地 `dify_workflows/文风学习agent.yml` 仍可能保留旧文案，只应视为手工编排参考。

执行原则：
- 运行时以 published workflow + 后端注册表为准。
- 本地 YAML 不是运行时权威。
- 若 YAML 中仍出现 `update_file` 或 `style_card.md`，视为待清理的提示词遗留，而不是后端契约。

### 6.3 读书存档 Agent（导入链路，不是互动写作主链路）
关键事实：
- 包含 code 节点直调 `tools/adaptive_slice`、`books/batch_import`、`books/commit_summary`。

结论：
- 该 workflow 主要用于归档导入/摘要，不应替代 `draft/sandbox` 互动写作事务。

---

## 7. 前端架构与 UI/UX 蓝图（严格执行版）

本章是交由“前端 AI”直接落地的实现蓝图。目标不是限定技术栈，而是限定行为与体验结果，确保任何框架都能复刻 LoreGit 的因果审阅控制台。

### 7.1 技术栈开放原则与功能硬约束

#### 7.1.1 选型开放原则（Open Choice）
前端 AI 可自由选择下列实现方案：
- 框架：React / Vue / Svelte / Solid 或同级方案。
- 状态管理：Redux / Zustand / Pinia / XState / RxJS Store 或同级方案。
- 编辑器：Monaco / CodeMirror 6 / ProseMirror 组合方案。
- UI 层：Tailwind / CSS Modules / Styled Components / UnoCSS 或同级方案。

#### 7.1.2 不可协商的硬约束（Hard MUST）
无论采用何种栈，必须满足以下约束：

1. 全局状态安全（MUST）
- 必须存在全局单例状态容器，统一托管以下关键字段：
  - `book_ref`
  - `active_file`
  - `active_file_type`
  - `hot_files`
  - `mainline_content`
  - `base_etag`
  - `draft_branch`（固定 `draft/sandbox`）
  - `draft_commit_id`
  - `conversation_id`
  - `conversation_by_file`
  - `fsm_state`
- `base_etag` 只能由读取接口成功响应更新，不得由 UI 输入或推理结果覆盖。
- `sync_all` 请求构建时必须从状态容器读取 `base_etag`，禁止从编辑器临时变量读取。
- 路由跳转、刷新、热更新后必须可恢复 `base_etag` 与 `fsm_state`，防止锁状态丢失。

2. 差异对比能力（MUST）
- 审阅态必须渲染“左旧右新”的并排 Diff。
- 差异必须以红/绿高亮展示删除与新增，禁止纯文本整页替换显示。
- Diff 组件须支持：
  - 最小粒度高亮（行级至少，词级优先）
  - 快速滚动同步
  - 可复制片段

3. 视觉基调（MUST）
- 默认深色主题（Dark Mode First）。
- 风格要求：极简、冷峻、工程控制台感，避免娱乐化装饰。
- 状态色语义固定：
  - 冲突：红色
  - 草稿可确认：绿色
  - 推演进行中：蓝青色/中性色

4. 交互原子性（MUST）
- 在 `THINKING` 和 `REVIEW` 状态下禁止并行发起第二次推演。
- 未完成裁决（confirm/rollback）前，不得覆盖当前审阅面板数据。
- `fsm_state != IDLE` 或存在未裁决草稿时，必须禁止切换 `active_file`（导航守卫）。

### 7.2 三段式硬核控制台布局（Layout Blueprint）

#### 7.2.1 左侧正史区（Mainline View）
定位：主线事实视图，承载“当前已确权状态”。

UI 元素：
- 顶部：当前书籍标识（book_name 或 book_id）、激活文件标签、ETag 徽标（只读）。
- 中央：只读编辑视图（`world_model.md` / `status_card.md` 等核心文件）。
- 底部（或顶部工具栏）：命令输入框 `Command Prompt` + 触发按钮 `Run`。

交互规则：
- 默认可滚动、可复制、不可直接改写主线内容。
- 每次进入 `IDLE` 都应显示最近一次成功读取的主线文本与 `base_etag`。
- `Run` 触发后进入 `THINKING`，并锁定命令输入。

#### 7.2.2 右侧沙盒区（Draft Sandbox View）
定位：草稿因果审阅区，展示 AI 推演对主线的“拟变更”。

激活条件：
- 仅当 `sync_all` 成功且 `fsm_state == REVIEW` 时激活。

UI 元素：
- 标题栏：`Draft Sandbox / draft/sandbox` + `commit_id`。
- 主体：Diff 组件
  - 左：`mainline_content`（旧）
  - 右：`draft_content`（新）
- 辅助信息：本轮 `writes` 影响文件列表、更新时间、origin/message。

渲染规则：
- 无草稿时显示空态占位文案（非隐藏空白）。
- 审阅态必须优先渲染差异，不得仅展示 AI 纯文本回复。

#### 7.2.3 底部悬浮裁决盘（Action Bar）
定位：唯一裁决入口，贯彻人类主权。

显示条件：
- 仅在 `REVIEW` 或 `CONFLICT` 状态展示。

按钮定义：
- 红色按钮：`湮灭回滚 (Rollback)` -> 调用 `POST /api/draft/rollback`
- 绿色按钮：`批准确权 (Confirm)` -> 调用 `POST /api/draft/confirm`

交互规则：
- `REVIEW`：两按钮可用。
- `CONFLICT`：`Confirm` 禁用，仅允许刷新主线后重试或回滚。
- 点击 `Confirm/Rollback` 后进入 `draftActionPending` 子加载态，两个按钮同时禁用，直到接口返回。
- 裁决成功后必须清空当前消息挂载的 `diff_preview/changed_files`（或等价字段），避免残留旧草稿视觉痕迹。

#### 7.2.4 Git 视图切换（Workbench Mode）
定位：将 Git DAG 作为“工作台模式”而非三栏内小组件，避免视觉挤压与交互退化。

UI 规则：
- 左侧 `File Explorer` 顶部必须提供 `编辑视图 / Git 视图` Toggle。
- `git_graph` 模式下，隐藏中栏正文与右栏聊天，Git DAG 独占中右部空间。

安全约束：
- 仅允许在 `fsm_state == IDLE` 且无待裁决草稿时切到 `git_graph`。
- 审阅中（`THINKING/REVIEW/CONFLICT`）禁止进入 `git_graph`，避免裁决入口被视觉隐藏。

### 7.3 前端因果律状态机（FSM）

#### 7.3.1 状态枚举（唯一真源）
- `IDLE`：正史态。持有最新主线内容与 `base_etag`，沙盒区为空或占位。
- `THINKING`：推演态。已发送推演请求，输入锁定，等待编排层。
- `REVIEW`：审阅态。草稿已生成，右侧 Diff + 裁决盘激活。
- `CONFLICT`：冲突态。写入遭遇 409，必须刷新取锁后再行动。

#### 7.3.2 事件定义
- `LOAD_MAINLINE_SUCCESS`
- `RUN_INFERENCE`
- `SYNC_ALL_SUCCESS`
- `SYNC_ALL_CONFLICT`
- `CONFIRM_SUCCESS`
- `ROLLBACK_SUCCESS`
- `REFRESH_LOCK_SUCCESS`
- `REQUEST_FAILED`

#### 7.3.3 转移规则（必须严格绑定）
```text
IDLE --RUN_INFERENCE--> THINKING
THINKING --SYNC_ALL_SUCCESS--> REVIEW
THINKING --SYNC_ALL_CONFLICT--> CONFLICT
THINKING --REQUEST_FAILED--> IDLE
REVIEW --CONFIRM_SUCCESS--> IDLE
REVIEW --ROLLBACK_SUCCESS--> IDLE
CONFLICT --REFRESH_LOCK_SUCCESS--> IDLE
CONFLICT --ROLLBACK_SUCCESS--> IDLE
```

#### 7.3.4 渲染绑定规则
- `IDLE`：左侧主线展示；右侧占位；裁决盘隐藏。
- `THINKING`：左侧只读锁定；右侧显示 Loading/进度；裁决盘隐藏。
- `REVIEW`：右侧 Diff 强制显示；裁决盘显示并可点击。
- `CONFLICT`：全局冲突条高亮红色；裁决盘仅保留安全动作；主按钮改为“刷新主线并重新取锁”。

### 7.4 前端数据模型（建议最小字段）
```ts
type FsmState = 'IDLE' | 'THINKING' | 'REVIEW' | 'CONFLICT'

interface CoreSessionState {
  bookRef: { kind: 'book_name' | 'book_id'; value: string }
  activeFile: string
  activeFileType: 'world_core' | 'summary' | 'style' | 'chapter' | 'error_archive'
  hotFiles: Array<{ fileName: string; fileType: 'world_core' | 'summary' | 'style' | 'chapter' | 'error_archive'; label: string }>
  mainlineContent: string
  draftContent: string
  baseEtag: string
  draftBranch: 'draft/sandbox'
  draftCommitId: string | null
  conversationId: string | null
  conversationByFile: Record<string, string>
  writesPreview: Array<{ file_name: string; op: 'update' | 'append' | 'prepend' }>
  draftActionPending: 'none' | 'confirm' | 'rollback'
  uiNotice: { type: 'success' | 'error' | 'info'; message: string; ts: number } | null
  workbenchMode: 'editor' | 'git_graph'
  gitGraphCommits: Array<{ commitId: string; parentIds: string[]; timestamp: string; message: string; refs: string[] }>
  gitGraphLoading: boolean
  gitGraphError: string | null
  selectedGitCommitId: string | null
  fsmState: FsmState
  lastError: { http: number; code: string; message: string } | null
}
```

### 7.5 推演与裁决时序（前端编排规范）

#### 7.5.1 推演（IDLE -> THINKING -> REVIEW/CONFLICT）
1. 调 `GET /books/get_file` 拉取主线内容与 `etag`。
2. 写入全局状态：`mainlineContent`、`baseEtag`、`fsmState=IDLE`。
3. 用户输入命令并触发推演，状态切 `THINKING`。
4. 编排层调用 Dify，产出新文本。
5. 组装 `sync_all`（必须带 `base_etag`）并提交。
6. 若 200：保存 `draftCommitId`、`draftContent`，状态切 `REVIEW`。
7. 若 409：保存冲突信息与 `draft_file`，状态切 `CONFLICT`。

#### 7.5.2 确认（REVIEW -> IDLE）
1. 用户点 `Confirm`。
2. 调 `POST /api/draft/confirm`。
3. 接口返回必须包含 `draft_branch_deleted=true`（可观测性断言），否则前端标记异常。
4. 成功后立即重新调 `GET /books/get_file`，并同步更新 `mainlineContent + baseEtag`（必须刷锁）。
5. 深清扫沙盒状态：清空 `draftContent/draftCommitId`，并清空当前轮次 `diff_preview/changed_files` 挂载。
6. 状态回 `IDLE`，同时弹出成功提示（commit 摘要 + mainline 分支）。

#### 7.5.3 回滚（REVIEW/CONFLICT -> IDLE）
1. 若有明确回退点，用 `commit_hash` 调 `POST /api/draft/rollback`。
2. 成功后刷新 `GET /books/get_file`，并同步更新 `mainlineContent + baseEtag`（必须刷锁）。
3. 深清扫沙盒状态：清空 `draftContent/draftCommitId`，并清空当前轮次 `diff_preview/changed_files` 挂载。
4. 状态回 `IDLE`，弹出回滚完成提示。

### 7.6 命令面板（Command Prompt）协议
命令面板是前端向编排层发起推演的唯一输入入口，最小字段：
- `instruction`: 用户自然语言命令
- `active_file`: 当前语义焦点文件
- `file_type`: 与 `active_file` 强一致（不一致必须在前端拦截）
- `book_ref`: 单一寻址字段（book_name 或 book_id）
- `intent_mode`: 可选（world/status/style）

硬规则：
- 不允许前端直接将命令文本映射为 Git 操作。
- 所有写入动作必须经编排层转换为 `writes[]` 后再调用 `sync_all`。

### 7.7 Diff 审阅体验最低验收标准
必须满足以下 UX 验收项：
- 1000+ 行文本 Diff 仍能流畅滚动。
- 行内新增/删除可一眼识别（红绿高亮）。
- 可切换“仅显示变更块 / 显示全文”。
- `REVIEW` 状态下始终能看到本轮提交 `commit_id`。
- 冲突态明确显示“当前锁已过期，请刷新主线后重试”。

### 7.8 前端 AI 交付物要求（对执行代理）
前端 AI 每次交付必须附带：
1. 页面状态机图（或等价转移表）。
2. API 调用封装层（含 409/428 处理分支）。
3. 全局状态定义与不可变更新策略。
4. 至少 3 条关键流程测试：
   - 正常推演 -> 审阅 -> 确认
   - 推演冲突 -> 刷新取锁 -> 重试
   - 审阅态回滚 -> 回到 IDLE

---

## 8. 错误码到前端动作映射（必须执行）

| HTTP | code | 含义 | 前端动作 |
| --- | --- | --- | --- |
| 400 | `INVALID_PAYLOAD` / `MISSING_FIELD` | 请求格式错误 | 阻止重试，提示修正参数 |
| 409 | `WRITE_CONFLICT` | ETag 冲突 | 弹出冲突提示；引导用户刷新并选择重试/人工合并；展示 `draft_file` |
| 428 | `PRECONDITION_REQUIRED` | 核心文件缺少 `base_etag` | 强制先读 `get_file` 重新取锁 |
| 500 | `GIT_*` / `DRAFT_*` | 后端事务失败 | 显示失败并允许人工重试，不自动死循环重试 |

补充：
- `sync_all` 无改动时会返回 success + no-change message，前端应视为幂等成功。

---

## 9. 冷档案读取约束（前端必须理解）

接口：`GET /books/get_cold_archive_range`

规则：
- 仅章节类文件可读（`chapter_*.md` 或 `^\d+.*\.md$` 或可提取章节数字）。
- 禁止读取核心文件：`summary.md`、`world_model.md`、`status_card.md`。
- 若请求行数超过 100，后端自动截断并在 `message` 给出说明。
- 响应包含 `real_file_name`，前端应以此更新 UI 显示。

可命中同一章的输入示例：
- `95`
- `95.md`
- `chapter95`
- `095`

---

## 10. Dify 与前端的无歧义边界

### 10.1 前端对 Dify 的约束
- 前端不得自行拼装 Git 语义（分支、commit、回滚）。
- 前端只提交“用户意图 + 当前文件上下文 + book_ref”。

### 10.2 编排层对 Dify 的约束
- 编排层必须在写入前取最新 ETag。
- 编排层必须把多文件改动合并成一个 `sync_all` 请求。
- 编排层必须处理 409/428，不得把错误吞掉。

### 10.3 关于仓库内 `call_dify_api` 的现状
- `POST /api/world/sync` 中的 `call_dify_api` 目前是占位实现（可用 `mock_ai_markdown`）。
- 生产链路应优先使用 Dify workflow + `api/draft/*` 工具调用。

---

## 11. 常见歧义与标准答案

1. “`book_name` 和 `book_id` 要不要都传？”
- 不要。只传一个。
- 同时传且冲突时，后端按 `book_id`。

2. “可以让 AI 直接调 `update_file` 吗？”
- 不可以作为主流程。
- AI 主流程必须走 `draft_sync_all`。

3. “Dify 提示词里写了 `update_file`，怎么办？”
- 以 tools 节点为准，不以文案为准。
- 需要在 YAML 中逐步清理旧文案，避免模型误导。

4. “回滚后为什么只返回 world_model content？”
- 当前 `/api/draft/rollback` 响应结构就是如此设计。
- 多文件回显需要前端后续再读对应文件。

---

## 12. 前端开发验收清单（可操作）

1. 能完成 `get_file -> sync_all -> confirm` 全链路。
2. 能完成 `get_file -> sync_all -> rollback` 全链路。
3. 对 409 冲突可展示 `draft_file` 并引导二次处理。
4. 前端不会在 AI 模式下调用 `books/update|append|prepend_file`。
5. 支持 `book_name` 单字段寻址并稳定运行。
6. 读取冷档案时正确展示 `real_file_name` 与截断提示。
7. 能解释并落地“同轮多文件必须单次 `writes` 提交”的规则。

---

## 13. 变更治理规则

1. 任何接口协议改动，必须同步更新：
- `docs/openapi_v3_5_1_draft_min.json`
- `docs/api.md`
- 本文件 `docs/handover_protocol.md`

2. 任何 Dify 工作流改动，必须同步提交：
- 对应 `dify_workflows/*.yml`
- 影响说明（写入 `docs/progress_log.md`）

3. 任何“文案与工具不一致”问题，优先修工具契约，再修提示词文案。

---

最后更新：2026-02-25（UTC）
对应阶段：v52_front_git_workspace_and_dag_visualization
