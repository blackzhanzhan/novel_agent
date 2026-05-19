param(
    [string]$DbContainer = "docker-db_postgres-1",
    [string]$Database = "dify",
    [string]$DbUser = "postgres",
    [string]$WorkflowId = "00ead8f9-d3c1-46d5-a520-87d1c5d59062",
    [string]$ProviderId = "c41fee3b-54dd-4e49-af9b-be30f68f6242",
    [string]$BaseGraphPath = ".runtime/continue_agent_graph_with_inputs_utf8.json",
    [string]$PromptPath = "novel_git_server/docs/dify_continuation_length_gate_prompt.md",
    [string]$RuntimeDir = ".runtime"
)

$ErrorActionPreference = "Stop"

function Assert-Tool {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required tool not found: $Name"
    }
}

function Sql-Literal {
    param([string]$Value)
    return "'" + ($Value -replace "'", "''") + "'"
}

function New-AgentToolFromProviderTool {
    param(
        [object]$ProviderTool,
        [string]$ProviderId,
        [string]$ProviderShowName
    )
    $params = [ordered]@{}
    foreach ($parameter in @($ProviderTool.parameters)) {
        $params[$parameter.name] = [ordered]@{
            auto = 1
            value = $null
        }
    }
    return [ordered]@{
        enabled = $true
        extra = [ordered]@{ description = [string]$ProviderTool.summary }
        parameters = $params
        provider_name = $ProviderId
        provider_show_name = $ProviderShowName
        settings = @{}
        tool_description = [string]$ProviderTool.summary
        tool_label = [string]$ProviderTool.operation_id
        tool_name = [string]$ProviderTool.operation_id
        type = "api"
    }
}

Assert-Tool docker

$root = (Resolve-Path ".").Path
$runtimePath = Join-Path $root $RuntimeDir
New-Item -ItemType Directory -Path $runtimePath -Force | Out-Null

if (-not (Test-Path $BaseGraphPath)) {
    throw "Base graph not found: $BaseGraphPath. Restore or export the verified continuation agent graph first."
}
if (-not (Test-Path $PromptPath)) {
    throw "Prompt fragment not found: $PromptPath."
}

$promptRaw = Get-Content -Path $PromptPath -Raw -Encoding UTF8
$parts = $promptRaw -split "<!-- query-suffix -->", 2
$instructionSuffix = $parts[0].TrimEnd()
$querySuffix = if ($parts.Count -gt 1) { $parts[1].Trim() } else { "" }

$ts = Get-Date -Format "yyyyMMdd_HHmmss"

$exportGraphSql = "select encode(convert_to(graph::text, 'UTF8'), 'base64') from workflows where id = $(Sql-Literal $WorkflowId);"
$graphB64 = ((docker exec $DbContainer psql -U $DbUser -d $Database -t -A -c $exportGraphSql) -join "" -replace "\s", "").Trim()
if ([string]::IsNullOrWhiteSpace($graphB64)) {
    throw "No workflow found for id $WorkflowId."
}
$currentGraphJson = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($graphB64))
$backupGraphPath = Join-Path $runtimePath "continuation_graph_before_length_gate_$ts.json"
Set-Content -Path $backupGraphPath -Value $currentGraphJson -Encoding UTF8

$providerSql = "select encode(convert_to(coalesce(row_to_json(t)::text, '{}'), 'UTF8'), 'base64') from (select id, name, tools_str from tool_api_providers where id = $(Sql-Literal $ProviderId)) t;"
$providerB64 = ((docker exec $DbContainer psql -U $DbUser -d $Database -t -A -c $providerSql) -join "" -replace "\s", "").Trim()
if ([string]::IsNullOrWhiteSpace($providerB64)) {
    throw "No tool provider found for id $ProviderId."
}
$provider = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($providerB64)) | ConvertFrom-Json
if ($provider.tools_str -is [string]) {
    $providerToolsParsed = $provider.tools_str | ConvertFrom-Json
    $providerTools = @()
    if ($providerToolsParsed -is [System.Array]) {
        for ($i = 0; $i -lt $providerToolsParsed.Length; $i++) {
            $providerTools += $providerToolsParsed[$i]
        }
    } else {
        $providerTools += $providerToolsParsed
    }
} else {
    $providerTools = @()
    foreach ($tool in $provider.tools_str) {
        $providerTools += $tool
    }
}
$lengthTool = $null
foreach ($tool in $providerTools) {
    if ([string]$tool.operation_id -eq "validate_chapter_lengths") {
        $lengthTool = $tool
        break
    }
}
if ($null -eq $lengthTool) {
    throw "Provider $ProviderId does not expose validate_chapter_lengths. Run patch_dify_loregit_chapter_length_tool.ps1 first."
}

$graph = Get-Content -Path $BaseGraphPath -Raw -Encoding UTF8 | ConvertFrom-Json
$agentNode = $graph.nodes | Where-Object { $_.data.type -eq "agent" } | Select-Object -First 1
if ($null -eq $agentNode) {
    throw "Base graph does not contain an agent node."
}

$agentParams = $agentNode.data.agent_parameters
$agentParams.maximum_iterations.value = 18

$existingTools = @($agentParams.tools.value)
$patchedTools = @($existingTools | Where-Object { $_.tool_name -ne "validate_chapter_lengths" })
$patchedTools += New-AgentToolFromProviderTool -ProviderTool $lengthTool -ProviderId $ProviderId -ProviderShowName $provider.name
$agentParams.tools.value = $patchedTools

if ($agentParams.instruction.value -notmatch "validate_chapter_lengths") {
    $agentParams.instruction.value = [string]$agentParams.instruction.value + "`n`n" + $instructionSuffix
}
if ($querySuffix -and $agentParams.query.value -notmatch "validate_chapter_lengths") {
    $agentParams.query.value = [string]$agentParams.query.value + "`n`n" + $querySuffix
}
if ($querySuffix -and $agentNode.data.memory.query_prompt_template -notmatch "validate_chapter_lengths") {
    $agentNode.data.memory.query_prompt_template = [string]$agentNode.data.memory.query_prompt_template + "`n`n" + $querySuffix
}

$patchedGraphPath = Join-Path $runtimePath "continuation_graph_length_gate_$ts.json"
$graph | ConvertTo-Json -Depth 100 -Compress | Set-Content -Path $patchedGraphPath -Encoding UTF8

$graphJson = Get-Content -Path $patchedGraphPath -Raw -Encoding UTF8
$patchSqlPath = Join-Path $runtimePath "patch_continuation_length_gate_$ts.sql"
$quote = '$codex$'
$sql = @(
    "begin;"
    "update workflows"
    "set graph = $quote$graphJson$quote::json,"
    "    updated_at = now()"
    "where id = $(Sql-Literal $WorkflowId);"
    "commit;"
) -join "`n"
Set-Content -Path $patchSqlPath -Value $sql -Encoding UTF8

$containerSql = "/tmp/" + [IO.Path]::GetFileName($patchSqlPath)
docker cp $patchSqlPath "${DbContainer}:$containerSql" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Failed to copy SQL patch into $DbContainer."
}
docker exec $DbContainer psql -U $DbUser -d $Database -f $containerSql
if ($LASTEXITCODE -ne 0) {
    throw "Failed to apply continuation length-gate patch."
}

$verify = [ordered]@{
    workflow_id = $WorkflowId
    backup = $backupGraphPath
    patched_graph = $patchedGraphPath
    sql = $patchSqlPath
    has_validate_chapter_lengths_tool = $true
    maximum_iterations = $agentParams.maximum_iterations.value
}
$verifyPath = Join-Path $runtimePath "patch_continuation_length_gate_verify_$ts.json"
$verify | ConvertTo-Json -Depth 20 | Set-Content -Path $verifyPath -Encoding UTF8

Write-Host "backup=$backupGraphPath"
Write-Host "patched_graph=$patchedGraphPath"
Write-Host "sql=$patchSqlPath"
Write-Host "verify=$verifyPath"
Write-Host "has_validate_chapter_lengths_tool=$($verify.has_validate_chapter_lengths_tool)"
