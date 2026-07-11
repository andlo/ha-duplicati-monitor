"""Report payload parsing for Duplicati Monitor.

Handles both Duplicati's native --send-http-json-urls JSON and this
integration's own internal contract (see docs/payload.md), auto-
detecting which one arrived on the webhook.

Named report.py (not webhook.py) deliberately: a submodule named
webhook.py inside this package would shadow the `webhook` name bound
via `from homeassistant.components import webhook` in __init__.py -
Python rebinds a package attribute to the submodule as a side effect
of `from .webhook import ...`, silently breaking that import. Keep it
this way.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import voluptuous as vol

try:
    from .const import (
        ATTR_ADDED_FILES,
        ATTR_BEGIN_TIME,
        ATTR_DELETED_FILES,
        ATTR_DURATION_SECONDS,
        ATTR_END_TIME,
        ATTR_ERRORS_COUNT,
        ATTR_EVENT,
        ATTR_EXAMINED_FILES,
        ATTR_JOB_ID,
        ATTR_JOB_NAME,
        ATTR_MESSAGE,
        ATTR_MODIFIED_FILES,
        ATTR_OPERATION,
        ATTR_PARSED_RESULT,
        ATTR_SERVER_ID,
        ATTR_SERVER_NAME,
        ATTR_SIZE_ADDED,
        ATTR_SIZE_MODIFIED,
        ATTR_WARNINGS_COUNT,
        EVENT_AFTER,
        PARSED_RESULTS,
    )
except ImportError:
    # Allows running this module standalone (e.g. from tests/) without
    # Home Assistant installed, where there is no parent package.
    from const import (
    ATTR_ADDED_FILES,
    ATTR_BEGIN_TIME,
    ATTR_DELETED_FILES,
    ATTR_DURATION_SECONDS,
    ATTR_END_TIME,
    ATTR_ERRORS_COUNT,
    ATTR_EVENT,
    ATTR_EXAMINED_FILES,
    ATTR_JOB_ID,
    ATTR_JOB_NAME,
    ATTR_MESSAGE,
    ATTR_MODIFIED_FILES,
    ATTR_OPERATION,
    ATTR_PARSED_RESULT,
    ATTR_SERVER_ID,
    ATTR_SERVER_NAME,
    ATTR_SIZE_ADDED,
    ATTR_SIZE_MODIFIED,
    ATTR_WARNINGS_COUNT,
    EVENT_AFTER,
    PARSED_RESULTS,
)

_LOGGER = logging.getLogger(__name__)

_SLUG = vol.All(str, vol.Length(min=1, max=64))

PAYLOAD_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_SERVER_ID): _SLUG,
        vol.Optional(ATTR_SERVER_NAME): str,
        vol.Required(ATTR_JOB_ID): _SLUG,
        vol.Optional(ATTR_JOB_NAME): str,
        vol.Optional(ATTR_EVENT, default=EVENT_AFTER): vol.In([EVENT_AFTER, "BEFORE"]),
        vol.Optional(ATTR_OPERATION, default="Backup"): str,
        vol.Optional(ATTR_PARSED_RESULT, default="Unknown"): vol.In(PARSED_RESULTS),
        vol.Optional(ATTR_BEGIN_TIME): str,
        vol.Optional(ATTR_END_TIME): str,
        vol.Optional(ATTR_DURATION_SECONDS): vol.Coerce(float),
        vol.Optional(ATTR_EXAMINED_FILES): vol.Coerce(int),
        vol.Optional(ATTR_ADDED_FILES): vol.Coerce(int),
        vol.Optional(ATTR_DELETED_FILES): vol.Coerce(int),
        vol.Optional(ATTR_MODIFIED_FILES): vol.Coerce(int),
        vol.Optional(ATTR_SIZE_ADDED): vol.Coerce(int),
        vol.Optional(ATTR_SIZE_MODIFIED): vol.Coerce(int),
        vol.Optional(ATTR_WARNINGS_COUNT, default=0): vol.Coerce(int),
        vol.Optional(ATTR_ERRORS_COUNT, default=0): vol.Coerce(int),
        vol.Optional(ATTR_MESSAGE): str,
    },
    extra=vol.ALLOW_EXTRA,
)


@dataclass
class JobReport:
    """A single parsed backup-job report."""

    server_id: str
    server_name: str
    job_id: str
    job_name: str
    raw: dict
    source_payload: dict | None = None

    @property
    def unique_key(self) -> tuple[str, str]:
        """Return the (server_id, job_id) key identifying this job."""
        return (self.server_id, self.job_id)


def parse_payload(data: dict) -> JobReport:
    """Validate and normalise an incoming webhook payload.

    Raises voluptuous.Invalid if the payload does not match the
    expected contract.
    """
    validated = PAYLOAD_SCHEMA(data)
    validated.setdefault(ATTR_BEGIN_TIME, None)
    validated.setdefault(ATTR_END_TIME, None)

    now_iso = datetime.now(timezone.utc).isoformat()
    _LOGGER.debug(
        "Parsed Duplicati report for %s/%s at %s",
        validated[ATTR_SERVER_ID],
        validated[ATTR_JOB_ID],
        now_iso,
    )

    return JobReport(
        server_id=validated[ATTR_SERVER_ID],
        server_name=validated.get(ATTR_SERVER_NAME) or validated[ATTR_SERVER_ID],
        job_id=validated[ATTR_JOB_ID],
        job_name=validated.get(ATTR_JOB_NAME) or validated[ATTR_JOB_ID],
        raw=validated,
    )


# ---------------------------------------------------------------------
# Native Duplicati JSON support (--send-http-json-urls)
#
# Duplicati's own JSON report is not officially schema-documented, so
# this translator is intentionally defensive: it tries several known
# key paths (gathered from community tooling such as duplicati-monitor
# and dupReport) and falls back gracefully. If your Duplicati version
# reports differently, check the "Last raw payload" diagnostic sensor
# this integration creates, and open an issue/PR with the shape you see.
# ---------------------------------------------------------------------


def _dig(data: dict, *paths: tuple[str, ...]):
    """Return the first value found by trying a list of key-paths."""
    for path in paths:
        node = data
        found = True
        for key in path:
            if isinstance(node, dict) and key in node:
                node = node[key]
            else:
                found = False
                break
        if found and node is not None:
            return node
    return None



def is_native_duplicati_payload(data: dict) -> bool:
    """True if this looks like Duplicati's own --send-http-json-urls body."""
    return isinstance(data.get("Data"), dict) or isinstance(data.get("Extra"), dict)


def _count_or_len(data: dict, count_paths: tuple, list_paths: tuple) -> int:
    """Prefer an explicit *ActualLength count, else count a list, else 0."""
    value = _dig(data, *count_paths)
    if isinstance(value, (int, float)):
        return int(value)
    listed = _dig(data, *list_paths)
    if isinstance(listed, list):
        return len(listed)
    return 0


def translate_native_payload(data: dict, query: dict) -> dict:
    """Translate a native Duplicati JSON report into our contract dict.

    `query` is the incoming request's query string (e.g. from
    `?server_id=nas01&server_name=NAS01` appended to the webhook URL in
    Duplicati's --send-http-json-urls option) and takes precedence for
    server identification, since Duplicati's own payload does not
    reliably include a stable machine identifier across setups.
    """
    server_id = query.get("server_id") or _dig(
        data, ("Extra", "machine-id"), ("Extra", "machine_id")
    )
    server_name = (
        query.get("server_name")
        or _dig(data, ("Extra", "machine-name"), ("Extra", "machine_name"))
        or server_id
    )
    if not server_id:
        raise vol.Invalid(
            "Could not determine server_id from the payload's Extra fields. "
            "Add ?server_id=your-machine-name to the webhook URL used in "
            "Duplicati's --send-http-json-urls option."
        )

    job_id = _dig(
        data, ("Extra", "backup-id"), ("Extra", "backup_id")
    ) or query.get("job_id")
    job_name = (
        _dig(data, ("Extra", "backup-name"), ("Extra", "backup_name"))
        or query.get("job_name")
        or job_id
    )
    if not job_id:
        job_id = job_name or "unknown"

    parsed_result = _dig(
        data,
        ("Data", "ParsedResult"),
        ("ParsedResult",),
        ("Data", "TestResults", "ParsedResult"),
    ) or "Unknown"
    # Duplicati may report e.g. "Success"/"Warning"/"Error"/"Fatal" - map
    # anything unrecognised to Unknown rather than rejecting the payload.
    if parsed_result not in PARSED_RESULTS:
        parsed_result = "Unknown"

    return {
        ATTR_SERVER_ID: str(server_id),
        ATTR_SERVER_NAME: str(server_name) if server_name else None,
        ATTR_JOB_ID: str(job_id),
        ATTR_JOB_NAME: str(job_name) if job_name else None,
        ATTR_OPERATION: _dig(data, ("Data", "MainOperation")) or "Backup",
        ATTR_PARSED_RESULT: parsed_result,
        ATTR_BEGIN_TIME: _dig(data, ("Data", "BeginTime"), ("BeginTime",)),
        ATTR_END_TIME: _dig(data, ("Data", "EndTime"), ("EndTime",)),
        ATTR_EXAMINED_FILES: _dig(data, ("Data", "ExaminedFiles"), ("ExaminedFiles",)) or 0,
        ATTR_ADDED_FILES: _dig(data, ("Data", "AddedFiles"), ("AddedFiles",)) or 0,
        ATTR_DELETED_FILES: _dig(data, ("Data", "DeletedFiles"), ("DeletedFiles",)) or 0,
        ATTR_MODIFIED_FILES: _dig(data, ("Data", "ModifiedFiles"), ("ModifiedFiles",)) or 0,
        ATTR_SIZE_ADDED: _dig(data, ("Data", "SizeOfAddedFiles"), ("SizeOfAddedFiles",)) or 0,
        ATTR_SIZE_MODIFIED: _dig(
            data, ("Data", "SizeOfModifiedFiles"), ("SizeOfModifiedFiles",)
        )
        or 0,
        ATTR_WARNINGS_COUNT: _count_or_len(
            data,
            (("Data", "WarningsActualLength"), ("WarningsActualLength",)),
            (("Data", "Warnings"), ("Warnings",)),
        ),
        ATTR_ERRORS_COUNT: _count_or_len(
            data,
            (("Data", "ErrorsActualLength"), ("ErrorsActualLength",)),
            (("Data", "Errors"), ("Errors",)),
        ),
        ATTR_MESSAGE: _dig(data, ("message",), ("Extra", "message")),
    }


def parse_incoming(data: dict, query: dict | None = None) -> JobReport:
    """Parse a webhook body, auto-detecting native Duplicati vs. our contract.

    `query` is the request's query-string parameters, used to supply
    server_id/server_name/job_id overrides for native payloads (or, if
    given, as a fallback for a contract payload that omits them).
    """
    query = dict(query or {})

    if is_native_duplicati_payload(data):
        contract = translate_native_payload(data, query)
    else:
        contract = dict(data)
        contract.setdefault(ATTR_SERVER_ID, query.get("server_id"))
        contract.setdefault(ATTR_SERVER_NAME, query.get("server_name"))
        contract.setdefault(ATTR_JOB_ID, query.get("job_id"))

    # Drop None values so PAYLOAD_SCHEMA's own optional/default handling applies.
    contract = {k: v for k, v in contract.items() if v is not None}
    report = parse_payload(contract)
    report.source_payload = data
    return report
