param(
    [switch]$InitEnv,
    [switch]$SkipDify,
    [switch]$Status,
    [switch]$Stop,
    [switch]$DryRun,
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173,
    [string]$EnvFile
)

$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Bootstrap = Join-Path $RootDir "deploy\demo\bootstrap.ps1"

if (-not (Test-Path -LiteralPath $Bootstrap)) {
    throw "deploy\demo\bootstrap.ps1 not found. Please run this script from the release package root."
}

$bootstrapArgs = @{
    BackendPort = $BackendPort
    FrontendPort = $FrontendPort
}
if ($InitEnv) { $bootstrapArgs.InitEnv = $true }
if ($SkipDify) { $bootstrapArgs.SkipDify = $true }
if ($Status) { $bootstrapArgs.Status = $true }
if ($Stop) { $bootstrapArgs.Stop = $true }
if ($DryRun) { $bootstrapArgs.DryRun = $true }
if ($EnvFile) { $bootstrapArgs.EnvFile = $EnvFile }

& $Bootstrap @bootstrapArgs
exit $LASTEXITCODE
