# duplicati-notify.ps1
#
# Use as --run-script-after in a Duplicati backup job on Windows.
# Reads Duplicati's result file and posts a small, stable JSON
# payload to the ha-duplicati-monitor webhook.
#
# Set these before use (env vars or edit directly below):
#   $env:HA_WEBHOOK_URL, $env:DUPLICATI_SERVER_ID, $env:DUPLICATI_SERVER_NAME

$ErrorActionPreference = "Stop"

if ($env:DUPLICATI__EVENTNAME -ne "AFTER") { exit 0 }

$HaWebhookUrl = if ($env:HA_WEBHOOK_URL) { $env:HA_WEBHOOK_URL } else { "https://homeassistant.local:8123/api/webhook/REPLACE_ME" }
$ServerId = if ($env:DUPLICATI_SERVER_ID) { $env:DUPLICATI_SERVER_ID } else { $env:COMPUTERNAME }
$ServerName = if ($env:DUPLICATI_SERVER_NAME) { $env:DUPLICATI_SERVER_NAME } else { $ServerId }
$JobId = if ($env:DUPLICATI__backup_name) { $env:DUPLICATI__backup_name } else { "unknown" }

function Get-ResultValue($key) {
    if (-not (Test-Path $env:DUPLICATI__RESULTFILE)) { return $null }
    $line = Select-String -Path $env:DUPLICATI__RESULTFILE -Pattern "^$key`:" | Select-Object -First 1
    if ($null -eq $line) { return $null }
    return ($line.Line -split ":", 2)[1].Trim()
}

$ParsedResult = Get-ResultValue "ParsedResult"
$BeginTime = Get-ResultValue "BeginTime"
$EndTime = Get-ResultValue "EndTime"
$DurationSeconds = 0
if ($BeginTime -and $EndTime) {
    try { $DurationSeconds = [int]((Get-Date $EndTime) - (Get-Date $BeginTime)).TotalSeconds }
    catch { $DurationSeconds = 0 }
}

$Payload = @{
    server_id            = $ServerId
    server_name          = $ServerName
    job_id               = $JobId
    job_name             = $JobId
    event                = "AFTER"
    operation            = if ($env:DUPLICATI__OPERATIONNAME) { $env:DUPLICATI__OPERATIONNAME } else { "Backup" }
    parsed_result        = if ($ParsedResult) { $ParsedResult } else { "Unknown" }
    begin_time           = $BeginTime
    end_time             = $EndTime
    duration_seconds     = $DurationSeconds
    examined_files       = [int](Get-ResultValue "ExaminedFiles")
    added_files          = [int](Get-ResultValue "AddedFiles")
    modified_files       = [int](Get-ResultValue "ModifiedFiles")
    deleted_files        = [int](Get-ResultValue "DeletedFiles")
    size_of_added_files  = [int64](Get-ResultValue "SizeOfAddedFiles")
    size_of_modified_files = [int64](Get-ResultValue "SizeOfModifiedFiles")
    warnings_count       = [int](Get-ResultValue "WarningsActualLength")
    errors_count         = [int](Get-ResultValue "ErrorsActualLength")
} | ConvertTo-Json

Invoke-RestMethod -Uri $HaWebhookUrl -Method Post -Body $Payload -ContentType "application/json" | Out-Null
