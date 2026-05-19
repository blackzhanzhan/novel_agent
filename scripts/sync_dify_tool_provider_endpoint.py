"""Sync the live Dify LoreGit ToolProvider endpoint to the runtime backend port.

The Dify PostgreSQL row is the runtime truth. This script updates only
host.docker.internal:<port> endpoint strings inside tool_api_providers.schema
and tool_api_providers.tools_str. It must not change tool operations, tool
count, prompts, workflows, or write semantics.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime"
PORTS_MANIFEST = RUNTIME / "ports.json"

DB_CONTAINER = "docker-db_postgres-1"
DB_NAME = "dify"
TOOL_PROVIDER_ID = "c41fee3b-54dd-4e49-af9b-be30f68f6242"
ENDPOINT_RE = re.compile(r"host\.docker\.internal:(\d+)")


def run(args: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=ROOT,
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
            f"COMMAND: {' '.join(str(a) for a in proc.args if a)}\n"
            f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return proc.stdout


def psql_at(sql: str) -> list[str]:
    out = psql(["-A", "-t", "-F", "\t", "-c", sql])
    return [line for line in out.splitlines() if line.strip()]


def dollar_quote(value: str) -> str:
    for tag in ("codex", "codex_endpoint", "codex_endpoint2"):
        marker = f"${tag}$"
        if marker not in value:
            return f"{marker}{value}{marker}"
    raise ValueError("Cannot build a safe dollar-quoted SQL string")


def sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def selected_backend_port(explicit_port: int | None) -> int:
    if explicit_port is not None:
        return explicit_port
    if not PORTS_MANIFEST.exists():
        raise RuntimeError(f"Runtime ports manifest not found: {PORTS_MANIFEST}")
    manifest = json.loads(PORTS_MANIFEST.read_text(encoding="utf-8-sig"))
    try:
        port = int(manifest["backend"]["selected_port"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"Runtime ports manifest has no backend.selected_port: {PORTS_MANIFEST}") from exc
    if port < 1 or port > 65535:
        raise RuntimeError(f"Invalid backend port in manifest: {port}")
    return port


def load_provider(provider_id: str) -> dict[str, Any]:
    rows = psql_at(
        f"""
        select
            encode(convert_to(schema, 'UTF8'), 'hex'),
            encode(convert_to(tools_str, 'UTF8'), 'hex'),
            name,
            schema_type_str
        from tool_api_providers
        where id = '{provider_id}'
        """
    )
    if len(rows) != 1:
        raise RuntimeError(f"Expected one ToolProvider row for {provider_id}, found {len(rows)}")
    schema_hex, tools_hex, name, schema_type = rows[0].split("\t", 3)
    schema_text = bytes.fromhex(schema_hex).decode("utf-8-sig")
    tools_text = bytes.fromhex(tools_hex).decode("utf-8-sig")
    schema = json.loads(schema_text)
    tools = json.loads(tools_text)
    if not isinstance(schema, dict):
        raise RuntimeError("ToolProvider schema is not a JSON object")
    if not isinstance(tools, list):
        raise RuntimeError("ToolProvider tools_str is not a JSON array")
    return {
        "id": provider_id,
        "name": name,
        "schema_type_str": schema_type,
        "schema_text": schema_text,
        "tools_text": tools_text,
        "schema": schema,
        "tools": tools,
    }


def tool_operation_ids(tools: list[Any]) -> list[str | None]:
    return [tool.get("operation_id") if isinstance(tool, dict) else None for tool in tools]


def schema_operation_ids(schema: dict[str, Any]) -> list[str | None]:
    operation_ids: list[str | None] = []
    paths = schema.get("paths")
    if not isinstance(paths, dict):
        return operation_ids
    for path in sorted(paths):
        path_item = paths[path]
        if not isinstance(path_item, dict):
            continue
        for method in sorted(path_item):
            operation = path_item[method]
            if isinstance(operation, dict):
                operation_ids.append(operation.get("operationId") or operation.get("operation_id"))
    return operation_ids


def endpoint_ports(*texts: str) -> list[int]:
    ports = sorted({int(match.group(1)) for text in texts for match in ENDPOINT_RE.finditer(text)})
    return ports


def backup_provider(provider: dict[str, Any], stamp: str, before_ports: list[int]) -> Path:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    out = RUNTIME / f"dify_tool_provider_endpoint_backup_{stamp}.json"
    payload = {
        "id": provider["id"],
        "name": provider["name"],
        "schema_type_str": provider["schema_type_str"],
        "schema_sha": sha_text(provider["schema_text"]),
        "tools_sha": sha_text(provider["tools_text"]),
        "endpoint_ports": before_ports,
        "schema": provider["schema"],
        "tools": provider["tools"],
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def patch_text(value: str, backend_port: int) -> str:
    return ENDPOINT_RE.sub(f"host.docker.internal:{backend_port}", value)


def validate_after(
    before: dict[str, Any],
    after_schema_text: str,
    after_tools_text: str,
    backend_port: int,
) -> dict[str, Any]:
    after_schema = json.loads(after_schema_text)
    after_tools = json.loads(after_tools_text)
    if not isinstance(after_schema, dict) or not isinstance(after_tools, list):
        raise RuntimeError("Patched ToolProvider JSON shape changed unexpectedly")

    before_tool_ops = tool_operation_ids(before["tools"])
    after_tool_ops = tool_operation_ids(after_tools)
    if before_tool_ops != after_tool_ops:
        raise RuntimeError("ToolProvider tools_str operation order changed")

    before_schema_ops = schema_operation_ids(before["schema"])
    after_schema_ops = schema_operation_ids(after_schema)
    if before_schema_ops != after_schema_ops:
        raise RuntimeError("ToolProvider schema operation ids changed")

    if len(before["tools"]) != len(after_tools):
        raise RuntimeError("ToolProvider tool count changed")

    ports_after = endpoint_ports(after_schema_text, after_tools_text)
    if ports_after and ports_after != [backend_port]:
        raise RuntimeError(f"ToolProvider endpoints still point to unexpected ports: {ports_after}")

    return {
        "tool_count": len(after_tools),
        "tool_operation_ids": after_tool_ops,
        "schema_operation_ids": after_schema_ops,
        "endpoint_ports_after": ports_after,
        "schema_sha_after": sha_text(after_schema_text),
        "tools_sha_after": sha_text(after_tools_text),
    }


def update_provider(provider_id: str, schema_text: str, tools_text: str) -> None:
    sql = (
        "begin;\n"
        "update tool_api_providers set "
        f"schema = {dollar_quote(schema_text)}, "
        f"tools_str = {dollar_quote(tools_text)}, "
        "updated_at = now() "
        f"where id = '{provider_id}';\n"
        "commit;\n"
    )
    psql([], input_text=sql)


def write_marker(stamp: str, payload: dict[str, Any]) -> Path:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    out = RUNTIME / f"dify_tool_provider_endpoint_marker_{stamp}.txt"
    lines = [
        f"provider_id={payload['provider_id']}",
        f"backend_port={payload['backend_port']}",
        f"dry_run={payload['dry_run']}",
        f"changed={payload['changed']}",
        f"endpoint_ports_before={','.join(str(port) for port in payload['endpoint_ports_before'])}",
        f"endpoint_ports_after={','.join(str(port) for port in payload['endpoint_ports_after'])}",
        f"backup={payload['backup']}",
    ]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend-port", type=int, default=None, help="selected local backend port")
    parser.add_argument("--provider-id", default=TOOL_PROVIDER_ID)
    parser.add_argument("--dry-run", action="store_true", help="validate and preview without DB writes")
    args = parser.parse_args()

    backend_port = selected_backend_port(args.backend_port)
    provider = load_provider(args.provider_id)
    before_ports = endpoint_ports(provider["schema_text"], provider["tools_text"])
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_provider(provider, stamp, before_ports)

    patched_schema_text = patch_text(provider["schema_text"], backend_port)
    patched_tools_text = patch_text(provider["tools_text"], backend_port)
    changed = patched_schema_text != provider["schema_text"] or patched_tools_text != provider["tools_text"]
    validation = validate_after(provider, patched_schema_text, patched_tools_text, backend_port)

    if changed and not args.dry_run:
        update_provider(args.provider_id, patched_schema_text, patched_tools_text)

    payload = {
        "provider_id": args.provider_id,
        "backend_port": backend_port,
        "dry_run": args.dry_run,
        "changed": changed,
        "backup": str(backup_path.relative_to(ROOT)),
        "endpoint_ports_before": before_ports,
        **validation,
    }
    marker_path = write_marker(stamp, payload)
    payload["marker"] = str(marker_path.relative_to(ROOT))
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
