"""Platform for localvolts integration."""

from __future__ import annotations

import requests
from requests.exceptions import RequestException
import datetime
import threading
from homeassistant.util import Throttle
from dateutil import parser, tz
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

import logging

DOMAIN = "localvolts"
_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = datetime.timedelta(seconds=10)  # Update every 10 seconds

MONETARY_CONVERSION_FACTOR = 100


def setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the sensor platform."""

    # Retrieve configuration data from the main component
    api_key = hass.data[DOMAIN]["api_key"]
    partner_id = hass.data[DOMAIN]["partner_id"]
    nmi_id = hass.data[DOMAIN]["nmi_id"]

    # Optional: Perform some checks or preparations with the configuration data
    if not all([api_key, partner_id, nmi_id]):
        _LOGGER.error("API Key or Partner ID or NMI is missing.")
        return

    # Create a shared data fetcher
    data_fetcher = LocalvoltsData(api_key, partner_id, nmi_id)

    # Add both sensor entities to Home Assistant
    add_entities(
        [
            LocalvoltsCostsFlexUpSensor(data_fetcher),
            LocalvoltsEarningsFlexUpSensor(data_fetcher),
        ]
    )


class LocalvoltsData:
    """Class for fetching and storing data from Localvolts API."""

    def __init__(self, api_key, partner_id, nmi_id):
        """Initialize the data fetcher."""
        self.api_key = api_key
        self.partner_id = partner_id
        self.nmi_id = nmi_id
        self.intervalEnd = None  # Store as datetime object
        self.lastUpdate = None  # Store as datetime object
        self.time_past_start = datetime.timedelta(0)  # Initialize to 0 seconds
        self.data = {}
        self._lock = threading.Lock()

    @Throttle(SCAN_INTERVAL)
    def update(self) -> None:
        """Fetch data from the Localvolts API."""
        with self._lock:
            # Get the current time in UTC
            current_utc_time = datetime.datetime.now(datetime.timezone.utc)

            # Calculate 'from_time' and 'to_time' as datetime objects
            from_time = current_utc_time
            to_time = current_utc_time + datetime.timedelta(minutes=5)

            _LOGGER.debug("intervalEnd = %s", self.intervalEnd)
            _LOGGER.debug("lastUpdate = %s", self.lastUpdate)
            _LOGGER.debug("from_time = %s", from_time)
            _LOGGER.debug("to_time = %s", to_time)

            # Determine if we need to fetch new data
            if (self.intervalEnd is None) or (current_utc_time > self.intervalEnd):
                # First time or new 5-minute interval
                _LOGGER.debug("New interval detected. Retrieving the latest data.")
                # Format times for the API request
                from_time_str = from_time.strftime("%Y-%m-%dT%H:%M:%SZ")
                to_time_str = to_time.strftime("%Y-%m-%dT%H:%M:%SZ")

                url = (
                    f"https://api.localvolts.com/v1/customer/interval?"
                    f"NMI={self.nmi_id}&from={from_time_str}&to={to_time_str}"
                )

                headers = {
                    "Authorization": f"apikey {self.api_key}",
                    "partner": self.partner_id,
                }

                try:
                    response = requests.get(url, headers=headers)
                    response.raise_for_status()
                except RequestException as e:
                    _LOGGER.error("Failed to fetch data from Localvolts API: %s", str(e))
                    return

                if response.status_code == 200:
                    # Process data
                    data = response.json()

                    for item in data:
                        # Check the 'quality' field
                        if item.get("quality", "").lower() == "exp":
                            # Parse the ISO 8601 strings with timezone information
                            interval_end = parser.isoparse(item["intervalEnd"])
                            last_update_time = parser.isoparse(item["lastUpdate"])

                            # Ensure both datetimes are timezone-aware
                            if interval_end.tzinfo is None:
                                interval_end = interval_end.replace(tzinfo=tz.UTC)
                            if last_update_time.tzinfo is None:
                                last_update_time = last_update_time.replace(
                                    tzinfo=tz.UTC
                                )

                            # Update instance variables
                            self.intervalEnd = interval_end
                            self.lastUpdate = last_update_time
                            self.data = item  # Store the entire item

                            # Calculate the interval start
                            interval_start = interval_end - datetime.timedelta(minutes=5)

                            # Calculate the time difference
                            self.time_past_start = last_update_time - interval_start
                            _LOGGER.debug(
                                "Data updated: intervalEnd=%s, lastUpdate=%s",
                                self.intervalEnd,
                                self.lastUpdate,
                            )
                            break  # Stop after finding the first 'exp' quality item
                        else:
                            _LOGGER.debug(
                                "Skipping non-'exp' quality data. Only 'exp' is processed."
                            )
                else:
                    _LOGGER.error(
                        "Failed to fetch data from Localvolts API, status code: %s",
                        response.status_code,
                    )
            else:
                _LOGGER.debug("Data did not change. Still in the same interval.")


class LocalvoltsSensor(SensorEntity):
    """Representation of a Localvolts Sensor."""

    def __init__(self, data_fetcher, data_key):
        """Initialize the sensor."""
        self.data_fetcher = data_fetcher
        self.data_key = data_key
        self._attr_native_value = None
        self.intervalEnd = None  # Store as datetime object
        self.lastUpdate = None  # Store as datetime object
        self.time_past_start = datetime.timedelta(0)  # Initialize to 0 seconds

    def update(self) -> None:
        """Fetch new state data for the sensor."""
        self.data_fetcher.update()
        if self.data_fetcher.data:
            self.intervalEnd = self.data_fetcher.intervalEnd
            self.lastUpdate = self.data_fetcher.lastUpdate
            self.time_past_start = self.data_fetcher.time_past_start
            self.process_data(self.data_fetcher.data)

    def process_data(self, item: dict) -> None:
        """Process the data for this sensor."""
        value = item.get(self.data_key)
        if value is not None:
            new_value = round(value / MONETARY_CONVERSION_FACTOR, 2)
            self._attr_native_value = new_value
            _LOGGER.debug("%s = %s", self.data_key, self._attr_native_value)
        else:
            _LOGGER.warning("Data key '%s' not found in the response.", self.data_key)
            self._attr_native_value = None


class LocalvoltsCostsFlexUpSensor(LocalvoltsSensor):
    """Sensor for monitoring costsFlexUp."""

    _attr_native_unit_of_measurement = "$/kWh"
    _attr_device_class = SensorDeviceClass.MONETARY

    def __init__(self, data_fetcher):
        """Initialize the sensor."""
        super().__init__(data_fetcher, "costsFlexUp")
        self._attr_name = "costsFlexUp"
        self._unique_id = f"{data_fetcher.nmi_id}_costsFlexUp"  # Unique ID for this sensor

    @property
    def unique_id(self):
        """Return a unique ID for this sensor."""
        return self._unique_id

    @property
    def extra_state_attributes(self):
        """Return additional state attributes."""
        return {
            "intervalEnd": self.intervalEnd.isoformat()
            if self.intervalEnd
            else None,
            "lastUpdate": self.lastUpdate.isoformat()
            if self.lastUpdate
            else None,
            "time_past_start": self.time_past_start.total_seconds(),  # Expose in seconds for precision
        }


class LocalvoltsEarningsFlexUpSensor(LocalvoltsSensor):
    """Sensor for monitoring earningsFlexUp."""

    _attr_native_unit_of_measurement = "$/kWh"
    _attr_device_class = SensorDeviceClass.MONETARY

    def __init__(self, data_fetcher):
        """Initialize the sensor."""
        super().__init__(data_fetcher, "earningsFlexUp")
        self._attr_name = "earningsFlexUp"
        self._unique_id = (
            f"{data_fetcher.nmi_id}_earningsFlexUp"  # Unique ID for this sensor
        )

    @property
    def unique_id(self):
        """Return a unique ID for this sensor."""
        return self._unique_id

    @property
    def extra_state_attributes(self):
        """Return additional state attributes."""
        return {
            "intervalEnd": self.intervalEnd.isoformat()
            if self.intervalEnd
            else None,
            "lastUpdate": self.lastUpdate.isoformat()
            if self.lastUpdate
            else None,
            "time_past_start": self.time_past_start.total_seconds(),  # Expose in seconds for precision
        }
