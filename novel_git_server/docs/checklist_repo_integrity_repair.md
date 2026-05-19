# Repo Integrity Repair Checklist

Date: 2026-03-09
Scope: read-path virtualization, write-path blocking, explicit repair, frontend integrity UX

- [x] a1 split `ensure_book_layout()` semantics into pure path resolution vs explicit materialization
- [x] a2 add repo integrity probe for missing core files / untracked layout files / missing repo baseline
- [x] a3 virtualize core-file reads in `GET /books/get_file`
- [x] a4 expose `exists` / `virtual` metadata in `GET /books/list_hot_files`
- [x] a5 make world-deduce read path compatible with virtual core files while blocking AI run on broken layout
- [x] a6 make Git console read path side-effect free
- [x] a7 add explicit `POST /books/repair_layout`
- [x] a8 guard repair/bootstrap with repo-level lock
- [x] a9 block normal writes when repo layout is incomplete
- [x] a10 add frontend missing-file placeholder state instead of stale ghost content
- [x] a11 add frontend integrity banner / broken-layout hints
- [x] a12 add frontend repair action and post-repair refresh closure
- [x] a13 block AI run when repo integrity is incomplete
- [x] a14 add regression tests for rollback / virtual reads / repair flow
- [x] a15 update docs and progress log
