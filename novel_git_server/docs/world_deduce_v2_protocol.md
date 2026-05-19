# World Deduce v2 Protocol (Bright Route)

## 0. Runtime Truth
- 后端正式调用对象是 Dify **已发布版本** `/v1/chat-messages`。
- `/develop` 画布只用于人工调试，不是后端运行时真相。
- 仓库内 `dify_workflows/*.yml` 是导出备份与手工编排参考，不直接决定后端实际命中的 workflow 版本。
- 后端保持单入口 deduce / deduce_stream，通过注册表按 `active_file + file_type` 选择 published workflow。

## 1. Scope
This protocol defines the writing authority split for world deduce flow:
- Flask stream endpoint: UI abstraction only (stream relay + masking), no hidden-payload write execution.
- Dify pipeline: owns extraction + write execution.
- `/api/draft/sync_all`: remains the only transactional write gateway.

Current routed agents:
- `world_model`
  - targets: `world_model.md`, `status_card.md`, `summary.md`, `error_archive.md`, `chapters/*.md`
- `style_guide`
  - target: `style_guide.md`

## 2. Stream Contract
### 2.1 Visible channel
- Model analysis text is streamed to frontend as normal `delta` events.

### 2.2 Hidden channel marker
- Marker: `[JSON_PAYLOAD_START]`
- Marker appears once.
- Content after marker is hidden payload, not for UI rendering.

### 2.3 Masking rule
- Flask must mask marker and all trailing payload from frontend deltas.
- Cross-chunk partial marker must be buffered (no half-marker leakage).

## 3. Hidden Payload Schema
Hidden payload must be strict JSON:

```json
{
  "writes": [
    {
      "file_name": "world_model.md",
      "op": "update",
      "content": "..."
    },
    {
      "file_name": "status_card.md",
      "op": "update",
      "content": "..."
    }
  ],
  "sync_meta": {
    "status": "success",
    "commit_id": "<optional>",
    "error_code": "<optional>",
    "error_message": "<optional>"
  }
}
```

Constraints:
- Allowed files: `world_model.md`, `status_card.md`.
- `status_card.md` must be capped by pipeline-side GC (`<= 15` lines suggested) and backend hard cap (`<= 20` lines).
- JSON must be standards-compliant (escaped quotes/newlines).

## 4. Dify Execution Responsibility
Dify workflow must execute writes in-code:
1. Extract hidden JSON from marker tail.
2. Validate JSON and file whitelist.
3. Fetch current `etag` for each target file via `GET /books/get_file`.
4. Build `writes[]` with `base_etag`.
5. Call `POST /api/draft/sync_all`.
6. Return sync result in `sync_meta`.

### 4.1 Markdown Section Indexing (for incremental world-model edits)
For `world_model.md`, Dify should prefer heading-addressed incremental edits instead of full-file regeneration:
1. Call `GET /books/get_markdown_outline` to fetch canonical heading tree.
2. Select the target canonical `section_path` from the returned outline.
3. Call `GET /books/get_markdown_section` for the local subsection context only.
4. Generate patch payload in Dify code/structured output.
5. Stitch full markdown in the Dify Python code node.
6. Submit the stitched full text through `POST /api/draft/sync_all` with `op: "update"`.

Recommended incremental patch ops at Dify layer:

```json
{
  "writes": [
    {
      "file_name": "world_model.md",
      "op": "replace_section",
      "section_path": ["人物", "陈末", "当前状态"],
      "content": "### 当前状态\n- 右手轻微震颤\n"
    }
  ]
}
```

```json
{
  "writes": [
    {
      "file_name": "world_model.md",
      "op": "append_under_section",
      "section_path": ["人物", "陈末"],
      "content": "### 新增弱点\n- 对修正力更敏感\n"
    }
  ]
}
```

Section-indexing guardrails:
- v1 only recognizes ATX headings (`#` .. `######`).
- YAML frontmatter at file start is skipped before heading scan.
- fenced code blocks are ignored during heading scan.
- empty sections must still return success with `content_length: 0`.
- duplicate sibling headings must use canonical `section_path` returned by outline, such as `Rule [2]`.
- `append_under_section` must insert after the parent's last descendant and before the next sibling/ancestor boundary.

## 5. ETag and Cold Start Rules
- Core files always require `base_etag`.
- If `get_file` returns 404 for target file, execution node must use empty-content etag:
  - `sha256("") = e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- `428 PRECONDITION_REQUIRED` handling:
  - Re-fetch etag and retry exactly once.
  - Retry should include jitter `100-300ms` to reduce ABA contention.
  - If retry is caused by an incremental section patch, Dify must re-fetch latest full markdown and re-apply the same patch operation on the latest content instead of reusing stale stitched output.

## 6. Error Semantics
- Marker exists but payload JSON invalid: fail fast (no write), explicit error.
- No marker: compatible legacy mode (visible response only, no write attempt).
- `sync_all` non-200 or `status!=success`: return failure marker in `sync_meta`.

## 7. Frontend Closure Rule
- Frontend should refresh stores only on `done` when sync success is explicitly confirmed.
- `done` without success confirmation must not trigger success refresh toast.

## 8. Non-Goals
- No backend hidden payload execution path.
- No bypass of optimistic lock.
- No direct `books/update_file` usage for AI transaction writes.
- No backend-side transactional section patch write endpoint in v1; patch stitching stays in Dify code nodes.
