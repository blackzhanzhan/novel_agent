"""Patch the live Dify reading archive agent code nodes from PostgreSQL.

Fixes:
1. 文本预切片: use absolute chapter numbers from titles instead of relative i+1
2. 聚合归档解析Summary: pure aggregation, no file writes
3. LLM prompt: genre-adaptive segment-level constraint extraction (replaces per-chapter compression)

Run: python scripts/patch_reading_archive_agent.py [--dry-run]
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

DB_CONTAINER = "docker-db_postgres-1"
DB_NAME = "dify"
APP_ID = "590dd17b-d9d0-4d5b-bffa-e6f1d8e45810"

EXPECTED_NODE_COUNT = 12
EXPECTED_EDGE_COUNT = 12

LLM_NODE_TITLE = "LLM 2"
LLM_NODE_ID = "1770953558856"

# ── Fix 1: segment-level batch sizing (larger batches for constraint extraction) ──

PRE_SLICE_CODE = r'''
import json as _json
import math
import re

def main(raw_text: str = "", upload_chunks: list = None) -> dict:
    """Relay node: parse raw_text OR relay upload_chunks into iteration-ready chunks."""
    if upload_chunks:
        return {"chunks": upload_chunks, "total_chapters": len(upload_chunks)}

    if not raw_text:
        return {"chunks": [], "total_chapters": 0}

    DELIMITER = "|||CHAPTER_START|||"
    raw_chunks = [c.strip() for c in raw_text.split(DELIMITER) if c.strip()]
    total = len(raw_chunks)
    if total == 0:
        return {"chunks": [], "total_chapters": 0}

    # Larger segments for constraint extraction (~50-100 chapters per segment)
    batch_size = max(50, math.ceil(total / 15))
    bundled_data = []
    for i in range(0, total, batch_size):
        batch = raw_chunks[i : i + batch_size]
        batch_chapters = []
        ch_nums = []
        for content in batch:
            lines = content.splitlines()
            title = lines[0].strip() if lines else ""
            body = chr(10).join(lines[1:]).strip() if len(lines) > 1 else ""
            if len(body) > 300000:
                body = body[:300000] + "...(Truncated)"
            batch_chapters.append({"title": title, "content": body})
            m = re.search(r"第(\d+)章", title)
            if m:
                ch_nums.append(int(m.group(1)))
        if ch_nums:
            range_label = "CH{}-{}".format(min(ch_nums), max(ch_nums))
        else:
            range_label = "CH{}-{}".format(i + 1, min(i + batch_size, total))
        bundled_data.append({
            "range": range_label,
            "chapters": batch_chapters,
        })

    return {"total_chapters": total, "chunks": bundled_data}
'''

# ── Fix 2: aggregation — merge segment constraints ──

AGGREGATION_CODE = r'''
import json
import re

def main(summary_list: list, book_id: str):
    """
    Pure aggregation: join batch summaries, build book-level overview.
    File writing is handled by the backend (tomato_import), not here.
    """
    valid = [str(s).strip() for s in summary_list if s]
    if not valid:
        return {"final_text": "", "commit_id": "none", "latest_chapter_json": "{}", "total_count": 0}

    header = "# 全书总汇总（自动索引）\n\n"
    header += f"- 段落数：{len(valid)}\n"
    header += "- 生成方式：按段落档案抽取约束；完整段落记录保留在下方。\n\n"

    # Build overview from first and last segment
    overview_sections = []
    if valid:
        first = valid[0]
        last = valid[-1] if len(valid) > 1 else ""
        # Extract story stage from first
        m = re.search(r"### 故事阶段\s*\n(.+?)(?=\n###|\n##|\Z)", first, re.S)
        if m:
            overview_sections.append(f"起始阶段：{m.group(1).strip()}")
        # Extract from last
        if last:
            m = re.search(r"### 故事阶段\s*\n(.+?)(?=\n###|\n##|\Z)", last, re.S)
            if m:
                overview_sections.append(f"当前阶段：{m.group(1).strip()}")

    # Collect all chapter ranges for coverage index
    ranges = []
    for seg in valid:
        m = re.search(r"## Batch Archive:\s*CH(\d+)\s*[-–—]\s*(\d+)", seg)
        if m:
            ranges.append((int(m.group(1)), int(m.group(2))))

    if ranges:
        coverage = f"覆盖范围：CH{ranges[0][0]}-CH{ranges[-1][1]}（{len(ranges)}段）"
        overview_sections.append(coverage)

    if overview_sections:
        header += "## 全书概览\n\n"
        for line in overview_sections:
            header += f"- {line}\n"
        header += "\n---\n\n"
    else:
        header += "---\n\n"

    header += "# 分批阅读档案\n\n"

    full_text = header + "\n\n".join(valid)

    # Count batch archives
    count = len(re.findall(r"## Batch Archive:", full_text))

    return {
        "final_text": full_text,
        "commit_id": "deferred_to_backend",
        "latest_chapter_json": "{}",
        "total_count": count
    }
'''

# ── Fix 3: Genre-adaptive segment-level LLM prompt ──

LLM_PROMPT = r'''# 角色设定
你是一名网文叙事约束提取专家。你的任务不是逐章复述剧情，而是从一批章节中提取会约束后续创作的核心信息。

# 任务描述
阅读以下章节内容：
{{#1770953322951.item#}}{{#context#}}

# 输出格式
严格按以下格式输出一个段落档案（严禁开场白）：

## Batch Archive: CH{起始}-{结束}
（起始和结束用本批实际章节号，从章节标题中提取）

### 故事阶段
{一句话定位当前大阶段的叙事目标和故事位置}

### 不可撤销事实
{本段确立的硬事实，后续不可推翻，每条一行}
- {事实}

### 核心驱动进度
{按实际存在的题材选填，不存在的子结构不生成。可多子结构并行。}

升级/战斗类：
- 境界/战力: {当前状态}
- 突破: {有/无，若有写明}
- 已揭示上限: {有/无}
- 突破预兆: {有/无}

智斗/悬疑/推理类：
- 已揭示规则: {关键已确认的规则/真相}
- 信息差: {谁知道了什么/谁还不知道}
- 博弈态势: {谁占优/僵持/暗流}
- 待解谜题: {核心未解问题}

轮回/循环/无限类：
- 循环状态: 第{N}次
- 本轮差异: {与上轮关键变化}
- 累积保留: {跨循环保留的知识/能力}
- 蝴蝶效应: {行为→结果链}

言情/感情类：
- 感情阶段: {暧昧/表白/危机/复合/...}
- 阻碍: {当前阻碍}
- 催化: {推动力}

种田/基建/生存类：
- 资源/建设状态: {当前}
- 里程碑: {本段达成}
- 威胁/挑战: {当前}

末世/恐怖类：
- 安全等级: {评估}
- 威胁源: {当前}
- 生存策略: {当前}

### 线索状态
{只列本段有推进或变化的线索}
- {线索名} ({主线/支线}) — {active推进中/dormant挂起/closing收束中}

### 伏笔台账
{只记录本段新埋设或有进展的伏笔}
- {伏笔简述} — {planted刚埋/nurturing正在培育/overdue逾期未收} (CH{章节}埋, 可见性:{读者已知/角色未知/仅角色已知})

### 未兑现承诺
{本段作出的新承诺}
- {承诺内容} (CH{章节}, 对{角色})

### 关系变化
{本段有实质变化的关系}
- {角色A}→{角色B}: {变化描述}

### 本段约束增量
{提炼给 world_model 的硬约束：新确立的规则、已关闭的可能性、世界观变化}

# 规则
1. 整段 800-1200 字，严禁超过 1500 字
2. 字段按信息量存在：无信息的字段直接省略整个章节，不生成"无"或"无变化"
3. 伏笔必须标注可见性维度：读者已知/角色未知/仅角色已知
4. 禁止搬运章节原文或做逐章摘要；只提取约束级信息
5. 禁止任何开场白、总结语或元评论
6. 核心驱动进度可包含多个子结构（混合题材），不存在的子结构不生成'''

EXPECTED_LLM_MARKERS = [
    "叙事约束提取专家",
    "核心驱动进度",
    "伏笔台账",
    "可见性",
    "字段按信息量",
    "不可撤销事实",
    "未兑现承诺",
    "关系变化",
    "约束增量",
    "800-1200",
]

# ── Helpers ──


def run(args: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=ROOT,
        input=input_text,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
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


def dollar_quote(value: str) -> str:
    for tag in ("codex", "codex2", "codex_ra"):
        marker = f"${tag}$"
        if marker not in value:
            return f"{marker}{value}{marker}"
    raise ValueError("Cannot build a safe dollar-quoted SQL string")


def sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def code_nodes(graph: dict) -> dict[str, dict]:
    result = {}
    for node in graph.get("nodes", []):
        if node.get("data", {}).get("type") == "code":
            title = node["data"].get("title", "")
            result[title] = node
    return result


def llm_node(graph: dict) -> dict | None:
    for node in graph.get("nodes", []):
        nd = node.get("data", {})
        if nd.get("type") == "llm" and nd.get("title") == LLM_NODE_TITLE:
            return node
    return None


def backup(workflows: list[dict], stamp: str) -> Path:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    out = RUNTIME / f"reading_archive_workflow_backup_{stamp}.json"
    payload = [
        {
            "id": item["id"],
            "version": item["version"],
            "graph_sha": sha_text(item["graph_text"]),
            "graph": item["graph"],
        }
        for item in workflows
    ]
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def load_workflows() -> tuple[str, list[dict]]:
    rows = []
    for line in psql(
        ["-A", "-t", "-F", "\t", "-c",
         f"SELECT id, version, graph FROM workflows WHERE app_id = '{APP_ID}'"]
    ).splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        wf_id, version, graph_text = parts[0], parts[1], "\t".join(parts[2:])
        graph = json.loads(graph_text)
        rows.append({"id": wf_id, "version": version, "graph_text": graph_text, "graph": graph})
    if not rows:
        raise RuntimeError(f"No workflows found for app {APP_ID}")
    live_id = ""
    for r in rows:
        if r["version"] == "live":
            live_id = r["id"]
    return live_id, rows


def validate_graph(graph: dict, label: str) -> dict:
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    if len(nodes) != EXPECTED_NODE_COUNT:
        raise RuntimeError(f"{label} node count {len(nodes)} != expected {EXPECTED_NODE_COUNT}")
    if len(edges) != EXPECTED_EDGE_COUNT:
        raise RuntimeError(f"{label} edge count {len(edges)} != expected {EXPECTED_EDGE_COUNT}")

    # Validate LLM node exists
    llm = llm_node(graph)
    if llm is None:
        raise RuntimeError(f"{label} LLM node '{LLM_NODE_TITLE}' not found")

    return {"nodes": len(nodes), "edges": len(edges), "llm_found": True}


def patch_graph(graph: dict) -> bool:
    changed = False
    codes = code_nodes(graph)

    # Patch 1: 文本预切片 (larger batch sizes for segments)
    pre_slice = codes.get("文本预切片")
    if pre_slice:
        old_code = pre_slice["data"].get("code", "")
        if old_code != PRE_SLICE_CODE:
            pre_slice["data"]["code"] = PRE_SLICE_CODE
            changed = True

    # Patch 2: 聚合归档解析Summary
    agg = codes.get("聚合归档解析Summary")
    if agg:
        old_code = agg["data"].get("code", "")
        if old_code != AGGREGATION_CODE:
            agg["data"]["code"] = AGGREGATION_CODE
            changed = True

    # Patch 3: LLM prompt — genre-adaptive segment-level constraint extraction
    llm = llm_node(graph)
    if llm:
        prompt_template = llm["data"].get("prompt_template", [])
        if isinstance(prompt_template, list) and len(prompt_template) > 0:
            for seg in prompt_template:
                if seg.get("role") == "system":
                    old_text = seg.get("text", "")
                    if old_text != LLM_PROMPT:
                        seg["text"] = LLM_PROMPT
                        changed = True
                    break

    return changed


def validate_prompt_markers(graph: dict, label: str) -> list[str]:
    """Validate LLM prompt contains expected markers. Returns list of missing."""
    llm = llm_node(graph)
    if llm is None:
        return [f"LLM node not found"]
    prompt_template = llm["data"].get("prompt_template", [])
    system_text = ""
    if isinstance(prompt_template, list):
        for seg in prompt_template:
            if seg.get("role") == "system":
                system_text = seg.get("text", "")
                break
    missing = []
    for marker in EXPECTED_LLM_MARKERS:
        if marker not in system_text:
            missing.append(marker)
    return missing


def update_workflows(workflows: list[dict]) -> None:
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
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    live_id, workflows = load_workflows()
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup(workflows, stamp)

    before = {}
    after = {}
    changed = False
    for item in workflows:
        before[item["id"]] = validate_graph(item["graph"], label=f"before:{item['version']}")
        if patch_graph(item["graph"]):
            changed = True
        after[item["id"]] = validate_graph(item["graph"], label=f"after:{item['version']}")

    # Validate markers after patching
    missing_markers = {}
    for item in workflows:
        missing = validate_prompt_markers(item["graph"], label=f"after:{item['version']}")
        if missing:
            missing_markers[item["version"]] = missing

    if changed and not args.dry_run:
        update_workflows(workflows)

    print(json.dumps({
        "app_id": APP_ID,
        "live_workflow_id": live_id,
        "backup": str(backup_path),
        "dry_run": args.dry_run,
        "changed": changed,
        "before": {k: {"nodes": v["nodes"], "edges": v["edges"]} for k, v in before.items()},
        "after": {k: {"nodes": v["nodes"], "edges": v["edges"]} for k, v in after.items()},
        "missing_llm_markers": missing_markers,
    }, indent=2, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
