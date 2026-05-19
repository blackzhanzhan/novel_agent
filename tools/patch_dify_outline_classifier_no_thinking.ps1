param(
    [string]$DbContainer = "docker-db_postgres-1",
    [string]$Database = "dify",
    [string]$DbUser = "postgres",
    [string[]]$WorkflowIds = @(
        "6b1fa251-96c3-4be1-a677-3b61cb8db2a8",
        "0ab3e326-ee3a-418b-b1d5-334ba3e5b0ed"
    )
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

Assert-Tool docker

if ($WorkflowIds.Count -eq 0) {
    throw "WorkflowIds cannot be empty."
}

$idList = ($WorkflowIds | ForEach-Object { Sql-Literal $_ }) -join ","
$exportSql = "SELECT encode(convert_to(coalesce(json_agg(json_build_object('id', id, 'graph', graph))::text, '[]'), 'UTF8'), 'base64') FROM workflows WHERE id IN ($idList);"
$raw = docker exec $DbContainer psql -U $DbUser -d $Database -t -A -c $exportSql

if ($LASTEXITCODE -ne 0) {
    throw "Failed to export Dify workflow graphs from $DbContainer."
}

$encodedPayload = (($raw -join "") -replace "\s", "").Trim()
if ([string]::IsNullOrWhiteSpace($encodedPayload)) {
    throw "Dify workflow export returned an empty payload."
}

$payload = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($encodedPayload)).Trim()
if ([string]::IsNullOrWhiteSpace($payload) -or $payload -eq "null") {
    throw "No workflow rows found for ids: $($WorkflowIds -join ', ')"
}

$rows = $payload | ConvertFrom-Json
if ($null -eq $rows) {
    throw "Dify workflow export returned no rows."
}

if ($rows -isnot [array]) {
    $rows = @($rows)
}

$updates = New-Object System.Collections.Generic.List[string]
$changedCount = 0

foreach ($row in $rows) {
    $graph = $row.graph
    if ($graph -is [string]) {
        $graph = $graph | ConvertFrom-Json
    }
    if ($null -eq $graph.nodes) {
        Write-Warning "Workflow $($row.id) has no graph.nodes; skipped."
        continue
    }

    $changed = $false
    foreach ($node in $graph.nodes) {
        if ($node.data.type -ne "question-classifier") {
            continue
        }

        if ($null -eq $node.data.model) {
            $node.data | Add-Member -NotePropertyName model -NotePropertyValue ([pscustomobject]@{}) -Force
        }
        if ($null -eq $node.data.model.completion_params) {
            $node.data.model | Add-Member -NotePropertyName completion_params -NotePropertyValue ([pscustomobject]@{}) -Force
        }

        $params = $node.data.model.completion_params
        $params | Add-Member -NotePropertyName thinking -NotePropertyValue $false -Force
        $params | Add-Member -NotePropertyName temperature -NotePropertyValue 0 -Force
        $params.PSObject.Properties.Remove("reasoning_effort")
        $changed = $true
    }

    if (-not $changed) {
        Write-Warning "Workflow $($row.id) has no question-classifier node; skipped."
        continue
    }

    $json = $graph | ConvertTo-Json -Depth 100 -Compress
    $tag = '$outline_classifier_' + (($row.id -replace '[^A-Za-z0-9]', '_')) + '$'
    $updates.Add("UPDATE workflows SET graph = $tag$json$tag::json, updated_at = now() WHERE id = $(Sql-Literal $row.id);")
    $changedCount++
}

if ($updates.Count -eq 0) {
    throw "No workflow updates generated."
}

$tempSql = Join-Path $env:TEMP ("patch_dify_outline_classifier_no_thinking_{0}.sql" -f ([guid]::NewGuid().ToString("N")))
Set-Content -Path $tempSql -Value ($updates -join "`n") -Encoding UTF8

$containerSql = "/tmp/" + [IO.Path]::GetFileName($tempSql)
docker cp $tempSql "${DbContainer}:$containerSql" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Failed to copy SQL patch into $DbContainer."
}

docker exec $DbContainer psql -U $DbUser -d $Database -f $containerSql
if ($LASTEXITCODE -ne 0) {
    throw "Failed to apply SQL patch in $DbContainer."
}

Remove-Item -LiteralPath $tempSql -Force
Write-Host "Patched $changedCount Dify workflow graph(s): question-classifier thinking=false, temperature=0, reasoning_effort removed."
