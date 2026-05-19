param(
    [string]$DbContainer = "docker-db_postgres-1",
    [string]$Database = "dify",
    [string]$DbUser = "postgres",
    [string]$ProviderId = "c41fee3b-54dd-4e49-af9b-be30f68f6242",
    [string]$OpenApiPath = "novel_git_server/docs/openapi_v3_5_1_draft_min.json",
    [string]$RuntimeDir = ".runtime",
    [string[]]$RequiredOperationIds = @("validate_chapter_lengths", "generate_style_diagnostics", "draft_replace_text", "validate_domain_facts")
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

function New-LocaleObject {
    param([string]$Value)
    return [ordered]@{
        en_US = $Value
        zh_Hans = $Value
        pt_BR = $Value
        ja_JP = $Value
    }
}

function New-ParameterFromSchema {
    param(
        [string]$Name,
        [object]$Schema,
        [bool]$Required
    )
    $description = ""
    if ($null -ne $Schema.description) {
        $description = [string]$Schema.description
    }
    $type = "string"
    if ($null -ne $Schema.type) {
        $type = [string]$Schema.type
    }
    if ($type -eq "integer") {
        $type = "number"
    }
    if (@("string", "number", "boolean", "array", "object") -notcontains $type) {
        $type = "string"
    }
    return [ordered]@{
        name = $Name
        label = (New-LocaleObject $Name)
        placeholder = (New-LocaleObject $description)
        scope = $null
        auto_generate = $null
        template = $null
        required = $Required
        default = $Schema.default
        min = $Schema.minimum
        max = $Schema.maximum
        precision = $null
        options = @()
        type = $type
        human_description = (New-LocaleObject $description)
        form = "llm"
        llm_description = $description
        input_schema = $null
    }
}

function New-ToolFromOpenApi {
    param(
        [object]$OpenApi,
        [string]$Path
    )
    $pathProperty = $OpenApi.paths.PSObject.Properties[$Path]
    if ($null -eq $pathProperty) {
        throw "OpenAPI path not found: $Path"
    }
    $pathSpec = $pathProperty.Value
    $methodProperty = $pathSpec.PSObject.Properties | Select-Object -First 1
    $method = $methodProperty.Name
    $operation = $methodProperty.Value
    $parameters = @()
    if ($null -ne $operation.parameters) {
        foreach ($parameter in @($operation.parameters)) {
            $schema = $parameter.schema
            if ($null -eq $schema) {
                $schema = [pscustomobject]@{ type = "string" }
            }
            if ($null -ne $parameter.description -and $null -eq $schema.description) {
                $schema | Add-Member -NotePropertyName description -NotePropertyValue ([string]$parameter.description) -Force
            }
            $parameters += New-ParameterFromSchema -Name ([string]$parameter.name) -Schema $schema -Required ([bool]$parameter.required)
        }
    }
    elseif ($null -ne $operation.requestBody) {
        $schema = $operation.requestBody.content.'application/json'.schema
        $requiredNames = @()
        if ($null -ne $schema.required) {
            $requiredNames = @($schema.required)
        }
        foreach ($property in $schema.properties.PSObject.Properties) {
            $parameters += New-ParameterFromSchema -Name $property.Name -Schema $property.Value -Required ($requiredNames -contains $property.Name)
        }
    }
    return [ordered]@{
        server_url = "$($OpenApi.servers[0].url)$Path"
        method = $method
        summary = $operation.description
        operation_id = $operation.operationId
        parameters = $parameters
        author = ""
        icon = $null
        openapi = $operation
        output_schema = @{}
    }
}

Assert-Tool docker

$root = (Resolve-Path ".").Path
$resolvedOpenApiPath = Resolve-Path $OpenApiPath
$runtimePath = Join-Path $root $RuntimeDir
New-Item -ItemType Directory -Path $runtimePath -Force | Out-Null

$openapi = Get-Content -Path $resolvedOpenApiPath -Raw -Encoding UTF8 | ConvertFrom-Json
$rebuiltTools = @()
foreach ($pathProperty in $openapi.paths.PSObject.Properties) {
    $rebuiltTools += New-ToolFromOpenApi -OpenApi $openapi -Path $pathProperty.Name
}

$exportSql = "SELECT encode(convert_to(coalesce(row_to_json(t)::text, '{}'), 'UTF8'), 'base64') FROM (SELECT id, schema, tools_str, description FROM tool_api_providers WHERE id = $(Sql-Literal $ProviderId)) t;"
$raw = docker exec $DbContainer psql -U $DbUser -d $Database -t -A -c $exportSql
if ($LASTEXITCODE -ne 0) {
    throw "Failed to export Dify tool provider from $DbContainer."
}

$encodedPayload = (($raw -join "") -replace "\s", "").Trim()
if ([string]::IsNullOrWhiteSpace($encodedPayload)) {
    throw "Dify provider export returned an empty payload."
}

$providerJson = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($encodedPayload)).Trim()
if ([string]::IsNullOrWhiteSpace($providerJson) -or $providerJson -eq "{}" -or $providerJson -eq "null") {
    throw "No tool_api_providers row found for id $ProviderId."
}

$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$backupPath = Join-Path $runtimePath "loregit_tool_provider_backup_before_openapi_patch_$ts.json"
Set-Content -Path $backupPath -Value $providerJson -Encoding UTF8

$provider = $providerJson | ConvertFrom-Json
$updatedTools = $rebuiltTools

$schemaJson = $openapi | ConvertTo-Json -Depth 100 -Compress
$toolsJsonItems = @()
foreach ($tool in $updatedTools) {
    $toolsJsonItems += ($tool | ConvertTo-Json -Depth 100 -Compress)
}
$toolsJson = "[$($toolsJsonItems -join ',')]"
$description = [string]$openapi.info.description

$sqlPath = Join-Path $runtimePath "patch_loregit_openapi_tools_$ts.sql"
$sql = @"
begin;
update tool_api_providers
set schema = `$codex`$$schemaJson`$codex`$,
    tools_str = `$codex`$$toolsJson`$codex`$,
    description = `$codex`$$description`$codex`$,
    updated_at = now()
where id = $(Sql-Literal $ProviderId);
commit;
"@
Set-Content -Path $sqlPath -Value $sql -Encoding UTF8

$containerSql = "/tmp/" + [IO.Path]::GetFileName($sqlPath)
docker cp $sqlPath "${DbContainer}:$containerSql" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Failed to copy SQL patch into $DbContainer."
}

docker exec $DbContainer psql -U $DbUser -d $Database -f $containerSql
if ($LASTEXITCODE -ne 0) {
    throw "Failed to apply SQL patch in $DbContainer."
}

$verify = [ordered]@{
    provider_id = $ProviderId
    required_operation_ids = $RequiredOperationIds
    backup = $backupPath
    sql = $sqlPath
    provider_tool_count = $updatedTools.Count
    provider_operation_ids = @($updatedTools | ForEach-Object { $_.operation_id })
}
$missingOperationIds = @()
foreach ($requiredId in $RequiredOperationIds) {
    if ($verify.provider_operation_ids -notcontains $requiredId) {
        $missingOperationIds += $requiredId
    }
}
$verify.required_operation_ids_missing = $missingOperationIds
$verify.required_operation_ids_present = ($missingOperationIds.Count -eq 0)
$verifyPath = Join-Path $runtimePath "patch_loregit_openapi_tools_verify_$ts.json"
$verify | ConvertTo-Json -Depth 20 | Set-Content -Path $verifyPath -Encoding UTF8

Write-Host "backup=$backupPath"
Write-Host "sql=$sqlPath"
Write-Host "verify=$verifyPath"
Write-Host "required_operation_ids_present=$($verify.required_operation_ids_present)"
if ($missingOperationIds.Count -gt 0) {
    throw "Provider patch verification failed. Missing operation ids: $($missingOperationIds -join ', ')"
}
