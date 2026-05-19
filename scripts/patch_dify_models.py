"""Normalize live Dify workflow model settings.

The local Dify PostgreSQL database is the runtime truth for this project. This
script only patches model-bearing workflow graph objects and tenant defaults:

- provider: langgenius/deepseek/deepseek
- model: deepseek-v4-flash
- completion_params.thinking: role-based policy

It deliberately avoids prompt, tool, topology, and prose changes.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime"

DB_CONTAINER = "docker-db_postgres-1"
DB_NAME = "dify"
TARGET_PROVIDER = "langgenius/deepseek/deepseek"
TARGET_MODEL = "deepseek-v4-flash"
DEFAULT_THINKING = True

APP_IDS = {
    "world": "099c3beb-9f14-4389-850b-d6b7259ad064",
    "outline": "b58303e8-4a67-4327-8f56-ff1dbfc4023e",
    "style": "bb3232af-7106-43ba-ae65-4f6e7fc82943",
    "reading_archive": "590dd17b-d9d0-4d5b-bffa-e6f1d8e45810",
    "continuation": "089d589b-09a5-42b9-864b-ccac331bb8f8",
    "review": "b3574a2f-d599-4641-bf77-4f5adf9fd089",
}

THINKING_BY_APP_ID = {
    APP_IDS["reading_archive"]: False,
}


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
            f"COMMAND: {' '.join(str(a) for a in proc.args if a)}\n"
            f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return proc.stdout


def dollar_quote(value: str) -> str:
    for tag in ("codex", "codex_model", "codex_model2"):
        marker = f"${tag}$"
        if marker not in value:
            return f"{marker}{value}{marker}"
    raise ValueError("Cannot build a safe dollar-quoted SQL string")


def sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def load_workflows() -> list[dict[str, Any]]:
    app_id_list = ",".join(sql_string(app_id) for app_id in APP_IDS.values())
    sql = f"""
select
  w.id::text,
  w.app_id::text,
  a.name,
  case when w.id = a.workflow_id then 'live' else coalesce(w.version, '') end as runtime_version,
  encode(convert_to(w.graph::text, 'UTF8'), 'hex') as graph_hex
from workflows w
join apps a on a.id = w.app_id
where w.app_id in ({app_id_list})
order by a.name, runtime_version, w.created_at;
"""
    rows: list[dict[str, Any]] = []
    out = psql(["-A", "-t", "-F", "\t", "-c", sql])
    for line in out.splitlines():
        if not line.strip():
            continue
        workflow_id, app_id, app_name, version, graph_hex = line.split("\t", 4)
        graph_text = bytes.fromhex(graph_hex).decode("utf-8")
        rows.append(
            {
                "id": workflow_id,
                "app_id": app_id,
                "app_name": app_name,
                "version": version,
                "graph_text": graph_text,
                "graph": json.loads(graph_text),
            }
        )
    if not rows:
        raise RuntimeError("No target Dify workflows found")
    return rows


def backup_workflows(workflows: list[dict[str, Any]], stamp: str) -> Path:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    out = RUNTIME / f"dify_model_workflow_backup_{stamp}.json"
    payload = [
        {
            "id": item["id"],
            "app_id": item["app_id"],
            "app_name": item["app_name"],
            "version": item["version"],
            "graph_sha": sha_text(item["graph_text"]),
            "graph": item["graph"],
        }
        for item in workflows
    ]
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def node_label(path: str, graph: dict[str, Any]) -> str:
    marker = "/nodes["
    if marker not in path:
        return ""
    tail = path.split(marker, 1)[1]
    index_text = tail.split("]", 1)[0]
    if not index_text.isdigit():
        return ""
    index = int(index_text)
    nodes = graph.get("nodes")
    if not isinstance(nodes, list) or index >= len(nodes):
        return ""
    node = nodes[index]
    if not isinstance(node, dict):
        return ""
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    return f"{node.get('id')}:{data.get('title')}:{data.get('type')}"


def is_model_config(obj: dict[str, Any], path: str) -> bool:
    if path.endswith("/agent_parameters/model/value"):
        return True
    if "provider" in obj and ("model" in obj or "name" in obj) and "completion_params" in obj:
        return True
    return False


def iter_model_configs(obj: Any, path: str = ""):
    if isinstance(obj, dict):
        if is_model_config(obj, path):
            yield path, obj
        for key, value in obj.items():
            yield from iter_model_configs(value, f"{path}/{key}")
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            yield from iter_model_configs(value, f"{path}[{index}]")


def target_thinking_for_app(app_id: str) -> bool:
    return THINKING_BY_APP_ID.get(app_id, DEFAULT_THINKING)


def normalize_model_config(config: dict[str, Any], *, target_thinking: bool) -> dict[str, tuple[Any, Any]]:
    changes: dict[str, tuple[Any, Any]] = {}

    old_provider = config.get("provider")
    if old_provider != TARGET_PROVIDER:
        config["provider"] = TARGET_PROVIDER
        changes["provider"] = (old_provider, TARGET_PROVIDER)

    if "model" in config and config.get("model") != TARGET_MODEL:
        old_model = config.get("model")
        config["model"] = TARGET_MODEL
        changes["model"] = (old_model, TARGET_MODEL)

    if "name" in config and config.get("name") != TARGET_MODEL:
        old_name = config.get("name")
        config["name"] = TARGET_MODEL
        changes["name"] = (old_name, TARGET_MODEL)

    completion_params = config.get("completion_params")
    if not isinstance(completion_params, dict):
        completion_params = {}
        config["completion_params"] = completion_params
        changes["completion_params"] = (None, {})
    old_thinking = completion_params.get("thinking")
    if old_thinking is not target_thinking:
        completion_params["thinking"] = target_thinking
        changes["completion_params.thinking"] = (old_thinking, target_thinking)

    return changes


def patch_workflows(workflows: list[dict[str, Any]]) -> tuple[bool, list[dict[str, Any]]]:
    changed = False
    events: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in workflows:
        graph = item["graph"]
        target_thinking = target_thinking_for_app(item["app_id"])
        for path, config in iter_model_configs(graph):
            key = (item["id"], path)
            if key in seen:
                continue
            seen.add(key)
            before = deepcopy(config)
            changes = normalize_model_config(config, target_thinking=target_thinking)
            if changes:
                changed = True
                events.append(
                    {
                        "workflow_id": item["id"],
                        "app_name": item["app_name"],
                        "version": item["version"],
                        "path": path,
                        "node": node_label(path, graph),
                        "before": {
                            "provider": before.get("provider"),
                            "model": before.get("model", before.get("name")),
                            "thinking": (
                                before.get("completion_params", {}).get("thinking")
                                if isinstance(before.get("completion_params"), dict)
                                else None
                            ),
                        },
                        "after": {
                            "provider": config.get("provider"),
                            "model": config.get("model", config.get("name")),
                            "thinking": config.get("completion_params", {}).get("thinking"),
                            "target_thinking": target_thinking,
                        },
                        "changed_fields": sorted(changes),
                    }
                )
    return changed, events


def update_workflows(workflows: list[dict[str, Any]]) -> None:
    statements = ["begin;"]
    for item in workflows:
        graph_text = json.dumps(item["graph"], ensure_ascii=False, separators=(",", ":"))
        statements.append(
            "update workflows "
            f"set graph = {dollar_quote(graph_text)}::jsonb, updated_at = now() "
            f"where id = {sql_string(item['id'])};"
        )
    statements.append("commit;")
    psql([], input_text="\n".join(statements) + "\n")


def tenant_default_changes() -> list[dict[str, Any]]:
    sql = "select id::text, provider_name, model_name, model_type from tenant_default_models order by created_at;"
    changes: list[dict[str, Any]] = []
    out = psql(["-A", "-t", "-F", "\t", "-c", sql])
    for line in out.splitlines():
        if not line.strip():
            continue
        row_id, provider, model, model_type = line.split("\t")
        if provider == TARGET_PROVIDER and model_type == "text-generation" and model != TARGET_MODEL:
            changes.append(
                {
                    "id": row_id,
                    "provider": provider,
                    "model_type": model_type,
                    "before_model": model,
                    "after_model": TARGET_MODEL,
                }
            )
    return changes


def update_tenant_defaults(changes: list[dict[str, Any]]) -> None:
    if not changes:
        return
    statements = ["begin;"]
    for change in changes:
        statements.append(
            "update tenant_default_models "
            f"set model_name = {sql_string(TARGET_MODEL)}, updated_at = now() "
            f"where id = {sql_string(change['id'])};"
        )
    statements.append("commit;")
    psql([], input_text="\n".join(statements) + "\n")


def verify() -> dict[str, Any]:
    workflows = load_workflows()
    bad: list[dict[str, Any]] = []
    total_configs = 0
    for item in workflows:
        for path, config in iter_model_configs(item["graph"]):
            total_configs += 1
            model = config.get("model", config.get("name"))
            thinking = (
                config.get("completion_params", {}).get("thinking")
                if isinstance(config.get("completion_params"), dict)
                else None
            )
            target_thinking = target_thinking_for_app(item["app_id"])
            if (
                config.get("provider") != TARGET_PROVIDER
                or model != TARGET_MODEL
                or thinking is not target_thinking
            ):
                bad.append(
                    {
                        "workflow_id": item["id"],
                        "app_name": item["app_name"],
                        "version": item["version"],
                        "path": path,
                        "node": node_label(path, item["graph"]),
                        "provider": config.get("provider"),
                        "model": model,
                        "thinking": thinking,
                        "target_thinking": target_thinking,
                    }
                )
    return {
        "workflow_count": len(workflows),
        "model_config_count": total_configs,
        "bad_model_configs": bad,
        "tenant_default_changes_remaining": tenant_default_changes(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()

    if args.verify:
        print(json.dumps(verify(), ensure_ascii=False, indent=2))
        return 0

    workflows = load_workflows()
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_workflows(workflows, stamp)
    workflow_changed, workflow_events = patch_workflows(workflows)
    default_changes = tenant_default_changes()

    if not args.dry_run:
        if workflow_changed:
            update_workflows(workflows)
        update_tenant_defaults(default_changes)

    result = {
        "target_provider": TARGET_PROVIDER,
        "target_model": TARGET_MODEL,
        "thinking_policy": {
            "default": DEFAULT_THINKING,
            "outline": target_thinking_for_app(APP_IDS["outline"]),
            "reading_archive": target_thinking_for_app(APP_IDS["reading_archive"]),
        },
        "dry_run": args.dry_run,
        "backup": str(backup_path.relative_to(ROOT)),
        "workflow_changed": workflow_changed,
        "workflow_event_count": len(workflow_events),
        "workflow_events": workflow_events,
        "tenant_default_changes": default_changes,
    }
    if not args.dry_run:
        result["verify"] = verify()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
