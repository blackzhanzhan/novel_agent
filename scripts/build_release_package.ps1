param(
    [string]$Version = "0.1.0",
    [string]$OutputDir
)

$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

if (-not $OutputDir) {
    $OutputDir = Join-Path $RootDir "dist"
}

$PackageName = "novel-agent-demo-v$Version"
$StageDir = Join-Path $OutputDir $PackageName
$ZipPath = Join-Path $OutputDir "$PackageName.zip"

function Copy-TrackedFile {
    param([string]$RelativePath)
    $src = Join-Path $RootDir $RelativePath
    if (-not (Test-Path -LiteralPath $src -PathType Leaf)) {
        return
    }
    $dst = Join-Path $StageDir $RelativePath
    $dstDir = Split-Path -Parent $dst
    New-Item -ItemType Directory -Force -Path $dstDir | Out-Null
    Copy-Item -LiteralPath $src -Destination $dst -Force
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
if (Test-Path -LiteralPath $StageDir) {
    Remove-Item -LiteralPath $StageDir -Recurse -Force
}
if (Test-Path -LiteralPath $ZipPath) {
    Remove-Item -LiteralPath $ZipPath -Force
}
New-Item -ItemType Directory -Force -Path $StageDir | Out-Null

$trackedBytes = & git -C $RootDir -c core.quotepath=false ls-files -z
if ($LASTEXITCODE -ne 0) {
    throw "git ls-files failed"
}
$tracked = @($trackedBytes -split "`0" | Where-Object { $_ })

$excludePrefixes = @(
    ".runtime/",
    "dev_repo/",
    ".codex/",
    ".claude/",
    ".vscode/",
    ".dify_backups/",
    "novels/",
    "novel_git_server/storage/",
    "frontend/node_modules/",
    "frontend/dist/",
    "frontend/.vite/",
    "novel_git_server/.venv/"
)
$excludeExact = @(
    "AGENTS.md"
)

foreach ($file in $tracked) {
    $norm = $file.Replace("\", "/")
    if ($excludeExact -contains $norm) { continue }
    $skip = $false
    foreach ($prefix in $excludePrefixes) {
        if ($norm.StartsWith($prefix)) {
            $skip = $true
            break
        }
    }
    if ($skip) { continue }
    Copy-TrackedFile -RelativePath $file
}

$releaseReadme = @"
# Novel Agent Demo Release v$Version

This package is a sanitized demo bundle for the AI novel writing workbench.

## Start

```powershell
.\start_demo.ps1 -InitEnv
# Fill deploy/demo/.env with Dify App keys and model provider keys.
.\start_demo.ps1
```

Open:

```text
http://127.0.0.1:5173/bookshelf.html
```

## Boundary

This release contains source code, Dify DSL YAML snapshots, frontend/backend code, and demo scripts. It does not contain Dify database backups, model API keys, Dify App API keys, private books, or runtime storage.

For details, read README.md and docs/DEPLOYMENT.md.
"@

Set-Content -LiteralPath (Join-Path $StageDir "RELEASE_README.md") -Value $releaseReadme -Encoding UTF8

$stageContents = Join-Path $StageDir "*"
Compress-Archive -Path $stageContents -DestinationPath $ZipPath -Force
if (-not (Test-Path -LiteralPath $ZipPath -PathType Leaf)) {
    throw "release zip was not created: $ZipPath"
}
Write-Output $ZipPath
