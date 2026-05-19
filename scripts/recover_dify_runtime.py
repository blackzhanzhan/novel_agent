"""Recover local Dify app/workflow/plugin runtime from .runtime evidence.

This script intentionally does not import old Dify YAML exports. The YAML files
are historical baselines only; the live recovery source is the SQL/JSON evidence
captured in .runtime after the workflow refactors.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime"

DB_CONTAINER = "docker-db_postgres-1"
MAIN_DB = "dify"
PLUGIN_DB = "dify_plugin"

OLD_TENANT_ID = "9dc77cc1-5dc7-4b24-a262-21d5ce09799c"
OLD_ACCOUNT_ID = "f0ab0953-7dae-4d6d-a11a-a491679fe325"

TOOL_PROVIDER_ID = "c41fee3b-54dd-4e49-af9b-be30f68f6242"

APP_IDS = {
    "outline": "b58303e8-4a67-4327-8f56-ff1dbfc4023e",
    "review": "590dd17b-d9d0-4d5b-bffa-e6f1d8e45810",
    "world": "099c3beb-9f14-4389-850b-d6b7259ad064",
    "style": "bb3232af-7106-43ba-ae65-4f6e7fc82943",
    "continuation": "089d589b-09a5-42b9-864b-ccac331bb8f8",
}

APP_LABELS = {
    APP_IDS["outline"]: ("灵感大纲agent", "🧭"),
    APP_IDS["review"]: ("审核agent", "🔎"),
    APP_IDS["world"]: ("世界模型agent", "🌐"),
    APP_IDS["style"]: ("文风学习agent", "✍️"),
    APP_IDS["continuation"]: ("续写agent", "📝"),
}

BASE_DUMP = RUNTIME / "dify_before_continuation_publish_20260428_104348.sql"
PLUGIN_DUMP = RUNTIME / "dify_plugin_before_restore_20260428_104654.sql"
TOOL_PROVIDER_BACKUP = (
    RUNTIME / "loregit_tool_provider_backup_before_openapi_patch_20260428_215606.json"
)
PLUGIN_PACKAGE_DIR = RUNTIME / "plugin_packages"

PLUGIN_PACKAGES = {
    "deepseek": {
        "identifier": "langgenius/deepseek:0.0.15@725407927b04e236212083d20e92830d60fa944e42cd357ef6902c160414f6f1",
        "plugin_id": "langgenius/deepseek",
        "provider": "deepseek",
        "local_name": "deepseek.difypkg",
        "api_tmp": "/tmp/deepseek.difypkg",
    },
    "agent": {
        "identifier": "langgenius/agent:0.0.34@4b41a374567eb7cb226ee2f851513794566956008f1166c63205efc921be72d8",
        "plugin_id": "langgenius/agent",
        "provider": "agent",
        "local_name": "agent.difypkg",
        "api_tmp": "/tmp/agent.difypkg",
    },
}

DEEPSEEK_PROVIDER_NAME = "langgenius/deepseek/deepseek"
DEEPSEEK_ENDPOINT_URL = "https://api.deepseek.com/v1"

MAIN_COPY_TABLES = ("api_tokens", "apps", "workflows")
PLUGIN_COPY_TABLES = (
    "agent_strategy_installations",
    "ai_model_installations",
    "datasource_installations",
    "endpoints",
    "install_tasks",
    "plugin_declarations",
    "plugin_installations",
    "plugin_readme_records",
    "plugins",
    "serverless_runtimes",
    "tenant_storages",
    "tool_installations",
    "trigger_installations",
)

FINAL_PATCHES = (
    RUNTIME / "dify_model_flash_high_20260426_173240.sql",
    RUNTIME / "patch_outline_classifier_no_thinking.sql",
    RUNTIME / "patch_dify_style_agent_workflow_20260428_132211.sql",
    RUNTIME / "patch_dify_review_agent_workflow_20260428_154114.sql",
    RUNTIME / "patch_dify_continuation_bounded_self_revision_20260428_155237.sql",
    RUNTIME / "patch_loregit_replace_text_20260428_170823.sql",
    RUNTIME / "patch_loregit_openapi_tools_20260428_215606.sql",
    RUNTIME / "patch_dify_domain_rules_workflows_utf8_20260428_200323.sql",
    RUNTIME / "patch_dify_domain_runtime_prompt_cleanup_20260428_214055.sql",
    RUNTIME / "patch_dify_domain_rule_schema_contract_20260428_215626.sql",
    RUNTIME / "patch_dify_review_discovery_prompt_20260428_235719.sql",
)


def run(args: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        **kwargs,
    )


def psql(db: str, sql: str) -> str:
    proc = run(
        [
            "docker",
            "exec",
            "-i",
            DB_CONTAINER,
            "psql",
            "-U",
            "postgres",
            "-d",
            db,
            "-v",
            "ON_ERROR_STOP=1",
        ],
        input=sql,
        capture_output=True,
    )
    if proc.returncode:
        raise RuntimeError(
            f"psql failed for {db}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return proc.stdout


def psql_at(db: str, sql: str) -> list[str]:
    proc = run(
        [
            "docker",
            "exec",
            DB_CONTAINER,
            "psql",
            "-U",
            "postgres",
            "-d",
            db,
            "-Atc",
            sql,
        ],
        capture_output=True,
    )
    if proc.returncode:
        raise RuntimeError(proc.stderr)
    return [line for line in proc.stdout.splitlines() if line.strip()]


def current_identity() -> tuple[str, str]:
    rows = psql_at(
        MAIN_DB,
        """
        select a.id::text || '|' || t.id::text
        from accounts a
        join tenant_account_joins taj on taj.account_id = a.id
        join tenants t on t.id = taj.tenant_id
        order by a.created_at desc
        limit 1
        """,
    )
    if not rows:
        raise RuntimeError("Cannot detect current Dify account/tenant")
    account_id, tenant_id = rows[0].split("|", 1)
    return account_id, tenant_id


def backup_tables(db: str, tables: tuple[str, ...], stamp: str) -> Path:
    out = RUNTIME / f"dify_restore_backup_{db}_{stamp}.sql"
    args = [
        "docker",
        "exec",
        DB_CONTAINER,
        "pg_dump",
        "-U",
        "postgres",
        "-d",
        db,
        "--data-only",
        "--inserts",
    ]
    for table in tables:
        args.extend(["-t", table])
    proc = run(args, capture_output=True)
    if proc.returncode:
        raise RuntimeError(proc.stderr)
    out.write_text(proc.stdout, encoding="utf-8")
    return out


def transformed(text: str, account_id: str, tenant_id: str) -> str:
    return text.replace(OLD_TENANT_ID, tenant_id).replace(OLD_ACCOUNT_ID, account_id)


def read_text_any(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16")
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig")
    return raw.decode("utf-8", errors="replace")


def extract_copy_sections(path: Path, tables: tuple[str, ...]) -> dict[str, str]:
    wanted = {f"COPY public.{table} " for table in tables}
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in read_text_any(path).splitlines():
        if current is None:
            for table in tables:
                if line.startswith(f"COPY public.{table} "):
                    current = table
                    sections[current] = [line]
                    break
            continue
        sections[current].append(line)
        if line == r"\.":
            current = None
    missing = [table for table in tables if table not in sections]
    if missing:
        raise RuntimeError(f"Missing COPY sections in {path}: {missing}")
    return {table: "\n".join(lines) + "\n" for table, lines in sections.items()}


def dq(value: str) -> str:
    for tag in ("codex", "codex2", "codex3"):
        marker = f"${tag}$"
        if marker not in value:
            return f"{marker}{value}{marker}"
    raise ValueError("Could not find a safe dollar quote tag")


def sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def load_frontend_tokens() -> dict[str, str]:
    path = RUNTIME / "frontend_agent_tokens.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def build_main_base_sql(account_id: str, tenant_id: str) -> str:
    sections = extract_copy_sections(BASE_DUMP, MAIN_COPY_TABLES)
    pieces: list[str] = [
        "begin;",
        "delete from api_tokens where app_id in (" + ",".join(sql_string(v) for v in APP_IDS.values()) + ");",
        "delete from workflows where app_id in (" + ",".join(sql_string(v) for v in APP_IDS.values()) + ");",
        "delete from apps where id in (" + ",".join(sql_string(v) for v in APP_IDS.values()) + ");",
    ]
    for table in MAIN_COPY_TABLES:
        pieces.append(transformed(sections[table], account_id, tenant_id))

    tokens = load_frontend_tokens()
    continuation_token = tokens.get("continuation_api_token")
    if continuation_token:
        pieces.append(
            """
            insert into api_tokens (id, app_id, type, token, last_used_at, created_at, tenant_id)
            values (
              public.uuid_generate_v4(),
              '089d589b-09a5-42b9-864b-ccac331bb8f8',
              'app',
              {token},
              null,
              now(),
              {tenant}
            )
            on conflict do nothing;
            """.format(token=sql_string(continuation_token), tenant=sql_string(tenant_id))
        )

    for app_id, (name, icon) in APP_LABELS.items():
        pieces.append(
            """
            update apps
            set name = {name},
                icon = {icon},
                icon_type = 'emoji',
                tenant_id = {tenant},
                created_by = {account},
                updated_by = {account},
                updated_at = now()
            where id = {app_id};
            """.format(
                name=sql_string(name),
                icon=sql_string(icon),
                tenant=sql_string(tenant_id),
                account=sql_string(account_id),
                app_id=sql_string(app_id),
            )
        )

    pieces.extend(
        [
            f"update workflows set tenant_id = {sql_string(tenant_id)}, created_by = {sql_string(account_id)}, updated_by = {sql_string(account_id)} where app_id in ("
            + ",".join(sql_string(v) for v in APP_IDS.values())
            + ");",
            f"update api_tokens set tenant_id = {sql_string(tenant_id)} where app_id in ("
            + ",".join(sql_string(v) for v in APP_IDS.values())
            + ");",
            """
            update apps a
            set workflow_id = w.id
            from (
              select distinct on (app_id) id, app_id
              from workflows
              where version = 'draft'
              order by app_id, updated_at desc nulls last, created_at desc
            ) w
            where a.id = w.app_id;
            """,
            """
            update apps a
            set workflow_id = w.id
            from (
              select distinct on (app_id) id, app_id
              from workflows
              where version <> 'draft'
              order by app_id, updated_at desc nulls last, created_at desc
            ) w
            where a.id = w.app_id and a.workflow_id is null;
            """,
            "commit;",
        ]
    )
    return "\n".join(pieces)


def build_plugin_sql(account_id: str, tenant_id: str) -> str:
    sections = extract_copy_sections(PLUGIN_DUMP, PLUGIN_COPY_TABLES)
    pieces = [
        "begin;",
        "truncate "
        + ", ".join(f"public.{table}" for table in PLUGIN_COPY_TABLES)
        + " restart identity cascade;",
    ]
    for table in PLUGIN_COPY_TABLES:
        pieces.append(transformed(sections[table], account_id, tenant_id))
    pieces.append("commit;")
    return "\n".join(pieces)


def build_tool_provider_sql(account_id: str, tenant_id: str) -> str:
    backup = json.loads(TOOL_PROVIDER_BACKUP.read_text(encoding="utf-8-sig"))
    schema = backup["schema"]
    tools_str = backup["tools_str"]
    description = backup.get("description", "")
    name = backup.get("name") or "LoreGit 后端工具集"
    schema_type = backup.get("schema_type_str") or "openapi"
    icon = json.dumps({"background": "#EFF1F5", "content": "LG"}, ensure_ascii=False)
    credentials = json.dumps({"auth_type": "none"}, ensure_ascii=False)
    return f"""
    begin;
    insert into tool_api_providers (
      id, name, schema, schema_type_str, user_id, tenant_id, tools_str, icon,
      credentials_str, description, created_at, updated_at, privacy_policy, custom_disclaimer
    )
    values (
      {sql_string(TOOL_PROVIDER_ID)},
      {sql_string(name)},
      {dq(schema)},
      {sql_string(schema_type)},
      {sql_string(account_id)},
      {sql_string(tenant_id)},
      {dq(tools_str)},
      {dq(icon)},
      {dq(credentials)},
      {dq(description)},
      now(),
      now(),
      '',
      ''
    )
    on conflict (id) do update set
      name = excluded.name,
      schema = excluded.schema,
      schema_type_str = excluded.schema_type_str,
      user_id = excluded.user_id,
      tenant_id = excluded.tenant_id,
      tools_str = excluded.tools_str,
      icon = excluded.icon,
      credentials_str = excluded.credentials_str,
      description = excluded.description,
      updated_at = now();
    commit;
    """


def build_deepseek_provider_sql(tenant_id: str) -> str:
    config = json.dumps({"api_key": "", "endpoint_url": DEEPSEEK_ENDPOINT_URL}, ensure_ascii=False)
    return f"""
    begin;
    delete from providers
    where tenant_id = {sql_string(tenant_id)}
      and provider_name = {sql_string(DEEPSEEK_PROVIDER_NAME)};

    delete from provider_credentials
    where tenant_id = {sql_string(tenant_id)}
      and provider_name = {sql_string(DEEPSEEK_PROVIDER_NAME)}
      and credential_name = 'DeepSeek local';

    insert into provider_credentials (
      id, tenant_id, provider_name, credential_name, encrypted_config, created_at, updated_at
    )
    values (
      public.uuid_generate_v4(),
      {sql_string(tenant_id)},
      {sql_string(DEEPSEEK_PROVIDER_NAME)},
      'DeepSeek local',
      {dq(config)},
      now(),
      now()
    );

    insert into providers (
      id, tenant_id, provider_name, provider_type, is_valid, credential_id,
      quota_type, quota_limit, quota_used, created_at, updated_at
    )
    select
      public.uuid_generate_v4(),
      {sql_string(tenant_id)},
      {sql_string(DEEPSEEK_PROVIDER_NAME)},
      'custom',
      true,
      pc.id,
      '',
      null,
      0,
      now(),
      now()
    from provider_credentials pc
    where pc.tenant_id = {sql_string(tenant_id)}
      and pc.provider_name = {sql_string(DEEPSEEK_PROVIDER_NAME)}
      and pc.credential_name = 'DeepSeek local'
    order by pc.updated_at desc
    limit 1;
    commit;
    """


def run_api_python(code: str, pass_env: tuple[str, ...] = ()) -> str:
    args = ["docker", "exec", "-i"]
    for name in pass_env:
        args.extend(["-e", name])
    args.extend(["docker-api-1", "sh", "-c", "cd /app/api && python -"])
    proc = run(args, input=code, capture_output=True)
    if proc.returncode:
        raise RuntimeError(
            f"api python failed\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return proc.stdout


def plugin_package_path(plugin: dict[str, str], storage_root: str = "/app/storage/plugin_packages") -> str:
    namespace, package_name = plugin["identifier"].split("/", 1)
    return f"{storage_root}/{namespace}/{package_name}"


def plugin_cwd_path(plugin: dict[str, str]) -> str:
    namespace, package_name = plugin["identifier"].split("/", 1)
    provider, version_hash = package_name.split(":", 1)
    version, checksum = version_hash.split("@", 1)
    return f"/app/storage/cwd/{namespace}/{provider}-{version}@{checksum}"


def ensure_plugin_packages_on_daemon() -> dict[str, object]:
    """Copy bundled local plugin packages back into plugin_daemon storage.

    Dify DB restores can preserve plugin_installation rows while the Docker
    plugin volume no longer contains the package files. This function only adds
    missing package files; it does not delete or rewrite existing runtime data.
    """
    copied: list[str] = []
    present: list[str] = []
    missing_local: list[str] = []
    for plugin in PLUGIN_PACKAGES.values():
        local_path = PLUGIN_PACKAGE_DIR / plugin["local_name"]
        if not local_path.exists():
            missing_local.append(str(local_path.relative_to(ROOT)))
            continue
        daemon_plugin_path = plugin_package_path(plugin, "/app/storage/plugin")
        daemon_package_path = plugin_package_path(plugin, "/app/storage/plugin_packages")
        probe = run(
            ["docker", "exec", "docker-plugin_daemon-1", "test", "-f", daemon_plugin_path]
        )
        if probe.returncode == 0:
            present.append(plugin["identifier"])
            continue
        tmp_path = f"/tmp/{plugin['local_name']}"
        run(
            ["docker", "cp", str(local_path), f"docker-plugin_daemon-1:{tmp_path}"],
            check=True,
            capture_output=True,
        )
        shell = (
            "set -e; "
            f"mkdir -p '{Path(daemon_plugin_path).parent.as_posix()}' "
            f"'{Path(daemon_package_path).parent.as_posix()}'; "
            f"cp '{tmp_path}' '{daemon_plugin_path}'; "
            f"cp '{tmp_path}' '{daemon_package_path}'"
        )
        run(
            ["docker", "exec", "docker-plugin_daemon-1", "sh", "-lc", shell],
            check=True,
            capture_output=True,
        )
        copied.append(plugin["identifier"])
    if missing_local:
        raise RuntimeError(
            "Missing local plugin packages:\n"
            + "\n".join(missing_local)
            + "\nRestore .runtime/plugin_packages before recovering Dify plugin storage."
        )
    return {"copied": copied, "present": present}


def install_plugin_packages(tenant_id: str) -> dict[str, object]:
    PLUGIN_PACKAGE_DIR.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for package in PLUGIN_PACKAGES.values():
        local_path = PLUGIN_PACKAGE_DIR / package["local_name"]
        if not local_path.exists():
            daemon_package = plugin_package_path(package)
            run(
                ["docker", "cp", f"docker-plugin_daemon-1:{daemon_package}", str(local_path)],
                check=True,
                capture_output=True,
            )
        run(
            [
                "docker",
                "cp",
                str(local_path),
                f"docker-api-1:{package['api_tmp']}",
            ],
            check=True,
            capture_output=True,
        )
        copied.append(str(local_path.relative_to(ROOT)))

    payload = {
        "tenant_id": tenant_id,
        "packages": [
            {
                "identifier": package["identifier"],
                "path": package["api_tmp"],
            }
            for package in PLUGIN_PACKAGES.values()
        ],
    }
    code = "payload = " + repr(json.dumps(payload, ensure_ascii=False)) + r'''
import json
import os
import requests
import time

payload = json.loads(payload)
base = os.environ["PLUGIN_DAEMON_URL"]
key = os.environ["PLUGIN_DAEMON_KEY"]
tenant_id = payload["tenant_id"]
headers = {"X-Api-Key": key}

uploaded = []
for package in payload["packages"]:
    with open(package["path"], "rb") as fh:
        response = requests.post(
            f"{base}/plugin/{tenant_id}/management/install/upload/package",
            headers=headers,
            files={"dify_pkg": ("dify_pkg", fh, "application/octet-stream")},
            data={"verify_signature": "false"},
            timeout=60,
        )
    body = response.json()
    if body.get("code") != 0:
        raise RuntimeError(f"plugin upload failed for {package['identifier']}: {body}")
    uploaded.append(package["identifier"])

identifiers = [package["identifier"] for package in payload["packages"]]
response = requests.post(
    f"{base}/plugin/{tenant_id}/management/install/identifiers",
    headers={**headers, "Content-Type": "application/json"},
    json={"plugin_unique_identifiers": identifiers, "source": "package", "metas": [{} for _ in identifiers]},
    timeout=60,
)
body = response.json()
if body.get("code") != 0:
    raise RuntimeError(f"plugin install failed: {body}")

install_data = body.get("data") or {}
task_id = install_data.get("task_id")
task_status = "already_installed" if install_data.get("all_installed") else "unknown"
if task_id:
    for _ in range(60):
        response = requests.get(
            f"{base}/plugin/{tenant_id}/management/install/tasks/{task_id}",
            headers=headers,
            timeout=20,
        )
        task_body = response.json()
        if task_body.get("code") != 0:
            time.sleep(1)
            continue
        task = task_body.get("data") or {}
        task_status = task.get("status", "")
        if task_status in {"success", "failed"}:
            if task_status == "failed":
                raise RuntimeError(f"plugin install task failed: {task}")
            break
        time.sleep(1)
    else:
        raise TimeoutError(f"plugin install task timed out: {task_id}")

print(json.dumps({"uploaded": uploaded, "task_id": task_id, "task_status": task_status}, ensure_ascii=False))
'''
    out = run_api_python(code, pass_env=("PLUGIN_DAEMON_URL", "PLUGIN_DAEMON_KEY"))
    result = json.loads(out.strip() or "{}")
    result["copied"] = copied
    return result


def verify_plugin_storage() -> dict[str, object]:
    plugin_ids = set(
        psql_at(
            PLUGIN_DB,
            """
            select plugin_unique_identifier
            from plugin_installations
            union
            select plugin_unique_identifier
            from ai_model_installations
            union
            select plugin_unique_identifier
            from agent_strategy_installations
            order by 1
            """,
        )
    )
    missing_db: list[str] = []
    missing_package: list[str] = []
    missing_runtime: list[str] = []
    for package in PLUGIN_PACKAGES.values():
        identifier = package["identifier"]
        if identifier not in plugin_ids:
            missing_db.append(identifier)
        for root in ("/app/storage/plugin", "/app/storage/plugin_packages"):
            proc = run(
                [
                    "docker",
                    "exec",
                    "docker-plugin_daemon-1",
                    "test",
                    "-f",
                    plugin_package_path(package, root),
                ]
            )
            if proc.returncode:
                missing_package.append(f"{root}:{identifier}")
        proc = run(
            ["docker", "exec", "docker-plugin_daemon-1", "test", "-d", plugin_cwd_path(package)]
        )
        if proc.returncode:
            missing_runtime.append(identifier)
    return {
        "plugin_db_required_missing": missing_db,
        "plugin_package_missing": missing_package,
        "plugin_runtime_missing": missing_runtime,
        "all_ok": not missing_db and not missing_package and not missing_runtime,
    }


def configure_deepseek_credentials(tenant_id: str) -> dict[str, object]:
    code = r'''
import base64
import json
import os
from pathlib import Path

import psycopg2
from Crypto.PublicKey import RSA
from libs import rsa as dify_rsa

tenant_id = os.environ["DIFY_RECOVERY_TENANT_ID"]
api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
if not api_key:
    raise RuntimeError("DEEPSEEK_API_KEY is required to configure DeepSeek provider credentials")

conn = psycopg2.connect(
    host=os.environ["DB_HOST"],
    port=os.environ["DB_PORT"],
    dbname=os.environ["DB_DATABASE"],
    user=os.environ["DB_USERNAME"],
    password=os.environ["DB_PASSWORD"],
)
cur = conn.cursor()
cur.execute(
    """
    select id, encrypted_config
    from provider_credentials
    where tenant_id = %s
      and provider_name = %s
    order by updated_at desc
    limit 1
    """,
    (tenant_id, "langgenius/deepseek/deepseek"),
)
row = cur.fetchone()
if not row:
    raise RuntimeError("DeepSeek provider credential row not found")

credential_id, raw_config = row
config = json.loads(raw_config)

private_key = RSA.generate(2048)
public_key = private_key.publickey().export_key().decode()
private_path = Path("/app/api/storage/privkeys") / tenant_id / "private.pem"
private_path.parent.mkdir(parents=True, exist_ok=True)
private_path.write_bytes(private_key.export_key())

encrypted_api_key = base64.b64encode(dify_rsa.encrypt(api_key, public_key)).decode()
new_config = json.dumps(
    {"api_key": encrypted_api_key, "endpoint_url": "https://api.deepseek.com/v1"},
    ensure_ascii=False,
)
cur.execute("update tenants set encrypt_public_key = %s, updated_at = now() where id = %s", (public_key, tenant_id))
cur.execute(
    "update provider_credentials set encrypted_config = %s, updated_at = now() where id = %s",
    (new_config, credential_id),
)
cur.execute(
    """
    update providers
    set credential_id = %s, is_valid = true, updated_at = now()
    where tenant_id = %s
      and provider_name = %s
    """,
    (credential_id, tenant_id, "langgenius/deepseek/deepseek"),
)
conn.commit()
print(json.dumps({"credential_id": str(credential_id), "private_key_written": str(private_path)}, ensure_ascii=False))
'''
    env = os.environ.copy()
    env["DIFY_RECOVERY_TENANT_ID"] = tenant_id
    proc = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            "-e",
            "DEEPSEEK_API_KEY",
            "-e",
            "DIFY_RECOVERY_TENANT_ID",
            "docker-api-1",
            "sh",
            "-c",
            "cd /app/api && python -",
        ],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        input=code,
        capture_output=True,
        env=env,
    )
    if proc.returncode:
        raise RuntimeError(
            f"deepseek credential configuration failed\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    clear_redis_pattern(f"*credentials*{tenant_id}*")
    return json.loads(proc.stdout.strip() or "{}")


def clear_redis_pattern(pattern: str) -> list[str]:
    rows = run(
        ["docker", "exec", "docker-redis-1", "redis-cli", "--scan", "--pattern", pattern],
        capture_output=True,
    ).stdout.splitlines()
    keys = [row.strip() for row in rows if row.strip()]
    for key in keys:
        run(["docker", "exec", "docker-redis-1", "redis-cli", "DEL", key], check=True, capture_output=True)
    return keys


def apply_patch_sql(path: Path, account_id: str, tenant_id: str) -> None:
    sql = transformed(read_text_any(path), account_id, tenant_id)
    psql(MAIN_DB, sql)


def restore(account_id: str, tenant_id: str, stamp: str) -> dict[str, object]:
    missing = [str(path) for path in (BASE_DUMP, PLUGIN_DUMP, TOOL_PROVIDER_BACKUP, *FINAL_PATCHES) if not path.exists()]
    if missing:
        raise RuntimeError("Missing required recovery evidence:\n" + "\n".join(missing))

    main_backup = backup_tables(
        MAIN_DB,
        ("apps", "workflows", "api_tokens", "tool_api_providers", "providers", "provider_credentials"),
        stamp,
    )
    plugin_backup = backup_tables(PLUGIN_DB, PLUGIN_COPY_TABLES, stamp)

    main_sql = build_main_base_sql(account_id, tenant_id)
    main_sql_path = RUNTIME / f"dify_restore_main_base_{stamp}.sql"
    main_sql_path.write_text(main_sql, encoding="utf-8")
    psql(MAIN_DB, main_sql)

    plugin_sql = build_plugin_sql(account_id, tenant_id)
    plugin_sql_path = RUNTIME / f"dify_restore_plugin_base_{stamp}.sql"
    plugin_sql_path.write_text(plugin_sql, encoding="utf-8")
    psql(PLUGIN_DB, plugin_sql)
    plugin_install = install_plugin_packages(tenant_id)

    tool_sql = build_tool_provider_sql(account_id, tenant_id)
    tool_sql_path = RUNTIME / f"dify_restore_tool_provider_{stamp}.sql"
    tool_sql_path.write_text(tool_sql, encoding="utf-8")
    psql(MAIN_DB, tool_sql)

    psql(MAIN_DB, build_deepseek_provider_sql(tenant_id))
    model_provider: object = "skipped_missing_DEEPSEEK_API_KEY"
    if os.environ.get("DEEPSEEK_API_KEY", "").strip():
        model_provider = configure_deepseek_credentials(tenant_id)

    applied_patches: list[str] = []
    for patch in FINAL_PATCHES:
        apply_patch_sql(patch, account_id, tenant_id)
        applied_patches.append(str(patch.relative_to(ROOT)))

    return {
        "main_backup": str(main_backup.relative_to(ROOT)),
        "plugin_backup": str(plugin_backup.relative_to(ROOT)),
        "generated_sql": [
            str(main_sql_path.relative_to(ROOT)),
            str(plugin_sql_path.relative_to(ROOT)),
            str(tool_sql_path.relative_to(ROOT)),
        ],
        "plugin_install": plugin_install,
        "model_provider": model_provider,
        "applied_patches": applied_patches,
    }


def verify() -> dict[str, object]:
    counts = dict(
        row.split("=", 1)
        for row in psql_at(
            MAIN_DB,
            """
            select 'apps=' || count(*) from apps where id in (
              'b58303e8-4a67-4327-8f56-ff1dbfc4023e',
              '590dd17b-d9d0-4d5b-bffa-e6f1d8e45810',
              '099c3beb-9f14-4389-850b-d6b7259ad064',
              'bb3232af-7106-43ba-ae65-4f6e7fc82943',
              '089d589b-09a5-42b9-864b-ccac331bb8f8'
            )
            union all
            select 'workflows=' || count(*) from workflows where app_id in (
              'b58303e8-4a67-4327-8f56-ff1dbfc4023e',
              '590dd17b-d9d0-4d5b-bffa-e6f1d8e45810',
              '099c3beb-9f14-4389-850b-d6b7259ad064',
              'bb3232af-7106-43ba-ae65-4f6e7fc82943',
              '089d589b-09a5-42b9-864b-ccac331bb8f8'
            )
            union all
            select 'api_tokens=' || count(*) from api_tokens where app_id in (
              'b58303e8-4a67-4327-8f56-ff1dbfc4023e',
              '590dd17b-d9d0-4d5b-bffa-e6f1d8e45810',
              '099c3beb-9f14-4389-850b-d6b7259ad064',
              'bb3232af-7106-43ba-ae65-4f6e7fc82943',
              '089d589b-09a5-42b9-864b-ccac331bb8f8'
            )
            union all
            select 'tool_api_providers=' || count(*) from tool_api_providers where id = 'c41fee3b-54dd-4e49-af9b-be30f68f6242'
            """,
        )
    )
    apps = psql_at(
        MAIN_DB,
        "select id::text || '|' || name || '|' || coalesce(workflow_id::text,'') from apps where id in ("
        + ",".join(sql_string(v) for v in APP_IDS.values())
        + ") order by name;",
    )
    marker_rows = psql_at(
        MAIN_DB,
        """
        select app_id::text || '|' || version || '|' ||
          (graph::text like '%validate_chapter_lengths%') || '|' ||
          (graph::text like '%draft_replace_text%') || '|' ||
          (graph::text like '%validate_domain_facts%') || '|' ||
          (graph::text like '%style_fingerprint.md%') || '|' ||
          (graph::text like '%style_constraints_for_continuation.md%') || '|' ||
          (graph::text like '%COMMIT_AGENT%') || '|' ||
          (graph::text like '%REVIEW_AGENT%') || '|' ||
          (graph::text like '%CONTINUATION_AGENT%')
        from workflows
        where app_id in (
          'b58303e8-4a67-4327-8f56-ff1dbfc4023e',
          '590dd17b-d9d0-4d5b-bffa-e6f1d8e45810',
          '099c3beb-9f14-4389-850b-d6b7259ad064',
          'bb3232af-7106-43ba-ae65-4f6e7fc82943',
          '089d589b-09a5-42b9-864b-ccac331bb8f8'
        )
        order by app_id, version;
        """,
    )
    provider_tools = psql_at(
        MAIN_DB,
        f"select tools_str from tool_api_providers where id = {sql_string(TOOL_PROVIDER_ID)}",
    )
    operation_ids: list[str] = []
    if provider_tools:
        try:
            operation_ids = [item.get("operation_id") for item in json.loads(provider_tools[0])]
        except Exception:
            operation_ids = []
    plugin_counts = dict(
        row.split("=", 1)
        for row in psql_at(
            PLUGIN_DB,
            """
            select 'plugins=' || count(*) from plugins
            union all select 'plugin_installations=' || count(*) from plugin_installations
            union all select 'ai_model_installations=' || count(*) from ai_model_installations
            union all select 'agent_strategy_installations=' || count(*) from agent_strategy_installations
            union all select 'tool_installations=' || count(*) from tool_installations
            """,
        )
    )
    plugin_ids = psql_at(
        PLUGIN_DB,
        """
        select plugin_unique_identifier
        from plugin_installations
        union
        select plugin_unique_identifier
        from ai_model_installations
        union
        select plugin_unique_identifier
        from agent_strategy_installations
        order by 1
        """,
    )
    required_ops = {
        "validate_chapter_lengths",
        "generate_style_diagnostics",
        "draft_append_markdown_section",
        "draft_replace_markdown_section",
        "draft_sync_markdown_sections",
        "draft_sync_all",
        "draft_confirm",
    }
    required_plugins = {package["identifier"] for package in PLUGIN_PACKAGES.values()}
    storage_missing: list[str] = []
    for package in PLUGIN_PACKAGES.values():
        plugin_id = package["identifier"]
        path = plugin_cwd_path(package)
        proc = run(["docker", "exec", "docker-plugin_daemon-1", "test", "-d", path])
        if proc.returncode:
            storage_missing.append(plugin_id)
    provider_rows = psql_at(
        MAIN_DB,
        """
        select count(*)::text
        from providers p
        join provider_credentials pc on pc.id = p.credential_id
        where p.tenant_id = (select tenant_id from apps limit 1)
          and p.provider_name = 'langgenius/deepseek/deepseek'
          and p.provider_type = 'custom'
          and p.is_valid = true
          and pc.encrypted_config is not null
          and pc.encrypted_config <> ''
        """,
    )
    tenant_rows = psql_at(MAIN_DB, "select tenant_id::text from apps limit 1")
    private_key_ok = False
    if tenant_rows:
        proc = run(
            [
                "docker",
                "exec",
                "docker-api-1",
                "test",
                "-f",
                f"/app/api/storage/privkeys/{tenant_rows[0]}/private.pem",
            ]
        )
        private_key_ok = proc.returncode == 0
    return {
        "counts": counts,
        "apps": apps,
        "marker_rows": marker_rows,
        "provider_tool_count": len(operation_ids),
        "required_operations_missing": sorted(required_ops - set(operation_ids)),
        "plugin_counts": plugin_counts,
        "plugin_db_required_missing": sorted(required_plugins - set(plugin_ids)),
        "plugin_storage_missing": storage_missing,
        "deepseek_provider_valid": bool(provider_rows and int(provider_rows[0]) > 0),
        "tenant_private_key_ok": private_key_ok,
        "all_ok": (
            counts.get("apps") == "5"
            and int(counts.get("workflows", "0")) >= 5
            and counts.get("tool_api_providers") == "1"
            and not (required_ops - set(operation_ids))
            and not (required_plugins - set(plugin_ids))
            and not storage_missing
            and bool(provider_rows and int(provider_rows[0]) > 0)
            and private_key_ok
        ),
    }


def restart_runtime() -> None:
    run(["docker", "restart", "docker-plugin_daemon-1", "docker-api-1", "docker-worker-1"], check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write recovered runtime into Dify")
    parser.add_argument(
        "--repair-plugin-storage",
        action="store_true",
        help="copy bundled plugin packages into plugin_daemon storage without changing DB rows",
    )
    parser.add_argument(
        "--verify-plugin-storage",
        action="store_true",
        help="verify plugin DB rows plus plugin_daemon package/runtime files only",
    )
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--restart", action="store_true")
    args = parser.parse_args()

    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    account_id, tenant_id = current_identity()
    report: dict[str, object] = {
        "stamp": stamp,
        "account_id": account_id,
        "tenant_id": tenant_id,
        "source": {
            "base_dump": str(BASE_DUMP.relative_to(ROOT)),
            "plugin_dump": str(PLUGIN_DUMP.relative_to(ROOT)),
            "tool_provider_backup": str(TOOL_PROVIDER_BACKUP.relative_to(ROOT)),
            "patch_count": len(FINAL_PATCHES),
        },
    }
    if args.repair_plugin_storage:
        report["plugin_storage_repair"] = ensure_plugin_packages_on_daemon()
        if args.restart:
            restart_runtime()
            report["restarted"] = ["docker-plugin_daemon-1", "docker-api-1", "docker-worker-1"]
    if args.verify_plugin_storage:
        report["plugin_storage_verify"] = verify_plugin_storage()
    if args.apply:
        report["restore"] = restore(account_id, tenant_id, stamp)
        if args.restart:
            restart_runtime()
            report["restarted"] = ["docker-plugin_daemon-1", "docker-api-1", "docker-worker-1"]
    if args.apply or args.verify_only:
        report["verify"] = verify()
    out_path = RUNTIME / f"dify_restore_verify_{stamp}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.verify_plugin_storage and not report.get("plugin_storage_verify", {}).get("all_ok"):
        return 2
    if (args.apply or args.verify_only) and not report.get("verify", {}).get("all_ok"):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
