"""Constants for the Duplicati Monitor integration."""
from __future__ import annotations

DOMAIN = "duplicati_monitor"
PLATFORMS = ["sensor", "binary_sensor", "update"]

CONF_WEBHOOK_ID = "webhook_id"

# Signal dispatched when a previously unseen (server_id, job_id) pair
# is discovered in an incoming payload. Platforms listen for this to
# create entities dynamically.
SIGNAL_NEW_JOB = f"{DOMAIN}_new_job_{{entry_id}}"

# Signal dispatched whenever fresh data has been stored for a job.
# Entities listen for this using their own (server_id, job_id) suffix.
SIGNAL_JOB_UPDATE = f"{DOMAIN}_job_update_{{entry_id}}_{{server_id}}_{{job_id}}"

# Signal dispatched after EVERY webhook update, regardless of which job
# - for entry-level aggregate sensors (job counts) that need to
# recompute across all known jobs, not just one.
SIGNAL_ANY_UPDATE = f"{DOMAIN}_any_update_{{entry_id}}"

PARSED_RESULTS = ["Success", "Warning", "Error", "Fatal", "Unknown"]
PROBLEM_RESULTS = {"Error", "Fatal"}

EVENT_BEFORE = "BEFORE"
EVENT_AFTER = "AFTER"

ATTR_SERVER_ID = "server_id"
ATTR_SERVER_NAME = "server_name"
ATTR_JOB_ID = "job_id"
ATTR_JOB_NAME = "job_name"
ATTR_EVENT = "event"
ATTR_OPERATION = "operation"
ATTR_PARSED_RESULT = "parsed_result"
ATTR_BEGIN_TIME = "begin_time"
ATTR_END_TIME = "end_time"
ATTR_DURATION_SECONDS = "duration_seconds"
ATTR_EXAMINED_FILES = "examined_files"
ATTR_ADDED_FILES = "added_files"
ATTR_DELETED_FILES = "deleted_files"
ATTR_MODIFIED_FILES = "modified_files"
ATTR_SIZE_ADDED = "size_of_added_files"
ATTR_SIZE_MODIFIED = "size_of_modified_files"
ATTR_WARNINGS_COUNT = "warnings_count"
ATTR_ERRORS_COUNT = "errors_count"
ATTR_MESSAGE = "message"

# From Duplicati's BackendStatistics block - what's actually stored at
# the destination, not just what changed in this run.
ATTR_TOTAL_SIZE = "total_size"
ATTR_VERSIONS = "versions"
ATTR_BYTES_UPLOADED = "bytes_uploaded"
ATTR_QUOTA_FREE = "destination_free_space"
ATTR_LOG_LINES = "log_lines"

# Duplicati's own version, as it puts it in every report it sends:
# "2.4.0.0 (2.4.0.0_stable_2026-09-03)" - the short number first, the
# full build string in parentheses. Present in BOTH wire formats (top
# level "Version" in the native JSON, a "Version: ..." line in the
# classic text report), so the update entity works either way.
ATTR_DUPLICATI_VERSION = "duplicati_version"

# ---------------------------------------------------------------------
# Update entity: is a newer Duplicati out?
#
# Read from Duplicati's OWN update manifest - the same file its
# built-in update check uses - rather than GitHub releases, so the
# answer matches what Duplicati itself would offer you, per channel,
# and doesn't depend on GitHub's unauthenticated rate limit.
#
# Wire format: one line `//SIGJSONv1: <base64 signature>`, then the
# JSON body. We only read the body; we are not verifying the signature
# (we install nothing - this entity is informational).
# ---------------------------------------------------------------------
UPDATE_MANIFEST_URL = "https://updates.duplicati.com/{channel}/latest-v2.manifest"
UPDATE_MANIFEST_SIG_PREFIX = "//SIGJSONv1:"
UPDATE_DEFAULT_CHANNEL = "stable"
# Duplicati ships a few times a year; twice a day is already generous.
UPDATE_SCAN_INTERVAL_HOURS = 12
# HA truncates release_summary at 255 chars.
UPDATE_SUMMARY_MAX_CHARS = 255

# Run-history storage (issue #1): how many past runs to keep per job,
# for the "history" sensor a dashboard can drill into.
MAX_HISTORY_ENTRIES = 20

# How long a job may go without a fresh AFTER-event before we consider
# it "stale" is intentionally NOT handled in v1 - see README roadmap.
