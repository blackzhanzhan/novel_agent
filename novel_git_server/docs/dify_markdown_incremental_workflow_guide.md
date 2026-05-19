# Dify Markdown Incremental Workflow Guide

## 1. Scope

This guide consolidates the Dify-side change plan for migrating Markdown updates from full-file rewrites to heading-indexed reads plus section-level draft writes.

The guide is written for the current live Dify workflow canvas with these lanes:

- `INIT_AGENT -> LLM -> 后端文件创立 -> 赋值INIT_AGENT -> 赋值INIT_AGENT -> 直接回复`
- `READ_AGENT -> LLM -> 后端文件创立 -> 赋值READ_AGENT -> 赋值READ_AGENT -> 直接回复`
- `ONLINE_AGENT -> LLM -> 后端文件创立 -> 赋值ONLINE_AGENT -> 赋值ONLINE_AGENT -> 直接回复`

## 2. Non-Goals

- Do not modify the overall workflow topology.
- Do not change the frontend response nodes.
- Do not patch local `dify_workflows/世界模型agent.yml` as the source of truth; real edits happen in Dify UI.

## 3. Current Backend Capabilities Already Available

These backend read APIs now exist and are the foundation for Dify incremental patching:

- `GET /books/get_markdown_outline`
- `GET /books/get_markdown_section`
- `POST /api/draft/sync_markdown_sections`

Rules already enforced by backend and local helper logic:

- only ATX headings (`#` to `######`) are indexed in v1
- YAML frontmatter at file start is skipped
- fenced code blocks are ignored during heading scan
- duplicate sibling headings are disambiguated with canonical `section_path`, for example `Rule [2]`
- empty sections are valid and return success with `content_length: 0`
- `append_under_section` must insert after the target parent section's last descendant

## 4. High-Level Migration Strategy

### Keep `INIT_AGENT` unchanged

Initialization is still full-file generation:

- `world_model.md`: full create/update
- `status_card.md`: full create/update

Do not force section patches into init flow.

### Upgrade `READ_AGENT` and `ONLINE_AGENT` first

For these two lanes:

1. Agent reads facts and chooses a target heading path.
2. LLM extracts a strict section write object instead of a whole markdown document.
3. Python code node submits section writes directly to `/api/draft/sync_markdown_sections`.

### Keep `status_card.md` on full replace during migration

`status_card.md` remains a short telegraph card with strict line limits.
Do not put it into heading-tree incremental patch flow in v1.

## 5. Target Runtime Behavior by Lane

### INIT lane

Keep current behavior:

- Agent may read summary and archive context
- LLM extracts `world_model_md` and `status_card_md`
- Python node fetches ETag and submits full-file `update`

### READ lane

New target behavior:

- When `active_file` is one of the Markdown knowledge files (`world_model.md`, `summary.md`, `brainstorm.md`, `master_outline.md`, `arc_outline.md`, `chapter_outline.md`):
  - call `get_markdown_outline`
  - choose canonical `section_path`
  - call `get_markdown_section`
  - optionally fetch supporting evidence windows
  - produce a minimal section write object:
    - `replace_section`
    - `append_under_section`
- When `active_file == status_card.md`:
  - keep legacy full replace mode

### ONLINE lane

Same as READ lane, but with online fact retrieval added before heading selection.

## 6. Node-by-Node Operation Manual

### 6.1 User Input

Do not change this node.

Expected inputs remain:

- `book_name` or `book_id`
- `active_file`

### 6.2 Intent Router

Do not change this node.

The existing branching between init/read/online remains valid.

### 6.3 Condition Branch

Do not change this node.

### 6.4 INIT_AGENT

Do not change this node in v1.

Reason:

- init flow is still full generation
- heading-indexed incremental patching is not needed for cold start

### 6.5 READ_AGENT

This node must change.

#### New mission

Transform it from:

- full-file merger / rewriter

into:

- heading-tree locator
- local evidence retriever
- minimal patch planner

#### Required tool set

Keep existing tools that are still relevant:

- `get_archive_range`
- `get_cold_archive_range`
- `extract_chapter_highlights`
- `get_file` or `get_core_archive`

Add these tools:

- `get_markdown_outline`
- `get_markdown_section`

#### Required tool call order for `world_model.md`

1. `get_markdown_outline`
2. `get_markdown_section`
3. only if necessary, fetch supporting evidence from summary/chapters

#### Hard rule

When `active_file == world_model.md`, do not read the entire `world_model.md` first.

### 6.6 READ lane LLM

This node must change.

#### New mission
Extract one strict section write object from the upstream agent text.

#### Recommended output schema

Use a single write object in v1, then wrap it into `writes[]` when calling Flask.

Fields:

- `file_name`: string
- `op`: string
- `section_path`: string array
- `content`: string
- `base_etag`: string

Allowed values:

- if `file_name` is a Markdown knowledge file:
  - `op = "replace_section"` or `op = "append_under_section"`
- if `file_name == "status_card.md"`:
  - `op = "full_replace"`

### 6.7 READ lane Python node (`后端文件创立`)

This node must change.

#### New mission

It becomes a section-write executor instead of a full-file stitcher.

#### Responsibilities

1. receive the extracted section write object
2. call `POST /api/draft/sync_markdown_sections`
3. if `409 WRITE_CONFLICT` occurs:
   - refetch outline/section and latest etag
   - regenerate the section write
   - retry once

#### Supported operations in v1

- `replace_section`
- `append_under_section`
- `full_replace` (status card only, migration fallback)

#### Hard rule

Do not send `replace_section` or `append_under_section` directly to Flask.
The Python node must always translate the patch into a final full-file `update`.

### 6.8 ONLINE_AGENT

This node changes the same way as `READ_AGENT`, but it must prioritize external fact retrieval before selecting target section.

#### Required behavior

- fetch external/online facts
- if `active_file == world_model.md`:
  - call `get_markdown_outline`
  - choose canonical `section_path`
  - call `get_markdown_section`
  - plan a minimal patch
- if `active_file != world_model.md`:
  - keep legacy whole-file behavior

### 6.9 ONLINE lane LLM

Reuse the same extraction schema as READ lane LLM.

Do not maintain two incompatible schemas.

### 6.10 ONLINE lane Python node (`后端文件创立`)

Reuse the same logic as READ lane Python node.

Best practice:

- copy the verified READ Python node
- only change variable mappings if necessary

### 6.11 Assign nodes (`赋值READ_AGENT`, `赋值ONLINE_AGENT`)

Prefer not to change these unless they depend on old structured fields.

Recommended simplification:

- Python node outputs only a single string `result`
- assign nodes store or forward this string

### 6.12 Reply nodes (`直接回复`)

Do not change these.

Continue to display agent natural-language output, not structured patch JSON.

## 7. Recommended Prompt for READ_AGENT

```text
# Role: Read Agent（标题树增量检索与局部补丁规划节点）

你的任务是：根据用户意图，在存储库中执行“多级检索协议”，精确获取客观事实，并仅为当前激活文件 `{{#用户输入.active_file#}}` 规划一次最小必要的增量修改。

---

## 核心目标
你不是整篇重写器，而是“标题树定位器 + 局部补丁规划器”。

你的职责分为两种模式：

### 模式 A：目标文件是 `world_model.md`
你必须优先采用“标题树增量修改模式”：
1. 先调用 `get_markdown_outline` 获取标题目录树。
2. 从目录树中选择最合适的目标 `section_path`。
3. 再调用 `get_markdown_section` 读取该标题下的局部正文。
4. 如有必要，再补充调用 `get_archive_range` / `get_cold_archive_range` / `extract_chapter_highlights` 获取事实依据。
5. 只输出一条最小补丁规划，不得整篇重写 world_model。

### 模式 B：目标文件不是 `world_model.md`
保持原有全量合并思路：
- 对 `status_card.md` 仍然允许输出完整最新内容。
- 不得强行套用标题树补丁逻辑。

---

## 核心铁律
1. **绝对禁止无脑整篇读取 `world_model.md`**。当目标是 `world_model.md` 时，必须先读目录树，再读目标区块。
2. **靶向锁死**：你只能更新 `{{#用户输入.active_file#}}`。
3. **客观优先**：一切新增设定都必须可回溯到 summary / chapter / 现实资料，不得凭空捏造。
4. **最小修改**：若只需改一个标题区块，就只规划一个区块补丁，禁止顺手扩写其它标题。
5. **重复标题去歧义**：如果目录树里存在同名标题，必须使用目录树返回的 canonical `section_path`，例如 `Rule [2]`，禁止自行猜测。
6. **严禁调用写工具**：你不负责真正写入，禁止直接调用写入类工具。
7. **如果目标区块正文为空，也视为合法区块**；不得把“空内容”误判为“读取失败”。
8. **若证据不足，则停止扩写**，只能做保守补充或明确说明无法确证。

---

## 多级检索协议（必须按顺序执行）

### 当 `active_file == world_model.md` 时
#### 第一级：目录树定位
调用 `get_markdown_outline(file_name=world_model.md)`，找到最接近本次任务目标的标题路径。

#### 第二级：局部正文提取
调用 `get_markdown_section(file_name=world_model.md, section_path=...)`，读取目标标题下的正文。

#### 第三级：事实补强
若局部正文不足以支撑修改，再补充调用：
- `get_archive_range` 读取 `summary.md` 局部
- `extract_chapter_highlights`
- `get_cold_archive_range`

#### 第四级：补丁规划
基于当前区块正文和事实依据，规划以下两类操作之一：
- `replace_section`
- `append_under_section`

### 当 `active_file != world_model.md` 时
按原有方式读取当前文件内容并进行增量合并，不必使用标题树接口。

---

## 输出协议（最高优先级）
你必须输出两阶段内容：

### 第一阶段：汇报与思考
用自然语言向用户汇报：
- 你锁定了哪个标题路径
- 你依据了哪些 summary / chapter / online 事实
- 为什么只修改这一块
- 你选择的是 `replace_section` 还是 `append_under_section`

这一部分会直接展示给用户。

### 第二阶段：隐藏补丁草案
汇报结束后，另起一行，输出且仅输出一次精准分隔符：
[JSON_PAYLOAD_START]

分隔符后，输出一个严格合法的 JSON 对象，禁止使用 Markdown 代码块包裹。

---

## JSON 草案格式

### 情况 A：目标是 `world_model.md`
你必须输出且仅输出一个最小补丁对象：

{
  "file_name": "world_model.md",
  "op": "replace_section",
  "section_path": ["一级标题", "二级标题", "三级标题"],
  "content": "完整的新标题块 Markdown"
}

或：

{
  "file_name": "world_model.md",
  "op": "append_under_section",
  "section_path": ["一级标题", "二级标题"],
  "content": "准备插入到该标题下的新 Markdown 区块"
}

约束：
1. `file_name` 必须是 `world_model.md`
2. `op` 只能是 `replace_section` 或 `append_under_section`
3. `section_path` 必须直接复用目录树中返回的 canonical 路径
4. `content` 必须是完整合法的 Markdown 片段
5. 如果选择 `replace_section`，`content` 的首行必须就是该目标标题本身
6. 如果选择 `append_under_section`，`content` 必须是完整新增子区块，不得只是半句正文

### 情况 B：目标是 `status_card.md`
你可以继续输出完整文件内容对象：

{
  "file_name": "status_card.md",
  "op": "full_replace",
  "content": "完整的最新状态卡 Markdown"
}

---

## 终止规则
1. `section_path` 找不到时，不得伪造。
2. 证据不足时，不得强行新增硬设定。
3. `</file>` / XML / 旧版 `<file name=...>` 协议全部废弃，不得输出。
4. `[JSON_PAYLOAD_START]` 之后只能是 JSON，不得再混入任何解释性文本。
5. 输出 JSON 后立刻停止，不要再写总结语。

---

## 风格要求
- 汇报阶段可以清晰解释，但必须简洁、可审计。
- 补丁必须保守、精确，不做“顺手优化”。
- 你是外科医生，不是重写引擎。
```

## 8. Recommended Prompt for ONLINE_AGENT

```text
# Role: Online Agent（在线事实映射与标题树局部补丁规划节点）

你的任务是：当用户要求引入现实资料、在线事实或外部映射时，先检索真实信息，再把这些信息以“最小必要修改”的方式映射进当前激活文件 `{{#用户输入.active_file#}}`。

---

## 核心目标
你不是整篇重写器，而是“在线事实侦察兵 + 标题树补丁规划器”。

---

## 模式划分
### 模式 A：目标文件是 `world_model.md`
必须优先使用标题树增量修改模式：
1. 调用在线检索工具获取真实信息。
2. 调用 `get_markdown_outline` 获取当前 world_model 的标题目录树。
3. 锁定最适合承载这条新事实的 `section_path`。
4. 调用 `get_markdown_section` 读取该区块正文。
5. 规划一次最小补丁：
   - `replace_section`
   - `append_under_section`

### 模式 B：目标文件不是 `world_model.md`
维持原有保守模式，允许整文件输出。

---

## 核心铁律
1. **现实优先**：必须优先检索真实信息，不得凭空捏造。
2. **标题树优先**：对 `world_model.md`，必须先读目录树，再读局部区块，禁止直接整篇读取并整篇重写。
3. **最小变更**：只改最适合承载事实的一个标题块。
4. **靶向锁死**：你只能更新 `{{#用户输入.active_file#}}`。
5. **重复标题去歧义**：必须使用目录树返回的 canonical `section_path`。
6. **严禁调用写工具**：你只负责规划补丁，不负责最终提交。
7. **证据不足时必须收缩**：宁可少写，也不能瞎写。

---

## 工作步骤
1. 先获取在线真实信息。
2. 若目标是 `world_model.md`，调用 `get_markdown_outline`。
3. 选中最匹配的 section。
4. 调用 `get_markdown_section`。
5. 把“在线事实”映射成局部补丁，不做整篇世界观重写。

---

## 输出协议
### 第一阶段：汇报与思考
向用户说明：
- 你引用了哪些在线事实
- 这些事实应当落在哪个标题路径下
- 为什么选择 `replace_section` 或 `append_under_section`

### 第二阶段：隐藏补丁 JSON
另起一行输出：
[JSON_PAYLOAD_START]

分隔符后只能输出 JSON，不得有任何解释文字。

---

## JSON 格式
### 当目标是 `world_model.md`
{
  "file_name": "world_model.md",
  "op": "replace_section",
  "section_path": ["一级标题", "二级标题", "三级标题"],
  "content": "新的完整 Markdown 区块"
}

或：

{
  "file_name": "world_model.md",
  "op": "append_under_section",
  "section_path": ["一级标题", "二级标题"],
  "content": "新的 Markdown 子区块"
}

### 当目标是 `status_card.md`
{
  "file_name": "status_card.md",
  "op": "full_replace",
  "content": "完整状态卡内容"
}

---

## 终止规则
1. `[JSON_PAYLOAD_START]` 之后只能是 JSON。
2. 禁止输出 XML / `<file>`。
3. 禁止输出多个补丁对象。
4. 禁止整篇重写 `world_model.md`，除非系统明确要求重建。
5. JSON 输出完毕后立即停止。
```

## 9. Recommended Prompt for READ/ONLINE Extraction LLM

```text
# 任务
你是一个精准的数据脱水与补丁抽取引擎。请从上游 Agent 输出的混杂文本中，提取出唯一合法的结构化补丁对象。

---

## 输入特征
上游文本包含两部分：
1. 给用户看的自然语言分析
2. 在 `[JSON_PAYLOAD_START]` 之后的隐藏 JSON 草案

你的任务不是理解业务，而是无情地抽取并净化这个隐藏 JSON。

---

## 抽取规则
1. 找到 `[JSON_PAYLOAD_START]`。
2. 仅提取该分隔符之后的 JSON 对象。
3. 严禁把分隔符前的自然语言解释混入结果。
4. 如果存在多余文本、尾部总结、注释、Markdown 代码块，必须全部剥离。
5. 输出必须严格符合 schema，不得附加任何额外字段。

---

## 字段规范
### 当补丁目标是 `world_model.md`
必须输出：
- `file_name`
- `op`
- `section_path`
- `content`

约束：
1. `file_name` 必须是 `world_model.md`
2. `op` 只能是：
   - `replace_section`
   - `append_under_section`
3. `section_path` 必须是字符串数组，且每个元素非空
4. `content` 必须为完整 Markdown 片段，不得为空

### 当目标是 `status_card.md`
允许输出：
- `file_name`
- `op`
- `content`

其中：
- `file_name` 必须是 `status_card.md`
- `op` 必须是 `full_replace`
- `content` 必须是完整状态卡 Markdown

---

## 绝对禁止
1. 禁止输出 Markdown 代码块
2. 禁止输出多余说明文字
3. 禁止输出多个对象
4. 禁止把旧版 XML `<file>` 协议混入结果
5. 禁止擅自修正业务语义；你只负责净化与抽取

---

## 物理熔断
若 `file_name == status_card.md`：
- 你必须强制净化为极简列表
- 建议最多 15 行
- 删除任何过渡句、总结句、问候句

若无法提取合法 JSON：
- 严格按 schema 输出空字段或失败占位，不要擅自发明结构
```

## 10. Recommended Structured Output Schema for READ/ONLINE LLM

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "file_name": {
      "type": "string",
      "description": "目标文件名。world_model.md 或 status_card.md"
    },
    "op": {
      "type": "string",
      "description": "当 file_name=world_model.md 时，只能是 replace_section 或 append_under_section；当 file_name=status_card.md 时，只能是 full_replace"
    },
    "section_path": {
      "type": "array",
      "description": "仅在 world_model patch 模式下使用的 canonical 标题路径",
      "items": {
        "type": "string"
      }
    },
    "content": {
      "type": "string",
      "description": "补丁内容或完整文件内容"
    }
  },
  "required": ["file_name", "op", "content"]
}
```

Notes:

- `section_path` should not be required because `status_card.md` does not use it
- do not use nested arrays or multiple patch objects in v1

## 11. Recommended Variable Mapping

### READ/ONLINE LLM input

- upstream context: corresponding agent `.text`

### READ/ONLINE Python node inputs

- `book_id`: from user input
- `active_file`: from user input
- `file_name`: from LLM structured output
- `op`: from LLM structured output
- `section_path`: from LLM structured output
- `content`: from LLM structured output

### Python node output

- `result`: single string

### Assign nodes

Prefer to consume only `result`, not old markdown body fields.

## 12. Python Node Execution Contract

### Core logic

The Python node must do the following:

1. detect whether the payload is:
   - `replace_section`
   - `append_under_section`
   - `full_replace`
2. call `GET /books/get_file`
3. if section patch mode:
   - fetch latest full text
   - apply patch locally
4. call `POST /api/draft/sync_all` with final full markdown and `op: "update"`
5. if response is `428`:
   - refetch latest full text
   - replay the same patch on latest content
   - retry once

### Hard patch semantics

The Python node implementation must obey the same rules as backend docs:

- skip YAML frontmatter before heading scan
- ignore headings inside fenced code blocks
- use canonical `section_path` for duplicates
- `append_under_section` inserts after the parent's last descendant

### Hard prohibition

Do not submit `replace_section` or `append_under_section` directly to Flask write API.

Flask transactional write remains:

- `file_name`
- `op: "update"`
- `content: <stitched full markdown>`
- `base_etag`

## 13. Suggested Python Node Skeleton

```python
def main(book_id, active_file, file_name, op, section_path, content):
    import random
    import time
    import requests

    BASE_URL = "http://172.19.0.1:8000"
    TIMEOUT = 20

    locator = {"book_id": book_id} if isinstance(book_id, str) and "_" in book_id else {"book_name": book_id}

    def get_file_payload(target_file):
        r = requests.get(
            f"{BASE_URL}/books/get_file",
            params={**locator, "file_name": target_file},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        return data["content"], data["etag"]

    def sync_full_text(target_file, full_text, base_etag):
        payload = {
            **locator,
            "origin": "ai",
            "message": f"incremental patch sync: {target_file}",
            "active_file": target_file,
            "write_scope": "active_file_strict" if target_file != "status_card.md" else "world_core",
            "writes": [
                {
                    "file_name": target_file,
                    "op": "update",
                    "content": full_text,
                    "base_etag": base_etag,
                }
            ],
        }
        return requests.post(
            f"{BASE_URL}/api/draft/sync_all",
            json=payload,
            timeout=TIMEOUT,
        )

    def apply_patch(full_text, file_name, op, section_path, content):
        # Implement local heading-based stitching here.
        # Must obey frontmatter skip / fenced code ignore / canonical path / append boundary rules.
        return new_full_text

    if file_name == "status_card.md" or op == "full_replace":
        _, latest_etag = get_file_payload(file_name)
        resp = sync_full_text(file_name, content, latest_etag)
        return {"result": f"ok={resp.status_code == 200} status={resp.status_code} body={(resp.text or '')[:300]}"}

    latest_text, latest_etag = get_file_payload(file_name)
    stitched = apply_patch(latest_text, file_name, op, section_path, content)
    resp = sync_full_text(file_name, stitched, latest_etag)

    if resp.status_code == 428:
        time.sleep(random.uniform(0.1, 0.3))
        latest_text, latest_etag = get_file_payload(file_name)
        stitched = apply_patch(latest_text, file_name, op, section_path, content)
        resp = sync_full_text(file_name, stitched, latest_etag)

    body = (resp.text or "")[:500].replace("\n", "\\n")
    return {"result": f"ok={resp.status_code == 200} status={resp.status_code} body={body}"}
```

## 14. Recommended Result String Format

Have the Python node return a single string `result`, for example:

Success:

```text
ok=true file=world_model.md op=replace_section commit_id=abc123
```

Section not found:

```text
ok=false reason=section_not_found file=world_model.md
```

Ambiguous path:

```text
ok=false reason=section_path_ambiguous file=world_model.md
```

Conflict after retry:

```text
ok=false reason=etag_conflict_after_retry file=world_model.md
```

This keeps assign nodes and reply lane stable.

## 15. Validation Sequence

Run tests in this order after Dify UI edits:

### Test 1: READ lane `replace_section`

Input:

- a task that clearly targets an existing `world_model.md` section

Expected:

- agent calls outline first
- then section
- LLM extracts `replace_section`
- Python node stitches and commits
- only target section changes

### Test 2: READ lane `append_under_section`

Input:

- a task that adds a new child heading under an existing parent section

Expected:

- inserted after the parent's last descendant
- next sibling heading remains outside the new child section

### Test 3: ONLINE lane `replace_section`

Input:

- a task that imports external reality or online facts into `world_model.md`

Expected:

- online fact retrieval happens first
- outline and target section are read
- only one section is updated

### Test 4: Conflict retry

Procedure:

- modify the same target file manually while Dify is preparing patch submission

Expected:

- first write hits `428`
- Python node refetches latest content
- reapplies patch
- retries exactly once

## 16. Common Failure Modes

1. The agent still reads the whole `world_model.md` before outline lookup.
2. The extraction LLM still outputs full markdown instead of a patch object.
3. Raw duplicate title path is used instead of canonical `section_path`.
4. Python node tries to send section patch directly to Flask.
5. `status_card.md` is mistakenly forced into heading-tree patch mode.

## 17. Recommended Rollout Order

1. update `READ_AGENT`
2. update READ lane extraction `LLM`
3. update READ lane Python node
4. verify `replace_section`
5. verify `append_under_section`
6. verify `428` replay
7. copy verified LLM + Python behavior to ONLINE lane
8. finally adjust ONLINE_AGENT prompt for external fact emphasis
