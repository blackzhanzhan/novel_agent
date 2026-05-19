# Document Map

这份文档说明项目文档的阅读顺序和定位，避免最后收口阶段继续从聊天记录里找项目叙事。

## 推荐阅读顺序

### 1. 项目首页

文件：

- `README.md`

用途：

- 给招聘方、观众或新接手开发者快速理解项目。
- 说明项目定位、核心能力、技术栈和演示主线。

适合谁看：

- 简历项目读者。
- B 站视频观众。
- 第一次打开仓库的人。

### 2. Demo 剧本

文件：

- `docs/DEMO_SCRIPT.md`

用途：

- 作为录屏和讲解脚本。
- 描述从导入初始化到创作循环，再到剧情分支实验室的完整演示路径。

适合谁看：

- 准备录制项目演示的人。
- 想快速理解产品闭环的人。

### 3. 架构总览

文件：

- `docs/ARCHITECTURE.md`

用途：

- 解释 React、Flask、Dify、Markdown 文件和 Git 如何分工。
- 说明为什么项目不是纯 Dify 画布，也不是普通聊天壳。

适合谁看：

- 面试官。
- 技术评审。
- 后续开发者。

### 4. 部署与可复现 Demo

文件：

- `docs/DEPLOYMENT.md`

用途：

- 说明本地 Windows demo pack 和 Compose demo pack 的启动目标、Dify 运行时真相、密钥边界和 smoke 验收标准。

适合谁看：

- 想在新机器上复现项目的人。
- 准备把项目交给面试官、评审或未来接手者的人。

### 5. Dify 持久化与备份恢复

文件：

- `docs/DIFY_PERSISTENCE_AND_BACKUP.md`

用途：

- 说明 PostgreSQL bind mount 现状、SQL 备份/恢复操作、恢复优先级和危险操作边界。

适合谁看：

- 需要恢复 Dify 运行时的开发者。
- 失忆后重新接手的自己。

### 6. 收口清单

文件：

- `docs/CLOSEOUT_CHECKLIST.md`

用途：

- 指导最后演示冲刺。
- 区分 P0 必须演示、P1 强烈建议、P2 可以后置。

适合谁看：

- 当前开发者。
- 继续接手收尾的人。

## 历史与内部资料

### 历史 PRD

文件：

- `prd.md`

定位：

- 历史产品蓝图和长期设想。
- 仍有价值，但不再作为外部展示入口。

阅读建议：

- 外部读者先看 `README.md`。
- 需要理解项目早期设计哲学时再看 `prd.md`。

### 后端 API 与 Dify 工具资料

目录：

- `novel_git_server/docs/`

定位：

- 后端接口、OpenAPI 工具集、Dify 增量写入指南和历史进度资料。
- 偏工程内部资料，不适合作为项目首页。

典型文件：

- `novel_git_server/docs/api.md`
- `novel_git_server/docs/openapi_v3_5_1_draft_min.json`
- `novel_git_server/docs/dify_markdown_incremental_workflow_guide.md`
- `novel_git_server/docs/style_agent_prompt_contract.md`
- `novel_git_server/docs/world_deduction_output_contract.md`

阅读建议：

- 调 Dify 工具或维护后端接口时再看。
- Demo 和简历叙事不应直接从这些文档开始。

### Dify 工作流 DSL

目录：

- `dify_workflows/`

定位：

- 当前 Dify Agent 工作流导出。
- 是 Agent 配置证据，不是产品说明文档。

当前工作流：

- `世界模型agent.yml`
- `文风学习agent.yml`
- `灵感大纲agent.yml`
- `读书存档agent.yml`

阅读建议：

- 调试 Dify 工作流时查看。
- 对外讲解时只需要说明它们对应哪些 Agent 能力。

### 参考上游资料

文件和目录：

- `REFERENCE_UPSTREAMS.md`
- `REFERENCE_OPENCODE_DESKTOP_ENTRY_MAP.md`
- `reference_upstreams/`

定位：

- UI 和工程参考资料。
- 不是 demo 主线的一部分。

### 前端主题说明

文件：

- `FRONTEND_THEME_OPTIONS.md`

定位：

- 前端视觉方向备忘。
- 后续做 UI polish 时有用。

## 当前文档体系

```text
README.md
docs/
├── DEMO_SCRIPT.md
├── ARCHITECTURE.md
├── DEPLOYMENT.md
├── CLOSEOUT_CHECKLIST.md
└── DOCUMENT_MAP.md
prd.md
novel_git_server/docs/
dify_workflows/
```

## 维护规则

- 外部展示入口优先维护 `README.md` 和 `docs/DEMO_SCRIPT.md`。
- 部署复现入口优先维护 `docs/DEPLOYMENT.md`。
- 架构变化优先更新 `docs/ARCHITECTURE.md`。
- 最后冲刺任务变化优先更新 `docs/CLOSEOUT_CHECKLIST.md`。
- `prd.md` 保留为历史文档，不要求每次开发同步更新。
- `novel_git_server/docs/` 保留为后端内部资料，不承担项目叙事职责。
- 运行数据、API key、storage 内容不写进文档。

## 一句话结论

新的文档体系把项目分成三层：

- 外部展示层：`README.md`、`docs/DEMO_SCRIPT.md`
- 技术解释层：`docs/ARCHITECTURE.md`
- 收口执行层：`docs/CLOSEOUT_CHECKLIST.md`

旧 PRD 和后端内部资料继续保留，但不再承担第一入口职责。
