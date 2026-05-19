# Dify Incremental Copyable Nodes Pack

## 1. Usage

This document is the copy-paste companion to:

- `novel_git_server/docs/dify_markdown_incremental_workflow_guide.md`

Use it when editing the live Dify workflow UI.

This pack assumes the current canvas shape remains unchanged:

- `INIT_AGENT -> LLM -> 后端文件创立 -> ...`
- `READ_AGENT -> LLM -> 后端文件创立 -> ...`
- `ONLINE_AGENT -> LLM -> 后端文件创立 -> ...`

## 2. What Changes and What Stays

### Keep unchanged

- `用户输入`
- `意图分发器`
- `条件分支`
- full `INIT_AGENT` lane
- right-side `直接回复` nodes

### Replace or update

- `READ_AGENT` system prompt
- `ONLINE_AGENT` system prompt
- READ lane `LLM` prompt and structured output schema
- ONLINE lane `LLM` prompt and structured output schema
- READ lane `后端文件创立` Python code
- ONLINE lane `后端文件创立` Python code

## 3. READ_AGENT Node

### 3.1 Tool Checklist

Keep these tools enabled:

- `get_archive_range`
- `get_cold_archive_range`
- `extract_chapter_highlights`
- `get_file` or `get_core_archive`

Add these tools:

- `get_markdown_outline`
- `get_markdown_section`

### 3.2 Copyable System Prompt

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

## 4. ONLINE_AGENT Node

### 4.1 Tool Checklist

Keep the same section tools as READ lane, plus your existing online retrieval tools.

Must include:

- `get_markdown_outline`
- `get_markdown_section`

### 4.2 Copyable System Prompt

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

## 5. READ/ONLINE LLM Node

Use the same extraction LLM in both READ and ONLINE lanes.

### 5.1 Copyable System Prompt

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

### 5.2 Copyable Structured Output Schema

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

## 6. READ/ONLINE Python Code Node (`后端文件创立`)

Use the same code in both READ and ONLINE lanes.

### 6.1 Recommended Input Mapping

Map these variables into the code node:

- `book_id`: user input `book_name` or resolved `book_id`
- `active_file`: user input `active_file`
- `file_name`: LLM structured output `file_name`
- `op`: LLM structured output `op`
- `section_path`: LLM structured output `section_path`
- `content`: LLM structured output `content`

### 6.2 Copyable Python Code

```python
def main(book_id: str, active_file: str, file_name: str, op: str, section_path, content: str) -> dict:
    import json
    import random
    import re
    import time
    import requests

    BASE_URL = "http://172.19.0.1:8000"
    TIMEOUT = 20
    STATUS_CARD_MAX_LINES = 15

    locator = {"book_id": book_id} if isinstance(book_id, str) and "_" in book_id else {"book_name": book_id}

    ATX_HEADING_RE = re.compile(r"^(#{1,6})[ \\t]+(.+?)[ \\t]*#*[ \\t]*$")
    FENCE_RE = re.compile(r"^[ \\t]*(`{3,}|~{3,})")

    def normalize_section_path(raw):
        if raw is None:
            return []
        if isinstance(raw, list):
            items = raw
        elif isinstance(raw, str):
            text = raw.strip()
            if not text:
                return []
            if text.startswith("["):
                decoded = json.loads(text)
                if not isinstance(decoded, list):
                    raise ValueError("section_path must be a JSON array of strings")
                items = decoded
            else:
                items = [part.strip() for part in text.split(">")]
        else:
            raise ValueError("section_path must be a list or string")

        normalized = []
        for item in items:
            if not isinstance(item, str) or not item.strip():
                raise ValueError("section_path must contain non-empty strings")
            normalized.append(item.strip())
        return normalized

    def clamp_status_card(text: str, max_lines: int = STATUS_CARD_MAX_LINES) -> str:
        if not isinstance(text, str):
            text = "" if text is None else str(text)
        lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
        return "\\n".join(lines[:max_lines])

    def split_lines(markdown: str):
        return markdown.splitlines(keepends=True)

    def detect_frontmatter_end(lines):
        if not lines:
            return 0
        first = lines[0].lstrip("\\ufeff").strip()
        if first != "---":
            return 0
        for idx in range(1, len(lines)):
            marker = lines[idx].strip()
            if marker in {"---", "..."}:
                return idx + 1
        return 0

    def strip_eol(line: str) -> str:
        if line.endswith("\\r\\n"):
            return line[:-2]
        if line.endswith("\\n") or line.endswith("\\r"):
            return line[:-1]
        return line

    def parse_sections(markdown: str):
        lines = split_lines(markdown)
        frontmatter_end = detect_frontmatter_end(lines)
        sections = []
        stack = []
        sibling_counts = {}
        in_fence = False
        fence_char = ""
        fence_len = 0

        def next_count(parent_key, title):
            key = (tuple(parent_key), title)
            sibling_counts[key] = sibling_counts.get(key, 0) + 1
            return sibling_counts[key]

        for line_number in range(frontmatter_end + 1, len(lines) + 1):
            raw_line = strip_eol(lines[line_number - 1])
            fence_match = FENCE_RE.match(raw_line)
            if fence_match:
                marker = fence_match.group(1)
                current_char = marker[0]
                current_len = len(marker)
                if not in_fence:
                    in_fence = True
                    fence_char = current_char
                    fence_len = current_len
                elif current_char == fence_char and current_len >= fence_len:
                    in_fence = False
                    fence_char = ""
                    fence_len = 0
                continue

            if in_fence:
                continue

            match = ATX_HEADING_RE.match(raw_line)
            if not match:
                continue

            level = len(match.group(1))
            title = match.group(2).strip()

            while stack and stack[-1]["level"] >= level:
                stack.pop()

            raw_path = [entry["raw_title"] for entry in stack]
            ordinal = next_count(raw_path, title)
            canonical = title if ordinal == 1 else f"{title} [{ordinal}]"
            section_path = [entry["canonical_title"] for entry in stack] + [canonical]

            sections.append(
                {
                    "title": title,
                    "level": level,
                    "heading_line": line_number,
                    "content_start_line": line_number + 1,
                    "end_line": len(lines),
                    "raw_section_path": raw_path + [title],
                    "section_path": section_path,
                    "ordinal": ordinal,
                }
            )
            stack.append(
                {
                    "level": level,
                    "raw_title": title,
                    "canonical_title": canonical,
                }
            )

        for idx, section in enumerate(sections):
            end_line = len(lines)
            for later in sections[idx + 1 :]:
                if later["level"] <= section["level"]:
                    end_line = later["heading_line"] - 1
                    break
            section["end_line"] = end_line

        return sections

    def find_section(markdown: str, section_path_list):
        sections = parse_sections(markdown)
        raw_matches = [sec for sec in sections if sec["raw_section_path"] == section_path_list]
        if len(raw_matches) > 1:
            raise ValueError("section_path_ambiguous")
        if len(raw_matches) == 1:
            return raw_matches[0]

        canonical_matches = [sec for sec in sections if sec["section_path"] == section_path_list]
        if len(canonical_matches) > 1:
            raise ValueError("section_path_ambiguous")
        if len(canonical_matches) == 1:
            return canonical_matches[0]

        raise ValueError("section_not_found")

    def normalize_patch_block(block: str, prefix_has_newline: bool, suffix_exists: bool) -> str:
        text = block or ""
        if text and not prefix_has_newline and not text.startswith("\\n"):
            text = "\\n" + text
        if text and suffix_exists and not text.endswith("\\n"):
            text = text + "\\n"
        return text

    def apply_patch(markdown: str, op_name: str, path_list, patch_content: str) -> str:
        if op_name == "full_replace":
            return patch_content

        section = find_section(markdown, path_list)
        lines = split_lines(markdown)

        if op_name == "replace_section":
            start_index = section["heading_line"] - 1
            end_index = section["end_line"]
            prefix = lines[:start_index]
            suffix = lines[end_index:]
            replacement = normalize_patch_block(
                patch_content,
                prefix_has_newline=(not prefix or prefix[-1].endswith("\\n")),
                suffix_exists=bool(suffix),
            )
            return "".join(prefix) + replacement + "".join(suffix)

        if op_name == "append_under_section":
            insert_index = section["end_line"]
            prefix = lines[:insert_index]
            suffix = lines[insert_index:]
            appended = normalize_patch_block(
                patch_content,
                prefix_has_newline=(not prefix or prefix[-1].endswith("\\n")),
                suffix_exists=bool(suffix),
            )
            return "".join(prefix) + appended + "".join(suffix)

        raise ValueError("unsupported_op")

    def get_file_payload(target_file: str):
        r = requests.get(
            f"{BASE_URL}/books/get_file",
            params={**locator, "file_name": target_file},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        return data["content"], data["etag"]

    def sync_full_text(target_file: str, full_text: str, base_etag: str):
        payload = {
            **locator,
            "origin": "ai",
            "message": f"incremental patch sync: {target_file}",
            "active_file": target_file,
            "write_scope": "active_file_strict" if target_file == "world_model.md" else "world_core",
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

    if not isinstance(file_name, str) or not file_name.strip():
        return {"result": "ok=false reason=missing_file_name"}
    file_name = file_name.strip()

    if not isinstance(op, str) or not op.strip():
        return {"result": "ok=false reason=missing_op file=%s" % file_name}
    op = op.strip()

    if not isinstance(content, str) or not content.strip():
        return {"result": "ok=false reason=empty_content file=%s" % file_name}
    content = content.strip()

    try:
        path_list = normalize_section_path(section_path)
    except Exception as exc:
        return {"result": f"ok=false reason=invalid_section_path error={str(exc)} file={file_name}"}

    if file_name == "status_card.md":
        op = "full_replace"
        content = clamp_status_card(content, STATUS_CARD_MAX_LINES)

    if file_name not in {"world_model.md", "status_card.md"}:
        return {"result": f"ok=false reason=unsupported_file file={file_name}"}

    if file_name == "world_model.md" and op not in {"replace_section", "append_under_section"}:
        return {"result": f"ok=false reason=unsupported_op file={file_name} op={op}"}

    if file_name == "status_card.md" and op != "full_replace":
        return {"result": f"ok=false reason=invalid_status_card_mode op={op}"}

    try:
        latest_text, latest_etag = get_file_payload(file_name)
    except Exception as exc:
        return {"result": f"ok=false reason=get_file_failed file={file_name} error={str(exc)}"}

    try:
        stitched = apply_patch(latest_text, op, path_list, content)
    except Exception as exc:
        return {"result": f"ok=false reason={str(exc)} file={file_name}"}

    try:
        resp = sync_full_text(file_name, stitched, latest_etag)
    except Exception as exc:
        return {"result": f"ok=false reason=sync_request_failed file={file_name} error={str(exc)}"}

    if resp.status_code == 428:
        time.sleep(random.uniform(0.1, 0.3))
        try:
            latest_text, latest_etag = get_file_payload(file_name)
            stitched = apply_patch(latest_text, op, path_list, content)
            resp = sync_full_text(file_name, stitched, latest_etag)
        except Exception as exc:
            return {"result": f"ok=false reason=etag_retry_failed file={file_name} error={str(exc)}"}

    body = (resp.text or "")[:500].replace("\\n", "\\\\n")
    if resp.status_code == 200:
        try:
            data = resp.json()
            commit_id = data.get("commit_id", "")
            return {"result": f"ok=true file={file_name} op={op} commit_id={commit_id} status=200 body={body}"}
        except Exception:
            return {"result": f"ok=true file={file_name} op={op} status=200 body={body}"}

    return {"result": f"ok=false file={file_name} op={op} status={resp.status_code} body={body}"}
```

### 6.3 Recommended Output Variable

```text
result
```

## 7. Assign Nodes

Prefer to keep them simple.

Recommended behavior:

- read Python node output `result`
- store or forward that string

Do not make assign nodes depend on old full-markdown extraction fields.

## 8. Reply Nodes

Do not change them.

Reply nodes should continue to use upstream Agent natural-language text, not patch JSON or Python result strings.

## 9. Quick Validation Checklist

### 9.1 READ lane `replace_section`

Expected:

- outline is called first
- section is called second
- LLM extracts one patch object
- Python node submits one stitched full-file update

### 9.2 READ lane `append_under_section`

Expected:

- new child block is inserted after the parent's last descendant
- next sibling heading stays outside the new child block

### 9.3 ONLINE lane patch

Expected:

- online retrieval happens
- then outline and section lookup
- then one patch object
- then stitched full-file update

### 9.4 `428` conflict retry

Expected:

- first write fails with `428`
- Python node refetches latest text
- reapplies patch once
- retries once

## 10. Common Bad States

1. Agent still reads whole `world_model.md` first.
2. LLM still outputs `world_model_md` instead of a patch object.
3. Duplicate title path uses raw path instead of canonical path from outline.
4. Python node tries to send `replace_section` directly to Flask.
5. `status_card.md` is forced into section patch mode.
