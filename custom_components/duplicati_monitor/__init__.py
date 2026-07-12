"""The Duplicati Monitor integration."""
from __future__ import annotations

import json
import logging

import voluptuous as vol
from aiohttp import web
from homeassistant.components import webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import CONF_WEBHOOK_ID, DOMAIN, PLATFORMS, SIGNAL_JOB_UPDATE, SIGNAL_NEW_JOB
from .report import JobReport, parse_incoming

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Duplicati Monitor from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "jobs": {},  # (server_id, job_id) -> JobReport
        "known_jobs": set(),
    }

    webhook.async_register(
        hass,
        DOMAIN,
        entry.title,
        entry.data[CONF_WEBHOOK_ID],
        _build_handler(entry.entry_id),
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    webhook.async_unregister(hass, entry.data[CONF_WEBHOOK_ID])
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded


def _build_handler(entry_id: str):
    """Build the aiohttp webhook handler bound to a specific entry."""

    async def handle_webhook(
        hass: HomeAssistant, webhook_id: str, request: web.Request
    ) -> web.Response:
        try:
            # Read and parse manually rather than request.json(): some
            # senders (Duplicati included) don't reliably set
            # Content-Type: application/json even though the body is
            # valid JSON, and HA's request.json() wrapper doesn't expose
            # aiohttp's content_type=None escape hatch to work around that.
            raw_body = await request.text()
            data = json.loads(raw_body)
        except ValueError:
            _LOGGER.warning(
                "Received non-JSON payload on webhook %s (first 300 chars): %r",
                webhook_id,
                raw_body[:300],
            )
            return web.Response(status=400, text="Invalid JSON")

        try:
            report: JobReport = parse_incoming(data, request.query)
        except vol.Invalid as err:
            _LOGGER.warning("Rejected Duplicati payload: %s", err)
            return web.Response(status=400, text=f"Invalid payload: {err}")
        store = hass.data[DOMAIN][entry_id]
        key = report.unique_key
        is_new = key not in store["known_jobs"]
        store["jobs"][key] = report
        store["known_jobs"].add(key)

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
