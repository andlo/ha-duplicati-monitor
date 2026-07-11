# Duplicati Monitor for Home Assistant

A Home Assistant integration that receives a small status report from
[Duplicati](https://github.com/duplicati/duplicati) every time a backup
job finishes - similar in spirit to
[duplicati-monitoring.com](https://www.duplicati-monitoring.com/), but
self-hosted and push-based (no polling, no exposing Duplicati's own
web UI to Home Assistant).

Each backup server becomes a **device**, and each backup job on that
server becomes a set of **entities** (status, last backup time,
duration, size, file counts, warnings/errors, and a "problem" binary
sensor) - all with proper `device_class`/`state_class`, so History and
Statistics graphs work out of the box.

## Status

Early v1. Core webhook receiving, dynamic devices/entities per
server+job, and the sensors above are implemented. Not yet included
(see Roadmap): a detailed run-by-run log view and a bundled dashboard.

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

Duplicati can POST its own JSON report directly to the webhook URL -
no script, no per-job setup. On each machine, open **Settings**
(server-wide default options, so it applies to every job on that
machine automatically) and add:

```
--send-http-json-urls=https://YOUR_HA:8123/api/webhook/<your-webhook-id>?server_id=nas01&server_name=NAS01
--send-http-level=All
```

- `server_id`/`server_name` in the query string identify this machine
  as a device in Home Assistant (Duplicati's own payload doesn't
  reliably include a stable machine id across setups, so we ask for it
  explicitly here - set it once per machine, keep `server_id` stable
  once chosen).
- `--send-http-level=All` makes sure successful backups are reported
  too, not just failures.
- The job name/id come from Duplicati's own payload automatically.

The integration auto-detects Duplicati's native JSON shape and
translates it. That translation is necessarily a best-effort mapping
(Duplicati's JSON report isn't formally schema-documented and has
shown minor differences across versions/community reports) - if a job
comes through with missing fields, enable the job's normally-hidden
**"Last raw payload" diagnostic sensor** (on that job's device,
disabled by default) to see exactly what Duplicati sent, and open an
issue/PR with what you find.

## What you get

One collector-level device (named after the integration entry) with:

- `sensor.*_webhook` (diagnostic) - state is your webhook id, the full
  URL is in its `webhook_url` attribute - your permanent reference,
  no digging through Settings > Automations needed.

Per backup job, under a device named after `server_name`:

- `sensor.*_status` - `Success` / `Warning` / `Error` / `Fatal` / `Unknown`
- `sensor.*_last_backup` - timestamp of the last completed run
- `sensor.*_duration` - seconds
- `sensor.*_backup_size` - bytes added/modified this run
- `sensor.*_examined_files`, `*_added_files`, `*_modified_files`, `*_deleted_files`
- `sensor.*_warnings`, `sensor.*_errors` (diagnostic category)
- `binary_sensor.*_problem` - on when the last run ended in Error/Fatal
- `sensor.*_last_raw_payload` (diagnostic, disabled by default) - the
  most recent raw incoming payload, for verifying/debugging the native
  JSON field mapping

Because the size/duration/file-count sensors use `state_class:
measurement`, Home Assistant's long-term statistics keep history for
them indefinitely (independent of the recorder purge interval), so
History and Statistics graphs work without any extra setup.

## Roadmap

Planned/possible future work is tracked as [GitHub issues](https://github.com/andlo/ha-duplicati-monitor/issues) - see the `enhancement` and `new feature` labels.

## License

MIT, see [LICENSE](LICENSE).
