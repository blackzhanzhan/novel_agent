param(
    [switch]$Stop,
    [switch]$Status,
    [switch]$SkipDify,
    [switch]$NoDynamicPorts,
    [switch]$SkipInstall,
    [switch]$InitEnv,
    [switch]$DryRun,
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173,
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
$StartAllScript = Join-Path $RootDir "start_all.ps1"
$BackendDir = Join-Path $RootDir "novel_git_server"
$FrontendDir = Join-Path $RootDir "frontend"
$BackendVenvPython = Join-Path $BackendDir "venv\Scripts\python.exe"
$RequirementsFile = Join-Path $BackendDir "requirements.txt"
$FrontendNodeModules = Join-Path $FrontendDir "node_modules"
$DefaultEnvFile = Join-Path $DeployDir ".env"
$ExampleEnvFile = Join-Path $DeployDir ".env.example"

if (-not $EnvFile) {
    $EnvFile = $DefaultEnvFile
}

function Write-Step {
    param([string]$Message)
    Write-Output ""
    Write-Output "== $Message =="
}

function Test-CommandExists {
    param([string]$Name)
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Protect-EnvValue {
    param([string]$Name, [string]$Value)
    if ($Name -match "(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)") {
        if ([string]::IsNullOrWhiteSpace($Value)) { return "<empty>" }
        return "***"
    }
    return $Value
}

function Import-DemoEnvFile {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }

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
        Write-Output ("[env] {0}={1}" -f $name, (Protect-EnvValue -Name $name -Value $value))
    }
}

function Initialize-DemoEnvFile {
    if (Test-Path -LiteralPath $DefaultEnvFile) {
        Write-Output "[env] already exists: $DefaultEnvFile"
        return
    }
    if (-not (Test-Path -LiteralPath $ExampleEnvFile)) {
        throw "[env] example file missing: $ExampleEnvFile"
    }
    if ($DryRun) {
        Write-Output "[dry-run] would copy $ExampleEnvFile -> $DefaultEnvFile"
        return
    }
    Copy-Item -LiteralPath $ExampleEnvFile -Destination $DefaultEnvFile
    Write-Output "[env] created $DefaultEnvFile from .env.example; fill API keys there if needed"
}

function Assert-Command {
    param([string]$Name, [string]$InstallHint)
    if (Test-CommandExists -Name $Name) {
        Write-Output "[preflight] $Name OK"
        return
    }
    throw "[preflight] $Name not found. $InstallHint"
}

function Invoke-Checked {
    param(
        [string]$Label,
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$WorkingDirectory
    )

    $printable = "$FilePath $($ArgumentList -join ' ')"
    if ($DryRun) {
        Write-Output "[dry-run] ${Label}: $printable"
        return
    }

    Write-Output "[$Label] $printable"
    Push-Location -LiteralPath $WorkingDirectory
    try {
        & $FilePath @ArgumentList
        if ($LASTEXITCODE -ne 0) {
            throw "[$Label] command failed with exit code $LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
    }
}

function Ensure-BackendVenv {
    if (Test-Path -LiteralPath $BackendVenvPython) {
        Write-Output "[deps] backend venv OK: $BackendVenvPython"
        return
    }
    if ($SkipInstall) {
        throw "[deps] backend venv missing: $BackendVenvPython"
    }
    Assert-Command -Name "python" -InstallHint "Install Python 3 and ensure python is on PATH."
    Invoke-Checked -Label "deps" -FilePath "python" -ArgumentList @("-m", "venv", (Join-Path $BackendDir "venv")) -WorkingDirectory $RootDir
    $pip = Join-Path $BackendDir "venv\Scripts\pip.exe"
    Invoke-Checked -Label "deps" -FilePath $pip -ArgumentList @("install", "-r", $RequirementsFile) -WorkingDirectory $BackendDir
}

function Ensure-FrontendDeps {
    if (Test-Path -LiteralPath $FrontendNodeModules) {
        Write-Output "[deps] frontend node_modules OK"
        return
    }
    if ($SkipInstall) {
        throw "[deps] frontend dependencies missing: $FrontendNodeModules"
    }
    Assert-Command -Name "npm" -InstallHint "Install Node.js LTS and npm."
    Invoke-Checked -Label "deps" -FilePath "npm" -ArgumentList @("install") -WorkingDirectory $FrontendDir
}

function Resolve-BootstrapDefaults {
    if (-not $script:OriginalBoundParameters.ContainsKey("WslDistro") -or [string]::IsNullOrWhiteSpace($WslDistro)) {
        $script:WslDistro = if ($env:NOVEL_AGENT_WSL_DISTRO) { $env:NOVEL_AGENT_WSL_DISTRO } else { "Ubuntu" }
    }
    if (-not $script:OriginalBoundParameters.ContainsKey("DifyComposeDir") -or [string]::IsNullOrWhiteSpace($DifyComposeDir)) {
        $script:DifyComposeDir = if ($env:NOVEL_AGENT_DIFY_COMPOSE_DIR) { $env:NOVEL_AGENT_DIFY_COMPOSE_DIR } else { "/home/zzy/dify/docker" }
    }
}

function Write-KeyWarnings {
    $keys = @(
        "DIFY_API_KEY",
        "DIFY_READING_ARCHIVE_API_KEY",
        "DIFY_WORLD_MODEL_API_KEY",
        "DIFY_STYLE_GUIDE_API_KEY",
        "DIFY_OUTLINE_API_KEY",
        "DIFY_CONTINUATION_API_KEY",
        "DIFY_REVIEW_API_KEY"
    )
    $present = @($keys | Where-Object { -not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($_, "Process")) })
    if ($present.Count -eq 0) {
        Write-Warning "[env] no Dify app API keys are set. Health checks may pass, but agent calls will fail until keys are provided."
    }
    elseif (-not $env:DIFY_CONTINUATION_API_KEY) {
        Write-Warning "[env] DIFY_CONTINUATION_API_KEY is not set; continuation demo will need it."
    }
    if (-not $env:DEEPSEEK_API_KEY) {
        Write-Warning "[env] DEEPSEEK_API_KEY is not set; backend-owned world initialization will need it."
    }
}

function Invoke-StartAll {
    $startArgs = @(
        "-BackendPort", "$BackendPort",
        "-FrontendPort", "$FrontendPort",
        "-WslDistro", "$WslDistro",
        "-DifyComposeDir", "$DifyComposeDir"
    )
    if ($Stop) { $startArgs += "-Stop" }
    if ($Status) { $startArgs += "-Status" }
    if ($SkipDify) { $startArgs += "-SkipDify" }
    if ($NoDynamicPorts) { $startArgs += "-NoDynamicPorts" }

    if ($DryRun) {
        Write-Output "[dry-run] would run: $StartAllScript $($startArgs -join ' ')"
        return
    }
    & $StartAllScript @startArgs
}

if (-not (Test-Path -LiteralPath $StartAllScript)) {
    throw "[bootstrap] start_all.ps1 not found: $StartAllScript"
}

if ($InitEnv) {
    Write-Step "Initialize env"
    Initialize-DemoEnvFile
}

Import-DemoEnvFile -Path $EnvFile
Resolve-BootstrapDefaults

Write-Step "Preflight"
Assert-Command -Name "git" -InstallHint "Install Git for Windows."
if (-not $SkipDify) {
    Assert-Command -Name "docker" -InstallHint "Install Docker Desktop."
    Assert-Command -Name "wsl" -InstallHint "Enable WSL and install the configured distro."
}
if (-not $Stop -and -not $Status) {
    Assert-Command -Name "npm" -InstallHint "Install Node.js LTS and npm."
}

Write-Output "[preflight] root=$RootDir"
Write-Output "[preflight] backend_port=$BackendPort frontend_port=$FrontendPort"
Write-Output "[preflight] wsl_distro=$WslDistro dify_compose_dir=$DifyComposeDir skip_dify=$($SkipDify.IsPresent)"
Write-KeyWarnings

if (-not $Stop -and -not $Status) {
    Write-Step "Dependencies"
    Ensure-BackendVenv
    Ensure-FrontendDeps
}

Write-Step "Runtime"
Invoke-StartAll

if (-not $Stop -and -not $Status -and -not $DryRun) {
    $portsManifest = Join-Path $RootDir ".runtime\ports.json"
    if (Test-Path -LiteralPath $portsManifest) {
        $manifest = Get-Content -LiteralPath $portsManifest -Raw -Encoding UTF8 | ConvertFrom-Json
        Write-Output ""
        Write-Output "[demo] frontend: $($manifest.frontend.url)"
        Write-Output "[demo] backend:  $($manifest.backend.health_url)"
        Write-Output "[demo] Dify:     $($manifest.dify.console_url)"
    }
}
