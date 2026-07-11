"""Sensor platform for Duplicati Monitor."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.components import webhook as webhook_component
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfInformation, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo, Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_WEBHOOK_ID, DOMAIN, PARSED_RESULTS, SIGNAL_JOB_UPDATE, SIGNAL_NEW_JOB
from .entity import DuplicatiJobEntity
from .webhook import JobReport

@dataclass(frozen=True, kw_only=True)
class DuplicatiSensorDescription(SensorEntityDescription):
    """Describes one Duplicati job sensor and how to read its value."""

    value_fn: callable = lambda raw: None


def _size_bytes(raw: dict) -> int | None:
    added = raw.get("size_of_added_files") or 0
    modified = raw.get("size_of_modified_files") or 0
    if not added and not modified:
        return None
    return added + modified


SENSOR_TYPES: tuple[DuplicatiSensorDescription, ...] = (
    DuplicatiSensorDescription(
        key="status",
        translation_key="status",
        device_class=SensorDeviceClass.ENUM,
        options=PARSED_RESULTS,
        value_fn=lambda raw: raw.get("parsed_result"),
    ),
    DuplicatiSensorDescription(
        key="last_backup",
        translation_key="last_backup",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda raw: raw.get("end_time"),
    ),
    DuplicatiSensorDescription(
        key="duration",
        translation_key="duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda raw: raw.get("duration_seconds"),
    ),
    DuplicatiSensorDescription(
        key="backup_size",
        translation_key="backup_size",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=_size_bytes,
    ),
    DuplicatiSensorDescription(
        key="examined_files",
        translation_key="examined_files",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:file-search-outline",
        value_fn=lambda raw: raw.get("examined_files"),
    ),
    DuplicatiSensorDescription(
        key="added_files",
        translation_key="added_files",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:file-plus-outline",
        value_fn=lambda raw: raw.get("added_files"),
    ),
    DuplicatiSensorDescription(
        key="modified_files",
        translation_key="modified_files",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:file-edit-outline",
        value_fn=lambda raw: raw.get("modified_files"),
    ),
    DuplicatiSensorDescription(
        key="deleted_files",
        translation_key="deleted_files",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:file-remove-outline",
        value_fn=lambda raw: raw.get("deleted_files"),
    ),
    DuplicatiSensorDescription(
        key="warnings_count",
        translation_key="warnings_count",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:alert-outline",
        entity_category="diagnostic",
        value_fn=lambda raw: raw.get("warnings_count", 0),
    ),
    DuplicatiSensorDescription(
        key="errors_count",
        translation_key="errors_count",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:alert-circle-outline",
        entity_category="diagnostic",
        value_fn=lambda raw: raw.get("errors_count", 0),
    ),
)

class DuplicatiJobSensor(DuplicatiJobEntity, SensorEntity):
    """A single metric for one Duplicati backup job."""

    entity_description: DuplicatiSensorDescription

    def __init__(
        self,
        entry_id: str,
        report: JobReport,
        description: DuplicatiSensorDescription,
    ) -> None:
        super().__init__(entry_id, report)
        self.entity_description = description
        self._attr_unique_id = (
            f"{entry_id}_{report.server_id}_{report.job_id}_{description.key}"
        )
        self._apply(report)

    def _apply(self, report: JobReport) -> None:
        self._report = report
        value = self.entity_description.value_fn(report.raw)
        if self.entity_description.device_class == SensorDeviceClass.TIMESTAMP and value:
            try:
                value = datetime.fromisoformat(value)
                if value.tzinfo is None:
                    value = value.replace(tzinfo=timezone.utc)
            except ValueError:
                value = None
        self._attr_native_value = value
        self._attr_extra_state_attributes = {
            "job_name": report.job_name,
            "job_id": report.job_id,
            "server_id": report.server_id,
        }

    async def async_added_to_hass(self) -> None:
        """Subscribe to updates for this specific job."""
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


class DuplicatiRawPayloadSensor(DuplicatiJobEntity, SensorEntity):
    """Diagnostic sensor exposing the last raw incoming payload.

    Useful for verifying/tuning the native-Duplicati-JSON field mapping
    against your actual Duplicati version - see webhook.py.
    """

    _attr_translation_key = "raw_payload"
    _attr_entity_category = "diagnostic"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_registry_enabled_default = False

    def __init__(self, entry_id: str, report: JobReport) -> None:
        super().__init__(entry_id, report)
        self._attr_unique_id = f"{entry_id}_{report.server_id}_{report.job_id}_raw"
        self._apply(report)

    def _apply(self, report: JobReport) -> None:
        self._report = report
        self._attr_native_value = datetime.now(timezone.utc)
        self._attr_extra_state_attributes = {
            "source_payload": json.dumps(report.source_payload)[:4000]
            if report.source_payload
            else None,
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


class DuplicatiWebhookInfoSensor(Entity, SensorEntity):
    """Always-present sensor showing this collector's webhook URL.

    Lives on its own "hub" device (one per config entry), separate
    from the per-server devices created once jobs start reporting in.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "webhook_info"
    _attr_entity_category = "diagnostic"
    _attr_icon = "mdi:webhook"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._entry = entry
        webhook_id = entry.data[CONF_WEBHOOK_ID]
        self._attr_unique_id = f"{entry.entry_id}_webhook_info"
        self._attr_native_value = webhook_id
        self._attr_extra_state_attributes = {
            "webhook_url": webhook_component.async_generate_url(hass, webhook_id),
        }

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=self._entry.title,
            manufacturer="Duplicati Monitor",
            model="Collector",
        )


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up sensors for existing jobs and listen for new ones."""
    store = hass.data[DOMAIN][entry.entry_id]

    async_add_entities([DuplicatiWebhookInfoSensor(hass, entry)])

    def _add_job(report: JobReport) -> None:
        async_add_entities(
            [
                DuplicatiJobSensor(entry.entry_id, report, description)
                for description in SENSOR_TYPES
            ]
            + [DuplicatiRawPayloadSensor(entry.entry_id, report)]
        )

    for report in store["jobs"].values():
        _add_job(report)

    entry.async_on_unload(
        async_dispatcher_connect(
            hass, SIGNAL_NEW_JOB.format(entry_id=entry.entry_id), _add_job
        )
    )
