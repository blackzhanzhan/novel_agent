param(
    [switch]$Stop,
    [switch]$Status,
    [string]$WslDistro = "Ubuntu",
    [string]$ComposeDir = "/home/zzy/dify/docker",
    [string]$ConsoleUrl = "http://localhost",
    [string]$ApiBaseUrl = "http://localhost/v1"
)

$ErrorActionPreference = "Stop"

function Test-HttpReachable {
    param([string]$Url)
    $response = $null
    try {
        $request = [System.Net.HttpWebRequest]::Create($Url)
        $request.Method = "GET"
        $request.Timeout = 3000
        $request.AllowAutoRedirect = $true
        $request.UserAgent = "novel-agent-startup-probe"
        $response = $request.GetResponse()
        return $true
    }
    catch [System.Net.WebException] {
        $response = $_.Exception.Response
        if ($response) {
            return $true
        }
        return $false
    }
    catch {
        return $false
    }
    finally {
        if ($response) {
            $response.Close()
        }
    }
}

function Invoke-WslCompose {
    param([string]$Command)
    $escapedDir = $ComposeDir.Replace("'", "'\''")
    $script = "cd '$escapedDir' && $Command"
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & wsl -d $WslDistro -- bash -lc $script 2>&1
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}

function Get-ServiceStateMap {
    $map = @{}
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $raw = docker ps --filter "name=docker-" --format "{{.Names}}`t{{.State}}`t{{.Status}}" 2>$null
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    foreach ($line in $raw) {
        $text = [string]$line
        if (-not $text.StartsWith("docker-")) { continue }
        $parts = $text.Split("`t")
        if ($parts.Length -lt 2) { continue }
        $name = $parts[0]
        $state = $parts[1]
        $status = if ($parts.Length -ge 3) { $parts[2] } else { "" }
        if ($name -match '^docker-(.+)-\d+$') {
            $service = $Matches[1]
            $map[$service] = @{ State = $state; Status = $status }
        }
    }
    return $map
}

function Test-RequiredServicesRunning {
    $required = @(
        "api",
        "worker",
        "web",
        "plugin_daemon",
        "db_postgres",
        "redis",
        "nginx",
        "sandbox",
        "ssrf_proxy"
    )
    $map = Get-ServiceStateMap
    foreach ($service in $required) {
        if (-not $map.ContainsKey($service) -or $map[$service].State -ne "running") {
            return $false
        }
    }
    return $true
}

function Get-DbPersistenceStatus {
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $out = (& docker inspect docker-db_postgres-1 2>&1) -join "`n"
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    try {
        $inspect = $out | ConvertFrom-Json
        $mount = @($inspect[0].Mounts) |
            Where-Object { $_.Destination -eq "/var/lib/postgresql/data" -and $_.Type -eq "bind" } |
            Select-Object -First 1
        if ($mount -and $mount.Source) { return "bind_mount=$($mount.Source)" }
    }
    catch {
    }
    return "bind_mount=MISSING_or_anonymous"
}

function Get-LatestBackup {
    $backupRoot = "C:/csptr/linuxptr/novel_agent/.dify_backups"
    if (-not (Test-Path $backupRoot)) { return "no_backups" }
    $latest = Get-ChildItem -Path $backupRoot -Directory | Sort-Object Name -Descending | Select-Object -First 1
    if (-not $latest) { return "no_backups" }
    $manifest = Join-Path $latest.FullName "manifest.json"
    if (Test-Path $manifest) { return "latest=$($latest.Name)" }
    return "latest=$($latest.Name)(no_manifest)"
}

function Write-Status {
    $consoleReachable = Test-HttpReachable -Url $ConsoleUrl
    $apiReachable = Test-HttpReachable -Url $ApiBaseUrl
    Write-Output "[dify] console=$consoleReachable api=$apiReachable compose_dir=$ComposeDir distro=$WslDistro"
    $dbPersistence = Get-DbPersistenceStatus
    $latestBackup = Get-LatestBackup
    Write-Output "[dify] db_persistence=$dbPersistence"
    Write-Output "[dify] backup=$latestBackup"
    if ($dbPersistence -like "*MISSING*") {
        Write-Warning "[dify] WARNING: db_postgres is NOT using a bind mount — data may be in an anonymous volume and lost on container removal"
    }
    $map = Get-ServiceStateMap
    if ($map.Count -eq 0) {
        Write-Output "[dify] compose services: none"
        return
    }
    foreach ($service in ($map.Keys | Sort-Object)) {
        $info = $map[$service]
        Write-Output ("[dify] service={0} state={1} status={2}" -f $service, $info.State, $info.Status)
    }
}

if ($Status) {
    Write-Status
    return
}

if ($Stop) {
    Invoke-WslCompose -Command "docker compose stop"
    Write-Output "[dify] stopped compose services in $ComposeDir"
    return
}

$servicesRunning = Test-RequiredServicesRunning
$consoleReachable = Test-HttpReachable -Url $ConsoleUrl
$apiReachable = Test-HttpReachable -Url $ApiBaseUrl
if ($servicesRunning -and $apiReachable) {
    Write-Output "[dify] already running (console=$ConsoleUrl api=$ApiBaseUrl)"
    return
}

Write-Output "[dify] starting missing or unhealthy compose services from $($WslDistro):$ComposeDir"
Invoke-WslCompose -Command "docker compose up -d"

$deadline = (Get-Date).AddSeconds(90)
while ((Get-Date) -lt $deadline) {
    $servicesRunning = Test-RequiredServicesRunning
    $apiReachable = Test-HttpReachable -Url $ApiBaseUrl
    if ($servicesRunning -and $apiReachable) {
        Write-Output "[dify] started (console=$ConsoleUrl api=$ApiBaseUrl)"
        return
    }
    Start-Sleep -Seconds 2
}

Write-Status

$missing = @()
$map = Get-ServiceStateMap
$required = @(
    "api", "worker", "web", "plugin_daemon",
    "db_postgres", "redis", "nginx", "sandbox", "ssrf_proxy"
)
foreach ($svc in $required) {
    if (-not $map.ContainsKey($svc) -or $map[$svc].State -ne "running") {
        $missing += $svc
    }
}
if ($missing.Count -gt 0) {
    throw "[dify] compose services did not become reachable within 90s. Missing: $($missing -join ', ')"
}
throw "[dify] compose services did not become reachable within 90s"
