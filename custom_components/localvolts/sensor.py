"""Platform for Localvolts sensor integration."""

from __future__ import annotations

import logging
from typing import Any

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
        item = self.coordinator.data
        if item:
            value = item.get(self.data_key)
            if value is not None:
                self._last_value = round(value / MONETARY_CONVERSION_FACTOR, 3)
        return self._last_value

    @property
    def extra_state_attributes(self):
        """Return basic interval attributes (intervalEnd and lastUpdate)."""
        interval_end = self.coordinator.intervalEnd
        last_update = self.coordinator.lastUpdate
        return {
            "intervalEnd": interval_end.isoformat() if interval_end else None,
            "lastUpdate": last_update.isoformat() if last_update else None,
        }


class LocalvoltsCostsFlexUpSensor(LocalvoltsPriceSensor):
    """Sensor for monitoring costsFlexUp."""

    _attr_native_unit_of_measurement = "$/kWh"
    _attr_device_class = SensorDeviceClass.MONETARY

    def __init__(self, coordinator: LocalvoltsDataUpdateCoordinator) -> None:
        super().__init__(coordinator, COSTS_FLEX_UP)
        self._attr_name = COSTS_FLEX_UP
        self._attr_unique_id = f"{coordinator.nmi_id}_{COSTS_FLEX_UP}"

    @property
    def extra_state_attributes(self):
        """Extend base attributes with demandInterval if available."""
        attributes = super().extra_state_attributes
        demand_interval = self.coordinator.data.get("demandInterval")
        if demand_interval is not None:
            attributes["demandInterval"] = demand_interval
        return attributes


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
        interval_end = self.coordinator.intervalEnd
        last_update = self.coordinator.lastUpdate
        return {
            "intervalEnd": interval_end.isoformat() if interval_end else None,
            "lastUpdate": last_update.isoformat() if last_update else None,
        }


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
        """
        Return all available interval fields as attributes.

        This method copies every key/value pair from the coordinator's data dictionary,
        converting any datetime objects to ISO strings for readability.  It then adds
        the `lastUpdate` and `intervalEnd` timestamps (converted to ISO strings) so
        that these are always present.
        """
        attrs: dict[str, Any] = {}
        data = getattr(self.coordinator, "data", {}) or {}
        # Copy all fields from the data record
        for key, value in data.items():
            if hasattr(value, "isoformat"):
                attrs[key] = value.isoformat()
            else:
                attrs[key] = value
        # Ensure lastUpdate and intervalEnd are included as ISO strings
        if getattr(self.coordinator, "lastUpdate", None):
            attrs["lastUpdate"] = self.coordinator.lastUpdate.isoformat()
        if getattr(self.coordinator, "intervalEnd", None):
            attrs["intervalEnd"] = self.coordinator.intervalEnd.isoformat()
        return attrs


class LocalvoltsForecastCostsSensor(LocalvoltsPriceSensor):
    """Sensor for monitoring forecasted costsFlexUp for the next 24 hours."""

    _attr_native_unit_of_measurement = "$/kWh"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_name = "Forecasted Costs Flex Up"
    _attr_unique_id = f"{coordinator.nmi_id}_forecast_costs_flex_up"

    def __init__(self, coordinator: LocalvoltsDataUpdateCoordinator) -> None:
        super().__init__(coordinator, "costsFlexUp")
        self._attr_name = "Forecasted Costs Flex Up"
        self._attr_unique_id = f"{coordinator.nmi_id}_forecast_costs_flex_up"

    @property
    def native_value(self):
        """Return the state of the sensor (scaled monetary value)."""
        if not self.coordinator.forecast_data:
            return None

        # Get the most recent forecast data
        latest_forecast = max(self.coordinator.forecast_data,
                              key=lambda x: x["intervalEnd"])
        value = latest_forecast.get("costsFlexUp")
        if value is not None:
            return round(value / MONETARY_CONVERSION_FACTOR, 3)
        return None

    @property
    def extra_state_attributes(self):
        """Return forecast-specific attributes."""
        attributes = super().extra_state_attributes
        if self.coordinator.forecast_data:
            latest_forecast = max(
                self.coordinator.forecast_data, key=lambda x: x["intervalEnd"])
            attributes["intervalEnd"] = latest_forecast["intervalEnd"]
            attributes["lastUpdate"] = latest_forecast["lastUpdate"]
            attributes["forecastCount"] = len(self.coordinator.forecast_data)
        return attributes

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Localvolts sensors from a config entry."""
    coordinator = hass.data[DOMAIN]['coordinator']

    async_add_entities(
        [
            LocalvoltsCostsFlexUpSensor(coordinator),
            LocalvoltsEarningsFlexUpSensor(coordinator),
            LocalvoltsDataLagSensor(coordinator),
            LocalvoltsIntervalEndSensor(coordinator),
            LocalvoltsForecastCostsSensor(coordinator),  
        ]
    )
