"""The Duplicati Monitor integration."""
from __future__ import annotations

import logging

import voluptuous as vol
from aiohttp import web
from homeassistant.components import webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.helpers import device_registry as dr

from .const import CONF_WEBHOOK_ID, DOMAIN, PLATFORMS, SIGNAL_JOB_UPDATE, SIGNAL_NEW_JOB
from .report import (
    JobReport,
    parse_raw_body,
    report_from_storage,
    report_to_storage,
)

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Duplicati Monitor from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    store_helper = Store(hass, STORAGE_VERSION, f"{DOMAIN}_{entry.entry_id}")
    persisted = await store_helper.async_load() or {}

    jobs: dict = {}
    known_jobs: set = set()
    for job_data in persisted.values():
        try:
            report = report_from_storage(job_data)
        except (KeyError, TypeError):
            _LOGGER.warning("Skipping corrupt persisted job entry: %r", job_data)
            continue
        jobs[report.unique_key] = report
        known_jobs.add(report.unique_key)

    hass.data[DOMAIN][entry.entry_id] = {
        "jobs": jobs,  # (server_id, job_id) -> JobReport
        "known_jobs": known_jobs,
        "store": store_helper,
    }

    webhook.async_register(
        hass,
        DOMAIN,
        entry.title,
        entry.data[CONF_WEBHOOK_ID],
        _build_handler(entry.entry_id),
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Run after platform setup, once entities have re-registered under
    # their new (server, job) devices - otherwise this could remove a
    # device that still has entities momentarily pointing at it,
    # cascading into losing their registry entries (and entity_id/
    # history continuity) before they get reassigned.
    _async_remove_orphaned_devices(hass, entry, jobs)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    webhook.async_unregister(hass, entry.data[CONF_WEBHOOK_ID])
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clean up persisted job data when the integration is removed."""
    await Store(hass, STORAGE_VERSION, f"{DOMAIN}_{entry.entry_id}").async_remove()


def _async_remove_orphaned_devices(
    hass: HomeAssistant, entry: ConfigEntry, jobs: dict
) -> None:
    """Remove devices that no longer match this entry's current model.

    v0.1.0 switched from one device per server to one device per
    (server, job) - this cleans up the old per-server devices (and any
    other stale device) left behind by that change, or by jobs that
    have since disappeared. Safe to run on every setup: it only ever
    removes devices whose identifiers don't match a currently known
    job or the collector hub device.
    """
    valid_identifiers = {(DOMAIN, entry.entry_id)}  # the "Webhook" hub device
    for report in jobs.values():
        valid_identifiers.add(
            (DOMAIN, f"{entry.entry_id}_{report.server_id}_{report.job_id}")
        )

    device_registry = dr.async_get(hass)
    for device in list(dr.async_entries_for_config_entry(device_registry, entry.entry_id)):
        if not (device.identifiers & valid_identifiers):
            _LOGGER.info("Removing orphaned device: %s", device.name)
            device_registry.async_remove_device(device.id)


def _build_handler(entry_id: str):
    """Build the aiohttp webhook handler bound to a specific entry."""

    async def handle_webhook(
        hass: HomeAssistant, webhook_id: str, request: web.Request
    ) -> web.Response:
        raw_body = await request.text()
        try:
            report: JobReport = parse_raw_body(raw_body, request.query)
        except vol.Invalid as err:
            _LOGGER.warning(
                "Rejected payload on webhook %s: %s (first 300 chars: %r)",
                webhook_id,
                err,
                raw_body[:300],
            )
            return web.Response(status=400, text=f"Invalid payload: {err}")
        store = hass.data[DOMAIN][entry_id]
        key = report.unique_key
        is_new = key not in store["known_jobs"]
        store["jobs"][key] = report
        store["known_jobs"].add(key)

        await store["store"].async_save(
            {
                f"{k[0]}|{k[1]}": report_to_storage(v)
                for k, v in store["jobs"].items()
            }
        )

        if is_new:
            _LOGGER.info(
                "Discovered new Duplicati job '%s' on server '%s'",
                report.job_id,
                report.server_id,
            )
            async_dispatcher_send(
                hass, SIGNAL_NEW_JOB.format(entry_id=entry_id), report
            )
        else:
            async_dispatcher_send(
                hass,
                SIGNAL_JOB_UPDATE.format(
                    entry_id=entry_id,
                    server_id=report.server_id,
                    job_id=report.job_id,
                ),
                report,
            )

        return web.Response(status=200, text="OK")

    return handle_webhook
