"""Webhook payload handling for Duplicati Monitor.

Duplicati itself does not send exactly this JSON shape - the shipped
scripts/duplicati-notify.sh (and .ps1) translate Duplicati's own
--run-script-after environment variables / result file into this
stable contract, so the integration does not depend on Duplicati's
internal report format.
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
