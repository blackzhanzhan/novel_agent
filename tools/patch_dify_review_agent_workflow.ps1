param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$script = Join-Path $root "scripts\patch_review_agent.py"

if (-not (Test-Path $script)) {
    throw "找不到审核智能体补丁脚本：$script"
}

$pythonArgs = @($script)
if ($DryRun) {
    $pythonArgs += "--dry-run"
}

python @pythonArgs
