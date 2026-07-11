"""Tests for the webhook payload parser."""
import sys
from pathlib import Path

import pytest
import voluptuous as vol

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "custom_components" / "duplicati_monitor")
)

from webhook import parse_payload  # noqa: E402  (falls back to absolute import, see webhook.py)


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
