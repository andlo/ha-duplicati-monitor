"""Binary sensor platform for Duplicati Monitor."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, PROBLEM_RESULTS, SIGNAL_JOB_UPDATE, SIGNAL_NEW_JOB
from .entity import DuplicatiJobEntity
from .report import JobReport


class DuplicatiProblemBinarySensor(DuplicatiJobEntity, BinarySensorEntity):
    """Indicates whether the last run of a job ended in error."""

    _attr_translation_key = "problem"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, entry_id: str, report: JobReport) -> None:
        super().__init__(entry_id, report)
        self._attr_unique_id = f"{entry_id}_{report.server_id}_{report.job_id}_problem"
        self._apply(report)

    def _apply(self, report: JobReport) -> None:
        self._report = report
        self._attr_is_on = report.raw.get("parsed_result") in PROBLEM_RESULTS
        self._attr_extra_state_attributes = {
            "job_name": report.job_name,
            "message": report.raw.get("message"),
        }

    async def async_added_to_hass(self) -> None:
        signal = SIGNAL_JOB_UPDATE.format(
            entry_id=self._entry_id, server_id=self._server_id, job_id=self._job_id
        )
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal, self._handle_update)
        )

    @callback
    def _handle_update(self, report: JobReport) -> None:
        self._apply(report)
        self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up problem binary sensors for existing jobs and listen for new ones."""
    store = hass.data[DOMAIN][entry.entry_id]

    def _add_job(report: JobReport) -> None:
        async_add_entities([DuplicatiProblemBinarySensor(entry.entry_id, report)])

    for report in store["jobs"].values():
        _add_job(report)

    entry.async_on_unload(
        async_dispatcher_connect(
            hass, SIGNAL_NEW_JOB.format(entry_id=entry.entry_id), _add_job
        )
    )
