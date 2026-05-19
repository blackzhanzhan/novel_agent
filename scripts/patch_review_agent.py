"""Clean review agent prompt surfaces in live Dify workflows.

The Dify PostgreSQL database is the runtime truth. This script keeps the
review workflow topology, model, tools, and responsibilities intact, then
normalizes the human-facing prompt surfaces that previously carried stale
book-specific examples, English tool blurbs, or mojibake.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime"

DB_CONTAINER = "docker-db_postgres-1"
DB_NAME = "dify"
APP_ID = "b3574a2f-d599-4641-bf77-4f5adf9fd089"
TOOL_PROVIDER_ID = "c41fee3b-54dd-4e49-af9b-be30f68f6242"
EXPECTED_MODEL_PROVIDER = "langgenius/deepseek/deepseek"
EXPECTED_MODEL = "deepseek-v4-flash"
EXPECTED_NODE_COUNT = 3
EXPECTED_EDGE_COUNT = 2

START_VARIABLE_SURFACES = {
    "book_name": {
        "hint": "当前书籍名称；如果前端已传入 book_id，可以保持为空。",
        "placeholder": "例如：我的作品",
    },
    "book_id": {
        "hint": "当前书库标识；由前端自动传入时优先使用。",
        "placeholder": "例如：book_xxx",
    },
    "active_file": {
        "hint": "本轮需要审核的草稿文件名，通常为 chapter_draft.md。",
        "placeholder": "chapter_draft.md",
    },
}

TOOL_DESCRIPTION_OVERRIDES = {
    "get_markdown_outline": "读取指定 Markdown 文件的标题结构、section_path 与 base_etag，用于安全定位审核目标和写入前校验。",
    "get_markdown_section": "读取指定 Markdown 文件的局部章节内容，用于核对草稿、章卡、世界观、状态和错误档案证据。",
    "get_archive_range": "按范围读取书库归档内容，用于抽样核对原文、摘要、世界观、状态和大纲证据。",
    "get_core_archive": "读取书库核心档案，用于快速取得当前作品的关键上下文；大文件只在必要时兜底使用。",
    "extract_chapter_highlights": "只读抽取章节高价值片段，用于给审核判断提供原文证据，不写入任何文件。",
    "validate_chapter_lengths": "只读统计 chapter_draft.md 中各章节篇幅，返回非空白字符数、目标线、缺口和状态；不写文件。",
    "draft_append_markdown_section": "在 draft/sandbox 分支向指定 Markdown 文件追加完整子章节；审核智能体只允许用于 error_archive.md 的可复用问题记录。",
    "draft_replace_markdown_section": "在 draft/sandbox 分支替换指定 Markdown section；content 必须包含目标标题行，base_etag 必须来自最近读取结果。",
}

STALE_TEXT_FRAGMENTS = (
    "donk",
    "????",
    "Flat append tool",
    "Flat replace tool",
    "Dify Agents",
    "MUST",
)


def run(args: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        input=input_text,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def psql(args: list[str], *, input_text: str | None = None) -> str:
    docker_args = ["docker", "exec"]
    if input_text is not None:
        docker_args.append("-i")
    docker_args.extend(
        [
            DB_CONTAINER,
            "psql",
            "-U",
            "postgres",
            "-d",
            DB_NAME,
            "-v",
            "ON_ERROR_STOP=1",
            *args,
        ]
    )
    proc = run(docker_args, input_text=input_text)
    if proc.returncode:
        raise RuntimeError(
            "psql failed\n"
            f"COMMAND: {' '.join(a for a in proc.args if a)}\n"
            f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return proc.stdout


def psql_at(sql: str) -> list[str]:
    out = psql(["-A", "-t", "-F", "\t", "-c", sql])
    return [line for line in out.splitlines() if line.strip()]


def dollar_quote(value: str) -> str:
    for tag in ("codex", "codex_review", "codex_review2"):
        marker = f"${tag}$"
        if marker not in value:
            return f"{marker}{value}{marker}"
    raise ValueError("Cannot build a safe dollar-quoted SQL string")


def sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def load_review_workflows() -> tuple[str, list[dict[str, Any]]]:
    app_rows = psql_at(
        f"""
        select id::text, workflow_id::text, name, mode
        from apps
        where id = '{APP_ID}'
        """
    )
    if len(app_rows) != 1:
        raise RuntimeError(f"Expected one review app row, found {len(app_rows)}")
    app_id, live_workflow_id, app_name, app_mode = app_rows[0].split("\t")
    if app_id != APP_ID:
        raise RuntimeError(f"Unexpected review app id: {app_id}")
    if app_mode != "advanced-chat":
        raise RuntimeError(f"Unexpected review app mode for {app_name}: {app_mode}")

    rows = psql_at(
        f"""
        select
            w.id::text,
            case when w.id = a.workflow_id then 'live' else w.version end,
            encode(convert_to(w.graph::text, 'UTF8'), 'hex')
        from workflows w
        join apps a on a.id = w.app_id
        where w.app_id = '{APP_ID}'
        order by case when w.id = a.workflow_id then 0 when w.version = 'draft' then 1 else 2 end,
                 w.updated_at desc nulls last,
                 w.created_at desc nulls last
        """
    )
    if not rows:
        raise RuntimeError("No review workflows found")

    workflows: list[dict[str, Any]] = []
    for row in rows:
        workflow_id, version, graph_hex = row.split("\t", 2)
        graph_text = bytes.fromhex(graph_hex).decode("utf-8")
        workflows.append({"id": workflow_id, "version": version, "graph_text": graph_text, "graph": json.loads(graph_text)})

    if not any(item["id"] == live_workflow_id and item["version"] == "live" for item in workflows):
        raise RuntimeError("Live review workflow row was not loaded")
    if not any(item["version"] == "draft" for item in workflows):
        raise RuntimeError("Draft review workflow row was not loaded")
    return live_workflow_id, workflows


def start_nodes(graph: dict[str, Any]) -> list[dict[str, Any]]:
    return [node for node in graph.get("nodes", []) if (node.get("data") or {}).get("type") == "start"]


def agent_nodes(graph: dict[str, Any]) -> list[dict[str, Any]]:
    return [node for node in graph.get("nodes", []) if isinstance((node.get("data") or {}).get("agent_parameters"), dict)]


def agent_tool_entries(node: dict[str, Any]) -> list[dict[str, Any]]:
    tools = node.get("data", {}).get("agent_parameters", {}).get("tools", {}).get("value", [])
    if not isinstance(tools, list):
        raise RuntimeError("Review agent tools value is not a list")
    if not all(isinstance(tool, dict) for tool in tools):
        raise RuntimeError("Review agent tool entry is not a dict")
    return tools


def patch_start_variables(graph: dict[str, Any]) -> bool:
    changed = False
    starts = start_nodes(graph)
    if len(starts) != 1:
        raise RuntimeError(f"Expected one review start node, found {len(starts)}")
    variables = starts[0].setdefault("data", {}).setdefault("variables", [])
    if not isinstance(variables, list):
        raise RuntimeError("Review start variables are not a list")
    for variable in variables:
        if not isinstance(variable, dict):
            continue
        variable_name = variable.get("variable")
        if not isinstance(variable_name, str):
            continue
        desired = START_VARIABLE_SURFACES.get(variable_name)
        if desired is None:
            continue
        for key, value in desired.items():
            if variable.get(key) != value:
                variable[key] = value
                changed = True
    return changed


def patch_tool_surfaces(graph: dict[str, Any]) -> bool:
    changed = False
    agents = agent_nodes(graph)
    if len(agents) != 1:
        raise RuntimeError(f"Expected one review agent node, found {len(agents)}")
    for entry in agent_tool_entries(agents[0]):
        tool_name = entry.get("tool_name")
        if entry.get("provider_show_name") != "LoreGit 后端工具集":
            entry["provider_show_name"] = "LoreGit 后端工具集"
            changed = True
        if not isinstance(tool_name, str):
            continue
        description = TOOL_DESCRIPTION_OVERRIDES.get(tool_name)
        if description is None:
            continue
        if entry.get("tool_description") != description:
            entry["tool_description"] = description
            changed = True
        extra = entry.setdefault("extra", {})
        if isinstance(extra, dict) and extra.get("description") != description:
            extra["description"] = description
            changed = True
    return changed


def validate_workflow(graph: dict[str, Any], *, label: str) -> dict[str, Any]:
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise RuntimeError(f"{label} review graph is missing nodes or edges arrays")
    if len(nodes) != EXPECTED_NODE_COUNT or len(edges) != EXPECTED_EDGE_COUNT:
        raise RuntimeError(f"{label} review topology changed unexpectedly: nodes={len(nodes)}, edges={len(edges)}")

    agents = agent_nodes(graph)
    if len(agents) != 1:
        raise RuntimeError(f"{label} expected one review agent node, found {len(agents)}")
    params = agents[0].get("data", {}).get("agent_parameters", {})
    model = (params.get("model") or {}).get("value") or {}
    if model.get("provider") != EXPECTED_MODEL_PROVIDER or model.get("model") != EXPECTED_MODEL:
        raise RuntimeError(f"{label} review model changed unexpectedly: {model}")
    completion_params = model.get("completion_params") if isinstance(model.get("completion_params"), dict) else {}
    if completion_params.get("thinking") is not True:
        raise RuntimeError(f"{label} review thinking mode is not enabled: {completion_params}")

    tools = [tool.get("tool_name") for tool in agent_tool_entries(agents[0])]
    graph_text = json.dumps(graph, ensure_ascii=False)
    for marker in STALE_TEXT_FRAGMENTS:
        if marker in graph_text:
            raise RuntimeError(f"{label} review graph still contains stale marker: {marker}")

    return {
        "nodes": len(nodes),
        "edges": len(edges),
        "tools": tools,
        "tool_count": len(tools),
        "graph_sha": sha_text(graph_text),
    }


def patch_graph(graph: dict[str, Any]) -> bool:
    changed = False
    changed = patch_start_variables(graph) or changed
    changed = patch_tool_surfaces(graph) or changed
    return changed


def backup(workflows: list[dict[str, Any]], stamp: str) -> Path:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    out = RUNTIME / f"review_agent_workflow_backup_{stamp}.json"
    payload = {
        "app_id": APP_ID,
        "workflows": [
            {
                "id": item["id"],
                "version": item["version"],
                "graph_sha": sha_text(item["graph_text"]),
                "graph": item["graph"],
            }
            for item in workflows
        ],
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def update_workflows(workflows: list[dict[str, Any]]) -> None:
    statements = ["begin;"]
    for item in workflows:
        graph_text = json.dumps(item["graph"], ensure_ascii=False, separators=(",", ":"))
        statements.append(
            "update workflows "
            f"set graph = {dollar_quote(graph_text)}, updated_at = now() "
            f"where id = '{item['id']}';"
        )
    statements.append(f"update apps set updated_at = now() where id = '{APP_ID}';")
    statements.append("commit;")
    psql([], input_text="\n".join(statements) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="validate and preview without DB writes")
    args = parser.parse_args()

    live_workflow_id, workflows = load_review_workflows()
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup(workflows, stamp)

    before_workflows = {}
    after_workflows = {}
    workflow_changed = False
    for item in workflows:
        before_workflows[item["id"]] = {
            "version": item["version"],
            "graph_sha": sha_text(json.dumps(item["graph"], ensure_ascii=False)),
        }
        changed = patch_graph(item["graph"])
        workflow_changed = changed or workflow_changed
        after_workflows[item["id"]] = {
            "version": item["version"],
            **validate_workflow(item["graph"], label=f"after:{item['version']}"),
            "changed": changed,
        }

    if workflow_changed and not args.dry_run:
        update_workflows(workflows)

    print(
        json.dumps(
            {
                "app_id": APP_ID,
                "tool_provider_id": TOOL_PROVIDER_ID,
                "live_workflow_id": live_workflow_id,
                "backup": str(backup_path.relative_to(ROOT)),
                "dry_run": args.dry_run,
                "changed": workflow_changed,
                "workflow_changed": workflow_changed,
                "workflow_ids": [{"id": item["id"], "version": item["version"]} for item in workflows],
                "before_workflows": before_workflows,
                "after_workflows": after_workflows,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
