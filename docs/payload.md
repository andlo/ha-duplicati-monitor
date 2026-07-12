# Webhook payload contract

The integration accepts three shapes on the same webhook URL, auto-detected:

1. **Duplicati's classic form-urlencoded plain-text report**
   (`--send-http-url`) - a single `message` field containing a
   human-readable text block (`ExaminedFiles: 276`, etc). This is what
   most default/UI-configured Duplicati setups actually send -
   confirmed against a real instance on 2026-07-12. See
   `translate_classic_message()` in `report.py`.
2. **Duplicati's native `--send-http-json-urls` JSON** - detected by
   the presence of a `Data` or `Extra` object.
3. **This integration's own internal contract**, documented below. This
   is what the above two get translated into internally, and it's
   also handy for manually testing the webhook with `curl` while
   troubleshooting - see the example at the bottom.

Both (1) and (2) accept `?server_id=...&server_name=...` on the URL
for machine identification - see the main
[README](../README.md#connecting-a-duplicati-job).

## Internal contract format

POST JSON to the integration's webhook URL. `Content-Type: application/json`.


```json
{
  "server_id": "nas01",
  "server_name": "NAS01",
  "job_id": "documents",
  "job_name": "Documents backup",
  "event": "AFTER",
  "operation": "Backup",
  "parsed_result": "Success",
  "begin_time": "2026-07-11T03:00:00+02:00",
  "end_time": "2026-07-11T03:14:00+02:00",
  "duration_seconds": 840,
  "examined_files": 12345,
  "added_files": 12,
  "deleted_files": 1,
  "modified_files": 34,
  "size_of_added_files": 1048576,
  "size_of_modified_files": 2097152,
  "warnings_count": 0,
  "errors_count": 0,
  "message": "Backup completed successfully"
}
```

Only `server_id` and `job_id` are required (short, slug-like values,
e.g. `nas01`, `documents` - they become part of the entity's
`unique_id`, so keep them stable once chosen). Everything else is
optional and defaults sensibly:

| Field | Required | Default |
|---|---|---|
| `server_id` | yes | - |
| `job_id` | yes | - |
| `server_name` | no | `server_id` |
| `job_name` | no | `job_id` |
| `event` | no | `AFTER` |
| `operation` | no | `Backup` |
| `parsed_result` | no | `Unknown` |
| `warnings_count` / `errors_count` | no | `0` |
| all other fields | no | omitted from sensor attributes |

`parsed_result` must be one of `Success`, `Warning`, `Error`, `Fatal`,
`Unknown`. Payloads that don't match this shape are rejected with
HTTP 400 (check the Home Assistant log for the reason).
