# Webhook payload contract

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
