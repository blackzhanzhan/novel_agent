# Novel Agent

面向长篇网文作者的本地 AI 创作工作台：把小说导入、世界观蒸馏、大纲协作、续写草稿、审核归档和剧情分支管理做成一套可维护的创作 IDE。

它不是普通聊天框应用：人类作者和 Agent 共同维护同一套 Markdown 创作资产，Dify 负责语义决策和工作流编排，Flask / LoreGit 提供确定性的文件、上下文与 Git 工具层，让章节草稿、审核意见、回退历史和剧情分支都可以被检查、回滚和继续推进。

## 工程证据

- 演示视频：<https://www.bilibili.com/video/BV12eVA69EGV/>
- GitHub Pages 技术档案：<https://blackzhanzhan.github.io/novel_agent/>
- 测试规模：`novel_git_server/tests` 当前包含 **50 个核心测试文件、426 个测试函数**，覆盖 Flask API、Git 分支 / diff / 回退、Markdown 区块写入、Dify ToolProvider 边界、运行时配置、公开体验会话隔离和章节审核归档等核心链路。
- 部署路径：仓库提供 Release ZIP、本地源码运行、Docker Compose 本地构建、GHCR 预构建镜像和只读体验模式服务器部署说明；`deploy/demo/deploy_doctor.py` 区分本地 demo 与 public-demo 画像做部署体检。

完整介绍、截图、架构说明、部署教程和 FAQ 都放在 GitHub Pages：

## [打开 GitHub Pages 技术档案](https://blackzhanzhan.github.io/novel_agent/)

备用入口：

- [仓库内 HTML 技术档案](docs/technical-dossier.html)
- [Markdown 技术档案](docs/TECHNICAL_DOSSIER.md)
- [完整部署说明](docs/DEPLOYMENT.md)

![Novel Agent 工作台](docs/assets/screenshots/02-workbench-main.jpg)
