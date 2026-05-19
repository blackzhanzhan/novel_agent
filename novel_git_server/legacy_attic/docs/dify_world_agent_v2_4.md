# Dify World Agent 搭建指南 (v2.4)

## 1. 设计哲学：三权分立

World Agent 必须同时依赖三类输入，不能只看当前状态：

1. 现状锚点 `current_state`
说明：我现在在哪，当前人物/资源/关系状态是什么。

2. 目标剧情 `target_outline`
说明：本章必须发生什么，剧情要去哪里。

3. 逻辑桥接 `gap_analysis`
说明：从现状到目标中间缺了什么，如何补齐因果链。

流程本质：
`current_state + target_outline -> gap_analysis -> updated_world_model`

## 2. Flask 端 HTTPS 准备

推荐：Dify 只访问 HTTPS 入口，Flask 继续监听 `127.0.0.1:5000`。

反向代理示例（Caddy）：

```caddyfile
api.yourdomain.com {
    reverse_proxy 127.0.0.1:5000
}
```

连通验证：

```bash
curl -i "https://api.yourdomain.com/checkout?view=world_model"
curl -i "https://api.yourdomain.com/outlines?latest=1&full=1"
```

## 3. Dify 工作流拓扑（主动推演流）

建议节点顺序：

1. `Start`
输入变量建议：
- `chapter_goal_hint` (可选，来自上游 Director)
- `outline_id` (可选，指定目标大纲)

2. `HTTP_CheckoutWorld`（输入 A：现状锚点）
- Method: `GET`
- URL: `https://api.yourdomain.com/checkout?view=world_model`
- 输出变量：
  - `current_commit_id = payload.commit_id`
  - `current_state = payload.markdown`

3. `HTTP_GetOutlines`（输入 B：剧情驱动）
- Method: `GET`
- URL: `https://api.yourdomain.com/outlines?latest=1&full=1`
- 说明：若有上游明确大纲，可直接用上游变量覆盖。
- 输出变量建议：
  - `target_outline = latest.content`（优先）
  - 回退：`latest.preview`

4. `Agent_WorldModel_GapPlanner`（核心：Gap Analysis）
- 输入必须同时包含：
  - `{{current_state}}`
  - `{{target_outline}}`
  - `{{chapter_goal_hint}}`（可选）
- 任务：
  - 对比现状与目标
  - 生成缺口清单（位置、时间、资金、身份、资源、关系、伏笔、禁忌约束）
  - 产出检索请求（若存在信息缺口）
- 输出 JSON（建议）：

```json
{
  "gap_list": ["从广州到首尔缺少出行与证件链条", "资金来源未交代"],
  "need_retrieval": true,
  "queries": ["主角护照状态", "可调用的资金来源", "过去章节中的首尔线索"]
}
```

5. `Condition_NeedRetrieval`
- 条件：`need_retrieval == true`

6. `Knowledge_Retrieval`（条件分支）
- 数据源：133 章历史库（章节正文、梗概、关键事件索引）
- 输入：`queries`
- 输出：`retrieved_facts`

7. `Agent_WorldModel_Synthesizer`
- 输入：
  - `{{current_state}}`
  - `{{target_outline}}`
  - `{{gap_list}}`
  - `{{retrieved_facts}}`（可空）
- 职责：
  - 补齐逻辑鸿沟
  - 生成新的世界状态核心段落（Markdown）
  - 只更新必要状态，不篡改无关设定
- 输出 JSON（建议）：

```json
{
  "message": "world update: chapter-34 active deduction",
  "updated_world_model": "## 核心状态档案\n- 位置: 首尔\n- 资金: ...\n- 关系: ...\n- 待回收伏笔: ..."
}
```

8. `HTTP_UpdateWorld`（写回 Flask）
- Method: `POST`
- URL: `https://api.yourdomain.com/world_model`
- Headers:
  - `Content-Type: application/json`
- Body:

```json
{
  "action": "update_world_model",
  "message": "{{Agent_WorldModel_Synthesizer.message}}",
  "parent_id": "{{HTTP_CheckoutWorld.payload.commit_id}}",
  "content": "{{Agent_WorldModel_Synthesizer.updated_world_model}}"
}
```

9. `HTTP_Verify`（可选但建议）
- Method: `GET`
- URL: `https://api.yourdomain.com/checkout?view=world_model&commit_id={{HTTP_UpdateWorld.commit_id}}`
- 用于确认状态已成功写入 commit 链。

## 4. Prompt 关键模板（World Agent）

系统指令必须包含：

1. 你必须先比较 `current_state` 与 `target_outline`，再做更新。
2. 你必须显式列出“缺失环节”，不能直接跳结论。
3. 缺失事实必须先检索历史，再写入最终状态。
4. 你的目标是让“状态变化服务剧情推进”，不是做静态摘要。

建议加入自问模板：
- 地理与时间是否连贯？
- 角色动机与资源是否足够支撑目标剧情？
- 是否触犯既有禁忌规则？
- 哪些伏笔需要新增或回收？

## 5. HTTPS 交换与错误处理

POST 端点全部是 `application/json` 硬切协议：
- `/save_outline` -> `action: save_outline`
- `/commit` -> `action: commit`
- `/world_model` -> `action: update_world_model`

错误码：
- `INVALID_PAYLOAD`
- `MISSING_FIELD`
- `ACTION_MISMATCH`

重试策略建议：

1. `INVALID_PAYLOAD`：不重试，直接修请求格式。
2. `MISSING_FIELD`：补字段后重发。
3. `ACTION_MISMATCH`：修 action 与端点匹配关系后重发。
4. 网络超时：指数退避（1s/2s/4s，最多 3 次）。

## 6. 最小可跑通参数集

若你只想先跑通闭环：

1. `HTTP_CheckoutWorld`
2. `HTTP_GetOutlines?latest=1&full=1`
3. `Agent_WorldModel_Synthesizer`（内部自行做 gap analysis）
4. `HTTP_UpdateWorld`

只要保证 Agent 同时读到 `current_state + target_outline`，就满足 v2.4 主动推演的底线。
