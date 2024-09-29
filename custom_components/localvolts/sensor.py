"""Platform for Localvolts sensor integration."""

from __future__ import annotations

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DOMAIN
from .coordinator import LocalvoltsDataUpdateCoordinator

MONETARY_CONVERSION_FACTOR = 100

COSTS_FLEX_UP = "costsFlexUp"
EARNINGS_FLEX_UP = "earningsFlexUp"

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(
    hass: HomeAssistant,
    config: dict,
    async_add_entities: AddEntitiesCallback,
    discovery_info=None,
) -> None:
    """Set up Localvolts sensors."""

    coordinator = hass.data[DOMAIN]['coordinator']

    async_add_entities(
        [
            LocalvoltsCostsFlexUpSensor(coordinator),
            LocalvoltsEarningsFlexUpSensor(coordinator),
            LocalvoltsDataLagSensor(coordinator),  # Updated sensor name
        ]
    )


class LocalvoltsSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Localvolts Sensor."""

    def __init__(self, coordinator: LocalvoltsDataUpdateCoordinator, data_key: str):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.data_key = data_key
        self._attr_should_poll = False  # DataUpdateCoordinator handles updates
        self._last_value = None  # Store the last known value

    @property
    def native_value(self):
        """Return the state of the sensor."""
        item = self.coordinator.data
        if item:
            value = item.get(self.data_key)
            if value is not None:
                self._last_value = round(value / MONETARY_CONVERSION_FACTOR, 3)
        # Return the last known value even if item is None or value is None
        return self._last_value

    @property
    def extra_state_attributes(self):
        """Return additional state attributes."""
        interval_end = self.coordinator.intervalEnd
        last_update = self.coordinator.lastUpdate

        return {
            "intervalEnd": interval_end.isoformat() if interval_end else None,
            "lastUpdate": last_update.isoformat() if last_update else None,
        }


class LocalvoltsCostsFlexUpSensor(LocalvoltsSensor):
    """Sensor for monitoring costsFlexUp."""

    _attr_native_unit_of_measurement = "$/kWh"
    _attr_device_class = SensorDeviceClass.MONETARY

    def __init__(self, coordinator):
        """Initialize the costsFlexUp sensor."""
        super().__init__(coordinator, COSTS_FLEX_UP)
        self._attr_name = COSTS_FLEX_UP
        self._attr_unique_id = f"{coordinator.nmi_id}_{COSTS_FLEX_UP}"


class LocalvoltsEarningsFlexUpSensor(LocalvoltsSensor):
    """Sensor for monitoring earningsFlexUp."""

    _attr_native_unit_of_measurement = "$/kWh"
    _attr_device_class = SensorDeviceClass.MONETARY

    def __init__(self, coordinator):
        """Initialize the earningsFlexUp sensor."""
        super().__init__(coordinator, EARNINGS_FLEX_UP)
        self._attr_name = EARNINGS_FLEX_UP
        self._attr_unique_id = f"{coordinator.nmi_id}_{EARNINGS_FLEX_UP}"


class LocalvoltsDataLagSensor(CoordinatorEntity, SensorEntity):
    """Sensor for monitoring the data lag time."""

    _attr_native_unit_of_measurement = "s"  # Seconds
    _attr_device_class = SensorDeviceClass.DURATION

    def __init__(self, coordinator):
        """Initialize the DataLag sensor."""
        super().__init__(coordinator)
        self._attr_name = "DataLag"  # Updated sensor name
        self._attr_unique_id = f"{coordinator.nmi_id}_data_lag"
        self._attr_should_poll = False

    @property
    def native_value(self):
        """Return the state of the sensor."""
        time_past_start = self.coordinator.time_past_start
        if time_past_start is not None:
            return time_past_start.total_seconds()
        return None

    @property
    def extra_state_attributes(self):
        """Return additional state attributes."""
        interval_end = self.coordinator.intervalEnd
        last_update = self.coordinator.lastUpdate

        return {
            "intervalEnd": interval_end.isoformat() if interval_end else None,
            "lastUpdate": last_update.isoformat() if last_update else None,
        }
