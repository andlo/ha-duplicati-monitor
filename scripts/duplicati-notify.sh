#!/bin/bash
# duplicati-notify.sh
#
# Use as --run-script-after in a Duplicati backup job (or paste into
# "Options > Run script after" in the web UI). Reads Duplicati's own
# result file and posts a small, stable JSON payload to the
# ha-duplicati-monitor webhook.
#
# Requires: jq, curl
#
# Configure via environment variables (set them in the job's
# "Advanced options" as --run-script-* or export them at the top of
# a copy of this script):
#   HA_WEBHOOK_URL       e.g. https://homeassistant.local:8123/api/webhook/xxxxxxxx
#   DUPLICATI_SERVER_ID  defaults to `hostname -s` - keep it stable and slug-like
#   DUPLICATI_SERVER_NAME defaults to DUPLICATI_SERVER_ID
#
# NOTE: The exact env var Duplicati exposes for the job/backup name
# has changed across versions. If JOB_ID below comes out "unknown",
# run `env | grep -i duplicati` from within the script (redirect to
# a file) on your system and adjust the JOB_ID line accordingly.

set -euo pipefail

HA_WEBHOOK_URL="${HA_WEBHOOK_URL:-https://homeassistant.local:8123/api/webhook/REPLACE_ME}"
SERVER_ID="${DUPLICATI_SERVER_ID:-$(hostname -s)}"
SERVER_NAME="${DUPLICATI_SERVER_NAME:-$SERVER_ID}"

# We only care about completed backups here.
if [ "${DUPLICATI__EVENTNAME:-}" != "AFTER" ]; then
    exit 0
fi

JOB_ID="${DUPLICATI__backup_name:-unknown}"
RESULTFILE="${DUPLICATI__RESULTFILE:-}"

get() {
    # Extract the value of a "Key: value" line from Duplicati's result file
    [ -n "$RESULTFILE" ] && [ -f "$RESULTFILE" ] || return 0
    grep -m1 "^$1:" "$RESULTFILE" 2>/dev/null | cut -d':' -f2- | xargs || true
}

PARSED_RESULT="$(get ParsedResult)"
BEGIN_TIME="$(get BeginTime)"
END_TIME="$(get EndTime)"
EXAMINED_FILES="$(get ExaminedFiles)"
ADDED_FILES="$(get AddedFiles)"
MODIFIED_FILES="$(get ModifiedFiles)"
DELETED_FILES="$(get DeletedFiles)"
SIZE_ADDED="$(get SizeOfAddedFiles)"
SIZE_MODIFIED="$(get SizeOfModifiedFiles)"
WARNINGS="$(get WarningsActualLength)"
ERRORS="$(get ErrorsActualLength)"

DURATION_SECONDS=0
if [ -n "$BEGIN_TIME" ] && [ -n "$END_TIME" ]; then
    DURATION_SECONDS=$(( $(date -d "$END_TIME" +%s) - $(date -d "$BEGIN_TIME" +%s) )) || DURATION_SECONDS=0
fi

payload=$(jq -n \
  --arg server_id "$SERVER_ID" \
  --arg server_name "$SERVER_NAME" \
  --arg job_id "$JOB_ID" \
  --arg event "AFTER" \
  --arg operation "${DUPLICATI__OPERATIONNAME:-Backup}" \
  --arg parsed_result "${PARSED_RESULT:-Unknown}" \
  --arg begin_time "$BEGIN_TIME" \
  --arg end_time "$END_TIME" \
  --argjson duration_seconds "${DURATION_SECONDS:-0}" \
  --argjson examined_files "${EXAMINED_FILES:-0}" \
  --argjson added_files "${ADDED_FILES:-0}" \
  --argjson modified_files "${MODIFIED_FILES:-0}" \
  --argjson deleted_files "${DELETED_FILES:-0}" \
  --argjson size_of_added_files "${SIZE_ADDED:-0}" \
  --argjson size_of_modified_files "${SIZE_MODIFIED:-0}" \
  --argjson warnings_count "${WARNINGS:-0}" \
  --argjson errors_count "${ERRORS:-0}" \
  '{server_id:$server_id, server_name:$server_name, job_id:$job_id,
    job_name:$job_id, event:$event, operation:$operation,
    parsed_result:$parsed_result, begin_time:$begin_time, end_time:$end_time,
    duration_seconds:$duration_seconds, examined_files:$examined_files,
    added_files:$added_files, modified_files:$modified_files,
    deleted_files:$deleted_files, size_of_added_files:$size_of_added_files,
    size_of_modified_files:$size_of_modified_files,
    warnings_count:$warnings_count, errors_count:$errors_count}')

curl -sS -X POST -H "Content-Type: application/json" \
  -d "$payload" "$HA_WEBHOOK_URL" >/dev/null
