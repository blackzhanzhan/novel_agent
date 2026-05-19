param(
    [Parameter(Mandatory = $true)]
    [string]$ApiKey,
    [string]$ApiContainer = "docker-api-1",
    [string]$RedisContainer = "docker-redis-1",
    [string]$RedisPassword = "difyai123456",
    [string]$TenantId = "9dc77cc1-5dc7-4b24-a262-21d5ce09799c",
    [string]$ProviderName = "langgenius/deepseek/deepseek",
    [string]$EndpointUrl = "https://api.deepseek.com",
    [bool]$ResetTenantKeypair = $true
)

$ErrorActionPreference = "Stop"

function Assert-Tool {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required tool not found: $Name"
    }
}

Assert-Tool docker

if ([string]::IsNullOrWhiteSpace($ApiKey)) {
    throw "ApiKey is required."
}

$python = @'
import json
import os
from datetime import datetime, timezone

from app import app
from core.helper import encrypter
from extensions.ext_database import db
from libs.rsa import generate_key_pair
from models.account import Tenant
from models.provider import ProviderCredential

api_key = os.environ["CODEX_DIFY_DEEPSEEK_API_KEY"]
tenant_id = os.environ["CODEX_DIFY_TENANT_ID"]
provider_name = os.environ["CODEX_DIFY_PROVIDER_NAME"]
endpoint_url = os.environ["CODEX_DIFY_ENDPOINT_URL"]
reset_keypair = os.environ.get("CODEX_DIFY_RESET_TENANT_KEYPAIR", "true").lower() == "true"

with app.app_context():
    tenant = db.session.query(Tenant).filter(Tenant.id == tenant_id).one_or_none()
    if tenant is None:
        raise SystemExit(f"Tenant not found: {tenant_id}")

    if reset_keypair:
        tenant.encrypt_public_key = generate_key_pair(str(tenant.id))

    rows = (
        db.session.query(ProviderCredential)
        .filter(
            ProviderCredential.tenant_id == tenant.id,
            ProviderCredential.provider_name == provider_name,
        )
        .all()
    )
    if not rows:
        raise SystemExit(f"Provider credential not found: {provider_name}")

    for row in rows:
        data = json.loads(row.encrypted_config) if row.encrypted_config else {}
        data["api_key"] = encrypter.encrypt_token(str(row.tenant_id), api_key)
        data.setdefault("endpoint_url", endpoint_url)
        data.setdefault("mode", "chat")
        data.setdefault("function_calling_type", "tool_call")
        data.setdefault("stream_function_calling", "supported")
        row.encrypted_config = json.dumps(data, ensure_ascii=False)
        row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)

    db.session.commit()
    print(f"updated_deepseek_credentials={len(rows)} reset_tenant_keypair={reset_keypair}")
'@

$envArgs = @(
    "-e", "CODEX_DIFY_DEEPSEEK_API_KEY=$ApiKey",
    "-e", "CODEX_DIFY_TENANT_ID=$TenantId",
    "-e", "CODEX_DIFY_PROVIDER_NAME=$ProviderName",
    "-e", "CODEX_DIFY_ENDPOINT_URL=$EndpointUrl",
    "-e", "CODEX_DIFY_RESET_TENANT_KEYPAIR=$($ResetTenantKeypair.ToString().ToLowerInvariant())"
)

$python | docker exec @envArgs -i $ApiContainer sh -lc "cd /app/api && .venv/bin/python -"
if ($LASTEXITCODE -ne 0) {
    throw "Failed to patch Dify DeepSeek credential."
}

docker exec $RedisContainer redis-cli -a $RedisPassword -n 0 FLUSHDB | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Failed to clear Dify Redis cache."
}

Write-Host "redis_cache_cleared=True"
