param(
    [switch]$Stop,
    [switch]$Status,
    [switch]$SkipDify,
    [switch]$NoDynamicPorts,
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173,
    [string]$WslDistro = "Ubuntu",
    [string]$DifyComposeDir = "/home/zzy/dify/docker"
)

$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ScriptsDir = Join-Path $RootDir "scripts"
$PortScript = Join-Path $ScriptsDir "runtime_ports.ps1"

if (-not (Test-Path -LiteralPath $PortScript)) {
    throw "[ports] script not found: $PortScript"
}
. $PortScript

$BackendDir = Join-Path $RootDir "novel_git_server"
$FrontendDir = Join-Path $RootDir "frontend"
$CanonicalPython = Join-Path $BackendDir "venv\Scripts\python.exe"

$difyScript = Join-Path $ScriptsDir "start_dify.ps1"
$backendScript = Join-Path $ScriptsDir "start_backend.ps1"
$frontendScript = Join-Path $ScriptsDir "start_frontend.ps1"
$difyEndpointSyncScript = Join-Path $ScriptsDir "sync_dify_tool_provider_endpoint.py"

function Invoke-LayerScript {
    param(
        [string]$Name,
        [string]$Path,
        [hashtable]$Parameters
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "[$Name] script not found: $Path"
    }

    Write-Output ""
    Write-Output "== $Name =="
    & $Path @Parameters
}

function Invoke-DifyToolProviderEndpointSync {
    param(
        [int]$BackendPort,
        [object]$ManifestObject
    )

    if (-not (Test-Path -LiteralPath $difyEndpointSyncScript)) {
        throw "[dify-sync] script not found: $difyEndpointSyncScript"
    }

    $python = $CanonicalPython
    if (-not (Test-Path -LiteralPath $python)) {
        $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
        if (-not $pythonCommand) {
            throw "[dify-sync] python runtime not found"
        }
        $python = $pythonCommand.Source
    }

    Write-Output ""
    Write-Output "== Dify ToolProvider Endpoint Sync =="
    $syncOutput = & $python $difyEndpointSyncScript --backend-port $BackendPort
    if ($LASTEXITCODE -ne 0) {
        throw "[dify-sync] endpoint sync failed"
    }
    $syncText = ($syncOutput -join "`n").Trim()
    $syncResult = $syncText | ConvertFrom-Json
    Write-Output "[dify-sync] provider=$($syncResult.provider_id) backend_port=$($syncResult.backend_port) changed=$($syncResult.changed) marker=$($syncResult.marker)"

    if ($ManifestObject -and $ManifestObject.Contains("dify")) {
        $ManifestObject["dify"]["tool_provider_endpoint_sync"] = if ($syncResult.changed) { "updated" } else { "already_synced" }
        $ManifestObject["dify"]["tool_provider_endpoint_marker"] = [string]$syncResult.marker
        $ManifestObject["dify"]["tool_provider_endpoint_backup"] = [string]$syncResult.backup
        $ManifestObject["dify"]["tool_provider_id"] = [string]$syncResult.provider_id
        $ManifestObject["dify"]["tool_provider_endpoint_port"] = [int]$syncResult.backend_port
        Write-RuntimePortsManifest -RootDir $RootDir -Manifest $ManifestObject | Out-Null
    }

}

function Test-BackendCanonicalProcess {
    param([int]$ProcessId, [int]$Port)
    $commandLine = Get-RuntimeProcessCommandLine -ProcessId $ProcessId
    return $commandLine -like "*$CanonicalPython*" -and $commandLine -like "*app.py*"
}

function Test-BackendHealthyPort {
    param([int]$Port)
    try {
        $resp = Invoke-RestMethod -Uri "http://127.0.0.1:${Port}/health" -TimeoutSec 2 -ErrorAction Stop
        return $resp.status -eq "ok"
    }
    catch {
        return $false
    }
}

function Test-FrontendCanonicalProcess {
    param([int]$ProcessId, [int]$Port)
    $commandLine = Get-RuntimeProcessCommandLine -ProcessId $ProcessId
    return $commandLine -like "*$FrontendDir*" -and
        $commandLine -like "*vite*" -and
        $commandLine -like "*--host 127.0.0.1*" -and
        $commandLine -like "*--port $Port*" -and
        $commandLine -like "*--config*" -and
        $commandLine -like "*vite.config.ts*"
}

function Test-FrontendHealthyPort {
    param([int]$Port)
    return Test-RuntimePortOpen -Port $Port
}

function Get-ManifestSelectedPort {
    param(
        [object]$Manifest,
        [string]$Role,
        [int]$Fallback
    )

    if ($Manifest) {
        $roleProperty = $Manifest.PSObject.Properties[$Role]
        if ($roleProperty -and $roleProperty.Value) {
            $portProperty = $roleProperty.Value.PSObject.Properties["selected_port"]
            if ($portProperty -and $portProperty.Value) {
                return [int]$portProperty.Value
            }
        }
    }
    return $Fallback
}

function Resolve-StartupPorts {
    $dynamicEnabled = -not $NoDynamicPorts.IsPresent
    $backendResolution = Resolve-RuntimePort `
        -Name "backend" `
        -PreferredPort $BackendPort `
        -IsCanonicalProcess ${function:Test-BackendCanonicalProcess} `
        -IsHealthyPort ${function:Test-BackendHealthyPort} `
        -DynamicEnabled $dynamicEnabled

    $frontendResolution = Resolve-RuntimePort `
        -Name "frontend" `
        -PreferredPort $FrontendPort `
        -IsCanonicalProcess ${function:Test-FrontendCanonicalProcess} `
        -IsHealthyPort ${function:Test-FrontendHealthyPort} `
        -DynamicEnabled $dynamicEnabled `
        -ExcludedPorts @([int]$backendResolution.selected_port)

    return [pscustomobject]@{
        dynamic_enabled = $dynamicEnabled
        backend = $backendResolution
        frontend = $frontendResolution
    }
}

function New-PortsManifest {
    param([Parameter(Mandatory = $true)][object]$ResolvedPorts)

    $selectedBackendPort = [int]$ResolvedPorts.backend.selected_port
    $selectedFrontendPort = [int]$ResolvedPorts.frontend.selected_port
    return [ordered]@{
        version = 1
        generated_at = (Get-Date).ToString("o")
        root_dir = $RootDir
        dynamic_ports_enabled = [bool]$ResolvedPorts.dynamic_enabled
        backend = [ordered]@{
            preferred_port = [int]$ResolvedPorts.backend.preferred_port
            selected_port = $selectedBackendPort
            selection = [string]$ResolvedPorts.backend.selection
            owner_process_ids = @($ResolvedPorts.backend.owner_process_ids)
            canonical_owner_process_ids = @($ResolvedPorts.backend.canonical_owner_process_ids)
            url = "http://127.0.0.1:$selectedBackendPort"
            health_url = "http://127.0.0.1:$selectedBackendPort/health"
            dify_host_url = "http://host.docker.internal:$selectedBackendPort"
        }
        frontend = [ordered]@{
            preferred_port = [int]$ResolvedPorts.frontend.preferred_port
            selected_port = $selectedFrontendPort
            selection = [string]$ResolvedPorts.frontend.selection
            owner_process_ids = @($ResolvedPorts.frontend.owner_process_ids)
            canonical_owner_process_ids = @($ResolvedPorts.frontend.canonical_owner_process_ids)
            url = "http://127.0.0.1:$selectedFrontendPort"
            backend_origin = "http://127.0.0.1:$selectedBackendPort"
        }
        dify = [ordered]@{
            console_url = "http://localhost"
            api_url = "http://localhost/v1"
            tool_provider_endpoint_sync = "pending"
        }
    }
}

function Write-RuntimePortSummary {
    param(
        [int]$SelectedBackendPort,
        [int]$SelectedFrontendPort,
        [object]$ResolvedPorts,
        [object]$Manifest
    )

    Write-Output ""
    Write-Output "== Runtime Ports =="
    if ($ResolvedPorts) {
        Write-Output "[ports] backend  preferred=$($ResolvedPorts.backend.preferred_port) selected=$SelectedBackendPort selection=$($ResolvedPorts.backend.selection)"
        Write-Output "[ports] frontend preferred=$($ResolvedPorts.frontend.preferred_port) selected=$SelectedFrontendPort selection=$($ResolvedPorts.frontend.selection) backend_origin=http://127.0.0.1:$SelectedBackendPort"
        Write-Output "[ports] dynamic allocation enabled=$($ResolvedPorts.dynamic_enabled)"
    }
    elseif ($Manifest) {
        $manifestPath = Get-RuntimePortsManifestPath -RootDir $RootDir
        Write-Output "[ports] manifest=$manifestPath"
        Write-Output "[ports] backend selected=$SelectedBackendPort frontend selected=$SelectedFrontendPort"
    }
    else {
        Write-Output "[ports] no manifest; using requested/default backend=$SelectedBackendPort frontend=$SelectedFrontendPort"
    }
}

function Stop-StaleManifestPorts {
    param(
        [object]$Manifest,
        [int]$SelectedBackendPort,
        [int]$SelectedFrontendPort
    )

    if (-not $Manifest) { return }

    $previousBackendPort = Get-ManifestSelectedPort -Manifest $Manifest -Role "backend" -Fallback $SelectedBackendPort
    $previousFrontendPort = Get-ManifestSelectedPort -Manifest $Manifest -Role "frontend" -Fallback $SelectedFrontendPort

    if ($previousFrontendPort -ne $SelectedFrontendPort) {
        Invoke-LayerScript -Name "stale frontend" -Path $frontendScript -Parameters @{ Port = $previousFrontendPort; BackendPort = $previousBackendPort; Stop = $true }
    }

    if ($previousBackendPort -ne $SelectedBackendPort) {
        Invoke-LayerScript -Name "stale backend" -Path $backendScript -Parameters @{ Port = $previousBackendPort; Stop = $true }
    }
}

$manifest = Read-RuntimePortsManifest -RootDir $RootDir
$effectiveBackendPort = Get-ManifestSelectedPort -Manifest $manifest -Role "backend" -Fallback $BackendPort
$effectiveFrontendPort = Get-ManifestSelectedPort -Manifest $manifest -Role "frontend" -Fallback $FrontendPort

if ($Stop) {
    Write-RuntimePortSummary -SelectedBackendPort $effectiveBackendPort -SelectedFrontendPort $effectiveFrontendPort -Manifest $manifest
    Invoke-LayerScript -Name "frontend" -Path $frontendScript -Parameters @{ Port = $effectiveFrontendPort; BackendPort = $effectiveBackendPort; Stop = $true }
    Invoke-LayerScript -Name "backend" -Path $backendScript -Parameters @{ Port = $effectiveBackendPort; Stop = $true }
    if (-not $SkipDify) {
        Invoke-LayerScript -Name "dify" -Path $difyScript -Parameters @{ WslDistro = $WslDistro; ComposeDir = $DifyComposeDir; Stop = $true }
    }
    Remove-RuntimePortsManifest -RootDir $RootDir
    return
}

if ($Status) {
    Write-RuntimePortSummary -SelectedBackendPort $effectiveBackendPort -SelectedFrontendPort $effectiveFrontendPort -Manifest $manifest
    if (-not $SkipDify) {
        Invoke-LayerScript -Name "dify" -Path $difyScript -Parameters @{ WslDistro = $WslDistro; ComposeDir = $DifyComposeDir; Status = $true }
    }
    Invoke-LayerScript -Name "backend" -Path $backendScript -Parameters @{ Port = $effectiveBackendPort; Status = $true }
    Invoke-LayerScript -Name "frontend" -Path $frontendScript -Parameters @{ Port = $effectiveFrontendPort; BackendPort = $effectiveBackendPort; Status = $true }
    return
}

$resolvedPorts = Resolve-StartupPorts
$BackendPort = [int]$resolvedPorts.backend.selected_port
$FrontendPort = [int]$resolvedPorts.frontend.selected_port
Write-RuntimePortSummary -SelectedBackendPort $BackendPort -SelectedFrontendPort $FrontendPort -ResolvedPorts $resolvedPorts
Stop-StaleManifestPorts -Manifest $manifest -SelectedBackendPort $BackendPort -SelectedFrontendPort $FrontendPort

if (-not $SkipDify) {
    Invoke-LayerScript -Name "dify" -Path $difyScript -Parameters @{ WslDistro = $WslDistro; ComposeDir = $DifyComposeDir }
}
Invoke-LayerScript -Name "backend" -Path $backendScript -Parameters @{ Port = $BackendPort }
Invoke-LayerScript -Name "frontend" -Path $frontendScript -Parameters @{ Port = $FrontendPort; BackendPort = $BackendPort }

$manifestObject = New-PortsManifest -ResolvedPorts $resolvedPorts
$manifestPath = Write-RuntimePortsManifest -RootDir $RootDir -Manifest $manifestObject
Write-Output ""
Write-Output "[ports] manifest written: $manifestPath"

if (-not $SkipDify) {
    Invoke-DifyToolProviderEndpointSync -BackendPort $BackendPort -ManifestObject $manifestObject
}

Write-Output ""
Write-Output "== Health Checks =="

$healthWarnCount = 0

$backendHealthOk = $false
try {
    $resp = Invoke-RestMethod -Uri "http://127.0.0.1:${BackendPort}/health" -TimeoutSec 3 -ErrorAction Stop
    if ($resp.status -eq "ok") { $backendHealthOk = $true }
}
catch { }

if ($backendHealthOk) {
    Write-Output "[health] Backend:        OK (http://127.0.0.1:$BackendPort/health)"
}
else {
    Write-Warning "[health] Backend:        FAIL (http://127.0.0.1:$BackendPort/health not responding)"
    $healthWarnCount++
}

$frontendProxyOk = $false
try {
    $null = Invoke-RestMethod -Uri "http://127.0.0.1:${FrontendPort}/books/ping?book_id=_proxy_test" -TimeoutSec 3 -ErrorAction Stop
    $frontendProxyOk = $true
}
catch {
    $statusCode = $null
    if ($_.Exception.Response) {
        $statusCode = [int]$_.Exception.Response.StatusCode
    }
    if ($statusCode -in 400, 404) { $frontendProxyOk = $true }
}

if ($frontendProxyOk) {
    Write-Output "[health] Frontend->B/E:  OK (proxy chain working)"
}
else {
    Write-Warning "[health] Frontend->B/E:  FAIL (frontend at :$FrontendPort cannot reach backend at :$BackendPort)"
    $healthWarnCount++
}

if ($SkipDify) {
    Write-Output "[health] ssrf_proxy:      SKIP (-SkipDify)"
    Write-Output "[health] Dify->Backend:   SKIP (-SkipDify)"
}
else {
    $ssrfStatus = docker ps --filter "name=docker-ssrf_proxy-1" --format "{{.Status}}" 2>$null
    if ($ssrfStatus) {
        Write-Output "[health] ssrf_proxy:      OK ($ssrfStatus)"
    }
    else {
        Write-Warning "[health] ssrf_proxy:      MISSING - Dify tool nodes will fail (sandbox cannot reach backend)"
        Write-Output "         Fix: wsl -d $WslDistro -- bash -lc `"cd $DifyComposeDir && docker compose up -d ssrf_proxy`""
        $healthWarnCount++
    }

    $sandboxReachable = $false
    try {
        $probeScript = "import urllib.request,sys; r=urllib.request.urlopen('http://host.docker.internal:${BackendPort}/health',timeout=5); sys.exit(0 if r.status==200 else 1)"
        $null = docker exec docker-sandbox-1 python3 -c $probeScript 2>$null
        if ($LASTEXITCODE -eq 0) {
            $sandboxReachable = $true
        }
    }
    catch { }

    if ($sandboxReachable) {
        Write-Output "[health] Dify->Backend:   OK (sandbox -> host.docker.internal:$BackendPort/health)"
    }
    else {
        if ($ssrfStatus) {
            Write-Warning "[health] Dify->Backend:   FAIL (ssrf_proxy is running but sandbox cannot reach http://host.docker.internal:$BackendPort/health)"
            Write-Output "         Check: is backend listening on 0.0.0.0:${BackendPort}? Is host.docker.internal resolvable from Docker?"
        }
        else {
            Write-Warning "[health] Dify->Backend:   SKIP (ssrf_proxy not running)"
        }
        $healthWarnCount++
    }
}

$exeReachable = $false
try {
    $resp = Invoke-WebRequest -Uri "http://127.0.0.1:18423/api/status" -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop
    if ($resp.StatusCode -eq 200) { $exeReachable = $true }
}
catch { }

if ($exeReachable) {
    Write-Output "[health] Tomato exe:      OK (port 18423)"
}
else {
    Write-Output "[health] Tomato exe:      SKIP (not running on port 18423 - online import will use HTTP fallback)"
}

if ($healthWarnCount -gt 0) {
    Write-Output ""
    Write-Warning "[health] $healthWarnCount issue(s) detected. See warnings above."
}
else {
    Write-Output "[health] All checks passed."
}

Write-Output ""
Write-Output "Ready:"
Write-Output "- Dify console: http://localhost"
Write-Output "- Dify API:     http://localhost/v1"
Write-Output "- backend:      http://127.0.0.1:$BackendPort/health"
Write-Output "- frontend:     http://127.0.0.1:$FrontendPort"
Write-Output ""
Write-Output "Tips:"
Write-Output "- .\start_all.ps1 -Status"
Write-Output "- .\start_all.ps1 -Stop"
