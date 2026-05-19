"""Patch live Dify style workflow and LoreGit ToolProvider.

The Dify PostgreSQL database is the runtime truth for this project. This script
keeps the current style workflow topology and model settings intact, then:

- exposes LoreGit generate_style_diagnostics on the live ToolProvider;
- refreshes the style-related OpenAPI snippets so style artifact files are valid
  read/write targets;
- updates the style Agent prompt/tool list so initialization/rebuild requests
  hand off to the promptless backend `/api/style/init_pipeline`, while the
  chat Agent remains a post-init discussion and refinement assistant.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime"
OPENAPI_PATH = ROOT / "novel_git_server" / "docs" / "openapi_v3_5_1_draft_min.json"

DB_CONTAINER = "docker-db_postgres-1"
DB_NAME = "dify"
APP_ID = "bb3232af-7106-43ba-ae65-4f6e7fc82943"
TOOL_PROVIDER_ID = "c41fee3b-54dd-4e49-af9b-be30f68f6242"
EXPECTED_MODEL_PROVIDER = "langgenius/deepseek/deepseek"
EXPECTED_MODEL = "deepseek-v4-flash"
EXPECTED_NODE_COUNT = 3
EXPECTED_EDGE_COUNT = 2

STYLE_ARTIFACTS = [
    "style_fingerprint.md",
    "style_review.md",
    "style_constraints_for_continuation.md",
]

STYLE_FILE_TARGETS = [
    "style_guide.md",
    "style_constraints_for_continuation.md",
    "style_review.md",
    "style_fingerprint.md",
]

OPERATION_PATHS = {
    "get_markdown_outline": ("get", "/books/get_markdown_outline"),
    "get_markdown_section": ("get", "/books/get_markdown_section"),
    "get_archive_range": ("get", "/books/get_archive_range"),
    "get_core_archive": ("get", "/books/get_file"),
    "extract_chapter_highlights": ("post", "/tools/extract_chapter_highlights"),
    "generate_style_diagnostics": ("post", "/tools/generate_style_diagnostics"),
    "draft_append_markdown_section": ("post", "/api/draft/append_markdown_section"),
    "draft_replace_markdown_section": ("post", "/api/draft/replace_markdown_section"),
    "draft_sync_markdown_sections": ("post", "/api/draft/sync_markdown_sections"),
}

STYLE_AGENT_TOOLS = [
    "get_core_archive",
    "extract_chapter_highlights",
    "get_archive_range",
    "get_markdown_outline",
    "get_markdown_section",
    "generate_style_diagnostics",
    "draft_append_markdown_section",
    "draft_replace_markdown_section",
]

TOOL_DESCRIPTION_OVERRIDES = {
    "get_markdown_outline": "读取指定 Markdown 文件的标题结构、section_path 与 base_etag，用于安全定位和写入前校验。",
    "get_markdown_section": "读取指定 Markdown 文件的局部章节内容，用于小范围取证、对齐和修订前确认。",
    "get_archive_range": "按范围读取书库归档内容，用于抽样核对摘要、原文样本、世界观、状态和文风证据。",
    "get_core_archive": "读取书库核心档案，用于快速取得当前作品的关键上下文；大文件只在必要时兜底使用。",
    "extract_chapter_highlights": "只读抽取章节高价值片段，用于给文风判断提供原文证据，不写入任何文件。",
    "generate_style_diagnostics": "只读生成文风诊断与打磨提示，把结果作为作者讨论参考；不写文件，不充当初始化入口。",
    "draft_append_markdown_section": "在 draft/sandbox 分支向指定 Markdown 文件追加完整子章节；参数必须扁平，file_name 只能是裸文件名。",
    "draft_replace_markdown_section": "在 draft/sandbox 分支替换指定 Markdown section；content 必须包含目标标题行，base_etag 必须来自最近读取结果。",
    "draft_sync_markdown_sections": "在 draft/sandbox 分支同步多个 Markdown 区块；文风助手默认不使用，除非专门脚本需要。",
}

PROMPT_MARKERS = [
    "STYLE_INIT_PIPELINE_HANDOFF",
    "/api/style/init_pipeline",
    "右下角「动作」面板",
    "STYLE_POST_INIT_REFINEMENT_PROTOCOL",
    "generate_style_diagnostics",
    "style_fingerprint.md",
    "style_review.md",
    "style_constraints_for_continuation.md",
    "explicit_user_write",
    "file_name 只能填写裸文件名",
]

STYLE_AGENT_QUERY = """当前书籍：{{#1771595354723.book_name#}}
当前 book_id：{{#1771595354723.book_id#}}
当前目标文件：{{#1771595354723.active_file#}}
用户当前意图：{{#sys.query#}}

你是可读可写的文风学习 Agent，但你不再承担初始化入口。先判断本轮是初始化/重建、只读讨论，还是初始化后的局部文风档案修订。

STYLE_INIT_PIPELINE_HANDOFF：
1. “初始化文风”“重建文风”“完整重跑文风”“生成文风三件套”“重新生成 style_fingerprint.md / style_review.md / style_constraints_for_continuation.md”都属于固定后台管线任务。
2. 这类任务必须交给本地后端 `/api/style/init_pipeline`，由右下角「动作」面板的“初始化/重建文风档案”按钮执行；聊天 Agent 不得接管。
3. 对初始化/重建请求，不得调用 generate_style_diagnostics 来生成三件套，不得调用 draft_append_markdown_section 或 draft_replace_markdown_section 写入三件套，不得宣称自己完成初始化。
4. 回答时只做用户指引：说明应使用右下角「动作」面板，并说明文风助手只负责初始化后的讨论、解释和局部修订。

STYLE_POST_INIT_REFINEMENT_PROTOCOL：
1. 初始化完成后，你可以读取 style_guide.md、style_fingerprint.md、style_review.md、style_constraints_for_continuation.md、summary.md、章节高光和必要原文片段，帮助作者理解、质疑、补充或收束文风档案。
2. generate_style_diagnostics 只允许作为诊断/证据工具使用，不能作为聊天内初始化/重建入口。
3. 只有作者明确要求“把这条补进文风档案”“修改这个判断”“按刚刚讨论更新文风提示”时，才允许写入最小 Markdown 区块。
4. 写入目标可以是 style_guide.md、style_fingerprint.md、style_review.md、style_constraints_for_continuation.md；style_guide.md 不能替代三件套初始化。
5. 只读讨论结尾必须说明“本轮未写入草稿”。

扁平写入工具纪律：
1. 只读讨论只调用读取工具，结尾说明“本轮未写入草稿”。
2. 明确写入时，只允许调用 draft_append_markdown_section 或 draft_replace_markdown_section。
3. 写入参数必须一层平铺：book_id 或 book_name、file_name、section_path、content、base_etag、origin、message；file_name 只能填写裸文件名，不得携带 draft/sandbox 或任何路径前缀。
4. origin 必须正好填写 explicit_user_write；base_etag 必须来自最近一次 get_markdown_outline、get_markdown_section 或 get_core_archive。
5. 工具成功后，用自然语言说明更新文件、落点和 commit_id；工具失败时，不要假称已经写入。
"""

STYLE_AGENT_INSTRUCTION = """STYLE_AGENT：文风学习、诊断与初始化后协作修订 Agent

你负责在文风初始化完成后，和作者讨论、解释、校准并局部修订文风相关文件。你是 post-init 文风助手，不是初始化入口；写入必须由用户明确意图触发。

输入上下文：
- 书籍：{{#1771595354723.book_name#}}
- book_id：{{#1771595354723.book_id#}}
- 目标文件：{{#1771595354723.active_file#}}
- 用户请求：{{#sys.query#}}

STYLE_INIT_PIPELINE_HANDOFF：
1. “初始化文风”“重建文风”“完整重跑文风”“生成文风三件套”不是聊天写入任务，而是无提示词后台任务。
2. 后台入口是 `/api/style/init_pipeline`，前台入口是右下角「动作」面板的“初始化/重建文风档案”。
3. 遇到这类请求时，不得调用 generate_style_diagnostics 去生成三件套，不得写入 style_fingerprint.md、style_review.md、style_constraints_for_continuation.md 来冒充初始化完成。
4. 你必须把用户引导回动作面板，并说明自己负责初始化后的讨论、解释和局部修订。

STYLE_POST_INIT_REFINEMENT_PROTOCOL：
1. 你可以帮助作者检查三件套是否准确、是否太硬、是否应该加入作者偏好、是否要把某些文风约束退化成续写提示。
2. 你可以读取最新原文、style_guide.md 和三件套，必要时调用 generate_style_diagnostics 作为诊断证据；诊断结果只是讨论依据，不是初始化执行权。
3. 作者明确要求写入时，只做最小必要区块补丁，不重建整套文风档案。
4. 写入内容必须服务作者复用：类别名、触发条件、原文证据、可模仿规则、给 continuation 的提示要清晰。
5. 如果只是讨论或证据不足，结尾说明“本轮未写入草稿”。

普通文风工作原则：
1. 先判断用户意图：
   - 初始化/重建：交给 `/api/style/init_pipeline`，提示使用右下角「动作」面板。
   - 明确写入：更新文风指南、补充 style_guide、按作者讨论修订三件套、同步切片、写入草稿、把这些归档、纳入模板。
   - 只读讨论：分析文风、解释怎么写、找证据看看、先评价、只读、不要写、暂不落稿。
2. 只有明确写入时，才允许调用 draft_append_markdown_section 或 draft_replace_markdown_section；调用时 origin 必须填 explicit_user_write。
3. 只读讨论时可以读取 summary、章节高光、style_guide 和三份文风产物，但不得写入；结尾明确“本轮未写入草稿”。
4. 推荐读取顺序：summary.md 定位高价值章节；extract_chapter_highlights 抽取原文证据；generate_style_diagnostics 做结构化文风诊断；get_markdown_outline 定位目标标题；get_markdown_section 校验目标区块。
5. 写入只做最小必要区块补丁：优先替换目标文件顶层区块；新增子标题或局部规则时才 append_under_section。
6. 写入内容必须服务作者复用：类别名、触发条件、原文证据、可模仿规则要清晰；不要堆砌无归纳价值的句子。
7. 若证据不足、section_path 歧义、用户只要讨论或明确禁止写入，停止写入并给出下一步建议。
8. 不输出隐藏控制标记；不要调用 draft_sync_all、draft_confirm、draft_rollback。

扁平写入工具纪律：
1. 只读讨论只调用读取工具，结尾说明“本轮未写入草稿”。
2. 明确写入时，只允许调用 draft_append_markdown_section 或 draft_replace_markdown_section。
3. 写入参数必须一层平铺：book_id 或 book_name、file_name、section_path、content、base_etag、origin、message。不要构造嵌套数组、批量补丁、隐藏控制标记或工具参数文本。
   file_name 只能填写裸文件名，不得携带 draft/sandbox 或任何路径前缀。
4. 新增子标题或新规则用 draft_append_markdown_section；替换已有标题块用 draft_replace_markdown_section。
5. origin 必须正好填写 explicit_user_write；base_etag 必须来自最近一次 get_markdown_outline、get_markdown_section 或 get_core_archive。
6. 工具成功后，用自然语言说明更新文件、落点和 commit_id；工具失败时，不要假称已经写入。
"""


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
    for tag in ("codex", "codex_style", "codex_style2"):
        marker = f"${tag}$"
        if marker not in value:
            return f"{marker}{value}{marker}"
    raise ValueError("Cannot build a safe dollar-quoted SQL string")


def sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def load_openapi() -> dict[str, Any]:
    return json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))


def operation_from_openapi(openapi: dict[str, Any], operation_id: str) -> tuple[str, str, dict[str, Any]]:
    method, path = OPERATION_PATHS[operation_id]
    try:
        operation = openapi["paths"][path][method]
    except KeyError as exc:
        raise RuntimeError(f"Local OpenAPI missing {operation_id} at {method.upper()} {path}") from exc
    return method, path, deepcopy(operation)


def server_base(schema: dict[str, Any], tools: list[dict[str, Any]]) -> str:
    for server in schema.get("servers", []):
        if isinstance(server, dict) and isinstance(server.get("url"), str) and server["url"].strip():
            return server["url"].rstrip("/")
    for tool in tools:
        raw = tool.get("server_url")
        if isinstance(raw, str) and "/" in raw:
            return raw.rsplit("/", 1)[0].rstrip("/")
    return "http://host.docker.internal:8001"


def request_schema(operation: dict[str, Any]) -> tuple[dict[str, Any], set[str]]:
    body = operation.get("requestBody")
    if not isinstance(body, dict):
        return {}, set()
    content = body.get("content")
    if not isinstance(content, dict):
        return {}, set()
    app_json = content.get("application/json")
    if not isinstance(app_json, dict):
        return {}, set()
    schema = app_json.get("schema")
    if not isinstance(schema, dict):
        return {}, set()
    required = schema.get("required")
    return schema.get("properties") or {}, set(required if isinstance(required, list) else [])


def dify_type(openapi_type: Any) -> str:
    if openapi_type in {"integer", "number"}:
        return "number"
    if openapi_type == "array":
        return "array"
    if openapi_type == "boolean":
        return "boolean"
    return "string"


def parameter_entry(name: str, schema: dict[str, Any], *, required: bool) -> dict[str, Any]:
    description = schema.get("description") if isinstance(schema.get("description"), str) else ""
    default = schema.get("default") if "default" in schema else None
    return {
        "name": name,
        "label": {"en_US": name, "zh_Hans": name, "pt_BR": name, "ja_JP": name},
        "placeholder": {"en_US": description, "zh_Hans": description, "pt_BR": description, "ja_JP": description},
        "scope": None,
        "auto_generate": None,
        "template": None,
        "required": required,
        "default": default,
        "min": schema.get("minimum"),
        "max": schema.get("maximum"),
        "precision": None,
        "options": [],
        "type": dify_type(schema.get("type")),
        "human_description": {"en_US": description, "zh_Hans": description, "pt_BR": description, "ja_JP": description},
        "form": "llm",
        "llm_description": description,
        "input_schema": None,
    }


def build_tool_entry(operation_id: str, openapi: dict[str, Any], base_url: str) -> dict[str, Any]:
    method, path, operation = operation_from_openapi(openapi, operation_id)
    description = (
        TOOL_DESCRIPTION_OVERRIDES.get(operation_id)
        or operation.get("description")
        or operation.get("summary")
        or operation_id
    )
    operation["summary"] = description
    operation["description"] = description
    parameters: list[dict[str, Any]] = []

    if "parameters" in operation:
        for raw_param in operation.get("parameters") or []:
            if not isinstance(raw_param, dict):
                continue
            name = raw_param.get("name")
            if not isinstance(name, str):
                continue
            schema = raw_param.get("schema") if isinstance(raw_param.get("schema"), dict) else {}
            merged = {**schema}
            if isinstance(raw_param.get("description"), str):
                merged.setdefault("description", raw_param["description"])
            parameters.append(parameter_entry(name, merged, required=bool(raw_param.get("required"))))
    else:
        props, required = request_schema(operation)
        for name, schema in props.items():
            if isinstance(schema, dict):
                parameters.append(parameter_entry(name, schema, required=name in required))

    return {
        "server_url": f"{base_url}{path}",
        "method": method,
        "summary": description,
        "operation_id": operation_id,
        "parameters": parameters,
        "author": "",
        "icon": None,
        "openapi": operation,
        "output_schema": {},
    }


def load_provider() -> dict[str, Any]:
    rows = psql_at(
        f"""
        select
            encode(convert_to(schema, 'UTF8'), 'hex'),
            encode(convert_to(tools_str, 'UTF8'), 'hex'),
            name,
            schema_type_str
        from tool_api_providers
        where id = '{TOOL_PROVIDER_ID}'
        """
    )
    if len(rows) != 1:
        raise RuntimeError(f"Expected one ToolProvider row, found {len(rows)}")
    schema_hex, tools_hex, name, schema_type = rows[0].split("\t", 3)
    schema_text = bytes.fromhex(schema_hex).decode("utf-8")
    tools_text = bytes.fromhex(tools_hex).decode("utf-8")
    return {
        "id": TOOL_PROVIDER_ID,
        "name": name,
        "schema_type_str": schema_type,
        "schema_text": schema_text,
        "tools_text": tools_text,
        "schema": json.loads(schema_text),
        "tools": json.loads(tools_text),
    }


def patch_provider(provider: dict[str, Any], openapi: dict[str, Any]) -> bool:
    changed = False
    schema = provider["schema"]
    tools = provider["tools"]
    base_url = server_base(schema, tools)

    schema.setdefault("servers", [{"url": base_url}])
    paths = schema.setdefault("paths", {})
    for operation_id in OPERATION_PATHS:
        method, path, operation = operation_from_openapi(openapi, operation_id)
        if operation_id == "generate_style_diagnostics" or operation_id in {
            "get_markdown_outline",
            "get_markdown_section",
            "get_core_archive",
            "draft_append_markdown_section",
            "draft_replace_markdown_section",
            "draft_sync_markdown_sections",
        }:
            description = TOOL_DESCRIPTION_OVERRIDES.get(operation_id)
            if description:
                operation["summary"] = description
                operation["description"] = description
            current_path = paths.setdefault(path, {})
            if current_path.get(method) != operation:
                current_path[method] = operation
                changed = True

    tool_by_id = {
        tool.get("operation_id"): index
        for index, tool in enumerate(tools)
        if isinstance(tool, dict)
    }
    for operation_id in OPERATION_PATHS:
        if operation_id == "generate_style_diagnostics" or operation_id in {
            "get_markdown_outline",
            "get_markdown_section",
            "get_core_archive",
            "draft_append_markdown_section",
            "draft_replace_markdown_section",
            "draft_sync_markdown_sections",
        }:
            desired = build_tool_entry(operation_id, openapi, base_url)
            index = tool_by_id.get(operation_id)
            if index is None:
                tools.append(desired)
                tool_by_id[operation_id] = len(tools) - 1
                changed = True
            elif tools[index] != desired:
                tools[index] = desired
                changed = True

    validate_provider(provider)
    return changed


def validate_provider(provider: dict[str, Any]) -> dict[str, Any]:
    schema_text = json.dumps(provider["schema"], ensure_ascii=False)
    tools_text = json.dumps(provider["tools"], ensure_ascii=False)
    operations = [tool.get("operation_id") for tool in provider["tools"] if isinstance(tool, dict)]
    for operation_id in ["generate_style_diagnostics", "draft_replace_markdown_section", "draft_append_markdown_section"]:
        if operation_id not in operations:
            raise RuntimeError(f"ToolProvider missing operation {operation_id}")
    for marker in ["generate_style_diagnostics", *STYLE_ARTIFACTS]:
        if marker not in schema_text or marker not in tools_text:
            raise RuntimeError(f"ToolProvider missing marker after patch: {marker}")
    return {
        "tool_count": len(provider["tools"]),
        "operations": operations,
        "schema_sha": sha_text(schema_text),
        "tools_sha": sha_text(tools_text),
    }


def load_style_workflows() -> tuple[str, list[dict[str, Any]]]:
    app_rows = psql_at(
        f"""
        select id::text, workflow_id::text, name, mode
        from apps
        where id = '{APP_ID}'
        """
    )
    if len(app_rows) != 1:
        raise RuntimeError(f"Expected one style app row, found {len(app_rows)}")
    app_id, live_workflow_id, app_name, app_mode = app_rows[0].split("\t")
    if app_id != APP_ID:
        raise RuntimeError(f"Unexpected style app id: {app_id}")
    if app_mode != "advanced-chat":
        raise RuntimeError(f"Unexpected style app mode for {app_name}: {app_mode}")

    rows = psql_at(
        f"""
        select
            w.id::text,
            case when w.id = a.workflow_id then 'live' else w.version end,
            encode(convert_to(w.graph::text, 'UTF8'), 'hex')
        from workflows w
        join apps a on a.id = w.app_id
        where w.app_id = '{APP_ID}'
          and (w.id = a.workflow_id or w.version = 'draft')
        order by case when w.id = a.workflow_id then 0 else 1 end, w.updated_at desc
        """
    )
    if len(rows) != 2:
        raise RuntimeError(f"Expected live and draft style workflows, found {len(rows)}")

    workflows: list[dict[str, Any]] = []
    for row in rows:
        workflow_id, version, graph_hex = row.split("\t", 2)
        graph_text = bytes.fromhex(graph_hex).decode("utf-8")
        workflows.append({"id": workflow_id, "version": version, "graph_text": graph_text, "graph": json.loads(graph_text)})
    if workflows[0]["id"] != live_workflow_id or workflows[0]["version"] != "live":
        raise RuntimeError("The first style workflow row is not the live workflow")
    if workflows[1]["version"] != "draft":
        raise RuntimeError("The second style workflow row is not the draft workflow")
    return live_workflow_id, workflows


def style_agent_node(graph: dict[str, Any]) -> dict[str, Any]:
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise RuntimeError("Workflow graph is missing nodes or edges arrays")
    if len(nodes) != EXPECTED_NODE_COUNT or len(edges) != EXPECTED_EDGE_COUNT:
        raise RuntimeError(f"Unexpected style topology: nodes={len(nodes)}, edges={len(edges)}")
    agents = [node for node in nodes if (node.get("data") or {}).get("type") == "agent"]
    if len(agents) != 1:
        raise RuntimeError(f"Expected one style agent node, found {len(agents)}")
    return agents[0]


def start_node(graph: dict[str, Any]) -> dict[str, Any]:
    starts = [node for node in graph.get("nodes", []) if (node.get("data") or {}).get("type") == "start"]
    if len(starts) != 1:
        raise RuntimeError(f"Expected one start node, found {len(starts)}")
    return starts[0]


def ensure_start_book_id_variable(graph: dict[str, Any]) -> bool:
    node = start_node(graph)
    variables = node.setdefault("data", {}).setdefault("variables", [])
    if not isinstance(variables, list):
        raise RuntimeError("Start node variables are not a list")
    if any(isinstance(item, dict) and item.get("variable") == "book_id" for item in variables):
        return False
    book_id_variable = {
        "hint": "",
        "type": "text-input",
        "label": "book_id",
        "default": "",
        "options": [],
        "required": False,
        "variable": "book_id",
        "placeholder": "",
    }
    insert_at = 0
    for index, item in enumerate(variables):
        if isinstance(item, dict) and item.get("variable") == "book_name":
            insert_at = index + 1
            break
    variables.insert(insert_at, book_id_variable)
    return True


def agent_tools(node: dict[str, Any]) -> list[dict[str, Any]]:
    tools = node.get("data", {}).get("agent_parameters", {}).get("tools", {}).get("value", [])
    if not isinstance(tools, list):
        raise RuntimeError("Style agent tools value is not a list")
    if not all(isinstance(tool, dict) for tool in tools):
        raise RuntimeError("Style agent tool entry is not a dict")
    return tools


def workflow_tool_entry(tool_name: str, provider_tools: list[dict[str, Any]], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    provider_tool = next((item for item in provider_tools if item.get("operation_id") == tool_name), None)
    if provider_tool is None:
        raise RuntimeError(f"Provider missing tool for workflow entry: {tool_name}")
    description = (
        TOOL_DESCRIPTION_OVERRIDES.get(tool_name)
        or provider_tool.get("summary")
        or provider_tool.get("openapi", {}).get("description")
        or tool_name
    )
    entry = deepcopy(existing) if existing is not None else {}
    entry.update(
        {
            "type": "api",
            "enabled": True,
            "tool_name": tool_name,
            "tool_label": tool_name,
            "provider_name": TOOL_PROVIDER_ID,
            "provider_show_name": "LoreGit 后端工具集",
            "tool_description": description,
            "extra": {"description": description},
            "settings": {},
        }
    )
    params: dict[str, dict[str, int]] = {}
    for param in provider_tool.get("parameters", []):
        name = param.get("name")
        if isinstance(name, str):
            params[name] = {"auto": 1}
    entry["parameters"] = params
    return entry


def validate_workflow(graph: dict[str, Any], *, label: str) -> dict[str, Any]:
    agent = style_agent_node(graph)
    params = agent.get("data", {}).get("agent_parameters", {})
    model = (params.get("model") or {}).get("value") or {}
    if model.get("provider") != EXPECTED_MODEL_PROVIDER or model.get("model") != EXPECTED_MODEL:
        raise RuntimeError(f"{label} style model changed unexpectedly: {model}")
    instruction = (params.get("instruction") or {}).get("value")
    query = (params.get("query") or {}).get("value")
    if not isinstance(instruction, str) or not isinstance(query, str):
        raise RuntimeError(f"{label} style prompt fields are not strings")
    tools = [tool.get("tool_name") for tool in agent_tools(agent)]
    if label.startswith("after:"):
        if tools != STYLE_AGENT_TOOLS:
            raise RuntimeError(f"{label} style tools mismatch: {tools}")
        for marker in PROMPT_MARKERS:
            if marker not in instruction and marker not in query:
                raise RuntimeError(f"{label} style prompt missing marker: {marker}")
        graph_text = json.dumps(graph, ensure_ascii=False)
        for marker in ["generate_style_diagnostics", *STYLE_ARTIFACTS]:
            if marker not in graph_text:
                raise RuntimeError(f"{label} style graph missing marker: {marker}")
    return {
        "nodes": len(graph.get("nodes", [])),
        "edges": len(graph.get("edges", [])),
        "tools": tools,
        "instruction_sha": sha_text(instruction),
        "query_sha": sha_text(query),
        "instruction_len": len(instruction),
        "query_len": len(query),
    }


def patch_workflow(graph: dict[str, Any], provider_tools: list[dict[str, Any]]) -> bool:
    changed = False
    if ensure_start_book_id_variable(graph):
        changed = True
    agent = style_agent_node(graph)
    params = agent.setdefault("data", {}).setdefault("agent_parameters", {})
    if params.setdefault("query", {"type": "constant"}).get("value") != STYLE_AGENT_QUERY:
        params["query"] = {"type": "constant", "value": STYLE_AGENT_QUERY}
        changed = True
    if params.setdefault("instruction", {"type": "constant"}).get("value") != STYLE_AGENT_INSTRUCTION:
        params["instruction"] = {"type": "constant", "value": STYLE_AGENT_INSTRUCTION}
        changed = True
    if params.get("maximum_iterations", {}).get("value") != 45:
        params["maximum_iterations"] = {"type": "constant", "value": 45}
        changed = True

    existing_by_name = {tool.get("tool_name"): tool for tool in agent_tools(agent)}
    desired_tools = [
        workflow_tool_entry(tool_name, provider_tools, existing_by_name.get(tool_name))
        for tool_name in STYLE_AGENT_TOOLS
    ]
    if agent_tools(agent) != desired_tools:
        params.setdefault("tools", {"type": "constant"})["type"] = "constant"
        params["tools"]["value"] = desired_tools
        changed = True
    return changed


def backup(provider: dict[str, Any], workflows: list[dict[str, Any]], stamp: str) -> Path:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    out = RUNTIME / f"style_agent_provider_workflow_backup_{stamp}.json"
    payload = {
        "tool_provider": {
            "id": provider["id"],
            "name": provider["name"],
            "schema_type_str": provider["schema_type_str"],
            "schema_sha": sha_text(provider["schema_text"]),
            "tools_sha": sha_text(provider["tools_text"]),
            "schema": provider["schema"],
            "tools": provider["tools"],
        },
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


def update_provider(provider: dict[str, Any]) -> None:
    schema_text = json.dumps(provider["schema"], ensure_ascii=False, separators=(",", ":"))
    tools_text = json.dumps(provider["tools"], ensure_ascii=False, separators=(",", ":"))
    sql = (
        "begin;\n"
        "update tool_api_providers set "
        f"schema = {dollar_quote(schema_text)}, "
        f"tools_str = {dollar_quote(tools_text)}, "
        "updated_at = now() "
        f"where id = '{TOOL_PROVIDER_ID}';\n"
        "commit;\n"
    )
    psql([], input_text=sql)


def update_workflows(workflows: list[dict[str, Any]]) -> None:
    statements = ["begin;"]
    for item in workflows:
        graph_text = json.dumps(item["graph"], ensure_ascii=False, separators=(",", ":"))
        statements.append(
            "update workflows "
            f"set graph = {dollar_quote(graph_text)}, updated_at = now() "
            f"where id = '{item['id']}';"
        )
    statements.append("commit;")
    psql([], input_text="\n".join(statements) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="validate and preview without DB writes")
    args = parser.parse_args()

    openapi = load_openapi()
    provider = load_provider()
    live_workflow_id, workflows = load_style_workflows()
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup(provider, workflows, stamp)

    before_provider = validate_provider(provider) if "generate_style_diagnostics" in provider["tools_text"] else {
        "tool_count": len(provider["tools"]),
        "operations": [tool.get("operation_id") for tool in provider["tools"] if isinstance(tool, dict)],
        "schema_sha": sha_text(provider["schema_text"]),
        "tools_sha": sha_text(provider["tools_text"]),
    }
    provider_changed = patch_provider(provider, openapi)
    after_provider = validate_provider(provider)

    before_workflows = {}
    after_workflows = {}
    workflow_changed = False
    for item in workflows:
        before_workflows[item["id"]] = validate_workflow(item["graph"], label=f"before:{item['version']}")
        workflow_changed = patch_workflow(item["graph"], provider["tools"]) or workflow_changed
        after_workflows[item["id"]] = validate_workflow(item["graph"], label=f"after:{item['version']}")

    changed = provider_changed or workflow_changed
    if changed and not args.dry_run:
        if provider_changed:
            update_provider(provider)
        if workflow_changed:
            update_workflows(workflows)

    print(
        json.dumps(
            {
                "app_id": APP_ID,
                "tool_provider_id": TOOL_PROVIDER_ID,
                "live_workflow_id": live_workflow_id,
                "backup": str(backup_path.relative_to(ROOT)),
                "dry_run": args.dry_run,
                "changed": changed,
                "provider_changed": provider_changed,
                "workflow_changed": workflow_changed,
                "workflow_ids": [{"id": item["id"], "version": item["version"]} for item in workflows],
                "before_provider": before_provider,
                "after_provider": after_provider,
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
