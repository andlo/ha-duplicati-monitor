"""Shared entity base classes for Duplicati Monitor."""
from __future__ import annotations

from homeassistant.helpers.entity import DeviceInfo, Entity

from .const import DOMAIN
from .report import JobReport


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
        """One device per (server, job) - not per server.

        v0.1.0 changed this from grouping all of a server's jobs under
        one device: with several jobs per server that made a device
        page an unsorted wall of entities. Job name is now part of the
        device name, so entity names below stay short ("Status", not
        "TEST status").
        """
        return DeviceInfo(
            identifiers={
                (DOMAIN, f"{self._entry_id}_{self._server_id}_{self._job_id}")
            },
            name=f"{self._report.server_name} - {self._report.job_name}",
            manufacturer="Duplicati",
            model="Backup job",
        )
