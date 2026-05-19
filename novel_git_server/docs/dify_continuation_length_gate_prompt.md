## 单章篇幅守门（强制）
- 三章仍然一次任务产出，但执行顺序必须是：写第 1 章 -> 写入草稿 -> 调用 validate_chapter_lengths -> 若该章低于 min_chars 则立刻用 draft_replace_markdown_section 原地扩写当前章 -> 再次 validate_chapter_lengths；当前章通过后才进入下一章。
- 每章目标线：target_chars=2500；硬下限：min_chars=2200；建议上限：max_chars=3200。统计口径以 validate_chapter_lengths 返回的 non_whitespace_chars 为准，不相信自我估算。
- 篇幅不足时只扩写当前章，不要重写已经通过的章节，不要把三章全部写完后再统一补救。
- 扩写优先增加有效正文：行动链、场景压力、人物反应、对话推进、感官细节和转折，不要用重复总结、设定解释或废话灌水。
- 统计报告和工具结果只用于内部判断，不得写入 chapter_draft.md 正文。
- 最终回复必须简短列出三章的篇幅状态：章节名、non_whitespace_chars、status；若仍有 under_min，必须明说卡住位置，不要宣称完成。

<!-- query-suffix -->
额外硬约束：每写完并写入一章后，必须调用 validate_chapter_lengths 校验 chapter_draft.md。低于 min_chars=2200 的章节必须先原地扩写并复验，通过后才能继续下一章；最终回复要报告每章篇幅状态。
