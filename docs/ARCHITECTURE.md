# Architecture Overview

本项目的架构目标是把长篇小说创作拆成几个稳定职责：资料导入、确定性文件工具、Agent 语义推理、人工审阅和版本分支。核心原则是：语义判断交给 Agent，确定性 IO 和版本历史交给本地后端与 Git。

## 总体结构

```text
┌─────────────────────┐
│ React/Vite Frontend │
│ 创作工作台 / 审阅台 │
└──────────┬──────────┘
           │ HTTP / SSE
┌──────────▼──────────┐
│ Flask Backend        │
│ 文件工具 / Git / API │
└──────────┬──────────┘
           │ Dify App API + OpenAPI tools
┌──────────▼──────────┐
│ Dify Agent Workflows │
│ 大纲 / 世界 / 文风 / 续写 / 审核 │
└──────────┬──────────┘
           │ read/write tools
┌──────────▼──────────┐
│ storage/<book_id>/   │
│ Markdown + nested Git│
└─────────────────────┘
```

## 前端职责

前端是作者直接操作的工作台。

主要职责：

- 展示项目文件、章节、大纲和当前创作状态。
- 提供右侧 Agent 对话和流式响应体验。
- 展示 Dify 运行过程、思考片段和阶段状态。
- 提供差异审阅工作台，让人类决定确认、回滚或重写。
- 提供 Git 视图，用于查看提交、分支和差异。
- 提供番茄小说导入面板。

前端不做的事：

- 不直接判断剧情合理性。
- 不绕过后端直接写本地文件。
- 不替代 Git 作为版本来源。

## Flask 后端职责

后端是确定性工具层。

主要职责：

- 管理 `storage/<book_id>/` 文件布局。
- 读写 Markdown 文件。
- 提供章节导入、区块读取、区块写入和冷档案读取 API。
- 对接 Dify OpenAPI 工具集。
- 管理 `draft/sandbox` 草稿分支。
- 执行 Git 提交、差异、回滚和分支操作。
- 做质量门槛、路径安全、ETag 冲突保护等确定性校验。

后端不做的事：

- 不裁决剧情是否好看。
- 不代替 Agent 合并语义冲突。
- 不把复杂世界观规则硬编码进 Python。

## Dify Agent 职责

Dify 承担语义编排和 Agent 决策。

当前核心 Agent：

- 读书存档 Agent：从章节中抽取资料和摘要。
- 世界模型 Agent：维护世界观、机制、状态卡和题材规则。
- 文风学习 Agent：生成叙事结构指纹、作者可读审查和续写硬约束。
- 灵感大纲 Agent：支持 brainstorm、master outline、arc outline、chapter outline。
- 续写 Agent：按章节大纲生成草稿，并支持局部修复。
- 审核 Agent：检查草稿是否违反世界观、状态卡、文风、大纲边界和错误档案。

Dify 调用后端工具完成读写，但最终写入仍由后端落盘和 Git 归档。

## 存储协议

每本书是一个独立工作区：

```text
novel_git_server/storage/<book_id>/
├── .git/
├── metadata.json
├── world_model.md
├── status_card.md
├── summary.md
├── style_fingerprint.md
├── style_review.md
├── style_constraints_for_continuation.md
├── error_archive.md
├── brainstorm.md
├── master_outline.md
├── arc_outline.md
├── chapter_outline.md
├── chapter_draft.md
├── import_report.json
└── chapters/
    ├── 0001_xxx.md
    └── 0002_xxx.md
```

设计理由：

- Markdown 文件可读、可审计、可被 Dify 工具直接读取。
- 每本书独立 Git 仓库，避免不同项目互相污染。
- 文件布局稳定，便于 Agent 明确读写边界。
- `chapters/` 存放原文或归档章节，`chapter_draft.md` 存放当前续写草稿。

## 导入初始化链路

```text
番茄 bulk_files
  -> 章节解析和质量门槛
  -> chapters/*.md + import_report.json
  -> 读书存档
  -> summary / world_model / status_card
  -> 文风指纹和续写硬约束
  -> 大纲底座
```

关键点：

- 导入器只做确定性清洗，不重写原文。
- 质量门槛只拦明显坏数据，不替作者判断文学质量。
- 导入后的章节可以被 `get_cold_archive_range` 读取，供读书存档 Agent 分段消费。

## 创作循环链路

```text
brainstorm
  -> master_outline
  -> arc_outline
  -> chapter_outline
  -> continuation_agent 写 chapter_draft.md
  -> review_agent 审核
  -> 人类三选一：修改 / 归档 / 打回重写
  -> error_archive 与状态文件更新
  -> 下一轮章节
```

关键点：

- 大纲是多级萃取，不是一次性生成。
- 续写写入草稿分支，不直接污染主线。
- 审核意见必须回到错误档案或人工决策，而不是漂浮在聊天记录里。

## 剧情分支实验室

项目的差异化核心是把剧情路线建模为 Git 分支。

示例：

```text
main
├── branch/expose-secret-early
└── branch/hidden-power-long-game
```

每个分支都可以拥有：

- 独立大纲调整。
- 独立 `chapter_draft.md`。
- 独立审核记录。
- 独立状态变化。

作者可以比较分支差异，再决定：

- 合并到主线。
- 继续保留为备选路线。
- 回滚或废弃。

这让“剧情试错”从手动复制文件变成版本控制里的可审计操作。

## 关键工程约束

- 文件写入必须经过后端 API。
- 重要写入必须有 Git 提交记录。
- 核心文件写入需要 ETag 或草稿审阅保护。
- Agent 只能写入被授权的文件范围。
- storage 是运行数据，不提交到项目源码。
- Dify 工作流 DSL 是当前 Agent 配置的重要证据，但不是唯一真相。

## 为什么不是纯 Dify 项目

纯 Dify 画布适合展示 Agent 编排，但很难完整承载：

- 本地文件系统级资料库。
- 每本书独立 Git 历史。
- 前端 diff 审阅体验。
- 剧情分支实验。
- 导入质量门槛和章节归档。

因此本项目采用 Dify + Flask + React + Git 的组合：Dify 负责语义，Flask 负责确定性工具，React 负责产品体验，Git 负责版本宇宙。
