# Markdown Section Indexing Checklist

## Goal
- Expose Markdown heading outline/section read APIs for Dify.
- Keep `/api/draft/sync_all` as the only transactional write gateway.
- Support future Dify-side patch stitching with deterministic section addressing.

## Atomic Tasks
- [x] a1 add Markdown section parsing utility with frontmatter skip and fenced-code awareness
- [x] a2 define stable `section_path` addressing for duplicate heading titles
- [x] a3 add section patch helpers for `replace_section` and `append_under_section`
- [x] a4 expose `GET /books/get_markdown_outline`
- [x] a5 expose `GET /books/get_markdown_section`
- [x] a6 add unit tests for nested headings, empty sections, duplicate titles, and frontmatter
- [x] a7 add API tests for outline/section endpoints and empty-section semantics
- [x] a8 add patch replay helper for optimistic-lock retry on concurrent writes
- [x] a9 update protocol/api/progress docs without changing live Dify workflow snapshots

## Guardrails
- Only parse ATX headings (`#` .. `######`) in v1.
- Ignore headings inside fenced code blocks.
- Skip YAML frontmatter at file start before heading detection.
- `section_path` must be full ancestry, not a single title string.
- Empty section reads must return success with `content_length: 0`.
- `append_under_section` must insert after the last descendant of the parent section, not at the raw parent tail.
- Concurrent patch retry must re-fetch latest content and reapply the same patch once before surfacing conflict.
