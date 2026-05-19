param(
    [Parameter(Mandatory)][string]$BackupDir,
    [string]$WslDistro = "Ubuntu",
    [string]$Container = "docker-db_postgres-1"
)

$ErrorActionPreference = "Stop"

foreach ($f in @("dify.sql", "dify_plugin.sql")) {
    $path = Join-Path $BackupDir $f
    if (-not (Test-Path $path)) { throw "Missing: $path" }
}

function Invoke-PsqlFile {
    param([string]$Db, [string]$File)
    $wslFile = ($File -replace "\\", "/" -replace "^C:", "/mnt/c")
    $cmd = "docker exec -i $Container psql -U postgres -d $Db -v ON_ERROR_STOP=1 < '$wslFile'"
    wsl -d $WslDistro -- bash -lc $cmd
    if ($LASTEXITCODE -ne 0) { throw "psql failed for $Db from $File" }
}

Write-Output "[restore] source=$BackupDir"

Invoke-PsqlFile -Db "dify" -File (Join-Path $BackupDir "dify.sql")
Write-Output "[restore] dify done"

Invoke-PsqlFile -Db "dify_plugin" -File (Join-Path $BackupDir "dify_plugin.sql")
Write-Output "[restore] dify_plugin done"

Write-Output "[restore] complete — restart Dify containers to apply"
