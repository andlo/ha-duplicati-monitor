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
