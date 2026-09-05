"""Update entity: is a newer Duplicati available for a reporting server?

One entity per Duplicati **server** (not per job - all jobs on a
machine share one binary), living on the collector hub device
alongside the summary sensors.

Where the two versions come from:

* installed - Duplicati stamps its own version into every report it
  sends, in both wire formats, so this needs no extra configuration
  and no access to Duplicati's web UI or its API. It only becomes
  known after that server's first report arrives.
* latest - Duplicati's own update manifest, the same file its built-in
  update check reads. Deliberately not GitHub releases: the manifest
  is per release channel, so a machine tracking `beta` is not told to
  "update" to a stable build it would never install, and there is no
  unauthenticated rate limit to trip over.

This entity is informational: Home Assistant cannot install a
Duplicati update, so `INSTALL` is not among the supported features -
same shape as the Immich/Nextcloud/Pi-hole update entities.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import timedelta

import aiohttp
from homeassistant.components.update import UpdateEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    ATTR_DUPLICATI_VERSION,
    DOMAIN,
    SIGNAL_ANY_UPDATE,
    SIGNAL_NEW_JOB,
    UPDATE_DEFAULT_CHANNEL,
    UPDATE_MANIFEST_SIG_PREFIX,
    UPDATE_MANIFEST_URL,
    UPDATE_SCAN_INTERVAL_HOURS,
    UPDATE_SUMMARY_MAX_CHARS,
)
from .report import JobReport

_LOGGER = logging.getLogger(__name__)

# "2.4.0.0 (2.4.0.0_stable_2026-09-03)" -> "2.4.0.0". The manifest
# reports the bare number, so compare on that and keep the full build
# string as an attribute.
_VERSION_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)")


def short_version(value: str | None) -> str | None:
    """Return the bare dotted number out of Duplicati's version string."""
    if not value:
        return None
    match = _VERSION_RE.match(str(value))
    return match.group(1) if match else str(value).strip() or None


def parse_manifest(text: str) -> dict:
    """Parse Duplicati's update manifest.

    Served as one `//SIGJSONv1: <base64 signature>` line followed by
    the JSON body. The signature is not verified - this integration
    installs nothing, it only reads a version number, and pulling in a
    signature-checking dependency for that would be out of proportion.
    """
    body = text
    if text.lstrip().startswith(UPDATE_MANIFEST_SIG_PREFIX):
        _, _, body = text.partition("\n")
    return json.loads(body)


class DuplicatiReleaseCoordinator(DataUpdateCoordinator[dict]):
    """Fetches the release manifest for one channel, shared by all
    update entities of this config entry."""

    def __init__(self, hass: HomeAssistant, channel: str = UPDATE_DEFAULT_CHANNEL) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_release_{channel}",
            update_interval=timedelta(hours=UPDATE_SCAN_INTERVAL_HOURS),
        )
        self._channel = channel

    async def _async_update_data(self) -> dict:
        url = UPDATE_MANIFEST_URL.format(channel=self._channel)
        session = async_get_clientsession(self.hass)
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
            response.raise_for_status()
            text = await response.text()
        return parse_manifest(text)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Create one update entity per reporting server."""
    store = hass.data[DOMAIN][entry.entry_id]

    coordinator = DuplicatiReleaseCoordinator(hass)
    # async_refresh, not async_config_entry_first_refresh: a manifest
    # fetch that fails (no internet on this box, upstream down) must
    # not block setup. The entity is still useful showing the installed
    # version alone, and the coordinator retries on its own schedule.
    await coordinator.async_refresh()

    known_servers: set[str] = set()

    @callback
    def _add_servers() -> None:
        new = []
        for report in store["jobs"].values():
            if report.server_id in known_servers:
                continue
            known_servers.add(report.server_id)
            new.append(
                DuplicatiServerUpdate(
                    entry, coordinator, report.server_id, report.server_name
                )
            )
        if new:
            async_add_entities(new)

    _add_servers()

    @callback
    def _on_new_job(report: JobReport) -> None:
        _add_servers()

    entry.async_on_unload(
        async_dispatcher_connect(
            hass, SIGNAL_NEW_JOB.format(entry_id=entry.entry_id), _on_new_job
        )
    )


class DuplicatiServerUpdate(UpdateEntity):
    """"Duplicati x.y.z is available" for one reporting machine."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_title = "Duplicati"

    def __init__(
        self,
        entry: ConfigEntry,
        coordinator: DuplicatiReleaseCoordinator,
        server_id: str,
        server_name: str,
    ) -> None:
        self._entry = entry
        self._coordinator = coordinator
        self._server_id = server_id
        self._attr_unique_id = f"{entry.entry_id}_update_{server_id}"
        self._attr_name = server_name
        self._attr_icon = "mdi:package-up"

    # -- versions ------------------------------------------------------

    @property
    def _installed_raw(self) -> str | None:
        """Version string from the most recent report of this server.

        Jobs on one machine all report the same binary, but a job whose
        last run predates an upgrade would report the old number - so
        take the newest report, not just any.
        """
        jobs = self.hass.data[DOMAIN][self._entry.entry_id]["jobs"]
        best_value = None
        best_time = ""
        for report in jobs.values():
            if report.server_id != self._server_id:
                continue
            value = report.raw.get(ATTR_DUPLICATI_VERSION)
            if not value:
                continue
            end_time = str(report.raw.get("end_time") or "")
            if best_value is None or end_time >= best_time:
                best_value, best_time = value, end_time
        return best_value

    @property
    def installed_version(self) -> str | None:
        return short_version(self._installed_raw)

    @property
    def latest_version(self) -> str | None:
        manifest = self._coordinator.data or {}
        latest = short_version(manifest.get("Version"))
        if latest is None:
            # Manifest unreachable: reporting None would make HA render
            # this as "update available" against a null version. Echo
            # the installed one instead, i.e. "nothing known to update".
            return self.installed_version
        return latest

    # -- presentation --------------------------------------------------

    @property
    def release_url(self) -> str | None:
        manifest = self._coordinator.data or {}
        return manifest.get("GenericUpdatePageUrl") or "https://duplicati.com/download"

    @property
    def release_summary(self) -> str | None:
        manifest = self._coordinator.data or {}
        summary = manifest.get("ChangeInfo") or manifest.get("Displayname")
        if not summary:
            return None
        return str(summary)[:UPDATE_SUMMARY_MAX_CHARS]

    @property
    def extra_state_attributes(self) -> dict:
        manifest = self._coordinator.data or {}
        return {
            "server_id": self._server_id,
            # Full build string, e.g. "2.4.0.0 (2.4.0.0_stable_2026-09-03)".
            "installed_build": self._installed_raw,
            "release_channel": manifest.get("ReleaseType"),
            "release_time": manifest.get("ReleaseTime"),
            "release_name": manifest.get("Displayname"),
        }

    @property
    def available(self) -> bool:
        # Until that server has reported once we have no installed
        # version to show, and an update entity without one is noise.
        return self.installed_version is not None

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=self._entry.title,
            manufacturer="Duplicati Monitor",
            model="Collector",
        )

    # -- lifecycle -----------------------------------------------------

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._coordinator.async_add_listener(self.async_write_ha_state)
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_ANY_UPDATE.format(entry_id=self._entry.entry_id),
                self._handle_report,
            )
        )

    @callback
    def _handle_report(self) -> None:
        """A fresh report may carry a new installed version (e.g. right
        after upgrading Duplicati)."""
        self.async_write_ha_state()
