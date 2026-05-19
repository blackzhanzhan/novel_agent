param(
    [switch]$Status,
    [switch]$VerifyOnly,
    [switch]$RestoreSqlBackup,
    [switch]$RecoverFromRuntimeEvidence,
    [switch]$RepairPluginStorage,
    [switch]$SyncEndpoint,
    [switch]$SkipStart,
    [switch]$RestartAfterRestore,
    [switch]$IUnderstandThisWritesDify,
    [switch]$DryRun,
    [int]$BackendPort = 0,
    [string]$BackupDir,
    [string]$WslDistro,
    [string]$DifyComposeDir,
    [string]$EnvFile
)

$ErrorActionPreference = "Stop"
$OriginalBoundParameters = @{}
foreach ($key in $PSBoundParameters.Keys) {
    $OriginalBoundParameters[$key] = $PSBoundParameters[$key]
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DeployDir = $ScriptDir
$RootDir = Split-Path -Parent (Split-Path -Parent $DeployDir)
$DefaultEnvFile = Join-Path $DeployDir ".env"
$StartDifyScript = Join-Path $RootDir "scripts\start_dify.ps1"
$PgRestoreScript = Join-Path $RootDir "scripts\dify_pg_restore.ps1"
$RecoverScript = Join-Path $RootDir "scripts\recover_dify_runtime.py"
$EndpointSyncScript = Join-Path $RootDir "scripts\sync_dify_tool_provider_endpoint.py"
$RuntimePortsManifest = Join-Path $RootDir ".runtime\ports.json"
$BackendVenvPython = Join-Path $RootDir "novel_git_server\venv\Scripts\python.exe"

if (-not $EnvFile) {
    $EnvFile = $DefaultEnvFile
}

function Write-Step {
    param([string]$Message)
    Write-Output ""
    Write-Output "== $Message =="
}

function Import-DemoEnvFile {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return }
    Write-Step "Environment"
    Write-Output "[env] loading $Path"
    foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#") -or $trimmed -notmatch "=") { continue }
        $name, $value = $trimmed.Split("=", 2)
        $name = $name.Trim()
        if (-not $name) { continue }
        $value = $value.Trim()
        if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        [Environment]::SetEnvironmentVariable($name, $value, "Process")
        if ($name -match "(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)") {
            Write-Output "[env] $name=***"
        }
        else {
            Write-Output "[env] $name=$value"
        }
    }
}

function Assert-Tool {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "[preflight] required tool not found: $Name"
    }
    Write-Output "[preflight] $Name OK"
}

function Get-PythonCommand {
    if (Test-Path -LiteralPath $BackendVenvPython) {
        return $BackendVenvPython
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) {
        throw "[preflight] python not found and backend venv is missing"
    }
    return $python.Source
}

function Resolve-Defaults {
    if (-not $script:OriginalBoundParameters.ContainsKey("WslDistro") -or [string]::IsNullOrWhiteSpace($WslDistro)) {
        $script:WslDistro = if ($env:NOVEL_AGENT_WSL_DISTRO) { $env:NOVEL_AGENT_WSL_DISTRO } else { "Ubuntu" }
    }
    if (-not $script:OriginalBoundParameters.ContainsKey("DifyComposeDir") -or [string]::IsNullOrWhiteSpace($DifyComposeDir)) {
        $script:DifyComposeDir = if ($env:NOVEL_AGENT_DIFY_COMPOSE_DIR) { $env:NOVEL_AGENT_DIFY_COMPOSE_DIR } else { "/home/zzy/dify/docker" }
    }
    if (-not $script:OriginalBoundParameters.ContainsKey("BackupDir") -or [string]::IsNullOrWhiteSpace($BackupDir)) {
        $script:BackupDir = $env:DIFY_SANITIZED_BACKUP_DIR
    }
    if (-not $script:OriginalBoundParameters.ContainsKey("BackendPort") -or $BackendPort -le 0) {
        $script:BackendPort = 8000
        if (Test-Path -LiteralPath $RuntimePortsManifest) {
            try {
                $manifest = Get-Content -LiteralPath $RuntimePortsManifest -Raw -Encoding UTF8 | ConvertFrom-Json
                if ($manifest.backend.selected_port) {
                    $script:BackendPort = [int]$manifest.backend.selected_port
                }
            }
            catch {
                Write-Warning "[ports] ignoring unreadable runtime ports manifest"
            }
        }
    }
}

function Invoke-External {
    param(
        [string]$Label,
        [string]$FilePath,
        [string[]]$ArgumentList
    )
    $commandText = "$FilePath $($ArgumentList -join ' ')"
    if ($DryRun) {
        Write-Output "[dry-run] ${Label}: $commandText"
        return
    }
    Write-Output "[$Label] $commandText"
    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "[$Label] failed with exit code $LASTEXITCODE"
    }
}

function Assert-LiveWriteAllowed {
    param([string]$Action)
    if (-not $IUnderstandThisWritesDify) {
        throw "[$Action] refused: pass -IUnderstandThisWritesDify to allow live Dify writes"
    }
}

function Assert-BackupDir {
    if ([string]::IsNullOrWhiteSpace($BackupDir)) {
        throw "[restore] BackupDir is required. Set -BackupDir or DIFY_SANITIZED_BACKUP_DIR in deploy/demo/.env"
    }
    if ($DryRun) {
        Write-Output "[dry-run] would require sanitized backup dir: $BackupDir"
        return
    }
    foreach ($file in @("dify.sql", "dify_plugin.sql")) {
        $path = Join-Path $BackupDir $file
        if (-not (Test-Path -LiteralPath $path)) {
            throw "[restore] missing $path"
        }
    }
}

function Invoke-DifyStart {
    if ($SkipStart -or $VerifyOnly -or $Status) {
        Write-Output "[dify] start skipped"
        return
    }
    Invoke-External -Label "dify" -FilePath $StartDifyScript -ArgumentList @(
        "-WslDistro", $WslDistro,
        "-ComposeDir", $DifyComposeDir
    )
}

function Invoke-DifyStatus {
    Invoke-External -Label "dify-status" -FilePath $StartDifyScript -ArgumentList @(
        "-Status",
        "-WslDistro", $WslDistro,
        "-ComposeDir", $DifyComposeDir
    )
}

function Invoke-DifyRestart {
    $restartCommand = "cd '$DifyComposeDir' && docker compose restart api worker plugin_daemon web"
    Invoke-External -Label "dify-restart" -FilePath "wsl" -ArgumentList @(
        "-d", $WslDistro,
        "--", "bash", "-lc", $restartCommand
    )
}

function Invoke-EndpointCheck {
    param([bool]$WriteLive)
    $endpointArgs = @("--backend-port", "$BackendPort")
    if (-not $WriteLive) {
        $endpointArgs += "--dry-run"
    }
    Invoke-External -Label "dify-endpoint" -FilePath (Get-PythonCommand) -ArgumentList (@($EndpointSyncScript) + $endpointArgs)
}

function Invoke-RecoverRuntime {
    param([string[]]$RuntimeArgs)
    Invoke-External -Label "dify-recover" -FilePath (Get-PythonCommand) -ArgumentList (@($RecoverScript) + $RuntimeArgs)
}

function Write-KeyWarnings {
    $required = @(
        "DIFY_WORLD_MODEL_API_KEY",
        "DIFY_STYLE_GUIDE_API_KEY",
        "DIFY_OUTLINE_API_KEY",
        "DIFY_CONTINUATION_API_KEY",
        "DIFY_REVIEW_API_KEY"
    )
    $missing = @($required | Where-Object { [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($_, "Process")) })
    if ($missing.Count -gt 0) {
        Write-Warning "[env] missing app keys: $($missing -join ', ')"
    }
    if ([string]::IsNullOrWhiteSpace($env:DEEPSEEK_API_KEY)) {
        Write-Warning "[env] DEEPSEEK_API_KEY is missing; model credential restore will stay unconfigured."
    }
}

if (-not $VerifyOnly -and -not $RestoreSqlBackup -and -not $RecoverFromRuntimeEvidence -and -not $RepairPluginStorage -and -not $SyncEndpoint -and -not $Status) {
    $VerifyOnly = $true
}

Import-DemoEnvFile -Path $EnvFile
Resolve-Defaults

Write-Step "Preflight"
Assert-Tool docker
Assert-Tool wsl
$python = Get-PythonCommand
Write-Output "[preflight] python=$python"
Write-Output "[preflight] backend_port=$BackendPort"
Write-Output "[preflight] wsl_distro=$WslDistro dify_compose_dir=$DifyComposeDir"
Write-KeyWarnings

if ($Status) {
    Write-Step "Dify status"
    Invoke-DifyStatus
    return
}

Write-Step "Dify startup"
Invoke-DifyStart

if ($RestoreSqlBackup) {
    Assert-LiveWriteAllowed -Action "restore-sql-backup"
    Assert-BackupDir
    Write-Step "Restore sanitized SQL backup"
    Invoke-External -Label "dify-sql-restore" -FilePath $PgRestoreScript -ArgumentList @(
        "-BackupDir", $BackupDir,
        "-WslDistro", $WslDistro
    )
    if ($RestartAfterRestore) {
        Invoke-DifyRestart
    }
}

if ($RecoverFromRuntimeEvidence) {
    Assert-LiveWriteAllowed -Action "recover-runtime-evidence"
    Write-Step "Recover from local runtime evidence"
    $args = @("--apply")
    if ($RestartAfterRestore) {
        $args += "--restart"
    }
    Invoke-RecoverRuntime -RuntimeArgs $args
}

if ($RepairPluginStorage) {
    Assert-LiveWriteAllowed -Action "repair-plugin-storage"
    Write-Step "Repair plugin storage"
    $args = @("--repair-plugin-storage", "--verify-plugin-storage")
    if ($RestartAfterRestore) {
        $args += "--restart"
    }
    Invoke-RecoverRuntime -RuntimeArgs $args
}

Write-Step "Endpoint"
if ($SyncEndpoint) {
    Assert-LiveWriteAllowed -Action "sync-endpoint"
    Invoke-EndpointCheck -WriteLive $true
}
else {
    Invoke-EndpointCheck -WriteLive $false
}

if ($VerifyOnly -or $RestoreSqlBackup -or $RecoverFromRuntimeEvidence -or $RepairPluginStorage) {
    Write-Step "Verify runtime"
    Invoke-RecoverRuntime -RuntimeArgs @("--verify-only")
}
