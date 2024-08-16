"""Platform for localvolts integration."""

from __future__ import annotations

import requests
import datetime
from datetime import timedelta
from homeassistant.util import Throttle

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

import logging

DOMAIN = "localvolts"
_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=15)  # Update every 15 seconds

def setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None
) -> None:
    """Set up the sensor platform."""
    
    # Retrieve configuration data from the main component
    api_key = hass.data[DOMAIN]['api_key']
    partner_id = hass.data[DOMAIN]['partner_id']
    nmi_id = hass.data[DOMAIN]['nmi_id']

    # Optional: Perform some checks or preparations with the configuration data
    if not api_key or not partner_id or not nmi_id:
        _LOGGER.error("API Key or Partner ID or NMI is missing.")
        return


    # Add both sensor entities to Home Assistant
    add_entities([
        LocalvoltsCostsFlexUpSensor(api_key, partner_id, nmi_id),
        LocalvoltsEarningsFlexUpSensor(api_key, partner_id, nmi_id)
    ])


class LocalvoltsSensor(SensorEntity):
    """Representation of a Localvolts Sensor."""

    def __init__(self, api_key, partner_id, nmi_id):
        """Initialize the sensor."""
        self.api_key = api_key
        self.partner_id = partner_id
        self.nmi_id = nmi_id
        self.intervalEnd = None
        self.lastUpdate = None
        self._attr_native_value = None

    @Throttle(SCAN_INTERVAL)
    def update(self) -> None:
        """Fetch new state data for the sensor.

        This is the only method that should fetch new data for Home Assistant.
        """

        # Get the current time in UTC
        current_utc_time = datetime.datetime.now(datetime.timezone.utc)
        
        # Format the time in the desired format (ISO 8601)
        from_time = current_utc_time.strftime('%Y-%m-%dT%H:%M:%SZ')
        # Add 5 minutes to the current time
        duration_minutes_later = current_utc_time + datetime.timedelta(minutes=5)
        to_time = duration_minutes_later.strftime('%Y-%m-%dT%H:%M:%SZ')

        _LOGGER.debug("intervalEnd = %s", self.intervalEnd)
        _LOGGER.debug("lastUpdate = %s", self.lastUpdate)
        _LOGGER.debug("from_time = %s", from_time)
        _LOGGER.debug("to_time = %s", to_time)

        #The first condition will be evaluated and, if true, the second condition will not need to be evaluated (handy because it would cause an error if intervalEnd is none)
        #The data will not be updated until about 20-30 seconds after the start of the interval so let's introduce a small timedelata sicne we know it won't be faster than 15 seconds in practice
        #if (self.intervalEnd is None) or (from_time > self.intervalEnd + timedelta(seconds=15)):
        if (self.intervalEnd is None) or (from_time > self.intervalEnd):
            #First time through the loop, or else it is the first time running in a new 5min interval 
            _LOGGER.debug("New interval so retrieve the latest data")
            url = "https://api.localvolts.com/v1/customer/interval?NMI=" + self.nmi_id + "&from=" + from_time + "&to=" + to_time
            #url = f"https://api.localvolts.com/v1/customer/interval?NMI={self.nmi_id}&from={from_time}&to={to_time}"
            headers = {
                "Authorization": "apikey " + self.api_key,
                "partner": "" + self.partner_id 
            }
            
            response = requests.get(url, headers=headers)
            
            if response.status_code == 200:

            # Process data
            # The response is JSON, you can convert it to a Python dictionary:
                data = response.json()
    
                for item in data:
    
                    # Check the 'quality' field
                    if item['quality'].lower() == 'exp':
                        self.intervalEnd = item['intervalEnd']
                        _LOGGER.debug("intervalEnd = %s", self.intervalEnd)
                        self.lastUpdate = item['lastUpdate']
                        _LOGGER.debug("lastUpdate = %s", self.lastUpdate)
                        self.process_data(item)
                    else:
                        _LOGGER.debug("Skipping forecast quality data.  Only exp will do.")
            else:
                _LOGGER.error("Failed to fetch data from localvolts API, will try again soon, status code: %s", response.status_code)
                
        else:
            _LOGGER.debug("Data did not change.  Still in same interval.")

    def process_data(self, item):
        """Process the fetched data. To be implemented by subclasses."""
        raise NotImplementedError

class LocalvoltsCostsFlexUpSensor(LocalvoltsSensor):
    """Sensor for monitoring costsFlexUp."""

    _attr_name = "costsFlexUp"
    _attr_native_unit_of_measurement = "$/kWh"
    _attr_device_class = SensorDeviceClass.MONETARY

    def process_data(self, item):
        """Process the costsFlexUp data."""
        new_value = round(item['costsFlexUp'] / 100, 2)
        #if self._attr_native_value != new_value:
        self._attr_native_value = new_value
        _LOGGER.debug("costsFlexUp = %s", self._attr_native_value)

    @property
    def extra_state_attributes(self):
        """Return additional state attributes."""
        return {
            "intervalEnd": self.intervalEnd,
            "lastUpdate": self.lastUpdate,
        }


class LocalvoltsEarningsFlexUpSensor(LocalvoltsSensor):
    """Sensor for monitoring earningsFlexUp."""

    _attr_name = "earningsFlexUp"
    _attr_native_unit_of_measurement = "$/kWh"
    _attr_device_class = SensorDeviceClass.MONETARY

    def process_data(self, item):
        """Process the earningsFlexUp data."""
        new_value = round(item['earningsFlexUp'] / 100, 2)
        #if self._attr_native_value != new_value:
        self._attr_native_value = new_value
        _LOGGER.debug("earningsFlexUp = %s", self._attr_native_value)

    @property
    def extra_state_attributes(self):
        """Return additional state attributes."""
        return {
            "intervalEnd": self.intervalEnd,
            "lastUpdate": self.lastUpdate,
        }
