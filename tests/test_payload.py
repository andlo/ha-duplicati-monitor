"""Tests for the webhook payload parser."""
import sys
from pathlib import Path

import pytest
import voluptuous as vol

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "custom_components" / "duplicati_monitor")
)

from report import parse_incoming, parse_payload  # noqa: E402  (falls back to absolute import, see report.py)


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
