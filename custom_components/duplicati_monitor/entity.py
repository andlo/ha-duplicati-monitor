"""Shared entity base classes for Duplicati Monitor."""
from __future__ import annotations

from homeassistant.helpers.entity import DeviceInfo, Entity

from .const import DOMAIN
from .webhook import JobReport


class DuplicatiJobEntity(Entity):
    """Base class for entities tied to one (server_id, job_id) job."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry_id: str, report: JobReport) -> None:
        self._entry_id = entry_id
        self._server_id = report.server_id
        self._job_id = report.job_id
        self._report = report

    @property
    def device_info(self) -> DeviceInfo:
        """Group all jobs from the same server under one device."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry_id}_{self._server_id}")},
            name=self._report.server_name,
            manufacturer="Duplicati",
            model="Backup server",
        )
