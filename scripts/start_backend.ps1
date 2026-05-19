param(
    [switch]$Stop,
    [switch]$Status,
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$BackendDir = Join-Path $RootDir "novel_git_server"
$RuntimeDir = Join-Path $RootDir ".runtime"
$PidFile = Join-Path $RuntimeDir $(if ($Port -eq 8000) { "backend.pid" } else { "backend_$Port.pid" })
$LogFile = Join-Path $RuntimeDir $(if ($Port -eq 8000) { "backend.log" } else { "backend_$Port.log" })
$ErrLogFile = Join-Path $RuntimeDir $(if ($Port -eq 8000) { "backend.err.log" } else { "backend_$Port.err.log" })
$HealthUrl = "http://127.0.0.1:$Port/health"
$CanonicalPython = Join-Path $BackendDir "venv\Scripts\python.exe"

New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null

function Read-PidFile {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    $raw = (Get-Content -LiteralPath $Path -Raw).Trim()
    if (-not $raw) { return $null }
    try { return [int]$raw } catch { return $null }
}

function Test-ProcessRunning {
    param([int]$ProcessId)
    return $ProcessId -and ($null -ne (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue))
}

function Test-PortOpen {
    param([int]$Port)
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $connect = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        if (-not $connect.AsyncWaitHandle.WaitOne(500)) { return $false }
        $client.EndConnect($connect)
        return $true
    }
    catch {
        return $false
    }
    finally {
        $client.Dispose()
    }
}

function Test-HttpOk {
    param([string]$Url)
    try {
        Invoke-RestMethod -Uri $Url -TimeoutSec 2 | Out-Null
        return $true
    }
    catch {
        return $false
    }
}

function Get-PortOwnerProcessIds {
    param([int]$Port)
    $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    return @($connections | Select-Object -ExpandProperty OwningProcess -Unique)
}

function Get-ProcessCommandLine {
    param([int]$ProcessId)
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
    if ($proc) { return [string]$proc.CommandLine }
    return ""
}

function Test-CanonicalBackendProcess {
    param([int]$ProcessId)
    $commandLine = Get-ProcessCommandLine -ProcessId $ProcessId
    return $commandLine -like "*$CanonicalPython*" -and $commandLine -like "*app.py*"
}

function Get-CanonicalBackendPortOwner {
    foreach ($owner in (Get-PortOwnerProcessIds -Port $Port)) {
        if (Test-CanonicalBackendProcess -ProcessId ([int]$owner)) {
            return [int]$owner
        }
    }
    return $null
}

function Stop-ProcessTree {
    param([int]$ProcessId)
    if (-not (Test-ProcessRunning -ProcessId $ProcessId)) { return }
    $children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$ProcessId" -ErrorAction SilentlyContinue
    foreach ($child in $children) {
        Stop-ProcessTree -ProcessId ([int]$child.ProcessId)
    }
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

function Wait-Health {
    param([int]$TimeoutSeconds)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-HttpOk -Url $HealthUrl) { return }
        Start-Sleep -Milliseconds 500
    }
    throw "[backend] did not become healthy at $HealthUrl within ${TimeoutSeconds}s"
}

function Import-EnvFile {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return }
    foreach ($line in Get-Content -LiteralPath $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#") -or $trimmed -notmatch "=") { continue }
        $name, $value = $trimmed.Split("=", 2)
        if ($name) {
            [Environment]::SetEnvironmentVariable($name.Trim(), $value.Trim(), "Process")
        }
    }
}

function Write-Status {
    $pidValue = Read-PidFile -Path $PidFile
    $processRunning = $pidValue -and (Test-ProcessRunning -ProcessId $pidValue)
    $healthOk = Test-HttpOk -Url $HealthUrl
    $portOpen = Test-PortOpen -Port $Port
    $portOwners = @(Get-PortOwnerProcessIds -Port $Port)
    $canonicalPortOwner = Get-CanonicalBackendPortOwner
    Write-Output "[backend] pid=$pidValue process=$processRunning port=$portOpen port_pid=$($portOwners -join ',') canonical=$($null -ne $canonicalPortOwner) health=$healthOk url=$HealthUrl"
}

if ($Status) {
    Write-Status
    return
}

if ($Stop) {
    $stopped = @()
    $pidValue = Read-PidFile -Path $PidFile
    if ($pidValue -and (Test-ProcessRunning -ProcessId $pidValue)) {
        Stop-ProcessTree -ProcessId $pidValue
        $stopped += $pidValue
    }

    foreach ($owner in (Get-PortOwnerProcessIds -Port $Port)) {
        $ownerId = [int]$owner
        if ($stopped -contains $ownerId) { continue }
        if (Test-CanonicalBackendProcess -ProcessId $ownerId) {
            Stop-ProcessTree -ProcessId $ownerId
            $stopped += $ownerId
        }
    }

    if ($stopped.Count -gt 0) {
        Write-Output "[backend] stopped (pid=$($stopped -join ','))"
    }
    else {
        Write-Output "[backend] not running"
    }
    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
    return
}

$pidValue = Read-PidFile -Path $PidFile
$healthOk = Test-HttpOk -Url $HealthUrl
$canonicalPortOwner = Get-CanonicalBackendPortOwner
if ($pidValue -and (Test-ProcessRunning -ProcessId $pidValue) -and $healthOk -and $canonicalPortOwner) {
    Write-Output "[backend] already running (pid=$pidValue)"
    return
}

if ($pidValue) {
    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
}

if ($healthOk) {
    $portOwners = @(Get-PortOwnerProcessIds -Port $Port)
    if ($canonicalPortOwner) {
        Set-Content -LiteralPath $PidFile -Value $canonicalPortOwner
        Write-Output "[backend] already serving canonical health on port $Port (port_pid=$canonicalPortOwner)"
        return
    }
    throw "[backend] port $Port is serving health from a noncanonical runtime (port_pid=$($portOwners -join ',')); refusing to reuse it"
}

if (Test-PortOpen -Port $Port) {
    $portOwners = @(Get-PortOwnerProcessIds -Port $Port)
    throw "[backend] port $Port is in use but $HealthUrl is not healthy (port_pid=$($portOwners -join ',')); refusing to start duplicate backend"
}

$python = $CanonicalPython
if (-not (Test-Path -LiteralPath $python)) {
    throw "[backend] python runtime not found: $python"
}

Import-EnvFile -Path (Join-Path $BackendDir ".env.local")
$previousPort = $env:PORT
$env:PORT = "$Port"
try {
    $process = Start-Process `
        -FilePath $python `
        -ArgumentList "app.py" `
        -WorkingDirectory $BackendDir `
        -RedirectStandardOutput $LogFile `
        -RedirectStandardError $ErrLogFile `
        -PassThru `
        -WindowStyle Hidden
}
finally {
    $env:PORT = $previousPort
}

Set-Content -LiteralPath $PidFile -Value $process.Id
Start-Sleep -Seconds 1
if (-not (Test-ProcessRunning -ProcessId $process.Id)) {
    throw "[backend] failed to start, check logs: $LogFile / $ErrLogFile"
}

Wait-Health -TimeoutSeconds 30
Write-Output "[backend] started (pid=$($process.Id)) logs=$LogFile / $ErrLogFile"
