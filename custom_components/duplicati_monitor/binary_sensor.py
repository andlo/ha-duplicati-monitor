"""Binary sensor platform for Duplicati Monitor."""
from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import DOMAIN, PROBLEM_RESULTS, SIGNAL_JOB_UPDATE, SIGNAL_NEW_JOB
from .entity import DuplicatiJobEntity
from .report import JobReport, compute_next_expected

# How often to re-check "did the expected backup time pass without a
# new report arriving" - this can't be purely event-driven, since the
# passage of time alone (no new webhook call) is what triggers it.
OVERDUE_CHECK_INTERVAL = timedelta(minutes=15)

# Tolerate this much extra time beyond the typical interval before
# flagging overdue, to absorb normal jitter (a backup starting a few
# minutes late shouldn't trigger an alert).
OVERDUE_GRACE_FACTOR = 0.5


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


class DuplicatiOverdueBinarySensor(DuplicatiJobEntity, BinarySensorEntity):
    """On when this job hasn't reported in longer than its typical
    interval (+ grace) - build an automation off this to get alerted
    when a backup silently stops running. Needs at least 2 past runs
    before it can estimate a schedule; stays off until then.
    """

    _attr_translation_key = "overdue"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry_id: str, report: JobReport, runs: list) -> None:
        super().__init__(entry_id, report)
        self._attr_unique_id = f"{entry_id}_{report.server_id}_{report.job_id}_overdue"
        self._runs = runs
        self._recompute()

    def _recompute(self) -> None:
        next_expected_iso, interval = compute_next_expected(self._runs)
        if not next_expected_iso or not interval:
            self._attr_is_on = False
            self._attr_extra_state_attributes = {"next_expected": None}
            return
        next_expected = datetime.fromisoformat(next_expected_iso)
        grace = timedelta(seconds=interval * OVERDUE_GRACE_FACTOR)
        self._attr_is_on = dt_util.utcnow() > (next_expected + grace)
        self._attr_extra_state_attributes = {"next_expected": next_expected_iso}

    async def async_added_to_hass(self) -> None:
        signal = SIGNAL_JOB_UPDATE.format(
            entry_id=self._entry_id, server_id=self._server_id, job_id=self._job_id
        )
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal, self._handle_update)
        )
        self.async_on_remove(
            async_track_time_interval(
                self.hass, self._handle_time_tick, OVERDUE_CHECK_INTERVAL
            )
        )

    @callback
    def _handle_update(self, report: JobReport) -> None:
        self._report = report
        self._runs = self.hass.data[DOMAIN][self._entry_id]["history"].get(
            (self._server_id, self._job_id), []
        )
        self._recompute()
        self.async_write_ha_state()

    @callback
    def _handle_time_tick(self, now) -> None:
        self._recompute()
        self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up problem binary sensors for existing jobs and listen for new ones."""
    store = hass.data[DOMAIN][entry.entry_id]

    @callback
    def _add_job(report: JobReport) -> None:
        runs = store["history"].get(report.unique_key, [])
        async_add_entities(
            [
                DuplicatiProblemBinarySensor(entry.entry_id, report),
                DuplicatiOverdueBinarySensor(entry.entry_id, report, runs),
            ]
        )

    for report in store["jobs"].values():
        _add_job(report)

    entry.async_on_unload(
        async_dispatcher_connect(
            hass, SIGNAL_NEW_JOB.format(entry_id=entry.entry_id), _add_job
        )
    )
