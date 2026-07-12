# Duplicati Monitor for Home Assistant

A Home Assistant integration that receives a small status report from
[Duplicati](https://github.com/duplicati/duplicati) every time a backup
job finishes - similar in spirit to
[duplicati-monitoring.com](https://www.duplicati-monitoring.com/), but
self-hosted and push-based (no polling, no exposing Duplicati's own
web UI to Home Assistant).

Each backup job becomes a **device** (named `"{server} - {job}"`), with
**entities** for status, last backup time, duration, size, versions,
file counts, warnings/errors, and a "problem" binary sensor - all with
proper `device_class`/`state_class`, so History and Statistics graphs
work out of the box. If several jobs run on the same server, assign
their devices to the same Home Assistant **Area** to keep them grouped
by physical machine while still having a manageable device page per job.

## Status

v0.1.0. Core webhook receiving, dynamic per-job devices/entities, and
the sensors above are implemented. Not yet included (see Roadmap): a
detailed run-by-run log view and a bundled dashboard.

## Installation

### HACS (recommended once published)
1. HACS > Integrations > ⋮ > Custom repositories > add this repo URL, category "Integration".
2. Install "Duplicati Monitor", restart Home Assistant.

### Manual
Copy `custom_components/duplicati_monitor` into your HA `config/custom_components/`
folder and restart Home Assistant.

## Setup

1. Settings > Devices & Services > Add Integration > "Duplicati Monitor".
2. Give it a name and a webhook id (a short, URL-safe slug - it's
   pre-filled based on the name, but you can change it, e.g. to match
   your Home Assistant instance name). It must be unique among your
   Duplicati Monitor collectors.
3. The next screen shows your exact webhook URL, e.g.
   `https://YOUR_HA:8123/api/webhook/<your-webhook-id>` - copy it,
   you'll need it in the next step. (You can always find it again
   later on the collector's **"Webhook" diagnostic sensor**.)
4. On each machine running Duplicati, point it at that URL - see below.

If your Home Assistant is not reachable from the backup machine
(e.g. it's on another network), you'll need a reverse proxy, VPN, or
Nabu Casa Cloud webhook URL instead of a local address.

## Connecting a Duplicati job

Duplicati can POST its own report directly to the webhook URL - no
script, no per-job setup. On each machine, open **Settings**
(server-wide default options, so it applies to every job on that
machine automatically) and add:

```
--send-http-url=http://YOUR_HA:8123/api/webhook/<your-webhook-id>?server_id=nas01&server_name=NAS01
--send-http-level=All
```

(Use `--send-http-json-urls` instead of `--send-http-url` if you
prefer - both are auto-detected and handled, see below. Match the
scheme, `http://` vs `https://`, to whatever your Home Assistant's
port actually serves; a scheme mismatch will fail silently from
Duplicati's side with no error in Home Assistant's logs at all, since
the request never arrives.)

- `server_id`/`server_name` in the query string identify this machine
  as a device in Home Assistant (Duplicati's own report doesn't
  reliably include a stable machine id across setups, so we ask for it
  explicitly here - set it once per machine, keep `server_id` stable
  once chosen). If omitted, the integration falls back to the machine
  name Duplicati embeds in its own report header, when present.
- `--send-http-level=All` makes sure successful backups are reported
  too, not just failures.
- The job name/id come from Duplicati's own report automatically.

**Two different wire formats, both handled automatically:** depending
on your Duplicati version/option, it may send either its classic
form-urlencoded plain-text report (a `message=...` field containing
human-readable text like `ExaminedFiles: 276`) or an actual JSON body.
The integration detects and parses both - you don't need to know or
care which one you're getting. If a job comes through with missing
fields, enable the job's normally-hidden **"Last raw payload"
diagnostic sensor** (on that job's device, disabled by default) to see
exactly what Duplicati sent, and open an issue/PR with what you find.

## What you get

One collector-level device (named after the integration entry) with:

- `sensor.*_webhook` (diagnostic) - state is your webhook id, the full
  URL is in its `webhook_url` attribute - your permanent reference,
  no digging through Settings > Automations needed.
- `sensor.duplicati_total`, `sensor.duplicati_ok`, `sensor.duplicati_problem`,
  `sensor.duplicati_health` (0-100%) - live counts/health across every
  currently known job, for zero-config dashboard summary tiles (see
  below). These have fixed entity IDs regardless of what you name the
  integration, so a dashboard can reference them directly.

Per backup job, under its own device named `"{server_name} - {job_name}"`:

- `sensor.*_status` - `Success` / `Warning` / `Error` / `Fatal` / `Unknown`
  (attribute `log_lines`: the last 50 log lines from that run, when
  Duplicati's native JSON reporting supplies them - not available with
  the classic plain-text format)
- `sensor.*_last_backup` - timestamp of the last completed run
- `sensor.*_duration` - seconds
- `sensor.*_backup_size` - added/modified this run (displays in GiB by
  default; size sensors use Home Assistant's built-in unit conversion,
  so you can switch to MB/TB etc. per-entity under Settings if you
  prefer - Settings > that entity > gear icon > Unit of measurement)
- `sensor.*_total_backup_size` - total size of everything currently
  stored at the destination (all versions combined)
- `sensor.*_versions` - number of backup versions currently retained
- `sensor.*_uploaded_bytes` (diagnostic) - bytes actually uploaded in
  this run (distinct from `backup_size`, which reflects source-file
  changes, not network traffic)
- `sensor.*_destination_free_space` (diagnostic) - free space at the
  backup destination, when Duplicati reports one
- `sensor.*_examined_files`, `*_added_files`, `*_modified_files`, `*_deleted_files`
- `sensor.*_warnings`, `sensor.*_errors` (diagnostic category)
- `binary_sensor.*_problem` - on when the last run ended in Error/Fatal
- `sensor.*_history` (diagnostic, disabled by default) - the last 20
  runs for this job, in its `runs` attribute (timestamp, result,
  file/warning/error counts, a trimmed message) - the data source for
  the dashboard log view below
- `sensor.*_last_raw_payload` (diagnostic, disabled by default) - the
  most recent raw incoming payload, for verifying/debugging the native
  JSON field mapping. View its content via the entity's "Attributes"
  section in its more-info dialog, or Developer Tools > States - HA
  doesn't show custom attributes on the basic entity card.

The `total_backup_size`/`versions`/`uploaded_bytes`/
`destination_free_space` sensors need Duplicati's native JSON reporting
(`--send-http-json-urls`) - they come from a `BackendStatistics` block
that the classic plain-text format (`--send-http-url`) doesn't include.
Everything else works with either format.

## Dashboard

[`docs/dashboard.yaml`](docs/dashboard.yaml) is a ready-to-paste,
single-view dashboard - summary tiles, a job status list, a combined
size graph, an activity log, and a per-job run log - built entirely
from built-in cards plus the `auto-entities` HACS card. Every card
filters by `integration: duplicati_monitor` (not entity-ID guessing),
and the per-job log section auto-discovers every job's "History"
sensor via Home Assistant's `integration_entities()`, so it never
needs editing as you add, rename, or remove jobs. No custom frontend
code, so no separate build/maintenance track. See the comments at the
top of that file for setup steps.

The easiest "drill down" into one job's full detail is Home
Assistant's own device page (Settings > Devices & Services > click any
job) - it's auto-generated with every sensor, graph, and current
value, for every job, with zero dashboard configuration.

Because the size/duration/file-count sensors use `state_class:
measurement`, Home Assistant's long-term statistics keep history for
them indefinitely (independent of the recorder purge interval), so
History and Statistics graphs work without any extra setup.

## Roadmap

Planned/possible future work is tracked as [GitHub issues](https://github.com/andlo/ha-duplicati-monitor/issues) - see the `enhancement` and `new feature` labels.

## License

MIT, see [LICENSE](LICENSE).
