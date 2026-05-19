param(
    [string]$ComposeDir = "/home/zzy/dify/docker",
    [string]$BackupDir = "/home/zzy/dify/backups",
    [string]$BackupPath = "",
    [string]$PluginBackupPath = "",
    [string]$DbContainer = "docker-db_postgres-1",
    [string]$Database = "dify",
    [string]$PluginDatabase = "dify_plugin",
    [string]$DbUser = "postgres",
    [string]$RuntimeDir = ".runtime",
    [bool]$RestorePluginDatabase = $true
)

$ErrorActionPreference = "Stop"

function Assert-Tool {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required tool not found: $Name"
    }
}

function Invoke-Wsl {
    param([string]$Command)
    wsl bash -lc $Command
    if ($LASTEXITCODE -ne 0) {
        throw "WSL command failed: $Command"
    }
}

Assert-Tool docker
Assert-Tool wsl

$root = (Resolve-Path ".").Path
$runtimePath = Join-Path $root $RuntimeDir
New-Item -ItemType Directory -Path $runtimePath -Force | Out-Null

if ([string]::IsNullOrWhiteSpace($BackupPath)) {
    $BackupPath = (wsl bash -lc "ls -1t $BackupDir/dify_after_persistent_plugin_fix_*.sql 2>/dev/null | head -1").Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($BackupPath)) {
        throw "No Dify runtime backup found under $BackupDir."
    }
}

Write-Host "backup=$BackupPath"
Invoke-Wsl "test -f '$BackupPath'"

if ($RestorePluginDatabase) {
    if ([string]::IsNullOrWhiteSpace($PluginBackupPath)) {
        $PluginBackupPath = (wsl bash -lc "ls -1t $BackupDir/dify_plugin_after_persistent_plugin_fix_*.sql 2>/dev/null | head -1").Trim()
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($PluginBackupPath)) {
            throw "No Dify plugin backup found under $BackupDir."
        }
    }
    Write-Host "plugin_backup=$PluginBackupPath"
    Invoke-Wsl "test -f '$PluginBackupPath'"
}

Write-Host "starting database container..."
Invoke-Wsl "cd '$ComposeDir' && docker compose up -d db_postgres"

$deadline = (Get-Date).AddSeconds(90)
do {
    $healthy = docker inspect $DbContainer --format "{{.State.Health.Status}}" 2>$null
    if ($healthy -eq "healthy") {
        break
    }
    Start-Sleep -Seconds 2
} while ((Get-Date) -lt $deadline)

if ($healthy -ne "healthy") {
    throw "Database container did not become healthy."
}

$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$emptyBackup = Join-Path $runtimePath "dify_before_runtime_restore_$ts.sql"
docker exec $DbContainer pg_dump -U $DbUser -d $Database | Set-Content -Path $emptyBackup -Encoding UTF8
if ($LASTEXITCODE -ne 0) {
    throw "Failed to snapshot current Dify database."
}

Write-Host "current_snapshot=$emptyBackup"

if ($RestorePluginDatabase) {
    $pluginEmptyBackup = Join-Path $runtimePath "dify_plugin_before_runtime_restore_$ts.sql"
    docker exec $DbContainer pg_dump -U $DbUser -d $PluginDatabase | Set-Content -Path $pluginEmptyBackup -Encoding UTF8
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to snapshot current Dify plugin database."
    }
    Write-Host "plugin_current_snapshot=$pluginEmptyBackup"
}

Write-Host "stopping Dify application containers..."
docker stop docker-api-1 docker-worker-1 docker-worker_beat-1 docker-web-1 docker-plugin_daemon-1 2>$null | Out-Null

Write-Host "restoring database..."
docker exec $DbContainer psql -U $DbUser -d $Database -v ON_ERROR_STOP=1 -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public; ALTER SCHEMA public OWNER TO postgres;"
if ($LASTEXITCODE -ne 0) {
    throw "Failed to reset public schema."
}

wsl bash -lc "cat '$BackupPath'" | docker exec -i $DbContainer psql -U $DbUser -d $Database -v ON_ERROR_STOP=1
if ($LASTEXITCODE -ne 0) {
    throw "Failed to restore Dify backup."
}

if ($RestorePluginDatabase) {
    Write-Host "restoring plugin database..."
    docker exec $DbContainer psql -U $DbUser -d $PluginDatabase -v ON_ERROR_STOP=1 -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public; ALTER SCHEMA public OWNER TO postgres;"
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to reset plugin public schema."
    }

    wsl bash -lc "cat '$PluginBackupPath'" | docker exec -i $DbContainer psql -U $DbUser -d $PluginDatabase -v ON_ERROR_STOP=1
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to restore Dify plugin backup."
    }
}

Write-Host "starting Dify stack..."
Invoke-Wsl "cd '$ComposeDir' && docker compose up -d"

$counts = docker exec $DbContainer psql -U $DbUser -d $Database -At -c "select 'accounts', count(*) from accounts union all select 'tenants', count(*) from tenants union all select 'apps', count(*) from apps union all select 'workflows', count(*) from workflows union all select 'tool_api_providers', count(*) from tool_api_providers;"
$verifyPath = Join-Path $runtimePath "dify_runtime_restore_verify_$ts.txt"
$counts | Set-Content -Path $verifyPath -Encoding UTF8

if ($RestorePluginDatabase) {
    $pluginCounts = docker exec $DbContainer psql -U $DbUser -d $PluginDatabase -At -c "select 'agent_strategy_installations', count(*) from agent_strategy_installations union all select 'ai_model_installations', count(*) from ai_model_installations union all select 'plugin_installations', count(*) from plugin_installations union all select 'plugins', count(*) from plugins;"
    $pluginVerifyPath = Join-Path $runtimePath "dify_plugin_runtime_restore_verify_$ts.txt"
    $pluginCounts | Set-Content -Path $pluginVerifyPath -Encoding UTF8
    Write-Host "plugin_verify=$pluginVerifyPath"
    $pluginCounts
}

Write-Host "verify=$verifyPath"
$counts
