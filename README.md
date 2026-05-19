# AI 小说创作工作台

一个面向长篇小说作者的本地 AI 创作工作台。项目目标不是让模型一次性“凭空写小说”，而是把已有文本、世界观、状态卡、文风指纹、大纲和章节草稿组织成一个可审阅、可回滚、可分支实验的创作系统。

项目适合演示三件事：

- 将已有小说导入为可维护的章节资料库。
- 通过 Dify Agent 工作流完成世界观、文风、大纲、续写和审核协作。
- 用 Git 管理剧情路线，允许同一套设定下并行探索多个创作分支。

## 核心定位

这是一个“类 Cursor 的小说创作 IDE”：

- 前端提供多面板写作工作台、流式对话、思考过程展示、文件浏览、差异审阅和 Git 视图。
- 后端负责本地文件读写、章节归档、Dify 工具桥接、草稿审阅、质量校验和 Git 提交。
- Dify 工作流承担 Agent 编排，包括读书存档、世界模型、文风学习、灵感大纲、续写和审核。
- 每本书拥有独立 `storage/<book_id>/` 工作区和 Git 历史，支持回滚、分支与差异比较。

## 演示主线

项目 demo 分为两大阶段。

### 1. 导入初始化

从已有小说资料开始：

1. 搜索或准备番茄小说导出目录。
2. 使用前端 `书籍 / 导入` 导入 Tomato-Novel-Downloader `bulk_files`。
3. 后端将章节清洗为可阅读 Markdown，写入 `storage/<book_id>/chapters/*.md`。
4. 质量门槛检查空章、短章、重复、断号、碎行和下载残留。
5. 读书存档、世界模型、状态卡、文风指纹和大纲 Agent 从原文中萃取创作底座。

这一段展示的是：系统可以把已有百万字文本变成可维护的创作资产，而不是只依赖单次 prompt。

### 2. 创作循环

在资料底座上进入持续创作：

1. 头脑风暴提出新主张。
2. 萃取为主线大纲、篇章大纲和逐章节大纲。
3. 续写 Agent 按逐章节大纲生成章节草稿。
4. 审核 Agent 检查世界观、状态卡、文风、错误档案和章节边界。
5. 作者在审阅工作台中选择：亲自修改、归档保留、打回续写 Agent 局部重写。
6. 审核发现的可复用问题沉淀到 `error_archive.md`，后续续写受其约束。

## 核心记忆点：剧情分支实验室

传统网文创作很难试错：一条剧情线写坏后，复制文件、回滚和对比都很重。

本项目把“剧情路线”建模为 Git 分支：

- 同一个头脑风暴或主线大纲可以派生不同剧情主张。
- 每条分支拥有独立草稿、状态变化和审核结果。
- 作者可以在 Git/diff 视图中比较路线差异。
- 好的分支可以合并回主线，失败路线可以保留、回滚或废弃。

这使项目不仅是一个 Dify Agent 画布，而是一个 Git-native 的小说创作系统。

## 技术栈

- Frontend: React, TypeScript, Vite
- Backend: Flask, Python
- Agent Orchestration: Dify Workflow / Chatbot Agent
- Storage: Markdown files, local filesystem
- Versioning: nested Git repositories per book
- Runtime: local Windows development stack with `start_all.ps1`

## 目录概览

```text
frontend/              # React 创作工作台
novel_git_server/      # Flask API、存储协议、Dify 工具桥
dify_workflows/        # 当前导出的 Dify 工作流 DSL
scripts/               # 本地启动脚本
tools/                 # 辅助工具
prd.md                 # 历史 PRD 和产品蓝图
docs/                  # 演示、架构和收口文档
```

运行数据位于 `novel_git_server/storage/`，不作为源码提交。

## 当前状态

项目处于本地演示冲刺阶段。已具备前后端基础工作台、Dify 工具桥、番茄章节导入、世界/文风/大纲/续写/审核等 Agent 链路的主体能力；后续重点是把完整 demo 路径打磨到可稳定录屏、可讲解、可写入 Wiki 的程度。

建议阅读顺序：

1. `README.md`
2. `docs/DEMO_SCRIPT.md`
3. `docs/ARCHITECTURE.md`
4. `docs/DEPLOYMENT.md`
5. `docs/CLOSEOUT_CHECKLIST.md`
6. `docs/DOCUMENT_MAP.md`
