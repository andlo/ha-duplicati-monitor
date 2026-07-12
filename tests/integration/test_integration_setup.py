"""Real integration test: run the full config-entry setup through HA's own
test harness and check the collector-level 'Webhook' sensor actually
gets created with a state. Not part of the lightweight pytest suite -
needs pytest-homeassistant-custom-component + homeassistant installed.

Run from the repo root with a symlink so 'custom_components' resolves:
    ln -s $(pwd)/custom_components /tmp/ha_test_config/custom_components
    PYTHONPATH=. pytest tests/test_integration_setup.py -v
"""
import pytest
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.duplicati_monitor.const import DOMAIN, CONF_WEBHOOK_ID


async def test_setup_creates_webhook_sensor(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Duplicati",
        data={CONF_WEBHOOK_ID: "duplicati-test"},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert result is True
    assert entry.state.value == "loaded"

    state = hass.states.get("sensor.duplicati_webhook")
    assert state is not None, (
        "No sensor.duplicati_webhook entity found. All states: "
        + str(list(hass.states.async_entity_ids("sensor")))
    )
    assert state.state == "duplicati-test"
    assert "webhook_url" in state.attributes


async def test_incoming_report_creates_job_sensors(hass, hass_client_no_auth):
    """Post a real payload through the actual HTTP webhook endpoint and
    check the resulting job sensors show up - the full path that broke
    in v0.0.1-v0.0.3."""
    assert await async_setup_component(hass, "http", {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Duplicati",
        data={CONF_WEBHOOK_ID: "duplicati-test2"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    client = await hass_client_no_auth()
    resp = await client.post(
        "/api/webhook/duplicati-test2",
        json={
            "server_id": "nas01",
            "job_id": "documents",
            "parsed_result": "Success",
            "examined_files": 42,
        },
    )
    assert resp.status == 200
    await hass.async_block_till_done()

    status_state = hass.states.get("sensor.nas01_documents_status")
    assert status_state is not None, (
        "No sensor.nas01_documents_status entity found. All states: "
        + str(list(hass.states.async_entity_ids("sensor")))
    )
    assert status_state.state == "Success"

    problem_state = hass.states.get("binary_sensor.nas01_documents_problem")
    assert problem_state is not None
    assert problem_state.state == "off"


async def test_incoming_report_with_wrong_content_type_still_works(
    hass, hass_client_no_auth
):
    """Real-world bug (found 2026-07-12): Duplicati doesn't reliably send
    Content-Type: application/json even though the body is valid JSON.
    aiohttp's request.json() rejects that by default - must be called
    with content_type=None to accept any content type."""
    assert await async_setup_component(hass, "http", {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Duplicati",
        data={CONF_WEBHOOK_ID: "duplicati-test3"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    client = await hass_client_no_auth()
    resp = await client.post(
        "/api/webhook/duplicati-test3",
        data=b'{"server_id": "nas01", "job_id": "photos", "parsed_result": "Success"}',
        headers={"Content-Type": "text/plain"},
    )
    assert resp.status == 200
    await hass.async_block_till_done()

    status_state = hass.states.get("sensor.nas01_photos_status")
    assert status_state is not None, (
        "No sensor.nas01_photos_status entity found (wrong-content-type "
        "payload was likely rejected). All states: "
        + str(list(hass.states.async_entity_ids("sensor")))
    )
    assert status_state.state == "Success"



async def test_classic_duplicati_form_report_creates_job_sensors(
    hass, hass_client_no_auth
):
    """Real-world scenario (found 2026-07-12, andlo's actual Duplicati
    setup): Duplicati's default report is form-urlencoded 'message=...'
    plain text, not JSON at all - this is the exact wire format, posted
    through the real HTTP endpoint with the real Content-Type Duplicati
    uses."""
    assert await async_setup_component(hass, "http", {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Duplicati",
        data={CONF_WEBHOOK_ID: "duplicati-test4"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    client = await hass_client_no_auth()
    body = (
        "message=Duplicati%20Backup%20report%20for%20TEST%20"
        "%28de061ef940dc4e2d98e397383be75bb8%2C%20DB-1%2C%20fedora%29"
        "%0A%0ADeletedFiles%3A%200%0AExaminedFiles%3A%20276"
        "%0AAddedFiles%3A%200%0AParsedResult%3A%20Success"
    )
    resp = await client.post(
        "/api/webhook/duplicati-test4?server_id=fedora&server_name=Fedora",
        data=body.encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status == 200
    await hass.async_block_till_done()

    status_state = hass.states.get("sensor.fedora_test_status")
    assert status_state is not None, (
        "No sensor.fedora_test_status entity found. All states: "
        + str(list(hass.states.async_entity_ids("sensor")))
    )
    assert status_state.state == "Success"



async def test_jobs_survive_a_restart(hass, hass_client_no_auth):
    """Real-world bug (found 2026-07-12, andlo's live setup): after a HA
    restart, previously-reporting jobs showed as 'unavailable' until the
    next Duplicati run, because job state only lived in memory. Jobs
    must now be persisted and restored immediately on setup."""
    assert await async_setup_component(hass, "http", {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Duplicati",
        data={CONF_WEBHOOK_ID: "duplicati-test5"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    client = await hass_client_no_auth()
    resp = await client.post(
        "/api/webhook/duplicati-test5",
        json={
            "server_id": "nas01",
            "job_id": "documents",
            "parsed_result": "Success",
            "examined_files": 42,
        },
    )
    assert resp.status == 200
    await hass.async_block_till_done()
    assert hass.states.get("sensor.nas01_documents_status").state == "Success"

    # Simulate a Home Assistant restart: unload then set up the entry
    # again, without ever posting to the webhook in between.
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    status_state = hass.states.get("sensor.nas01_documents_status")
    assert status_state is not None, (
        "sensor.nas01_documents_status disappeared entirely after restart"
    )
    assert status_state.state == "Success", (
        f"Expected the persisted 'Success' state to survive the restart, "
        f"got {status_state.state!r} instead (this is the 'all entities "
        f"became unavailable' bug)"
    )
