"""Platform for localvolts integration."""

from __future__ import annotations

import requests
#from datetime import datetime
import datetime
from datetime import timedelta

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


    # Add sensor entity to Home Assistant
    add_entities([LocalvoltsSensor(api_key, partner_id, nmi_id)])


class LocalvoltsSensor(SensorEntity):
    """Representation of a Sensor."""

    _attr_name = "costsFlexUp"
    _attr_native_unit_of_measurement = "$/kWh" #UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.MONETARY
    #_attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, api_key, partner_id, nmi_id):
        """Initialize the sensor."""
        self.api_key = api_key
        self.partner_id = partner_id
        self.nmi_id = nmi_id
        self.last_interval = None

    @property
    def EarningsFlexUp(self) -> str | None:
        return "earninsgFlexUpValue"

    @property
    def unique_id(self):
        # Example: using partnerID as unique ID
        return f"localvolts_sensor_{self.partner_id}"


    @property
    def state_attributes(self):
        """Return the state attributes of the sensor."""
        attributes = super().state_attributes or {}
        attributes["earnings_flex_up"] = self.EarningsFlexUp
        return attributes

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

        _LOGGER.debug("intervalEnd = %s", self.last_interval)
        _LOGGER.debug("from_time = %s", from_time)
        _LOGGER.debug("to_time = %s", to_time)

        #The first condition will be evaluated and, if true, the second condition will not need to be evaluated (handy because it would cause an error if last_interval is none)
        #The data will not be updated until about 20-30 seconds after the start of the interval so let's introduce a small timedelata sicne we know it won't be faster than 15 seconds in practice
        #if (self.last_interval is None) or (from_time > self.last_interval + timedelta(seconds=15)):
        if (self.last_interval is None) or (from_time > self.last_interval):
            #First time through the loop, or else it is the first time running in a new 5min interval 
            _LOGGER.debug("New interval so retrieve the latest costsFlexUp")
            url = "https://api.localvolts.com/v1/customer/interval?NMI=" + self.nmi_id + "&from=" + from_time + "&to=" + to_time
            
            headers = {
                "Authorization": "apikey " + self.api_key,
                "partner": "" + self.partner_id 
            }
            
            response = requests.get(url, headers=headers)
            
            # Optional: If the response is JSON, you can convert it to a Python dictionary:
            data = response.json()
            
            # Now, extract the 'costsFlexUp' field from the data
            
            for item in data:

                quality = item['quality'].lower()
                _LOGGER.debug("quality = %s", quality)
                
                
                # Check the 'quality' field
                if quality == 'exp':
                    self.last_interval = item['intervalEnd']
                    _LOGGER.debug("intervalEnd = %s", self.last_interval)
                    new_value = round(item['costsFlexUp'] / 100, 2)
                    # Update the value if it's different
                    if self._attr_native_value != new_value:
                        self._attr_native_value = new_value
                    _LOGGER.debug("costsFlexUp = %s", self._attr_native_value)
                else:
                    _LOGGER.debug("Skipping forecast quality data.  Only exp will do.")
    #            self._attr_native_value = round(item['costsFlexUp'] / 100, 2)
                
        else:
            _LOGGER.debug("costsFlexUp did not change.  Still in same interval.")

