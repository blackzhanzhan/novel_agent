# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
import json
import subprocess
from datetime import datetime
from pathlib import Path


DB_CONTAINER = "docker-db_postgres-1"
DATABASE = "dify"
DB_USER = "postgres"
REVIEW_APP_ID = "590dd17b-d9d0-4d5b-bffa-e6f1d8e45810"

DISCOVERY_CONTRACT = """## 主动领域发现流程（必须执行）
- 不允许只做泛泛文风审稿。每轮审核都必须先过三道门：既有规则门、历史错误复盘门、新领域候选门。
- 既有规则门：先读 `domain_rules.md`，再调用 `validate_domain_facts` 校验 `chapter_draft.md`。如果出现 violation，审核结论必须是不通过，并说明 rule_id、证据片段、建议交给续写 Agent 局部修复。
- 历史错误复盘门：必须读 `error_archive.md`，把其中已经反复出现或标记为 hard_ban、领域规则候选、机制缺口的条目，与本轮新增/变更章节逐项对照。近似复发也要指出，不得因为措辞变化而放过同类错误。
- 新领域候选门：对 `domain_rules.md` 未覆盖但影响后续续写的领域、题材、机制、职业流程、规则、地图、武器、经济、组织制度、能力体系、时间线或专有名词错误，必须形成“领域规则候选”写入 `error_archive.md`，交给 world Agent 后续维护成 `domain-rule`。
- 候选只来自当前书库证据、草稿上下文、既有设定、状态卡、摘要、章节大纲或作者确认；证据不足时写“待确认候选”，不得硬造题材规则。
- 审核通过前必须能解释：已有规则是否通过、历史错误是否复发、是否发现新的可复用领域候选。只要任一门不通过，就不能输出“审核通过”。

## error_archive.md 领域候选写入格式
- 只有真实、可复用、会影响后续续写的问题才写入；临时吐槽、一次性措辞建议、纯文风口味不要写入。
- 写入时只允许使用草稿写入工具写 `error_archive.md`，严禁写 `chapter_draft.md`、`domain_rules.md` 或其他文件。
- 候选条目必须包含以下字段，缺一不可：
  - `类型`: 领域规则候选 或 机制缺口
  - `严重度`: error / warning / info
  - `触发文本`: 从 `chapter_draft.md` 精确摘录的短片段
  - `证据来源`: 来自哪个文件或上下文，例如 `chapter_draft.md`、`world_model.md`、`status_card.md`、`summary.md`、`chapter_outline.md`、`error_archive.md`
  - `问题说明`: 为什么这是领域/机制错误，而不是一次性审稿意见
  - `建议规则类型`: `context_forbidden_terms`、`regex_forbidden`、`ordered_patterns_forbidden` 或 `forbidden_terms`
  - `正例烟测`: 将来应触发违例的最小片段
  - `负例烟测`: 将来不应误伤的最小片段
  - `需要 world Agent 确认`: 需要确认的底层规则或证据缺口
- 如果本轮只发现已有 `domain_rules.md` 能覆盖的违例，优先在审核意见里报告，不要重复写入同一条旧候选；如果发现旧规则漏检或误伤，写入“机制缺口”。"""

QUERY_SUFFIX = (
    "审核时必须执行三道门：既有规则门 validate_domain_facts、历史错误复盘门、新领域候选门。"
    "发现未覆盖但可复用的领域机制错误时，只能把结构化候选写入 error_archive.md，不能修改正文或 domain_rules.md。"
)


def run_psql(sql: str) -> str:
    return subprocess.check_output(
        ["docker", "exec", DB_CONTAINER, "psql", "-U", DB_USER, "-d", DATABASE, "-t", "-A", "-c", sql],
        text=True,
    ).strip()


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def dollar(value: str) -> str:
    return "$codex$" + value.replace("$codex$", "$co dex$") + "$codex$"


def fetch_rows() -> list[dict]:
    raw = run_psql(
        "select encode(convert_to(coalesce(json_agg(row_to_json(t))::text,'[]'),'UTF8'),'base64') "
        f"from (select id,app_id,version,graph,updated_at from workflows where app_id={sql_literal(REVIEW_APP_ID)} order by version) t;"
    )
    return json.loads(base64.b64decode("".join(raw.split())).decode("utf-8"))


def remove_section(text: str, heading: str) -> str:
    marker = "\n\n" + heading
    start = text.find(marker)
    if start < 0:
        return text
    next_heading = text.find("\n\n## ", start + len(marker))
    if next_heading < 0:
        return text[:start].rstrip()
    return (text[:start].rstrip() + text[next_heading:]).rstrip()


def remove_query_suffix(text: str) -> str:
    marker = "\n\n审核时必须执行三道门："
    idx = text.find(marker)
    if idx >= 0:
        return text[:idx].rstrip()
    return text


def patch_graph(graph: dict) -> dict:
    for node in graph.get("nodes", []):
        params = (node.get("data") or {}).get("agent_parameters") or {}
        if not params:
            continue
        instruction_param = params.get("instruction")
        if isinstance(instruction_param, dict):
            instruction = instruction_param.get("value") or ""
            instruction = remove_section(instruction, "## 主动领域发现流程（必须执行）")
            instruction = remove_section(instruction, "## error_archive.md 领域候选写入格式")
            instruction_param["value"] = instruction.rstrip() + "\n\n" + DISCOVERY_CONTRACT

        query_param = params.get("query")
        if isinstance(query_param, dict):
            query = remove_query_suffix(query_param.get("value") or "")
            query_param["value"] = query.rstrip() + "\n\n" + QUERY_SUFFIX
    return graph


def graph_stats(graph: dict) -> list[dict]:
    rows = []
    for node in graph.get("nodes", []):
        params = (node.get("data") or {}).get("agent_parameters") or {}
        if not params:
            continue
        instruction = params.get("instruction", {}).get("value", "") if isinstance(params.get("instruction"), dict) else ""
        query = params.get("query", {}).get("value", "") if isinstance(params.get("query"), dict) else ""
        tools = []
        if isinstance(params.get("tools"), dict):
            tools = [tool.get("tool_name") for tool in params["tools"].get("value", []) if isinstance(tool, dict)]
        rows.append(
            {
                "node_id": node.get("id"),
                "title": (node.get("data") or {}).get("title"),
                "instruction_qmarks": instruction.count("?"),
                "query_qmarks": query.count("?"),
                "has_discovery_contract": "主动领域发现流程" in instruction and "历史错误复盘门" in instruction,
                "has_candidate_format": "正例烟测" in instruction and "负例烟测" in instruction,
                "has_query_suffix": "审核时必须执行三道门" in query,
                "has_validate_domain_facts": "validate_domain_facts" in tools,
                "has_error_archive_write_tool": "draft_append_markdown_section" in tools,
                "forbidden_write_tools_absent": not any(
                    tool in tools
                    for tool in [
                        "draft_replace_text",
                        "draft_replace_markdown_section",
                        "draft_sync_markdown_sections",
                        "draft_sync_all",
                    ]
                ),
            }
        )
    return rows


def main() -> None:
    runtime = Path(".runtime")
    runtime.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    rows = fetch_rows()
    if not rows:
        raise SystemExit("review workflow rows not found")

    backup_path = runtime / f"dify_review_discovery_prompt_backup_{ts}.json"
    backup_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    updates: list[tuple[str, str]] = []
    verify: dict[str, object] = {"versions": {}}
    for row in rows:
        graph = patch_graph(json.loads(row["graph"]))
        updates.append((row["id"], json.dumps(graph, ensure_ascii=False, separators=(",", ":"))))
        verify["versions"][row["version"]] = graph_stats(graph)

    sql_lines = ["begin;"]
    for workflow_id, graph_text in updates:
        sql_lines.append("update workflows")
        sql_lines.append(f"set graph = {dollar(graph_text)}, updated_at = now()")
        sql_lines.append(f"where id = {sql_literal(workflow_id)};")
    sql_lines.append(f"update apps set updated_at = now() where id = {sql_literal(REVIEW_APP_ID)};")
    sql_lines.append("commit;")

    sql_path = runtime / f"patch_dify_review_discovery_prompt_{ts}.sql"
    sql_path.write_text("\n".join(sql_lines), encoding="utf-8")
    subprocess.check_call(["docker", "cp", str(sql_path), f"{DB_CONTAINER}:/tmp/{sql_path.name}"])
    subprocess.check_call(["docker", "exec", DB_CONTAINER, "psql", "-U", DB_USER, "-d", DATABASE, "-f", f"/tmp/{sql_path.name}"])

    all_ok = True
    for stats in verify["versions"].values():
        for row in stats:
            all_ok = all_ok and row["instruction_qmarks"] == 0 and row["query_qmarks"] == 0
            all_ok = all_ok and row["has_discovery_contract"] and row["has_candidate_format"]
            all_ok = all_ok and row["has_query_suffix"]
            all_ok = all_ok and row["has_validate_domain_facts"] and row["has_error_archive_write_tool"]
            all_ok = all_ok and row["forbidden_write_tools_absent"]
    verify["backup"] = str(backup_path)
    verify["sql"] = str(sql_path)
    verify["all_ok"] = all_ok

    verify_path = runtime / f"patch_dify_review_discovery_prompt_verify_{ts}.json"
    verify_path.write_text(json.dumps(verify, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"backup": str(backup_path), "sql": str(sql_path), "verify": str(verify_path), "all_ok": all_ok}, ensure_ascii=True))
    if not all_ok:
        raise SystemExit("review discovery prompt verification failed")


if __name__ == "__main__":
    main()
