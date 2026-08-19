"""Platform for Localvolts sensor integration. August 2025"""

from __future__ import annotations

import logging
from typing import Any
from datetime import datetime, timedelta

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import LocalvoltsDataUpdateCoordinator

MONETARY_CONVERSION_FACTOR = 100

COSTS_FLEX_UP = "costsFlexUp"
EARNINGS_FLEX_UP = "earningsFlexUp"

_LOGGER = logging.getLogger(__name__)


def _interval_attrs(coordinator: LocalvoltsDataUpdateCoordinator) -> dict[str, Any]:
    """Return the common intervalEnd/lastUpdate attribute pair."""
    interval_end = coordinator.intervalEnd
    last_update = coordinator.lastUpdate
    return {
        "intervalEnd": interval_end.isoformat() if interval_end else None,
        "lastUpdate": last_update.isoformat() if last_update else None,
    }


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Localvolts sensors from a config entry."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]

    async_add_entities(
        [
            LocalvoltsCostsFlexUpSensor(coordinator),
            LocalvoltsEarningsFlexUpSensor(coordinator),
            LocalvoltsDataLagSensor(coordinator),
            LocalvoltsIntervalEndSensor(coordinator),
            LocalvoltsForecastCostsSensor(coordinator),
        ]
    )


class LocalvoltsSensor(CoordinatorEntity, SensorEntity):
    """Representation of a generic Localvolts sensor."""

    def __init__(self, coordinator: LocalvoltsDataUpdateCoordinator, data_key: str) -> None:
        super().__init__(coordinator)
        self.data_key = data_key
        self._attr_should_poll = False
        self._last_value = None

class LocalvoltsPriceSensor(LocalvoltsSensor):
    """LocalVolts Price Sensor"""

    @property
    def native_value(self):
        """Return the state of the sensor (scaled monetary value)."""
        # coordinator.data can be None before the first successful refresh
        # (see gurrier/localvolts#21 - this crashed with the same shape).
        coordinator_data = self.coordinator.data or {}
        item = coordinator_data.get("exp", coordinator_data)
        if item:
            value = item.get(self.data_key)
            if value is not None:
                self._last_value = round(value / MONETARY_CONVERSION_FACTOR, 3)
        return self._last_value

    @property
    def extra_state_attributes(self):
        """Return basic interval attributes (intervalEnd and lastUpdate)."""
        return _interval_attrs(self.coordinator)

class LocalvoltsCostsFlexUpSensor(LocalvoltsPriceSensor):
    """Sensor for monitoring costsFlexUp."""

    _attr_native_unit_of_measurement = "$/kWh"
    _attr_device_class = SensorDeviceClass.MONETARY

    def __init__(self, coordinator: LocalvoltsDataUpdateCoordinator) -> None:
        super().__init__(coordinator, COSTS_FLEX_UP)
        self._attr_name = COSTS_FLEX_UP
        self._attr_unique_id = f"{coordinator.nmi_id}_{COSTS_FLEX_UP}"

class LocalvoltsEarningsFlexUpSensor(LocalvoltsPriceSensor):
    """Sensor for monitoring earningsFlexUp."""

    _attr_native_unit_of_measurement = "$/kWh"
    _attr_device_class = SensorDeviceClass.MONETARY

    def __init__(self, coordinator: LocalvoltsDataUpdateCoordinator) -> None:
        super().__init__(coordinator, EARNINGS_FLEX_UP)
        self._attr_name = EARNINGS_FLEX_UP
        self._attr_unique_id = f"{coordinator.nmi_id}_{EARNINGS_FLEX_UP}"

class LocalvoltsDataLagSensor(CoordinatorEntity, SensorEntity):
    """Sensor for monitoring the data lag time in seconds."""

    _attr_native_unit_of_measurement = "s"
    _attr_device_class = SensorDeviceClass.DURATION

    def __init__(self, coordinator: LocalvoltsDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_name = "DataLag"
        self._attr_unique_id = f"{coordinator.nmi_id}_data_lag"
        self._attr_should_poll = False

    @property
    def native_value(self):
        """Return the duration since the interval started, in seconds."""
        time_past_start = self.coordinator.time_past_start
        return time_past_start.total_seconds() if time_past_start else None

    @property
    def extra_state_attributes(self):
        """Return basic interval attributes for data lag."""
        return _interval_attrs(self.coordinator)

class LocalvoltsIntervalEndSensor(CoordinatorEntity, SensorEntity):
    """Sensor for monitoring the end time of the latest interval."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: LocalvoltsDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_name = "IntervalEnd"
        self._attr_unique_id = f"{coordinator.nmi_id}_interval_end"
        self._attr_should_poll = False
        
    @property
    def native_value(self):
        """Return the interval end as a datetime object."""
        return self.coordinator.intervalEnd

    @property
    def extra_state_attributes(self):
        """Return every field the API returned for the current interval.

        Unlike the forecast sensor's list of ~287 intervals, this is a
        single interval's worth of scalar fields, so the payload stays
        small - no need for an allowlist.
        """
        data = getattr(self.coordinator, "data", {}) or {}
        data = data.get("exp", data) or {}
        return dict(data)

class LocalvoltsForecastCostsSensor(CoordinatorEntity, SensorEntity):
    """Sensor for monitoring forecasted costsFlexUp for the next 24 hours."""

    _attr_native_unit_of_measurement = "c/kWh"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_name = "Forecasted Costs Flex Up"

    def __init__(self, coordinator: LocalvoltsDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_name = "Forecasted Costs Flex Up"
        self._attr_unique_id = f"{coordinator.nmi_id}_forecast_costs_flex_up"
        self._attr_should_poll = False

    @property
    def native_value(self):
        """Return the state of the sensor (cents per kWh)."""
        if not self.coordinator.forecast_data:
            return None

        # Get the next upcoming forecast interval (soonest intervalEnd)
        next_forecast = min(self.coordinator.forecast_data,
                            key=lambda x: x["intervalEnd"])
        value = next_forecast.get("costsFlexUp")
        if value is not None:
            return round(value, 3)
        return None

    @property
    def extra_state_attributes(self):
        attributes = {}
        forecast = []
        if self.coordinator.forecast_data:
            for fcast in self.coordinator.forecast_data:
                try:
                    interval_end_dt = datetime.fromisoformat(fcast["intervalEnd"].replace("Z", "+00:00"))
                    duration = int(fcast.get("intervalDuration", 5))
                    start_time_dt = interval_end_dt - timedelta(minutes=duration)
                    # Carry through every field the API returned for this interval
                    # (not just a hand-picked subset), so nothing the API exposes
                    # is silently dropped. duration/start_time/end_time are added
                    # as convenience fields on top of the raw data.
                    entry = dict(fcast)
                    entry["duration"] = duration
                    entry["start_time"] = start_time_dt.isoformat()
                    entry["end_time"] = interval_end_dt.isoformat()
                    if "earningsFlexUp" in entry:
                        entry["earningsFlexUp"] = round(entry["earningsFlexUp"], 5)
                    if "costsFlexUp" in entry:
                        entry["costsFlexUp"] = round(entry["costsFlexUp"], 5)
                    forecast.append(entry)
                except Exception as err:
                    _LOGGER.debug("Skipping unparsable forecast entry %s: %s", fcast, err)
                    continue
            attributes["forecast"] = forecast
            attributes["forecastcount"] = len(forecast)

        return attributes


