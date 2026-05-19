"""Migrate workflows.graph from text to jsonb, then fix existing double-escaped data.

Root cause: Dify backend used json.dumps(ensure_ascii=True) which produces \\uXXXX
escapes for CJK. These were stored in a text column where they became double-escaped
(\\\\u7528). When read back, the double-escapes produce literal \\u7528 strings
instead of the character 用.

Fix has two parts:
1. ALTER column to jsonb: prevents future double-escaping because PostgreSQL's
   jsonb parser correctly handles \\uXXXX (single backslash) from json.dumps().
2. Fix existing data: recursively decode literal \\uXXXX sequences in all string
   values in the stored jsonb data.

Run: python scripts/migrate_graph_to_jsonb.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime"

DB_CONTAINER = "docker-db_postgres-1"
DB_NAME = "dify"

BACKSLASH_U_RE = re.compile(r"\\u[0-9a-fA-F]{4}")


def run(args: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, cwd=ROOT, input=input_text, text=True,
        encoding="utf-8", errors="replace", capture_output=True,
    )


def psql(args: list[str], *, input_text: str | None = None) -> str:
    docker_args = ["docker", "exec"]
    if input_text is not None:
        docker_args.append("-i")
    docker_args.extend([DB_CONTAINER, "psql", "-U", "postgres", "-d", DB_NAME,
                        "-v", "ON_ERROR_STOP=1", *args])
    proc = run(docker_args, input_text=input_text)
    if proc.returncode:
        raise RuntimeError(f"psql failed\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    return proc.stdout


def dollar_quote(value: str) -> str:
    for tag in ("migrate", "migrate2", "migrate3"):
        marker = f"${tag}$"
        if marker not in value:
            return f"{marker}{value}{marker}"
    raise ValueError("Cannot build a safe dollar-quoted SQL string")


def decode_if_escaped(value: str) -> str:
    if "\\u" not in value:
        return value
    try:
        decoded = json.loads(f'"{value}"')
    except json.JSONDecodeError:
        return value
    return decoded if isinstance(decoded, str) else value


def recursive_decode(obj: Any) -> tuple[Any, bool]:
    if isinstance(obj, str):
        if "\\u" in obj and BACKSLASH_U_RE.search(obj):
            decoded = decode_if_escaped(obj)
            return decoded, decoded != obj
        return obj, False
    elif isinstance(obj, dict):
        changed = False
        new_dict = {}
        for k, v in obj.items():
            new_v, c = recursive_decode(v)
            new_dict[k] = new_v
            changed = changed or c
        return new_dict if changed else obj, changed
    elif isinstance(obj, list):
        changed = False
        new_list = []
        for v in obj:
            new_v, c = recursive_decode(v)
            new_list.append(new_v)
            changed = changed or c
        return new_list if changed else obj, changed
    return obj, False


def get_column_type() -> str:
    result = psql(["-A", "-t", "-c",
                   "SELECT udt_name FROM information_schema.columns "
                   "WHERE table_name = 'workflows' AND column_name = 'graph'"])
    return result.strip()


def backup_workflows() -> Path:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = RUNTIME / f"workflows_pre_jsonb_backup_{stamp}.json"

    is_jsonb = get_column_type() == "jsonb"
    if is_jsonb:
        rows = psql(["-A", "-t", "-F", "\t", "-c",
                     "SELECT id::text, version, graph::text FROM workflows ORDER BY updated_at DESC"])
    else:
        rows = psql(["-A", "-t", "-F", "\t", "-c",
                     "SELECT id::text, version, encode(convert_to(graph, 'UTF8'), 'hex') "
                     "FROM workflows ORDER BY updated_at DESC"])

    payload = []
    for line in rows.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 3 or not parts[2]:
            continue
        wf_id, version, graph_raw = parts[0], parts[1], parts[2]
        if is_jsonb:
            graph_text = graph_raw
        else:
            graph_text = bytes.fromhex(graph_raw).decode("utf-8")
        payload.append({"id": wf_id, "version": version, "graph": graph_text})

    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def load_workflows() -> list[dict[str, Any]]:
    is_jsonb = get_column_type() == "jsonb"
    if is_jsonb:
        rows = psql(["-A", "-t", "-F", "\t", "-c",
                     "SELECT id::text, version, encode(convert_to(graph::text, 'UTF8'), 'hex') "
                     "FROM workflows"])
    else:
        rows = psql(["-A", "-t", "-F", "\t", "-c",
                     "SELECT id::text, version, encode(convert_to(graph, 'UTF8'), 'hex') "
                     "FROM workflows"])

    result = []
    for line in rows.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 3 or not parts[2]:
            continue
        wf_id, version, graph_hex = parts[0], parts[1], parts[2]
        graph_text = bytes.fromhex(graph_hex).decode("utf-8")
        graph = json.loads(graph_text)
        result.append({"id": wf_id, "version": version, "graph": graph})
    return result


def fix_existing_data(dry_run: bool) -> int:
    """Decode literal \\uXXXX in existing jsonb data. Returns count of fixed rows."""
    workflows = load_workflows()
    fixed = 0

    for item in workflows:
        new_graph, changed = recursive_decode(item["graph"])
        if changed:
            fixed += 1
            if not dry_run:
                graph_text = json.dumps(new_graph, ensure_ascii=False, separators=(",", ":"))
                psql([], input_text=(
                    f"UPDATE workflows SET graph = {dollar_quote(graph_text)}::jsonb, "
                    f"updated_at = now() WHERE id = '{item['id']}';\n"
                ))
                print(f"  fixed: {item['id'][:8]} v={item['version']}")

    return fixed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--fix-only", action="store_true",
                        help="Only fix existing data, skip ALTER TABLE")
    args = parser.parse_args()

    ctype = get_column_type()
    print(f"Column type: {ctype}")

    # Step 1: ALTER TABLE (if needed)
    if not args.fix_only and ctype == "text":
        print("\n=== Step 1: Migrate text → jsonb ===")

        # Validate
        result = psql(["-A", "-t", "-c",
                       "SELECT count(*) FROM workflows WHERE graph IS NOT NULL"])
        total = int(result.strip())
        print(f"  Total workflows: {total}")

        # Backup
        backup_path = backup_workflows()
        print(f"  Backup: {backup_path}")

        if args.dry_run:
            print(f"  DRY RUN: would ALTER {total} rows")
        else:
            psql(["-c", "ALTER TABLE workflows ALTER COLUMN graph TYPE jsonb USING graph::jsonb"])
            print(f"  ALTER TABLE completed")
            print(f"  New type: {get_column_type()}")

    elif not args.fix_only and ctype == "jsonb":
        print("  Already jsonb, skipping ALTER TABLE")

    # Step 2: Fix existing data
    print("\n=== Step 2: Fix existing double-escaped data ===")
    backup_path = backup_workflows()
    print(f"  Pre-fix backup: {backup_path}")

    fixed = fix_existing_data(args.dry_run)
    action = "would fix" if args.dry_run else "fixed"
    print(f"  {action} {fixed} workflow(s)")

    # Verification
    print("\n=== Verification ===")
    sample = psql(["-A", "-t", "-c",
                   "SELECT graph->'nodes'->0->'data'->>'title' FROM workflows "
                   "WHERE id = '250b523f-7a81-49a8-83ee-0e8b6de2f497'"])
    title = sample.strip()
    has_literal_escape = "\\u" in title and BACKSLASH_U_RE.search(title) is not None
    print(f"  Sample title: {title}")
    print(f"  Still has literal \\uXXXX: {has_literal_escape}")

    if not has_literal_escape:
        print("\n  PASS: No more literal \\uXXXX sequences in sample data")
    else:
        print("\n  WARN: Sample still contains literal \\uXXXX — manual inspection needed")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
