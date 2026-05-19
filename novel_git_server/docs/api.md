# Project Chronos API v3.1

Updated: 2026-02-20 (runtime-synced with `app.py` + `agents/*.py`)
lunch：
cd /home/zhouzhanyue/文档/novel_agent/novel_git_server
PYTHONPATH=.venv/Lib/site-packages python3 app.py

## Global Contract
- Content-Type: `application/json` for all POST APIs.
- Response encoding: UTF-8 (`ensure_ascii = False`).
- Book addressing: `book_id` OR `book_name`.
  - Resolution priority: explicit `book_id` first.
  - If `book_id` is absent and `book_name` exists, backend generates deterministic id and locates/creates storage.
- Error envelope:

```json
{
  "status": "error",
  "code": "MISSING_FIELD | INVALID_PAYLOAD | PRECONDITION_REQUIRED | WRITE_CONFLICT | GIT_COMMIT_FAILED | ACTION_MISMATCH ...",
  "message": "human readable message",
  "warning": "optional, appears on partial rollback failure",
  "draft_file": "optional, appears on conflict draft fallback"
}
```

## Route Index (Runtime)
- `GET /health`
- `GET /books/ping`
- `POST /books/init`
- `GET /books/search`
- `POST /books/add_chapter`
- `POST /books/batch_import`
- `POST /commit_world_state`
- `POST /books/commit_summary`
- `POST /api/world/sync`
- `POST /api/world/rollback`
- `POST /api/world/confirm`
- `POST /api/world/deduce`
- `POST /api/draft/sync_markdown_sections`
- `POST /api/draft/append_markdown_section`
- `POST /api/draft/replace_markdown_section`
- `POST /api/draft/sync_all`
- `POST /api/draft/rollback`
- `POST /api/draft/confirm`
- `GET /checkout`
- `GET /books/history`
- `POST /tools/read_chapter`
- `POST /tools/search_chapter_index`
- `POST /tools/adaptive_slice`
- `POST /tools/validate_chapter_lengths`
- `POST /tools/validate_domain_facts`
- `POST /tools/generate_style_diagnostics`
- `GET /books/get_file`
- `GET /books/get_archive_range`
- `GET /books/get_cold_archive_range`
- `POST /books/prepend_file`
- `POST /books/append_file`
- `POST /books/update_file`

Legacy routes (`/save_outline`, `/outlines`, `/commit`, `/history`, `/world_model`) are intentionally not registered.

## 1) Health & Base

### GET /health
Success example:

```json
{
  "status": "ok",
  "service": "chronos-v3",
  "database_json": "retired"
}
```

### GET /books/ping?book_id=... OR /books/ping?book_name=...
Purpose: resolve addressing + ensure book layout.

Success example:

```json
{
  "status": "success",
  "book_id": "donk_93845573",
  "book_dir": "C:/.../storage/donk_93845573"
}
```

## 2) Library

### POST /books/init
Body:

```json
{
  "book_name": "重生CS",
  "book_id": "optional_explicit_id"
}
```

Behavior:
- `book_name` is required.
- If `book_id` not provided, deterministic id is generated from `book_name`.
- Initializes/repairs book folder and metadata.

Success example:

```json
{
  "status": "success",
  "book_id": "zhongshengcs_xxxxxxxx",
  "book_name": "重生CS",
  "book_dir": "C:/.../storage/zhongshengcs_xxxxxxxx",
  "metadata_path": "C:/.../storage/zhongshengcs_xxxxxxxx/metadata.json"
}
```

### GET /books/search?query=...
Behavior:
- Fuzzy search by `book_id` and `metadata.book_name`.
- Skips broken folders instead of failing whole search.

Success example:

```json
{
  "status": "success",
  "query": "donk",
  "total": 1,
  "matches": [
    {
      "book_id": "donk_93845573",
      "book_name": "donk",
      "score": 1.0
    }
  ]
}
```

## 3) Chapter Ingestion

### POST /books/add_chapter
Body:

```json
{
  "book_id": "optional",
  "book_name": "optional",
  "chapter_index": 1,
  "title": "optional",
  "content": "chapter markdown text"
}
```

Success example:

```json
{
  "status": "success",
  "book_id": "donk_93845573",
  "chapter_index": 1,
  "title": "第1章 重生与天命",
  "file_path": "C:/.../chapters/0001_第1章_重生与天命.md"
}
```

### POST /books/batch_import
Body:

```json
{
  "book_id": "optional",
  "book_name": "optional",
  "content": "string_or_list"
}
```

Behavior:
- Accepts `content` as `string` or `list`.
- Split delimiter: `|||CHAPTER_START|||`.
- Uses next available chapter index and appends.
- Writes all imported chapters first, then archives the whole batch as one git commit in the target book repo.
- Success response includes `commit_id`.

Success example:

```json
{
  "status": "success",
  "saved_count": 156,
  "total_parsed": 156,
  "book_id": "donk_93845573",
  "commit_id": "abcdef1234..."
}
```

## 4) Core State Commits

### POST /commit_world_state
Body:

```json
{
  "book_id": "optional",
  "book_name": "optional",
  "content": "# world model markdown",
  "message": "optional commit message"
}
```

Behavior:
- Full write to `world_model.md`.
- `git add .` + `git commit`.
- `nothing to commit` treated as success.

Success example:

```json
{
  "status": "success",
  "book_id": "donk_93845573",
  "commit_id": "abcdef1234...",
  "file_path": "C:/.../world_model.md"
}
```

### POST /books/commit_summary
Body:

```json
{
  "book_id": "optional",
  "book_name": "optional",
  "content": "# summary markdown",
  "message": "optional commit message"
}
```

Success shape is the same as `/commit_world_state`, but writes `summary.md`.

### POST /api/world/sync
Body:

```json
{
  "book_id": "optional",
  "book_name": "optional",
  "content": "human edited full markdown",
  "mock_ai_markdown": "optional test-only placeholder"
}
```

Behavior:
- Uses `draft/world_model` as the only write branch for iterative world-model loop.
- If draft branch does not exist, backend creates it from mainline (`main` first, fallback `master`).
- Writes human content and commits: `Human: [timestamp] instruction added`.
- Calls `call_dify_api(...)` placeholder; if `mock_ai_markdown` is provided, it is used as AI output.
- Writes AI content and commits: `AI: [timestamp] logic synchronized`.
- Returns latest markdown and latest commit hash on draft branch.

Success example:

```json
{
  "status": "success",
  "book_id": "donk_93845573",
  "branch": "draft/world_model",
  "mainline_branch": "master",
  "human_commit_id": "a1b2c3...",
  "commit_id": "d4e5f6...",
  "content": "# ai markdown"
}
```

### POST /api/world/rollback
Body:

```json
{
  "book_id": "optional",
  "book_name": "optional",
  "commit_hash": "target commit hash"
}
```

Behavior:
- Only operates on `draft/world_model`.
- Executes hard reset to target commit (`git reset --hard <hash>`).
- Returns rolled-back markdown content from `world_model.md`.

Success example:

```json
{
  "status": "success",
  "book_id": "donk_93845573",
  "branch": "draft/world_model",
  "commit_id": "a1b2c3...",
  "content": "# rolled back markdown"
}
```

### POST /api/world/confirm
Body:

```json
{
  "book_id": "optional",
  "book_name": "optional"
}
```

Behavior:
- Switches to mainline branch (`main` first, fallback `master`).
- Merges `draft/world_model` into mainline.
- Deletes `draft/world_model` after successful merge.

Success example:

```json
{
  "status": "success",
  "book_id": "donk_93845573",
  "mainline_branch": "master",
  "merged_branch": "draft/world_model",
  "commit_id": "f0e1d2...",
  "content": "# merged markdown"
}
```

### POST /api/world/deduce
Body:

```json
{
  "book_id": "optional",
  "book_name": "optional",
  "intent": "required, user command",
  "active_file": "required, target markdown filename",
  "base_etag": "optional, forwarded to Dify workflow context",
  "conversation_id": "optional, continue existing Dify conversation",
  "chapter_index": 0,
  "mock_ai_markdown": "optional test shortcut"
}
```

Behavior:
- This endpoint is the frontend orchestration entry (`Frontend -> Flask -> Dify`).
- Flask calls Dify `POST /chat-messages` in blocking mode and returns Dify `answer` and `conversation_id`.
- This endpoint itself does not commit files; new Markdown workflows should write through `POST /api/draft/sync_markdown_sections`.
- `POST /api/draft/sync_all` remains a compatibility path for legacy full-file workflows.
- If `DIFY_API_KEY` is missing or Dify is unreachable, returns `DIFY_API_FAILED`.

Success example:

```json
{
  "status": "success",
  "book_id": "donk_93845573",
  "branch": "master",
  "file_name": "world_model.md",
  "content": "# current file content",
  "etag": "sha256...",
  "commit_id": "latest head",
  "conversation_id": "dify-conv-id",
  "answer": "AI natural language response"
}
```

Error example:

```json
{
  "status": "error",
  "code": "DIFY_API_FAILED",
  "message": "Dify API returned HTTP 401"
}
```

### POST /api/world/deduce_stream
Body（与 `/api/world/deduce` 一致）:

```json
{
  "book_id": "optional",
  "book_name": "optional",
  "intent": "required, user command",
  "active_file": "required, target markdown filename",
  "base_etag": "optional, forwarded to Dify workflow context",
  "conversation_id": "optional, continue existing Dify conversation",
  "chapter_index": 0,
  "mock_ai_markdown": "optional test shortcut"
}
```

Behavior:
- 返回 `text/event-stream`，用于前端实时渲染 AI 打字流。
- Flask 以 streaming 模式调用 Dify **已发布版本** `/chat-messages`，并把增量文本透传为 `delta` 事件。
- 具体命中的 published workflow 由后端注册表根据 `active_file + file_type` 选择：
  - `world_model.md / status_card.md / summary.md / error_archive.md / chapters/*.md` -> `routed_agent = world_model`
  - `style_guide.md + file_type=style` -> `routed_agent = style_guide`
- 支持暗门截流协议：当流式文本出现 `[JSON_PAYLOAD_START]` 后，后续文本不会继续透传到前端，而是作为隐藏 payload 在后端做合法性校验。
- 后端本身不执行隐藏 payload 写入；新的 Dify Markdown 工作流应通过 `POST /api/draft/sync_markdown_sections` 执行正式写入。
- `POST /api/draft/sync_all` 仅保留给旧整文件链路兼容使用。
- 若出现 marker 但 payload 缺失/非法，会发出 `error(code=JSON_PAYLOAD_INVALID)` 并中止本轮流。
- 若整轮未出现 marker，保持普通流式文本处理。
- 流结束时会检查 `draft/sandbox` 上目标文件是否发生变化；若发生变化，追加 `draft_ready` 事件并返回局部 diff 预览。
- 若本轮没有任何 `delta` 文本，但 Dify 在 `workflow_finished` 给出了 `outputs.text`，后端会补发一次 `delta`（兜底防空气泡）。
- 若 Dify API 超时，但草稿分支已经实际生成新提交，后端会补发 `draft_ready + done(sync_status=timeout_after_write)`，避免前端把“已写成功”误判成纯失败。

SSE event contract:
- `ack`：请求已受理，包含 `book_id/file_name/branch/base_etag/file_type/routed_agent`。
- `stage`：工作流进度事件，包含 `stage_code/stage_text`，用于显示“正在路由/调用工具/整理输出”等状态。
- `delta`：增量文本片段，字段 `text`（可直接拼接显示）。
- `draft_ready`：检测到草稿更新，包含 `commit_id/etag/content/diff_preview`。
- `done`：本次流结束，包含 `conversation_id/answer/draft_changed/write_confirmed/sync_status/sync_commit_id/routed_agent(通过 ack 提供)`。
- `error`：流内错误，包含 `code/message/status`。

`stage` example:

```json
{
  "stage_code": "tool_call",
  "stage_text": "正在执行: 调用工具获取上下文...",
  "source_event": "node_started",
  "node_title": "读取核心档案",
  "node_type": "tool"
}
```

`draft_ready` example:

```json
{
  "book_id": "donk_93845573",
  "file_name": "world_model.md",
  "branch": "draft/sandbox",
  "commit_id": "0f19c6...",
  "etag": "sha256...",
  "content": "# updated markdown on draft branch",
  "diff_preview": "--- a/world_model.md\n+++ b/world_model.md\n@@ ..."
}
```

## 5) Checkout & History

### GET /checkout
Query:
- `book_id` or `book_name`
- `include` (optional): comma-separated tokens from `world_model,summary,status_card,chapters`
- `last_n` (optional, default `3`, minimum `1`)
- `commit_id` (optional; if provided, read from git snapshot)

Example:

`/checkout?book_name=donk&include=world_model, summary, status_card, chapters&last_n=3`

Success example:

```json
{
  "status": "success",
  "book_id": "donk_93845573",
  "payload": {
    "include": ["world_model", "summary", "status_card", "chapters"],
    "last_n": 3,
    "commit_id": null,
    "markdown": "## world_model\\n...\\n\\n## summary\\n...\\n\\n## chapter:0153_第152章_震旦.md\\n..."
  }
}
```

### GET /books/history
Query: `book_id` or `book_name`

Compatibility:
- `parent_id` remains for legacy consumers.
- `parent_ids` is now returned to expose full git ancestry for merge-aware UIs.
- `refs` lists short ref names that currently point to this commit (e.g. `master`, `main`, `draft/sandbox`).

Success example:

```json
{
  "status": "success",
  "book_id": "donk_93845573",
  "total": 3,
  "history": [
    {
      "commit_id": "abc...",
      "parent_id": "def...",
      "parent_ids": ["def..."],
      "timestamp": "2026-02-15 21:00:00 +0000",
      "message": "[AI_Update] world update",
      "refs": ["master"]
    }
  ]
}
```

### GET /books/git_graph
Query: `book_id` or `book_name`

Purpose:
- Return a merge-aware commit DAG payload for frontend graph visualization.
- Includes all refs (`git log --all`) and preserves multi-parent commits.

Success example:

```json
{
  "status": "success",
  "book_id": "donk_93845573",
  "total": 4,
  "commits": [
    {
      "commit_id": "9f00...",
      "parent_id": "3cd1...",
      "parent_ids": ["3cd1...", "8a17..."],
      "timestamp": "2026-02-25 10:11:00 +0000",
      "message": "merge feature status lane",
      "refs": ["master"]
    }
  ]
}
```

## 6) Tools

### POST /tools/read_chapter
Body:

```json
{
  "book_id": "optional",
  "book_name": "optional",
  "chapter_index": 12
}
```

Returns chapter full text.

### POST /tools/extract_chapter_highlights
Body:

```json
{
  "book_id": "optional",
  "book_name": "optional",
  "chapter_index": 12,
  "keywords": ["高利贷", "大满贯", "流浪汉"],
  "context_sentences": 2
}
```

Constraints:
- `keywords` must be a non-empty list; max size is 20.
- `context_sentences` is optional; default `2`, max `6`.
- Backward compatible alias: if `context_sentences` is absent, payload key `context_lines` is accepted.
- Fast path uses pure Python absolute-index string scan (no vector/NLP dependency).
- Snippet payload is hard-capped by `max_total_chars = 1000`.
- Hit windows are expanded by sentence boundaries (`。！？\n`) with 200-char fallback scan.
- Adjacent/overlapping windows are merged into single char-range snippet blocks.

Success example:

```json
{
  "status": "success",
  "book_id": "donk_93845573",
  "chapter_index": 12,
  "file_path": "C:/.../chapters/0012_xxx.md",
  "keywords": ["高利贷", "大满贯", "流浪汉"],
  "context_sentences": 2,
  "total_chars_in_chapter": 12073,
  "hit_line_count": 1,
  "hit_count": 1,
  "snippet_count": 1,
  "total_chars": 673,
  "max_total_chars": 1000,
  "truncated": false,
  "snippets": [
    {
      "start_char": 11400,
      "end_char": 12073,
      "hit_offsets": [11720],
      "hit_line_numbers": [1],
      "hit_keywords": ["高利贷"],
      "content": "..."
    }
  ]
}
```

No-hit example (still `200`):

```json
{
  "status": "success",
  "book_id": "donk_93845573",
  "chapter_index": 12,
  "context_sentences": 2,
  "total_chars_in_chapter": 12073,
  "hit_line_count": 0,
  "hit_count": 0,
  "snippet_count": 0,
  "total_chars": 0,
  "max_total_chars": 1000,
  "truncated": false,
  "snippets": [],
  "message": "未命中关键词，请调整关键词或扩大上下文。"
}
```

### POST /tools/search_chapter_index
Body:

```json
{
  "book_id": "optional",
  "book_name": "optional",
  "keyword": "异火"
}
```

Returns per-file hit counts.

### POST /tools/validate_domain_facts
Body:

```json
{
  "book_id": "optional",
  "book_name": "optional",
  "file_name": "chapter_draft.md",
  "rules_file": "domain_rules.md",
  "markdown": "optional inline smoke-test markdown"
}
```

Purpose: read-only validation for generated domain rules. The backend does not hardcode
genre-specific facts; it only consumes `domain-rule` JSON code blocks that have been
written into `domain_rules.md` by the current book's source import, world agent, or
review feedback loop.

If `markdown` is provided, the endpoint validates that inline snippet instead of reading
`file_name`. This is intended for world/review agents to smoke-test newly generated rules
against minimal positive and negative examples before declaring the rule file complete.

Supported rule types:
- `forbidden_terms`
- `context_forbidden_terms`
- `regex_forbidden`
- `ordered_patterns_forbidden`

Success returns:
- `ok`
- `rule_count`
- `violation_count`
- `parse_errors`
- `violations`

### POST /tools/adaptive_slice
Body:

```json
{
  "arg1": ["raw text block A", "raw text block B"]
}
```

Returns:
- `total_chapters`
- `data` (bundled chapter batches with `range` + `chapters`)

## 7) Generic Archive APIs (World Agent Core)

### GET /books/get_file
Query:
- `file_name` (required, relative path)
- `book_id` or `book_name`

Constraints:
- Only `.md` / `.json`
- Must stay inside `storage/{book_id}/`
- Path traversal and `.git` internals blocked

Success example:

```json
{
  "status": "success",
  "book_id": "donk_93845573",
  "file_name": "status_card.md",
  "file_path": "C:/.../status_card.md",
  "etag": "sha256hex...",
  "content": "# 状态卡片\\n..."
}
```

Notes:
- Response header also includes `ETag: <sha256hex>`.

### GET /books/get_archive_range
Query:
- `file_name` (required, relative path)
- `start_line` (required, positive integer, 1-based)
- `end_line` (required, positive integer, 1-based)
- `book_id` or `book_name`

Constraints:
- Reuses the same path-safety guard as `/books/get_file`.
- Only `.md` / `.json`, and path traversal / `.git` internals are blocked.
- Window must satisfy:
  - `end_line >= start_line`
  - `end_line - start_line + 1 <= max_lines`
- Backend hard cap: `max_lines = 500`

Success example:

```json
{
  "status": "success",
  "book_id": "donk_93845573",
  "file_name": "summary.md",
  "file_path": "C:/.../summary.md",
  "etag": "sha256hex...",
  "start_line": 21,
  "end_line": 40,
  "returned_end_line": 40,
  "line_count": 20,
  "total_lines": 742,
  "max_lines": 500,
  "content": "..."
}
```

Notes:
- `etag` is computed from the full file content (not only selected line window).
- Response header also includes `ETag: <sha256hex>`.

### GET /books/get_markdown_outline
Query:
- `file_name` (required, markdown relative path)
- `book_id` or `book_name`

Constraints:
- Reuses the same path-safety guard and virtual-core behavior as `/books/get_file`.
- Only `.md` files are allowed.
- 当前推荐用于：
  - `world_model.md`
  - `summary.md`
  - `status_card.md`
  - `style_guide.md`
  - `error_archive.md`
  - `brainstorm.md`
  - `master_outline.md`
  - `arc_outline.md`
  - `chapter_outline.md`
- Parser rules in v1:
  - only ATX headings (`#` to `######`)
  - YAML frontmatter at file start is skipped before heading scan
  - fenced code blocks are ignored during heading scan
- Duplicate sibling headings are disambiguated by canonical `section_path` tokens:
  - first `## Rule` -> `["Root", "Rule"]`
  - second `## Rule` -> `["Root", "Rule [2]"]`

Success example:

```json
{
  "status": "success",
  "book_id": "donk_93845573",
  "file_name": "world_model.md",
  "file_path": "C:/.../world_model.md",
  "etag": "sha256hex...",
  "exists": true,
  "virtual": false,
  "outline": [
    {
      "title": "Root",
      "level": 1,
      "section_path": ["Root"],
      "raw_section_path": ["Root"],
      "heading_line": 4,
      "content_start_line": 5,
      "end_line": 18,
      "child_count": 0,
      "ordinal": 1
    },
    {
      "title": "Rule",
      "level": 2,
      "section_path": ["Root", "Rule [2]"],
      "raw_section_path": ["Root", "Rule"],
      "heading_line": 11,
      "content_start_line": 12,
      "end_line": 14,
      "child_count": 1,
      "ordinal": 2
    }
  ]
}
```

Notes:
- Response header also includes `ETag: <sha256hex>`.
- Clients should feed the returned canonical `section_path` back into `/books/get_markdown_section`.

### GET /books/get_markdown_section
Query:
- `file_name` (required, markdown relative path)
- `section_path` (required)
- `book_id` or `book_name`

`section_path` formats:
- JSON array string: `["人物","陈末","当前状态"]`
- fallback plain string: `人物 > 陈末 > 当前状态`

Constraints:
- Reuses the same path-safety guard and virtual-core behavior as `/books/get_file`.
- Only `.md` files are allowed.
- 与 `/books/get_markdown_outline` 搭配使用，推荐先拿 canonical `section_path` 再读局部正文。
- Empty section bodies return `200 success` with `content_length: 0`.
- Ambiguous raw paths return `409 SECTION_PATH_AMBIGUOUS`; clients should retry with canonical path from outline.

### POST /api/draft/sync_markdown_sections
Body:

```json
{
  "book_id": "optional",
  "book_name": "optional",
  "message": "optional commit message",
  "origin": "ai",
  "writes": [
    {
      "file_name": "chapter_outline.md",
      "op": "replace_section",
      "section_path": ["篇章二：ESL Pro League Season 17（3-4月）—— 连胜的预警"],
      "content": "## 新区块正文",
      "base_etag": "sha256..."
    }
  ]
}
```

Behavior:
- 在 `draft/sandbox` 分支内执行 Markdown 区块级写入。
- 当前支持：
  - `replace_section`
  - `append_under_section`
- 同一文件可包含多条 section patch，后端会按请求顺序顺次应用。
- 每个目标文件都必须提供最新 `base_etag`；若 etag 过期，返回 `409 WRITE_CONFLICT` 并保留 AI 草稿。
- 写入成功后会在 `draft/sandbox` 生成新提交，供后续 diff / 审阅使用。

Success example:

```json
{
  "status": "success",
  "book_id": "donk_93845573",
  "branch": "draft/sandbox",
  "mainline_branch": "main",
  "commit_id": "abcdef1234",
  "updated_files": [
    {
      "file_name": "chapter_outline.md",
      "etag": "sha256hex..."
    }
  ]
}
```

Notes:
- 这是新的 Markdown 主写路径。
- `POST /api/draft/sync_all` 继续保留，但推荐只用于旧整文件工作流兼容。

Success example:

```json
{
  "status": "success",
  "book_id": "donk_93845573",
  "file_name": "world_model.md",
  "file_path": "C:/.../world_model.md",
  "etag": "sha256hex...",
  "exists": true,
  "virtual": false,
  "title": "当前状态",
  "level": 3,
  "section_path": ["人物", "陈末", "当前状态"],
  "raw_section_path": ["人物", "陈末", "当前状态"],
  "heading_line": 42,
  "content_start_line": 43,
  "end_line": 47,
  "heading": "### 当前状态\\n",
  "content": "- 右手轻微震颤\\n",
  "content_length": 12,
  "section_markdown": "### 当前状态\\n- 右手轻微震颤\\n",
  "ordinal": 1
}
```

Ambiguous path example:

```json
{
  "status": "error",
  "code": "SECTION_PATH_AMBIGUOUS",
  "message": "section_path is ambiguous; use canonical path from outline: Root > Rule"
}
```

Validation error examples:

```json
{
  "status": "error",
  "code": "INVALID_PAYLOAD",
  "message": "end_line must be greater than or equal to start_line"
}
```

```json
{
  "status": "error",
  "code": "INVALID_PAYLOAD",
  "message": "请求行数（501行）超过上限（500行），请通过多次分段读取实现。"
}
```

### GET /books/get_cold_archive_range
Query:
- `file_name` (required)
- `start_line` (required, positive integer, 1-based)
- `end_line` (required, positive integer, 1-based)
- `book_id` or `book_name`

Constraints:
- Read-only cold archive channel, no ETag in response body or headers.
- `file_name` can resolve in two phases:
  - exact filename resolution (existing behavior), where names can match:
    - `chapter_*.md`
    - `^\d+.*\.md$`
  - prefix fallback when exact miss occurs:
    - backend extracts first numeric token from `file_name` (e.g. `95.md`, `chapter95`, `095`)
    - token is normalized to 4-digit key (e.g. `0095`)
    - backend scans `storage/{book_id}/chapters/` for first filename starting with `0095_`
- If no exact match and no numeric token exists, request is rejected.
- Exact-match allowlist patterns:
  - `chapter_*.md`
  - `^\d+.*\.md$`
- Hard blacklist (always forbidden): `summary.md`, `world_model.md`, `status_card.md`.
- Read scope is limited to:
  - `storage/{book_id}/chapters/` (primary)
  - `storage/{book_id}/` root fallback for scattered chapter files.
- Path traversal and `.git` internals are blocked.
- Window rules:
  - `end_line >= start_line`
  - max window is 100 lines; if request exceeds 100, backend auto-truncates and returns warning in `message`.
  - if `end_line` exceeds file length, backend clips to EOF without error.

Success example:

```json
{
  "status": "success",
  "book_id": "donk_93845573",
  "file_name": "chapters/0123_demo.md",
  "real_file_name": "0123_demo.md",
  "file_path": "C:/.../chapters/0123_demo.md",
  "start_line": 1,
  "end_line": 200,
  "returned_end_line": 100,
  "line_count": 100,
  "total_lines": 357,
  "max_lines": 100,
  "content": "...",
  "message": "请求行数（200行）超过上限（100行），已自动截断到 100 行。"
}
```

Validation error examples:

```json
{
  "status": "error",
  "code": "INVALID_PAYLOAD",
  "message": "file_name is forbidden for cold archive reader"
}
```

```json
{
  "status": "error",
  "code": "INVALID_PAYLOAD",
  "message": "file_name must match chapter_*.md or ^\\d+.*\\.md$ or contain numeric chapter index"
}
```

### POST /books/update_file
Body:

```json
{
  "book_id": "optional",
  "book_name": "optional",
  "file_name": "status_card.md",
  "content": "# new markdown text",
  "base_etag": "required_for_core_files_optional_for_others",
  "message": "optional commit message",
  "origin": "ai | user | system(optional)"
}
```

Behavior:
- Opaque text write (no semantic parsing).
- Core archive files require optimistic-lock precondition:
  - `world_model.md`, `summary.md`, `status_card.md`, `style_guide.md`, `error_archive.md`
  - request must provide `base_etag`, otherwise returns `428 PRECONDITION_REQUIRED`
- Non-core files (e.g. `chapters/*.md`) keep compatibility mode:
  - `base_etag` optional; if provided and stale, request is rejected with `409 WRITE_CONFLICT`
- Atomic pipeline: temp file -> replace target -> git add/commit.
- Short critical section file lock (`fcntl.flock`) protects check->write->commit from concurrent writes.
- Commit prefixes:
  - `origin=ai` -> `[AI_Update]`
  - `origin=user` -> `[User_Edit]`
  - default/others -> `[System_Update]`
- On stale `base_etag`, backend writes conflict draft and returns conflict metadata.
- On commit failure:
  - backend attempts file rollback
  - if rollback also fails, response includes `warning`

Success example:

```json
{
  "status": "success",
  "book_id": "donk_93845573",
  "file_name": "error_archive.md",
  "file_path": "C:/.../error_archive.md",
  "etag": "sha256hex...",
  "commit_id": "abcdef1234..."
}
```

Conflict example (`409 WRITE_CONFLICT`):

```json
{
  "status": "error",
  "code": "WRITE_CONFLICT",
  "message": "文件已被其他协作者更新，请重新读取后再提交。",
  "book_id": "donk_93845573",
  "file_name": "world_model.md",
  "base_etag": "stale_sha256...",
  "current_etag": "latest_sha256...",
  "draft_file": "C:/.../storage/donk_93845573/conflicts/20260220T120000Z_world_model.md_update.ai_conflict_draft.md"
}
```

Missing precondition example (`428 PRECONDITION_REQUIRED`):

```json
{
  "status": "error",
  "code": "PRECONDITION_REQUIRED",
  "message": "base_etag is required for core archive file: world_model.md"
}
```

Failure example (rollback warning):

```json
{
  "status": "error",
  "code": "GIT_COMMIT_FAILED",
  "message": "fatal: ...",
  "warning": "rollback_failed: file is locked"
}
```

### POST /books/append_file
Body:

```json
{
  "book_id": "optional",
  "book_name": "optional",
  "file_name": "summary.md",
  "append_content": "\n新增片段",
  "base_etag": "required_for_core_files_optional_for_others",
  "message": "optional commit message",
  "origin": "ai | user | system(optional)"
}
```

Behavior:
- Append write uses atomic temp file replace (`tempfile` + `os.replace`).
- Path safety rules are identical to `/books/update_file` and `/books/get_file`.
- Git scope is strictly file-level (`git add -- <file>` + `git commit -- <file>`).
- Core-file optimistic locking and compatibility rules are the same as `/books/update_file`.
- Stale `base_etag` returns `409 WRITE_CONFLICT` and saves `.ai_conflict_draft.md`.
- Empty `append_content` short-circuits as success with no commit.

Success example:

```json
{
  "status": "success",
  "book_id": "donk_93845573",
  "file_name": "summary.md",
  "file_path": "C:/.../summary.md",
  "appended_chars": 12,
  "new_size": 4821,
  "etag": "sha256hex...",
  "commit_id": "abcdef1234..."
}
```

### POST /books/prepend_file
Body:

```json
{
  "book_id": "optional",
  "book_name": "optional",
  "file_name": "world_model.md",
  "prepend_content": "新的核心设定",
  "base_etag": "required_for_core_files_optional_for_others",
  "message": "optional commit message",
  "origin": "ai | user | system(optional)"
}
```

Behavior:
- Prepend write runs in memory (`new_content = prepend_content + "\\n\\n" + current_content` when current content exists).
- If current file is empty, backend writes `new_content = prepend_content` to avoid extra blank separator.
- Whitespace-only `prepend_content` short-circuits as success with no write/commit.
- Path safety, optimistic-lock contract, and conflict fallback rules are the same as `/books/update_file`.
- Stale `base_etag` returns `409 WRITE_CONFLICT` and saves `.ai_conflict_draft.md`.
- Write path remains atomic (`tempfile` + `os.replace`) and path-scoped (`git add/commit -- <file>`).

Success example:

```json
{
  "status": "success",
  "book_id": "donk_93845573",
  "file_name": "world_model.md",
  "file_path": "C:/.../world_model.md",
  "prepended_chars": 16,
  "new_size": 4980,
  "etag": "sha256hex...",
  "commit_id": "abcdef1234..."
}
```

No-change short-circuit example:

```json
{
  "status": "success",
  "book_id": "donk_93845573",
  "file_name": "summary.md",
  "appended_chars": 0,
  "message": "No append content provided, file is unchanged.",
  "commit_id": null
}
```
