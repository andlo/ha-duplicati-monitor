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

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import parse_qs

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


# ---------------------------------------------------------------------
# Classic Duplicati "--send-http-url" plain-text report support
#
# This is Duplicati's older/default report format: a single
# form-urlencoded "message" field whose value is a human-readable text
# block, e.g.:
#
#   Duplicati Backup report for TEST (abc123, DB-1, myhostname)
#
#   DeletedFiles: 0
#   ExaminedFiles: 276
#   AddedFiles: 0
#   ParsedResult: Success
#   ...
#
# Confirmed against a real Duplicati instance on 2026-07-12 - this is
# what most default/UI-configured Duplicati setups actually send,
# distinct from the --send-http-json-urls JSON option above.
# ---------------------------------------------------------------------

_HEADER_RE = re.compile(
    r"^Duplicati\s+(?P<operation>\S+)\s+report for\s+(?P<job_name>.+?)\s*\((?P<paren>[^)]*)\)"
)
_FIELD_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_]*):\s?(.*)$")

_CLASSIC_FIELD_MAP = {
    "ParsedResult": ATTR_PARSED_RESULT,
    "BeginTime": ATTR_BEGIN_TIME,
    "EndTime": ATTR_END_TIME,
    "ExaminedFiles": ATTR_EXAMINED_FILES,
    "AddedFiles": ATTR_ADDED_FILES,
    "DeletedFiles": ATTR_DELETED_FILES,
    "ModifiedFiles": ATTR_MODIFIED_FILES,
    "SizeOfAddedFiles": ATTR_SIZE_ADDED,
    "SizeOfModifiedFiles": ATTR_SIZE_MODIFIED,
    "WarningsActualLength": ATTR_WARNINGS_COUNT,
    "ErrorsActualLength": ATTR_ERRORS_COUNT,
}


def extract_classic_message(raw_body: str) -> str | None:
    """If raw_body is form-urlencoded with a 'message' field, return its
    (already URL-decoded) value. Otherwise return None."""
    try:
        parsed = parse_qs(raw_body, strict_parsing=True, errors="strict")
    except ValueError:
        return None
    values = parsed.get("message")
    if not values:
        return None
    return values[0]


def translate_classic_message(message: str, query: dict) -> dict:
    """Translate Duplicati's classic plain-text report into our contract."""
    lines = message.splitlines()
    contract: dict = {}

    if lines:
        match = _HEADER_RE.match(lines[0].strip())
        if match:
            contract[ATTR_OPERATION] = match.group("operation")
            contract[ATTR_JOB_NAME] = match.group("job_name").strip()
            paren_parts = [p.strip() for p in match.group("paren").split(",") if p.strip()]
            if paren_parts:
                # Last parenthesised part is conventionally the machine
                # name, e.g. "(abc123, DB-1, myhostname)".
                contract[ATTR_SERVER_NAME] = paren_parts[-1]

    for line in lines[1:]:
        field_match = _FIELD_RE.match(line.strip())
        if not field_match:
            continue
        key, value = field_match.group(1), field_match.group(2).strip()
        contract_key = _CLASSIC_FIELD_MAP.get(key)
        if contract_key:
            contract[contract_key] = value

    contract[ATTR_MESSAGE] = message[:500]

    server_id = query.get("server_id") or contract.get(ATTR_SERVER_NAME)
    server_name = query.get("server_name") or contract.get(ATTR_SERVER_NAME) or server_id
    job_id = query.get("job_id") or contract.get(ATTR_JOB_NAME)
    job_name = query.get("job_name") or contract.get(ATTR_JOB_NAME) or job_id

    if not server_id:
        raise vol.Invalid(
            "Could not determine server_id from the classic-format report. "
            "Add ?server_id=your-machine-name to the report URL."
        )

    contract[ATTR_SERVER_ID] = server_id
    contract[ATTR_SERVER_NAME] = server_name
    contract[ATTR_JOB_ID] = job_id or "unknown"
    contract[ATTR_JOB_NAME] = job_name or contract[ATTR_JOB_ID]

    if contract.get(ATTR_PARSED_RESULT) not in PARSED_RESULTS:
        contract[ATTR_PARSED_RESULT] = "Unknown"

    return {k: v for k, v in contract.items() if v is not None}


def parse_raw_body(raw_body: str, query: dict | None = None) -> JobReport:
    """Parse a webhook request body of unknown shape.

    Tries, in order: JSON (native Duplicati JSON or our own contract,
    via parse_incoming), then Duplicati's classic form-urlencoded
    plain-text report. Raises voluptuous.Invalid with a clear message
    if neither matches.
    """
    query = dict(query or {})

    try:
        data = json.loads(raw_body)
    except ValueError:
        data = None

    if data is not None:
        return parse_incoming(data, query)

    message = extract_classic_message(raw_body)
    if message is not None:
        contract = translate_classic_message(message, query)
        report = parse_payload(contract)
        report.source_payload = {"message": message}
        return report

    raise vol.Invalid(
        "Payload is neither valid JSON nor Duplicati's classic "
        "form-urlencoded report format."
    )
