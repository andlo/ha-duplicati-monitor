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


async def test_one_device_per_job_and_orphan_cleanup(hass, hass_client_no_auth):
    """v0.1.0 model change: one device per (server, job), not per
    server. Also verifies old-style per-server devices left behind by
    that change get cleaned up automatically."""
    from homeassistant.helpers import device_registry as dr

    assert await async_setup_component(hass, "http", {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Duplicati",
        data={CONF_WEBHOOK_ID: "duplicati-test6"},
    )
    entry.add_to_hass(hass)

    device_registry = dr.async_get(hass)
    stale_device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, f"{entry.entry_id}_nas01")},
        name="NAS01",
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    client = await hass_client_no_auth()
    resp = await client.post(
        "/api/webhook/duplicati-test6",
        json={
            "server_id": "nas01",
            "server_name": "NAS01",
            "job_id": "documents",
            "job_name": "Documents",
            "parsed_result": "Success",
        },
    )
    assert resp.status == 200
    await hass.async_block_till_done()

    job_device = device_registry.async_get_device(
        identifiers={(DOMAIN, f"{entry.entry_id}_nas01_documents")}
    )
    assert job_device is not None, "No per-(server, job) device was created"
    assert job_device.name == "NAS01 - Documents"

    # Setting up again (simulating a HA restart, with the job already
    # persisted) should remove the stale per-server-only device.
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert device_registry.async_get(stale_device.id) is None, (
        "Old-style per-server device was not cleaned up"
    )
    assert (
        device_registry.async_get_device(
            identifiers={(DOMAIN, f"{entry.entry_id}_nas01_documents")}
        )
        is not None
    ), "Per-job device disappeared after restart"


async def test_run_history_accumulates_trims_and_survives_restart(
    hass, hass_client_no_auth
):
    """Post several runs, check the history sensor's `runs` attribute
    grows and is capped at MAX_HISTORY_ENTRIES, then simulate a
    restart and confirm the history survived."""
    from custom_components.duplicati_monitor.const import MAX_HISTORY_ENTRIES

    assert await async_setup_component(hass, "http", {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Duplicati",
        data={CONF_WEBHOOK_ID: "duplicati-test7"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    client = await hass_client_no_auth()
    for i in range(MAX_HISTORY_ENTRIES + 5):
        resp = await client.post(
            "/api/webhook/duplicati-test7",
            json={
                "server_id": "nas01",
                "job_id": "documents",
                "parsed_result": "Success",
                "examined_files": i,
            },
        )
        assert resp.status == 200
    await hass.async_block_till_done()

    history_state = hass.states.get("sensor.nas01_documents_history")
    assert history_state is not None
    runs = history_state.attributes["runs"]
    assert len(runs) == MAX_HISTORY_ENTRIES, (
        f"Expected history capped at {MAX_HISTORY_ENTRIES}, got {len(runs)}"
    )
    # Oldest entries should have been dropped - the last run's
    # examined_files should be the most recent value posted.
    assert runs[-1]["examined_files"] == MAX_HISTORY_ENTRIES + 4

    # Simulate a restart.
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    history_state = hass.states.get("sensor.nas01_documents_history")
    assert history_state is not None
    assert len(history_state.attributes["runs"]) == MAX_HISTORY_ENTRIES, (
        "Run history did not survive a restart"
    )


async def test_summary_sensors_count_jobs_by_status(hass, hass_client_no_auth):
    """Entry-level 'X of Y' sensors, for zero-config dashboard tiles -
    should recompute live as jobs report in with different results."""
    assert await async_setup_component(hass, "http", {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Duplicati",
        data={CONF_WEBHOOK_ID: "duplicati-test8"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    client = await hass_client_no_auth()

    async def post(server_id, job_id, result):
        resp = await client.post(
            "/api/webhook/duplicati-test8",
            json={
                "server_id": server_id,
                "job_id": job_id,
                "parsed_result": result,
            },
        )
        assert resp.status == 200

    await post("nas01", "documents", "Success")
    await post("nas01", "photos", "Fatal")
    await post("nas02", "backup", "Success")
    await hass.async_block_till_done()

    assert hass.states.get("sensor.duplicati_total").state == "3"
    assert hass.states.get("sensor.duplicati_ok").state == "2"
    assert hass.states.get("sensor.duplicati_problem").state == "1"

    # A job flipping from Success to Fatal should update the counts live.
    await post("nas02", "backup", "Fatal")
    await hass.async_block_till_done()

    assert hass.states.get("sensor.duplicati_total").state == "3"
    assert hass.states.get("sensor.duplicati_ok").state == "1"
    assert hass.states.get("sensor.duplicati_problem").state == "2"


async def test_stale_summary_entities_migrate_to_new_unique_id(hass):
    """Real-world bug (andlo, 2026-07-12): renaming the summary sensors
    in v0.3.1 changed their intended entity_id, but didn't rename the
    already-registered entities (entity_id is sticky once assigned) -
    HA's own 'unknown entities used in a dashboard' repair check
    caught it. v0.3.2 also bumped their unique_id so old registrations
    become orphaned and get cleaned up automatically on upgrade."""
    from homeassistant.helpers import entity_registry as er

    entity_registry = er.async_get(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Duplicati Monitor",
        data={CONF_WEBHOOK_ID: "duplicati-migrate-test"},
    )
    entry.add_to_hass(hass)

    # Simulate a pre-0.3.2 registration under the OLD unique_id scheme.
    stale = entity_registry.async_get_or_create(
        domain="sensor",
        platform=DOMAIN,
        unique_id=f"{entry.entry_id}_summary_jobs_total",
        config_entry=entry,
        suggested_object_id="duplicati_monitor_jobs_total",
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entity_registry.async_get(stale.entity_id) is None, (
        "Stale pre-0.3.2 summary entity was not cleaned up"
    )
    assert hass.states.get("sensor.duplicati_total") is not None, (
        "New-style summary entity was not created"
    )
