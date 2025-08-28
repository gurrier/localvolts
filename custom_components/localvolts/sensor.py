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
        # Access the 'exp' dict if present, else fallback to previous behavior
        item = self.coordinator.data.get("exp", self.coordinator.data)
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
        # {{change 1}}
        self._attr_name = "costsFlexUp"
        self._attr_unique_id = f"localvolts_{coordinator.nmi_id}_costsflexup"

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
        # {{change 2}}
        self._attr_name = "earningsFlexUp"
        self._attr_unique_id = f"localvolts_{coordinator.nmi_id}_earningsflexup"

class LocalvoltsDataLagSensor(CoordinatorEntity, SensorEntity):
    """Sensor for monitoring the data lag time in seconds."""

    _attr_native_unit_of_measurement = "s"
    _attr_device_class = SensorDeviceClass.DURATION

    def __init__(self, coordinator: LocalvoltsDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        # {{change 3}}
        self._attr_name = "DataLag"
        self._attr_unique_id = f"localvolts_{coordinator.nmi_id}_datalag"
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
        # {{change 4}}
        self._attr_name = "IntervalEnd"
        self._attr_unique_id = f"localvolts_{coordinator.nmi_id}_intervalend"
        self._attr_should_poll = False

    @property
    def native_value(self):
        """Return the interval end as a datetime object."""
        return self.coordinator.intervalEnd

    @property
    def extra_state_attributes(self):
        """
        Return limited attributes to avoid exceeding size limits.
        
        Only include essential fields to prevent database performance issues.
        """
        attrs: dict[str, Any] = {}
        
        # Only include critical fields that are needed
        if self.coordinator.intervalEnd:
            attrs["intervalEnd"] = self.coordinator.intervalEnd.isoformat()
            
        if self.coordinator.lastUpdate:
            attrs["lastUpdate"] = self.coordinator.lastUpdate.isoformat()
            
        # Only include a few key fields from data, not all of them
        data = getattr(self.coordinator, "data", {})
        critical_fields = ["costsFlexUp", "earningsFlexUp", "demandInterval", "intervalStart"]
        
        for field in critical_fields:
            if field in data:
                value = data[field]
                if hasattr(value, "isoformat"):
                    attrs[field] = value.isoformat()
                else:
                    attrs[field] = value
                    
        return attrs

class LocalvoltsForecastCostsSensor(CoordinatorEntity, SensorEntity):
    """Sensor for monitoring forecasted costsFlexUp for the next 24 hours."""

    _attr_native_unit_of_measurement = "$/kWh"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_name = "Forecasted Costs Flex Up"

    def __init__(self, coordinator: LocalvoltsDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_name = "Forecasted Costs Flex Up"
        self._attr_unique_id = f"{coordinator.nmi_id}_forecast_costs_flex_up"
        self._attr_should_poll = False

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
        attributes = {}
        if self.coordinator.forecast_data:
            # Include all forecast data points as attributes
            forecast_data = []
            for forecast in self.coordinator.forecast_data:
                forecast_entry = {
                    "intervalEnd": forecast["intervalEnd"],
                    "costsFlexUp": round(forecast.get("costsFlexUp", 0) / MONETARY_CONVERSION_FACTOR, 3),
                    "earningsFlexUp": round(forecast.get("earningsFlexUp", 0) / MONETARY_CONVERSION_FACTOR, 3),
                }
                forecast_data.append(forecast_entry)
            attributes["forecast_data"] = forecast_data
            attributes["forecastCount"] = len(self.coordinator.forecast_data)
        return attributes

