# Dify 提示词清单

更新时间：2026-05-18

## 范围

本清单记录当前本地 Dify 数据库里的提示词表面。运行真相以 Dify PostgreSQL 的 `workflows.graph` 为准；`dify_workflows/*.yml` 只是历史导出快照，不能直接当作恢复源。

本轮清洗目标：

- 面向作者和模型的提示词使用中文表述。
- 不保留具体书名、角色名、赛事名或旧测试书示例。
- 工具说明不再继承英文或乱码描述。
- 不改变正文生成职责边界：Codex 只修补提示词和验证工具，不生成小说正文。

## 当前校验

| 检查面 | 结果 | 证据 |
| --- | --- | --- |
| Dify 运行库提示词扫描 | 0 个硬编码、英文规约、乱码问题 | `.runtime/prompt_cn_generic_4_live_scan_after_script_fix.json` |
| 可复跑补丁脚本扫描 | 0 个硬编码、英文规约、乱码问题 | `.runtime/prompt_cn_generic_4_script_scan_after_fix.json` |
| 本地导出快照扫描 | 0 个硬编码、英文规约、乱码问题 | `.runtime/prompt_cn_generic_5_exports_after_yaml.json` |
| 运行库清单快照 | 已生成 | `.runtime/prompt_cn_generic_5_live_inventory.json` |

## Agent 清单

| 应用 | 当前职责 | 提示词来源 | 思考模式 | 写入边界 |
| --- | --- | --- | --- | --- |
| 读书存档agent | 已从主动链路退役；摘要归档由后端摘要管线承担，Dify 仅保留历史兼容工作流。 | 历史工作流，无主动 agent 节点 | 不适用 | 不作为当前摘要生产入口 |
| 世界模型agent | 初始化后阶段的世界观读取、解释、局部修订、在线考据与约束生命周期整理。 | `scripts/patch_world_model_agent.py` | 已开启 | 只在明确写入时更新世界观、状态卡或相关约束文件 |
| 文风学习agent | 文风初始化后的讨论、解释、证据诊断和局部修订；初始化本身交给后端动作管线。 | `scripts/patch_style_agent.py` | 已开启 | 只在作者明确要求时最小写入文风相关文件 |
| 灵感大纲agent | 大纲讨论与大纲落档分离：讨论节点负责发散和搜索参考，落档节点负责写入四层大纲。 | `scripts/patch_outline_agent.py` | 已开启 | 只写 `brainstorm.md`、`master_outline.md`、`arc_outline.md`、`chapter_outline.md` |
| 续写agent | 根据大纲卡和上下文写入章节草稿，并执行篇幅硬门与文风建议回报。 | `scripts/patch_continuation_agent.py` | 已开启 | 只写 `chapter_draft.md` |
| 审核agent | 审核剧情连续性、世界观状态、因果链和章节卡履约；文风只作为建议输入。 | `scripts/patch_review_agent.py` | 已开启 | 只把可复用问题沉淀到 `error_archive.md` |

## 工作流版本

| 应用 | 当前运行版 | 草稿版 | 历史版处理 |
| --- | --- | --- | --- |
| 世界模型agent | 已清洗 | 已清洗 | 只清洗提示词表面，不升级拓扑 |
| 文风学习agent | 已清洗 | 已清洗 | 历史版无本轮运行修补需求 |
| 灵感大纲agent | 已清洗 | 已清洗 | 历史版仅作为历史证据 |
| 续写agent | 已清洗 | 已清洗 | 历史版仅保留兼容证据 |
| 审核agent | 已清洗 | 已清洗 | 已清洗工具卡片和变量提示表面 |
| 读书存档agent | 保留历史兼容 | 保留历史兼容 | 已退役，不再作为主动生成链路 |

## 关键边界

- 世界观初始化、文风初始化等无提示词后台动作，应由工作台动作面板触发，不塞回聊天框。
- 文风诊断是作者建议，不是滚动续写调度硬门。
- 审核 agent 不负责替作者改文风，也不直接续写正文。
- 大纲 agent 的搜索结果只能作为外部参考，不能自动覆盖书内事实。
- 续写 agent 可以参考文风提示和原文样本，但必须保持章节卡、世界观、状态卡、篇幅门和因果链边界。
- 如果重新导出 `dify_workflows/*.yml`，必须重新运行提示词扫描；导出快照不得替代 Dify 运行库。

## 复验命令

```powershell
python scripts\scan_dify_prompt_hygiene.py --source live-db --format json --output .runtime\prompt_live_scan.json
python scripts\scan_dify_prompt_hygiene.py --source scripts --format json --output .runtime\prompt_script_scan.json
python scripts\scan_dify_prompt_hygiene.py --source exports --format json --output .runtime\prompt_export_scan.json
```
