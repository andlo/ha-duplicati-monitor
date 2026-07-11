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
2. Give it a name (e.g. "Duplicati") and finish.
3. Go to Settings > Automations & Scenes > Webhooks (or check the
   integration's diagnostics) to find the generated webhook URL. It
   looks like:
   `https://YOUR_HA:8123/api/webhook/<random-id>`
4. On each machine running Duplicati, configure a post-backup
   notification (see below) pointing at that URL.

If your Home Assistant is not reachable from the backup machine
(e.g. it's on another network), you'll need a reverse proxy, VPN, or
Nabu Casa Cloud webhook URL instead of a local address.

## Connecting a Duplicati job

There are two ways to feed Duplicati into this integration. **Option A
needs no script at all** and is recommended.

### Option A: Duplicati's built-in JSON reporting (recommended)

Duplicati can POST its own JSON report directly - no script, no
per-job setup. On each machine, open **Settings** (server-wide
default options, so it applies to every job automatically - not a
per-job option) and add:

```
--send-http-json-urls=https://YOUR_HA:8123/api/webhook/<your-webhook-id>?server_id=nas01&server_name=NAS01
--send-http-level=All
```

- `server_id`/`server_name` in the query string identify this machine
  as a device in Home Assistant (Duplicati's own payload doesn't
  reliably include a stable machine id across setups, so we ask for it
  explicitly here - set it once per machine).
- `--send-http-level=All` makes sure successful backups are reported
  too, not just failures.
- The job name/id come from Duplicati's own payload automatically.

The integration auto-detects Duplicati's native JSON shape and
translates it. That translation is necessarily a best-effort mapping
(Duplicati's JSON report isn't formally schema-documented and has
shown minor differences across versions/community reports) - if a job
comes through with missing fields, enable the job's normally-hidden
**"Last raw payload" diagnostic sensor** (Settings > Devices & Services
> Duplicati Monitor > the job's device > that entity, disabled by
default) to see exactly what Duplicati sent, and open an issue/PR with
what you find.

### Option B: translator script (fallback / full control)

If Option A doesn't fit your setup (very old Duplicati version, you
want custom-computed fields, `--send-http-json-urls` misbehaving on
your install - this has been reported by some users), a small
translator script is provided in [`scripts/`](scripts/):

- `duplicati-notify.sh` (Linux/macOS)
- `duplicati-notify.ps1` (Windows)

In each Duplicati backup job: **Options > Run script after** (or edit
the job as text and add `--run-script-after=/path/to/duplicati-notify.sh`).
Set these variables at the top of your copy of the script (or as
environment variables available to Duplicati):

| Variable | Purpose | Default |
|---|---|---|
| `HA_WEBHOOK_URL` | The webhook URL from Setup step 3 | *(required)* |
| `DUPLICATI_SERVER_ID` | Stable id grouping all jobs on this machine into one device | `hostname` |
| `DUPLICATI_SERVER_NAME` | Friendly device name | same as `DUPLICATI_SERVER_ID` |

The script reads Duplicati's own `--run-script-after` result file
(`$DUPLICATI__RESULTFILE`) and posts one JSON object per finished job,
in this integration's own stable contract (see
[`docs/payload.md`](docs/payload.md)) - unlike Option A, this bypasses
native-JSON translation entirely, at the cost of needing the script
installed per machine.

⚠️ The Duplicati environment variable that carries the backup job's
name has varied across Duplicati versions. If jobs show up as
"unknown" in Home Assistant, run `env | grep -i duplicati` from inside
the script (redirected to a file) to find the right one on your
version, and adjust the script.

## What you get

Per backup job, under a device named after `DUPLICATI_SERVER_NAME`:

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

## Roadmap (not in v1)

- A detailed run-by-run log (v1 only keeps the latest state per job,
  like the sensors above - it relies on HA's own history/statistics
  for trends, not a custom log store).
- A bundled Lovelace dashboard/strategy summarizing all servers/jobs.
- Automatic entity cleanup when a job hasn't reported in a long time.

## License

MIT, see [LICENSE](LICENSE).
