"""Tests for the webhook payload parser."""
import sys
from pathlib import Path

import pytest
import voluptuous as vol

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "custom_components" / "duplicati_monitor")
)

from report import parse_incoming, parse_payload, parse_raw_body  # noqa: E402  (falls back to absolute import, see report.py)


def test_minimal_valid_payload():
    report = parse_payload({"server_id": "nas01", "job_id": "documents"})
    assert report.server_id == "nas01"
    assert report.job_id == "documents"
    assert report.server_name == "nas01"
    assert report.job_name == "documents"
    assert report.raw["parsed_result"] == "Unknown"


def test_missing_required_field_raises():
    with pytest.raises(vol.Invalid):
        parse_payload({"job_id": "documents"})


def test_invalid_parsed_result_raises():
    with pytest.raises(vol.Invalid):
        parse_payload({"server_id": "nas01", "job_id": "d", "parsed_result": "Nope"})


def test_full_payload_roundtrip():
    payload = {
        "server_id": "nas01",
        "server_name": "NAS01",
        "job_id": "documents",
        "job_name": "Documents backup",
        "parsed_result": "Success",
        "examined_files": 100,
        "size_of_added_files": 2048,
    }
    report = parse_payload(payload)
    assert report.raw["examined_files"] == 100
    assert report.unique_key == ("nas01", "documents")


def test_native_payload_via_query_server_id():
    """Native Duplicati JSON, server identified via the webhook URL's query string."""
    native = {
        "Data": {
            "ParsedResult": "Success",
            "BeginTime": "2026-07-11T03:00:00+02:00",
            "EndTime": "2026-07-11T03:14:00+02:00",
            "ExaminedFiles": 12345,
            "AddedFiles": 12,
            "DeletedFiles": 1,
            "ModifiedFiles": 34,
            "SizeOfAddedFiles": 1048576,
            "SizeOfModifiedFiles": 2097152,
            "WarningsActualLength": 0,
            "ErrorsActualLength": 0,
        },
        "Extra": {"backup-name": "Documents backup", "backup-id": "documents"},
    }
    report = parse_incoming(native, {"server_id": "nas01", "server_name": "NAS01"})
    assert report.server_id == "nas01"
    assert report.server_name == "NAS01"
    assert report.job_id == "documents"
    assert report.job_name == "Documents backup"
    assert report.raw["parsed_result"] == "Success"
    assert report.raw["examined_files"] == 12345
    assert report.source_payload == native


def test_native_payload_via_extra_machine_fields():
    """Native Duplicati JSON where Extra itself carries machine info."""
    native = {
        "Data": {"ParsedResult": "Warning", "ExaminedFiles": 5},
        "Extra": {
            "machine-name": "NAS01",
            "machine-id": "nas01",
            "backup-name": "documents",
        },
    }
    report = parse_incoming(native, {})
    assert report.server_id == "nas01"
    assert report.server_name == "NAS01"
    assert report.job_id == "documents"
    assert report.raw["parsed_result"] == "Warning"


def test_native_payload_missing_server_id_raises():
    native = {"Data": {"ParsedResult": "Success"}, "Extra": {"backup-name": "x"}}
    with pytest.raises(vol.Invalid):
        parse_incoming(native, {})


def test_contract_payload_still_works_via_dispatch():
    report = parse_incoming({"server_id": "nas01", "job_id": "documents"}, {})
    assert report.server_id == "nas01"
    assert report.job_id == "documents"


def test_classic_message_format_real_world_sample():
    """Real payload captured from a live Duplicati instance on 2026-07-12:
    Duplicati's default report is form-urlencoded 'message=...', NOT
    JSON, even when a JSON-looking option is configured. This is the
    exact shape parse_raw_body must handle."""
    raw_body = (
        "message=Duplicati%20Backup%20report%20for%20TEST%20"
        "%28de061ef940dc4e2d98e397383be75bb8%2C%20DB-1%2C%20fedora%29"
        "%0A%0ADeletedFiles%3A%200%0ADeletedFolders%3A%200"
        "%0AModifiedFiles%3A%200%0AExaminedFiles%3A%20276"
        "%0AOpenedFiles%3A%200%0AAddedFiles%3A%200"
        "%0ASizeOfModifiedFiles%3A%200%0ASizeOfAddedFiles%3A%200"
        "%0AParsedResult%3A%20Success"
    )
    report = parse_raw_body(raw_body, {"server_id": "fedora", "server_name": "Fedora"})
    assert report.server_id == "fedora"
    assert report.server_name == "Fedora"
    assert report.job_id == "TEST"
    assert report.raw["parsed_result"] == "Success"
    assert report.raw["examined_files"] == 276


def test_classic_message_format_server_id_from_message_when_no_query():
    """Without a ?server_id= override, fall back to the machine name
    embedded in the message header's last parenthesised part."""
    raw_body = (
        "message=Duplicati%20Backup%20report%20for%20TEST%20"
        "%28abc123%2C%20DB-1%2C%20myhostname%29"
        "%0A%0AExaminedFiles%3A%2010%0AParsedResult%3A%20Warning"
    )
    report = parse_raw_body(raw_body, {})
    assert report.server_id == "myhostname"
    assert report.job_id == "TEST"
    assert report.raw["parsed_result"] == "Warning"


def test_unparseable_body_raises():
    with pytest.raises(vol.Invalid):
        parse_raw_body("this is neither json nor form data {{{", {})


def test_native_payload_backend_statistics_fields():
    """Real native-JSON payload captured from andlo's live Duplicati
    instance on 2026-07-12 (--send-http-json-urls), trimmed to the
    fields that matter for this test. Confirms extraction of the
    BackendStatistics block: total size, version count, upload bytes,
    free destination space, and log lines."""
    native = {
        "Data": {
            "ExaminedFiles": 276,
            "ParsedResult": "Success",
            "WarningsActualLength": 0,
            "ErrorsActualLength": 0,
            "LogLines": ["line one", "line two"],
            "BackendStatistics": {
                "BytesUploaded": 0,
                "KnownFileCount": 6,
                "KnownFileSize": 50579180,
                "KnownFilesets": 2,
                "FreeQuotaSpace": 9717628928,
            },
        },
        "Extra": {
            "backup-name": "TEST",
            "backup-id": "DB-1",
            "machine-id": "de061ef940dc4e2d98e397383be75bb8",
            "machine-name": "fedora",
        },
    }
    report = parse_incoming(native, {})
    assert report.server_id == "de061ef940dc4e2d98e397383be75bb8"
    assert report.server_name == "fedora"
    assert report.job_id == "DB-1"
    assert report.job_name == "TEST"
    assert report.raw["total_size"] == 50579180
    assert report.raw["versions"] == 2
    assert report.raw["bytes_uploaded"] == 0
    assert report.raw["destination_free_space"] == 9717628928
    assert report.raw["log_lines"] == ["line one", "line two"]


def test_dotnet_duration_parsed_from_native_json():
    """Real bug (found 2026-07-12): Duplicati's Duration field is a
    .NET TimeSpan string ("00:14:00.7046721"), not a plain number -
    duration_seconds was never populated at all, showing 'Unknown'."""
    from report import parse_dotnet_duration_seconds

    assert parse_dotnet_duration_seconds("00:00:00.7046721") == pytest.approx(0.7046721)
    assert parse_dotnet_duration_seconds("00:14:00") == 840.0
    assert parse_dotnet_duration_seconds("1.05:30:00") == 86400 + 5 * 3600 + 30 * 60
    assert parse_dotnet_duration_seconds(None) is None
    assert parse_dotnet_duration_seconds("not a duration") is None

    native = {
        "Data": {
            "ParsedResult": "Success",
            "Duration": "00:14:00.7046721",
        },
        "Extra": {"backup-name": "TEST", "machine-name": "fedora"},
    }
    report = parse_incoming(native, {"server_id": "fedora"})
    assert report.raw["duration_seconds"] == pytest.approx(840.7046721)


def test_dotnet_duration_parsed_from_classic_message():
    raw_body = (
        "message=Duplicati%20Backup%20report%20for%20TEST%20"
        "%28abc123%2C%20DB-1%2C%20fedora%29"
        "%0A%0AExaminedFiles%3A%2010%0AParsedResult%3A%20Success"
        "%0ADuration%3A%2000%3A14%3A00.7046721"
    )
    report = parse_raw_body(raw_body, {})
    assert report.raw["duration_seconds"] == pytest.approx(840.7046721)


def test_report_to_history_entry_excludes_bulky_fields():
    from report import report_to_history_entry

    payload = {
        "server_id": "nas01",
        "job_id": "documents",
        "parsed_result": "Success",
        "examined_files": 100,
        "message": "x" * 1000,
    }
    report = parse_payload(payload)
    entry = report_to_history_entry(report)
    assert entry["parsed_result"] == "Success"
    assert entry["examined_files"] == 100
    assert len(entry["message"]) == 300
    assert "recorded_at" in entry
    assert "source_payload" not in entry
    assert "log_lines" not in entry


def test_compute_next_expected_needs_at_least_two_runs():
    from report import compute_next_expected

    assert compute_next_expected([]) == (None, None)
    assert compute_next_expected([{"recorded_at": "2026-01-01T00:00:00+00:00"}]) == (None, None)


def test_compute_next_expected_daily_cadence():
    from report import compute_next_expected

    runs = [
        {"recorded_at": "2026-01-01T03:00:00+00:00"},
        {"recorded_at": "2026-01-02T03:00:00+00:00"},
        {"recorded_at": "2026-01-03T03:00:00+00:00"},
    ]
    next_expected, interval = compute_next_expected(runs)
    assert interval == 86400.0  # 24h
    assert next_expected == "2026-01-04T03:00:00+00:00"
