"""Scan Dify prompt surfaces for hardcoded story terms and prompt hygiene drift.

The live Dify PostgreSQL database is the runtime truth. Exported workflow YAML
and patch scripts are scanned as reproducibility surfaces that can reintroduce
prompt drift later.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DB_CONTAINER = "docker-db_postgres-1"
DB_NAME = "dify"

HARDCODED_TERMS = (
    "donk",
    "陈末",
    "Major",
    "BLAST",
    "七君",
    "场外军师",
    "莫斯科",
    "伊甸园",
    "地下竞技场",
    "CS1.6",
    "CS:GO",
    "群星猎枪篇",
    "西游",
    "孙悟空",
    "唐僧",
    "完全恢复生命活性",
)

ENGLISH_PATTERNS = (
    r"\bApply this protocol\b",
    r"\bFinal-answer\b",
    r"\bYour job\b",
    r"\bYou are\b",
    r"\bDo not\b",
    r"\bWhen the author\b",
    r"\bIf the author\b",
    r"\bmust(?: not)?\b",
    r"\bnever\b",
    r"(?<![-_])\bonly\b",
)

MOJIBAKE_MARKERS = (
    "\ufffd",
    "????",
    "褰撳",
    "涔﹀",
    "鐩",
    "浣滆",
    "闈犲",
    "绂佹",
    "鍏堣",
    "璇诲",
    "鍐欏",
    "鍒濆",
    "姣忔",
    "佃",
    "犺",
    "€?",
    "鏄",
    "鍦",
    "鐨",
    "鍙",
    "浣",
    "绂",
    "鈥",
    "銆",
    "锛",
    "乣",
    "乻",
    "乭",
    "乵",
    "乬",
    "乫",
)

PROMPTISH_PATH_RE = re.compile(
    r"(prompt|instruction|query|template|system|opening_statement|pre_prompt|"
    r"context|role|class|variable|hint|placeholder|description|tool_description|"
    r"provider_show_name|memory)",
    re.IGNORECASE,
)
PROMPTISH_TEXT_MARKERS = (
    "AGENT",
    "Agent",
    "协议",
    "职责",
    "必须",
    "禁止",
    "SOURCE_FACT",
    "AUTHOR_PROPOSAL",
    "WORLD_MODEL_REQUIRED",
)
SCRIPT_PROMPT_NAME_RE = re.compile(
    r"(PROMPT|QUERY|INSTRUCTION|PROTOCOL|GUARD|MARKERS|CLASS|TOOLS)", re.IGNORECASE
)


@dataclass
class PromptIssue:
    source: str
    categories: list[str]
    sample: str
    length: int
    terms: list[str] = field(default_factory=list)
    english_hits: list[str] = field(default_factory=list)
    mojibake_hits: list[str] = field(default_factory=list)
    app: str | None = None
    version: str | None = None
    workflow_id: str | None = None
    node: str | None = None
    path: str | None = None
    file: str | None = None
    line: int | None = None


def compact_sample(text: str, limit: int = 260) -> str:
    return " ".join(text.split())[:limit]


def walk_strings(obj: Any, path: str = "") -> Iterable[tuple[str, str]]:
    if isinstance(obj, dict):
        for key, value in obj.items():
            next_path = f"{path}.{key}" if path else str(key)
            yield from walk_strings(value, next_path)
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            yield from walk_strings(value, f"{path}[{index}]")
    elif isinstance(obj, str):
        yield path, obj


def is_promptish(path: str, text: str) -> bool:
    if PROMPTISH_PATH_RE.search(path):
        return True
    if len(text) > 240 and any(marker in text for marker in PROMPTISH_TEXT_MARKERS):
        return True
    return False


def english_hits(text: str) -> list[str]:
    hits: list[str] = []
    for pattern in ENGLISH_PATTERNS:
        if re.search(pattern, text):
            hits.append(pattern.strip(r"\b"))
    return hits


def mojibake_hits(text: str) -> list[str]:
    hits = [marker for marker in MOJIBAKE_MARKERS if marker in text]
    question_clusters = re.findall(r"\?{4,}", text)
    if question_clusters and "????" not in hits:
        hits.append("????")
    return hits


def inspect_text(
    text: str,
    *,
    source: str,
    app: str | None = None,
    version: str | None = None,
    workflow_id: str | None = None,
    node: str | None = None,
    path: str | None = None,
    file: str | None = None,
    line: int | None = None,
) -> PromptIssue | None:
    hardcoded = [term for term in HARDCODED_TERMS if term in text]
    english = english_hits(text)
    mojibake = mojibake_hits(text)

    categories: list[str] = []
    if hardcoded:
        categories.append("hardcoded")
    if english:
        categories.append("english")
    if mojibake:
        categories.append("mojibake")
    if not categories:
        return None

    return PromptIssue(
        source=source,
        categories=categories,
        terms=hardcoded,
        english_hits=english,
        mojibake_hits=mojibake,
        sample=compact_sample(text),
        length=len(text),
        app=app,
        version=version,
        workflow_id=workflow_id,
        node=node,
        path=path,
        file=file,
        line=line,
    )


def psql_hex_rows(sql: str) -> list[str]:
    proc = subprocess.run(
        [
            "docker",
            "exec",
            DB_CONTAINER,
            "psql",
            "-U",
            "postgres",
            "-d",
            DB_NAME,
            "-At",
            "-c",
            sql,
        ],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def node_title_from_path(graph: dict[str, Any], path: str) -> str | None:
    match = re.search(r"nodes\[(\d+)\]", path)
    if not match:
        return None
    try:
        node = graph.get("nodes", [])[int(match.group(1))]
    except (IndexError, ValueError, TypeError):
        return None
    data = node.get("data") or {}
    return data.get("title") or data.get("label") or node.get("id")


def scan_graph_strings(
    graph: dict[str, Any],
    *,
    app: str,
    version: str,
    workflow_id: str,
) -> list[PromptIssue]:
    issues: list[PromptIssue] = []
    for path, text in walk_strings(graph):
        if len(text.strip()) < 8 or not is_promptish(path, text):
            continue
        issue = inspect_text(
            text,
            source="live-db",
            app=app,
            version=version,
            workflow_id=workflow_id,
            node=node_title_from_path(graph, path),
            path=path,
        )
        if issue:
            issues.append(issue)
    return issues


def scan_live_db() -> list[PromptIssue]:
    sql = """
    select encode(convert_to(json_build_object(
      'app_name', a.name,
      'workflow_id', w.id::text,
      'version', coalesce(w.version, ''),
      'graph', w.graph
    )::text,'UTF8'),'hex')
    from workflows w join apps a on a.id=w.app_id
    order by a.name, w.updated_at desc nulls last, w.created_at desc nulls last;
    """
    issues: list[PromptIssue] = []
    for row_hex in psql_hex_rows(sql):
        row = json.loads(bytes.fromhex(row_hex).decode("utf-8-sig"))
        graph = row["graph"]
        if isinstance(graph, str):
            graph = json.loads(graph)
        issues.extend(
            scan_graph_strings(
                graph,
                app=row["app_name"],
                version=row["version"],
                workflow_id=row["workflow_id"],
            )
        )
    return issues


def script_prompt_assignments(path: Path) -> Iterable[tuple[int, str]]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        for line_no, line in enumerate(text.splitlines(), start=1):
            if any(term in line for term in HARDCODED_TERMS) or english_hits(line) or mojibake_hits(line):
                yield line_no, line
        return

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        target_names = [getattr(target, "id", "") for target in node.targets]
        if not any(SCRIPT_PROMPT_NAME_RE.search(name) for name in target_names):
            continue
        segment = ast.get_source_segment(text, node.value) or ""
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            segment = node.value.value
        if len(segment.strip()) >= 8:
            yield node.lineno, segment


def scan_scripts() -> list[PromptIssue]:
    patterns = (
        "scripts/patch_*agent.py",
        "scripts/patch_*workflow.py",
        "tools/patch_dify_*.py",
        "tools/patch_dify_*.ps1",
    )
    files: list[Path] = []
    for pattern in patterns:
        files.extend(sorted(ROOT.glob(pattern)))

    issues: list[PromptIssue] = []
    for path in files:
        for line_no, text in script_prompt_assignments(path):
            issue = inspect_text(
                text,
                source="scripts",
                file=str(path.relative_to(ROOT)),
                line=line_no,
            )
            if issue:
                issues.append(issue)
    return issues


def scan_exports() -> list[PromptIssue]:
    issues: list[PromptIssue] = []
    for path in sorted((ROOT / "dify_workflows").glob("*.yml")):
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        for line_no, line in enumerate(text.splitlines(), start=1):
            issue = inspect_text(
                line,
                source="exports",
                file=str(path.relative_to(ROOT)),
                line=line_no,
            )
            if issue:
                issues.append(issue)
    return issues


def summarize(issues: list[PromptIssue]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "issue_count": len(issues),
        "by_category": {"hardcoded": 0, "english": 0, "mojibake": 0},
        "by_source": {},
    }
    for issue in issues:
        summary["by_source"][issue.source] = summary["by_source"].get(issue.source, 0) + 1
        for category in issue.categories:
            summary["by_category"][category] += 1
    return summary


def scan_sources(sources: list[str]) -> list[PromptIssue]:
    issues: list[PromptIssue] = []
    if "all" in sources or "live-db" in sources:
        issues.extend(scan_live_db())
    if "all" in sources or "scripts" in sources:
        issues.extend(scan_scripts())
    if "all" in sources or "exports" in sources:
        issues.extend(scan_exports())
    return issues


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scan Dify prompt hygiene surfaces.")
    parser.add_argument(
        "--source",
        action="append",
        choices=["all", "live-db", "scripts", "exports"],
        default=None,
        help="Source to scan. Can be repeated. Defaults to all.",
    )
    parser.add_argument("--format", choices=["json", "text"], default="json")
    parser.add_argument("--output", type=Path, help="Optional path to write the JSON report.")
    parser.add_argument("--fail-on-hardcoded", action="store_true")
    parser.add_argument("--fail-on-english", action="store_true")
    parser.add_argument("--fail-on-mojibake", action="store_true")
    return parser


def should_fail(args: argparse.Namespace, issues: list[PromptIssue]) -> bool:
    category_flags = {
        "hardcoded": args.fail_on_hardcoded,
        "english": args.fail_on_english,
        "mojibake": args.fail_on_mojibake,
    }
    for issue in issues:
        if any(category_flags[category] for category in issue.categories):
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    sources = args.source or ["all"]
    issues = scan_sources(sources)
    report = {
        "sources": sources,
        "summary": summarize(issues),
        "issues": [asdict(issue) for issue in issues],
    }

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
        for issue in issues:
            location = issue.file or f"{issue.app}:{issue.workflow_id}:{issue.node}:{issue.path}"
            print(f"- {issue.source} {issue.categories} {location} :: {issue.sample}")

    return 1 if should_fail(args, issues) else 0


if __name__ == "__main__":
    raise SystemExit(main())
