param(
    [string]$WslDistro = "Ubuntu",
    [string]$OutDir = "C:/csptr/linuxptr/novel_agent/.dify_backups",
    [string]$Container = "docker-db_postgres-1"
)

$ErrorActionPreference = "Stop"

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$dest = Join-Path $OutDir $stamp
New-Item -ItemType Directory -Path $dest -Force | Out-Null

function Invoke-PgDump {
    param([string]$Db, [string]$OutFile)
    $wslDest = ($dest -replace "\\", "/" -replace "^C:", "/mnt/c")
    $wslOut = "$wslDest/$OutFile"
    $cmd = "docker exec $Container pg_dump -U postgres -d $Db --no-password > '$wslOut'"
    wsl -d $WslDistro -- bash -lc $cmd
    if ($LASTEXITCODE -ne 0) { throw "pg_dump failed for $Db" }
}

function Invoke-PgDumpGlobals {
    param([string]$OutFile)
    $wslDest = ($dest -replace "\\", "/" -replace "^C:", "/mnt/c")
    $wslOut = "$wslDest/$OutFile"
    $cmd = "docker exec $Container pg_dumpall -U postgres --globals-only > '$wslOut'"
    wsl -d $WslDistro -- bash -lc $cmd
    if ($LASTEXITCODE -ne 0) { throw "pg_dumpall globals failed" }
}

Write-Output "[backup] stamp=$stamp dest=$dest"

Invoke-PgDump -Db "dify" -OutFile "dify.sql"
Write-Output "[backup] dify.sql done"

Invoke-PgDump -Db "dify_plugin" -OutFile "dify_plugin.sql"
Write-Output "[backup] dify_plugin.sql done"

Invoke-PgDumpGlobals -OutFile "globals.sql"
Write-Output "[backup] globals.sql done"

$manifest = @{
    stamp     = $stamp
    container = $Container
    files     = @("dify.sql", "dify_plugin.sql", "globals.sql")
    sha256    = @{}
}
foreach ($f in $manifest.files) {
    $path = Join-Path $dest $f
    $hash = (Get-FileHash -Path $path -Algorithm SHA256).Hash
    $manifest.sha256[$f] = $hash
}

$manifestPath = Join-Path $dest "manifest.json"
$manifest | ConvertTo-Json -Depth 4 | Set-Content -Path $manifestPath -Encoding UTF8
Write-Output "[backup] manifest written: $manifestPath"
Write-Output "[backup] complete"
