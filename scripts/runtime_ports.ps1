$ErrorActionPreference = "Stop"

function Test-RuntimePortOpen {
    param(
        [Parameter(Mandatory = $true)][int]$Port,
        [string]$HostName = "127.0.0.1",
        [int]$TimeoutMilliseconds = 500
    )

    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $connect = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $connect.AsyncWaitHandle.WaitOne($TimeoutMilliseconds)) { return $false }
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

function Get-RuntimePortOwnerProcessIds {
    param([Parameter(Mandatory = $true)][int]$Port)
    $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    return @($connections | Select-Object -ExpandProperty OwningProcess -Unique)
}

function Get-RuntimeProcessCommandLine {
    param([Parameter(Mandatory = $true)][int]$ProcessId)
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
    if ($proc) { return [string]$proc.CommandLine }
    return ""
}

function Find-RuntimeAvailablePort {
    param(
        [Parameter(Mandatory = $true)][int]$PreferredPort,
        [int]$SearchLimit = 50,
        [int[]]$ExcludedPorts = @()
    )

    if ($PreferredPort -lt 1 -or $PreferredPort -gt 65535) {
        throw "[ports] invalid preferred port: $PreferredPort"
    }

    $lastPort = [Math]::Min(65535, $PreferredPort + $SearchLimit - 1)
    for ($candidate = $PreferredPort; $candidate -le $lastPort; $candidate++) {
        if ($ExcludedPorts -contains $candidate) { continue }
        if (-not (Test-RuntimePortOpen -Port $candidate)) {
            return $candidate
        }
    }
    throw "[ports] no available port found from $PreferredPort to $lastPort"
}

function Test-RuntimeHttpOk {
    param([Parameter(Mandatory = $true)][string]$Url)
    try {
        Invoke-RestMethod -Uri $Url -TimeoutSec 2 | Out-Null
        return $true
    }
    catch {
        return $false
    }
}

function Resolve-RuntimePort {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][int]$PreferredPort,
        [Parameter(Mandatory = $true)][scriptblock]$IsCanonicalProcess,
        [Parameter(Mandatory = $true)][scriptblock]$IsHealthyPort,
        [bool]$DynamicEnabled = $true,
        [int]$SearchLimit = 50,
        [int[]]$ExcludedPorts = @()
    )

    if ($PreferredPort -lt 1 -or $PreferredPort -gt 65535) {
        throw "[ports] invalid preferred $Name port: $PreferredPort"
    }

    $lastPort = [Math]::Min(65535, $PreferredPort + $SearchLimit - 1)
    for ($candidate = $PreferredPort; $candidate -le $lastPort; $candidate++) {
        if ($ExcludedPorts -contains $candidate) { continue }

        $owners = @(Get-RuntimePortOwnerProcessIds -Port $candidate)
        if ($owners.Count -eq 0 -and -not (Test-RuntimePortOpen -Port $candidate)) {
            $selection = if ($candidate -eq $PreferredPort) { "preferred_free" } else { "dynamic_free" }
            return [pscustomobject]@{
                name = $Name
                preferred_port = $PreferredPort
                selected_port = $candidate
                selection = $selection
                owner_process_ids = @()
                canonical_owner_process_ids = @()
                healthy = $false
            }
        }

        $canonicalOwners = @()
        foreach ($owner in $owners) {
            $ownerId = [int]$owner
            if (& $IsCanonicalProcess $ownerId $candidate) {
                $canonicalOwners += $ownerId
            }
        }

        $healthy = $false
        try {
            $healthy = [bool](& $IsHealthyPort $candidate)
        }
        catch {
            $healthy = $false
        }

        if ($canonicalOwners.Count -gt 0 -and $healthy) {
            $selection = if ($candidate -eq $PreferredPort) { "preferred_canonical" } else { "dynamic_canonical" }
            return [pscustomobject]@{
                name = $Name
                preferred_port = $PreferredPort
                selected_port = $candidate
                selection = $selection
                owner_process_ids = @($owners)
                canonical_owner_process_ids = @($canonicalOwners)
                healthy = $true
            }
        }

        if ($candidate -eq $PreferredPort -and -not $DynamicEnabled) {
            throw "[ports] preferred $Name port $PreferredPort is occupied but not reusable; dynamic allocation is disabled (port_pid=$($owners -join ','))"
        }
    }

    throw "[ports] no reusable $Name port found from $PreferredPort to $lastPort"
}

function Get-RuntimePortsManifestPath {
    param([Parameter(Mandatory = $true)][string]$RootDir)
    return Join-Path (Join-Path $RootDir ".runtime") "ports.json"
}

function Read-RuntimePortsManifest {
    param([Parameter(Mandatory = $true)][string]$RootDir)
    $path = Get-RuntimePortsManifestPath -RootDir $RootDir
    if (-not (Test-Path -LiteralPath $path)) { return $null }
    try {
        return Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        Write-Warning "[ports] ignoring unreadable manifest: $path"
        return $null
    }
}

function Write-RuntimePortsManifest {
    param(
        [Parameter(Mandatory = $true)][string]$RootDir,
        [Parameter(Mandatory = $true)][object]$Manifest
    )
    $runtimeDir = Join-Path $RootDir ".runtime"
    New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
    $path = Get-RuntimePortsManifestPath -RootDir $RootDir
    $Manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $path -Encoding UTF8
    return $path
}

function Remove-RuntimePortsManifest {
    param([Parameter(Mandatory = $true)][string]$RootDir)
    $path = Get-RuntimePortsManifestPath -RootDir $RootDir
    Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
}
