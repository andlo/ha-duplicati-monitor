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
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.network import NoURLAvailableError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import (
    CONF_WEBHOOK_ID,
    DOMAIN,
    PARSED_RESULTS,
    PROBLEM_RESULTS,
    SIGNAL_ANY_UPDATE,
    SIGNAL_JOB_UPDATE,
    SIGNAL_NEW_JOB,
)
from .entity import DuplicatiJobEntity
from .report import JobReport, compute_next_expected


@dataclass(frozen=True, kw_only=True)
class DuplicatiSensorDescription(SensorEntityDescription):
    """Describes one Duplicati job sensor and how to read its value."""

    value_fn: callable = lambda raw: None
    include_log: bool = False
    icon_fn: callable | None = None


def _size_bytes(raw: dict) -> int | None:
    added = raw.get("size_of_added_files") or 0
    modified = raw.get("size_of_modified_files") or 0
    if not added and not modified:
        return None
    return added + modified


_STATUS_ICONS = {
    "Success": "mdi:check-circle",
    "Warning": "mdi:alert",
    "Error": "mdi:alert-circle",
    "Fatal": "mdi:close-circle",
    "Unknown": "mdi:help-circle",
}


def _status_icon(raw: dict) -> str:
    return _STATUS_ICONS.get(raw.get("parsed_result"), "mdi:backup-restore")


SENSOR_TYPES: tuple[DuplicatiSensorDescription, ...] = (
    DuplicatiSensorDescription(
        key="status",
        translation_key="status",
        device_class=SensorDeviceClass.ENUM,
        options=PARSED_RESULTS,
        value_fn=lambda raw: raw.get("parsed_result"),
        icon_fn=_status_icon,
        include_log=True,
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
        suggested_unit_of_measurement=UnitOfInformation.GIBIBYTES,
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
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda raw: raw.get("warnings_count", 0),
    ),
    DuplicatiSensorDescription(
        key="errors_count",
        translation_key="errors_count",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:alert-circle-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda raw: raw.get("errors_count", 0),
    ),
    DuplicatiSensorDescription(
        key="total_backup_size",
        translation_key="total_backup_size",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIBIBYTES,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:database",
        value_fn=lambda raw: raw.get("total_size"),
    ),
    DuplicatiSensorDescription(
        key="versions",
        translation_key="versions",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:file-multiple-outline",
        value_fn=lambda raw: raw.get("versions"),
    ),
    DuplicatiSensorDescription(
        key="uploaded_bytes",
        translation_key="uploaded_bytes",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIBIBYTES,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:cloud-upload-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda raw: raw.get("bytes_uploaded"),
    ),
    DuplicatiSensorDescription(
        key="destination_free_space",
        translation_key="destination_free_space",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIBIBYTES,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:harddisk",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda raw: raw.get("destination_free_space"),
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
        if self.entity_description.icon_fn:
            self._attr_icon = self.entity_description.icon_fn(report.raw)
        attributes = {
            "job_name": report.job_name,
            "job_id": report.job_id,
            "server_id": report.server_id,
        }
        if self.entity_description.include_log:
            log_lines = report.raw.get("log_lines")
            if isinstance(log_lines, list):
                attributes["log_lines"] = log_lines[-50:]
        self._attr_extra_state_attributes = attributes

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
    against your actual Duplicati version - see report.py. Disabled by
    default; enable it via Settings > Devices & Services > the job's
    device > this entity > the gear icon. View its content via the
    entity's "Attributes" section in its more-info dialog, or
    Developer Tools > States.
    """

    _attr_translation_key = "raw_payload"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
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
            "source_payload": json.dumps(report.source_payload, indent=2)[:4000]
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


class DuplicatiHistorySensor(DuplicatiJobEntity, SensorEntity):
    """Exposes a bounded run history for this job, for a dashboard log
    view (e.g. a markdown card templating over the `runs` attribute -
    see docs/dashboard.yaml). State is simply how many runs are stored.
    """

    _attr_translation_key = "history"
    _attr_icon = "mdi:history"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry_id: str, report: JobReport, runs: list) -> None:
        super().__init__(entry_id, report)
        self._attr_unique_id = f"{entry_id}_{report.server_id}_{report.job_id}_history"
        self._apply(report, runs)

    def _apply(self, report: JobReport, runs: list) -> None:
        self._report = report
        self._attr_native_value = len(runs)
        self._attr_extra_state_attributes = {"runs": runs}

    async def async_added_to_hass(self) -> None:
        signal = SIGNAL_JOB_UPDATE.format(
            entry_id=self._entry_id, server_id=self._server_id, job_id=self._job_id
        )
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal, self._handle_update)
        )

    @callback
    def _handle_update(self, report: JobReport) -> None:
        runs = self.hass.data[DOMAIN][self._entry_id]["history"].get(
            (self._server_id, self._job_id), []
        )
        self._apply(report, runs)
        self.async_write_ha_state()


class DuplicatiNextExpectedSensor(DuplicatiJobEntity, SensorEntity):
    """Estimated next-run time, inferred from the interval between
    recent runs (Duplicati doesn't expose its own schedule to us).
    `typical_interval_seconds` attribute holds the interval used.
    Needs at least 2 runs to estimate anything - state is unknown
    until then. Pair with binary_sensor.*_overdue for alerting.
    """

    _attr_translation_key = "next_expected"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, entry_id: str, report: JobReport, runs: list) -> None:
        super().__init__(entry_id, report)
        self._attr_unique_id = f"{entry_id}_{report.server_id}_{report.job_id}_next_expected"
        self._apply(report, runs)

    def _apply(self, report: JobReport, runs: list) -> None:
        self._report = report
        next_expected, interval = compute_next_expected(runs)
        if next_expected:
            try:
                self._attr_native_value = datetime.fromisoformat(next_expected)
            except ValueError:
                self._attr_native_value = None
        else:
            self._attr_native_value = None
        self._attr_extra_state_attributes = {
            "typical_interval_seconds": interval,
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
        runs = self.hass.data[DOMAIN][self._entry_id]["history"].get(
            (self._server_id, self._job_id), []
        )
        self._apply(report, runs)
        self.async_write_ha_state()


class DuplicatiWebhookInfoSensor(SensorEntity):
    """Always-present sensor showing this collector's webhook URL.

    Lives on its own "hub" device (one per config entry), separate
    from the per-server devices created once jobs start reporting in.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "webhook_info"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:webhook"

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._webhook_id = entry.data[CONF_WEBHOOK_ID]
        self._attr_unique_id = f"{entry.entry_id}_webhook_info"
        self._attr_native_value = self._webhook_id

    @property
    def extra_state_attributes(self) -> dict:
        """Computed lazily so it reflects Settings > System > Network
        even if that wasn't configured yet when this entity was created."""
        return {"webhook_url": self._webhook_url()}

    def _webhook_url(self) -> str:
        try:
            return webhook_component.async_generate_url(self.hass, self._webhook_id)
        except NoURLAvailableError:
            path = webhook_component.async_generate_path(self._webhook_id)
            return (
                f"{path} (Home Assistant doesn't have an internal/external "
                "URL configured yet - set one under Settings > System > "
                "Network to see the full address here; until then, prefix "
                "this path with your own HA address)"
            )

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=self._entry.title,
            manufacturer="Duplicati Monitor",
            model="Collector",
        )


class DuplicatiSummarySensor(SensorEntity):
    """Aggregate count across all currently known jobs on this
    collector (e.g. "how many are OK right now") - lives on the hub
    device, recomputed on every webhook call. Meant to drive simple
    "X of Y" style dashboard tiles without any per-job dashboard
    editing - see docs/dashboard.yaml.
    """

    _attr_has_entity_name = False
    _attr_should_poll = False
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self, entry: ConfigEntry, key: str, name: str, icon: str, predicate
    ) -> None:
        self._entry = entry
        self._key = key
        self._predicate = predicate
        self._attr_unique_id = f"{entry.entry_id}_summary2_{key}"
        # Explicit entity_id: has_entity_name=False only affects the
        # displayed name, NOT entity_id generation - HA still folds the
        # device (collector) name into an auto-generated entity_id
        # otherwise, making it depend on what the user typed as the
        # integration's name. Setting it directly keeps it fixed.
        self.entity_id = f"sensor.duplicati_{key}"
        self._attr_name = name
        self._attr_icon = icon
        self._apply()

    def _apply(self) -> None:
        jobs = self.hass.data[DOMAIN][self._entry.entry_id]["jobs"] if self.hass else {}
        self._attr_native_value = sum(
            1 for report in jobs.values() if self._predicate(report.raw)
        )

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=self._entry.title,
            manufacturer="Duplicati Monitor",
            model="Collector",
        )

    async def async_added_to_hass(self) -> None:
        self._apply()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_ANY_UPDATE.format(entry_id=self._entry.entry_id),
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        self._apply()
        self.async_write_ha_state()


class DuplicatiOkPercentSensor(SensorEntity):
    """Percentage of known jobs currently OK (0-100) - meant to drive
    a native `gauge` dashboard card as a donut-like "health ring",
    closer to duplicati-monitoring.com's overview without adding
    another HACS card. See docs/dashboard.yaml.
    """

    _attr_has_entity_name = False
    _attr_should_poll = False
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:percent-circle"

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_summary2_health"
        self.entity_id = "sensor.duplicati_health"
        self._attr_name = "Duplicati Health %"
        self._apply()

    def _apply(self) -> None:
        jobs = self.hass.data[DOMAIN][self._entry.entry_id]["jobs"] if self.hass else {}
        if not jobs:
            self._attr_native_value = 100
            return
        ok = sum(1 for r in jobs.values() if r.raw.get("parsed_result") == "Success")
        self._attr_native_value = round(100 * ok / len(jobs))

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=self._entry.title,
            manufacturer="Duplicati Monitor",
            model="Collector",
        )

    async def async_added_to_hass(self) -> None:
        self._apply()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_ANY_UPDATE.format(entry_id=self._entry.entry_id),
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        self._apply()
        self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up sensors for existing jobs and listen for new ones."""
    store = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        [
            DuplicatiWebhookInfoSensor(entry),
            DuplicatiSummarySensor(
                entry, "total", "Duplicati Total", "mdi:counter", lambda raw: True
            ),
            DuplicatiSummarySensor(
                entry,
                "ok",
                "Duplicati OK",
                "mdi:check-circle",
                lambda raw: raw.get("parsed_result") == "Success",
            ),
            DuplicatiSummarySensor(
                entry,
                "problem",
                "Duplicati Problem",
                "mdi:alert-circle",
                lambda raw: raw.get("parsed_result") in PROBLEM_RESULTS,
            ),
            DuplicatiOkPercentSensor(entry),
        ]
    )

    @callback
    def _add_job(report: JobReport) -> None:
        runs = store["history"].get(report.unique_key, [])
        async_add_entities(
            [
                DuplicatiJobSensor(entry.entry_id, report, description)
                for description in SENSOR_TYPES
            ]
            + [
                DuplicatiRawPayloadSensor(entry.entry_id, report),
                DuplicatiHistorySensor(entry.entry_id, report, runs),
                DuplicatiNextExpectedSensor(entry.entry_id, report, runs),
            ]
        )

    for report in store["jobs"].values():
        _add_job(report)

    entry.async_on_unload(
        async_dispatcher_connect(
            hass, SIGNAL_NEW_JOB.format(entry_id=entry.entry_id), _add_job
        )
    )
