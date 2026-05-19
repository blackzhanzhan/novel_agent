param(
    [switch]$Stop,
    [switch]$Status,
    [int]$Port = 5173,
    [int]$BackendPort = 8000
)

$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$FrontendDir = Join-Path $RootDir "frontend"
$RuntimeDir = Join-Path $RootDir ".runtime"
$PidFile = Join-Path $RuntimeDir $(if ($Port -eq 5173) { "frontend.pid" } else { "frontend_$Port.pid" })
$BackendPortFile = Join-Path $RuntimeDir $(if ($Port -eq 5173) { "frontend.backend_port" } else { "frontend_$Port.backend_port" })
$LogFile = Join-Path $RuntimeDir $(if ($Port -eq 5173) { "frontend.log" } else { "frontend_$Port.log" })
$ErrLogFile = Join-Path $RuntimeDir $(if ($Port -eq 5173) { "frontend.err.log" } else { "frontend_$Port.err.log" })

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

function Stop-ProcessTree {
    param([int]$ProcessId)
    if (-not (Test-ProcessRunning -ProcessId $ProcessId)) { return }
    $children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$ProcessId" -ErrorAction SilentlyContinue
    foreach ($child in $children) {
        Stop-ProcessTree -ProcessId ([int]$child.ProcessId)
    }
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
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

function Test-FrontendDevServerProcess {
    param([int]$ProcessId)
    $commandLine = Get-ProcessCommandLine -ProcessId $ProcessId
    return $commandLine -like "*$FrontendDir*" -and
        $commandLine -like "*vite*" -and
        $commandLine -like "*--host 127.0.0.1*" -and
        $commandLine -like "*--port $Port*"
}

function Test-CanonicalFrontendProcess {
    param([int]$ProcessId)
    $commandLine = Get-ProcessCommandLine -ProcessId $ProcessId
    return (Test-FrontendDevServerProcess -ProcessId $ProcessId) -and
        $commandLine -like "*--config*" -and
        $commandLine -like "*vite.config.ts*"
}

function Get-CanonicalFrontendPortOwner {
    foreach ($owner in (Get-PortOwnerProcessIds -Port $Port)) {
        if (Test-CanonicalFrontendProcess -ProcessId ([int]$owner)) {
            return [int]$owner
        }
    }
    return $null
}

function Wait-PortOpen {
    param([int]$TimeoutSeconds)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-PortOpen -Port $Port) { return }
        Start-Sleep -Milliseconds 500
    }
    throw "[frontend] did not open port $Port within ${TimeoutSeconds}s"
}

function Wait-PortClosed {
    param([int]$TimeoutSeconds)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (-not (Test-PortOpen -Port $Port)) { return }
        Start-Sleep -Milliseconds 250
    }
    throw "[frontend] did not release port $Port within ${TimeoutSeconds}s"
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

function Write-Status {
    $pidValue = Read-PidFile -Path $PidFile
    $backendPortValue = Read-PidFile -Path $BackendPortFile
    $processRunning = $pidValue -and (Test-ProcessRunning -ProcessId $pidValue)
    $portOpen = Test-PortOpen -Port $Port
    $portOwners = @(Get-PortOwnerProcessIds -Port $Port)
    $canonicalPortOwner = Get-CanonicalFrontendPortOwner
    Write-Output "[frontend] pid=$pidValue process=$processRunning port=$portOpen port_pid=$($portOwners -join ',') canonical=$($null -ne $canonicalPortOwner) backend_port=$backendPortValue url=http://127.0.0.1:$Port"
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
        if (Test-FrontendDevServerProcess -ProcessId $ownerId) {
            Stop-ProcessTree -ProcessId $ownerId
            $stopped += $ownerId
        }
    }

    if ($stopped.Count -gt 0) {
        Write-Output "[frontend] stopped (pid=$($stopped -join ','))"
    }
    else {
        Write-Output "[frontend] not running"
    }
    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $BackendPortFile -Force -ErrorAction SilentlyContinue
    return
}

$pidValue = Read-PidFile -Path $PidFile
$recordedBackendPort = Read-PidFile -Path $BackendPortFile
$backendPortMatches = $recordedBackendPort -and $recordedBackendPort -eq $BackendPort
$portOpen = Test-PortOpen -Port $Port
$canonicalPortOwner = Get-CanonicalFrontendPortOwner
if ($pidValue -and (Test-ProcessRunning -ProcessId $pidValue) -and $portOpen -and $canonicalPortOwner -and $backendPortMatches) {
    Write-Output "[frontend] already running (pid=$pidValue)"
    return
}

if ($pidValue) {
    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
}

if ($portOpen) {
    $portOwners = @(Get-PortOwnerProcessIds -Port $Port)
    if ($canonicalPortOwner) {
        if ($backendPortMatches) {
            Set-Content -LiteralPath $PidFile -Value $canonicalPortOwner
            Write-Output "[frontend] port $Port already serving canonical dev server (port_pid=$canonicalPortOwner)"
            return
        }
        Write-Output "[frontend] restarting canonical dev server on port $Port for backend $BackendPort (previous backend=$recordedBackendPort)"
        Stop-ProcessTree -ProcessId $canonicalPortOwner
        Wait-PortClosed -TimeoutSeconds 10
        $portOpen = $false
    }
    else {
        throw "[frontend] port $Port is in use by a noncanonical dev server (port_pid=$($portOwners -join ',')); refusing to reuse it"
    }
}

$npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $npmCommand) {
    $npmCommand = Get-Command npm -ErrorAction SilentlyContinue
}
if (-not $npmCommand) {
    throw "[frontend] npm not found"
}

# Pre-check: backend must be reachable before starting frontend
$backendHealthUrl = "http://127.0.0.1:$BackendPort/health"
if (-not (Test-HttpOk -Url $backendHealthUrl)) {
    throw "[frontend] backend is not reachable at $backendHealthUrl — start backend first"
}

$previousFlaskOrigin = $env:VITE_FLASK_ORIGIN
$env:VITE_FLASK_ORIGIN = "http://127.0.0.1:$BackendPort"
try {
    $process = Start-Process `
        -FilePath $npmCommand.Source `
        -ArgumentList "run", "dev", "--", "--host", "127.0.0.1", "--port", "$Port", "--config", "vite.config.ts" `
        -WorkingDirectory $FrontendDir `
        -RedirectStandardOutput $LogFile `
        -RedirectStandardError $ErrLogFile `
        -PassThru `
        -WindowStyle Hidden
}
finally {
    $env:VITE_FLASK_ORIGIN = $previousFlaskOrigin
}

Set-Content -LiteralPath $PidFile -Value $process.Id
Set-Content -LiteralPath $BackendPortFile -Value $BackendPort
Start-Sleep -Seconds 1
if (-not (Test-ProcessRunning -ProcessId $process.Id)) {
    throw "[frontend] failed to start, check logs: $LogFile / $ErrLogFile"
}

Wait-PortOpen -TimeoutSeconds 45

# Post-check: verify frontend proxy can reach backend
$proxyCheckUrl = "http://127.0.0.1:$Port/books/ping?book_id=_proxy_test"
$proxyOk = $false
$proxyDeadline = (Get-Date).AddSeconds(10)
while ((Get-Date) -lt $proxyDeadline) {
    try {
        $null = Invoke-RestMethod -Uri $proxyCheckUrl -TimeoutSec 3 -ErrorAction Stop
        $proxyOk = $true
        break
    }
    catch {
        $statusCode = $null
        if ($_.Exception.Response) {
            $statusCode = [int]$_.Exception.Response.StatusCode
        }
        # 400/404 from backend = proxy is working, backend rejected the dummy request
        if ($statusCode -in 400, 404) {
            $proxyOk = $true
            break
        }
    }
    Start-Sleep -Milliseconds 500
}

if ($proxyOk) {
    Write-Output "[frontend] started (pid=$($process.Id)) proxy=OK logs=$LogFile / $ErrLogFile"
}
else {
    Write-Warning "[frontend] started (pid=$($process.Id)) but proxy check failed — frontend may not reach backend at $backendHealthUrl"
    Write-Output "         logs=$LogFile / $ErrLogFile"
}
