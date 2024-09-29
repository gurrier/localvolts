"""Coordinator for Localvolts integration."""

import datetime
import logging
from dateutil import parser, tz

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

import aiohttp

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = datetime.timedelta(seconds=10)  # Update every 10 seconds

class LocalvoltsDataUpdateCoordinator(DataUpdateCoordinator):
    """DataUpdateCoordinator to manage fetching data from Localvolts API."""

    def __init__(self, hass: HomeAssistant, api_key, partner_id, nmi_id):
        """Initialize the coordinator."""
        self.api_key = api_key
        self.partner_id = partner_id
        self.nmi_id = nmi_id
        self.intervalEnd = None
        self.lastUpdate = None
        self.time_past_start = datetime.timedelta(0)
        self.data = {}

        super().__init__(
            hass,
            _LOGGER,
            name="Localvolts Data",
            update_interval=SCAN_INTERVAL,
        )

    async def _async_update_data(self):
        """Fetch data from the API endpoint."""
        current_utc_time = datetime.datetime.now(datetime.timezone.utc)
        from_time = current_utc_time
        to_time = current_utc_time + datetime.timedelta(minutes=5)

        _LOGGER.debug("intervalEnd = %s", self.intervalEnd)
        _LOGGER.debug("lastUpdate = %s", self.lastUpdate)
        _LOGGER.debug("from_time = %s", from_time)
        _LOGGER.debug("to_time = %s", to_time)

        # Determine if we need to fetch new data
        if (self.intervalEnd is None) or (current_utc_time > self.intervalEnd):
            _LOGGER.debug("New interval detected. Retrieving the latest data.")
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
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, headers=headers) as response:
                        response.raise_for_status()
                        data = await response.json()
            except aiohttp.ClientError as e:
                _LOGGER.error("Failed to fetch data from Localvolts API: %s", str(e))
                raise UpdateFailed(f"Error communicating with API: {e}") from e

            # Process data
            new_data_found = False
            for item in data:
                if item.get("quality", "").lower() == "exp":
                    interval_end = parser.isoparse(item["intervalEnd"])
                    last_update_time = parser.isoparse(item["lastUpdate"])

                    # Ensure timezone awareness
                    if interval_end.tzinfo is None:
                        interval_end = interval_end.replace(tzinfo=tz.UTC)
                    if last_update_time.tzinfo is None:
                        last_update_time = last_update_time.replace(tzinfo=tz.UTC)

                    # Update variables
                    self.intervalEnd = interval_end
                    self.lastUpdate = last_update_time
                    self.data = item

                    interval_start = interval_end - datetime.timedelta(minutes=5)
                    self.time_past_start = last_update_time - interval_start
                    _LOGGER.debug(
                        "Data updated: intervalEnd=%s, lastUpdate=%s",
                        self.intervalEnd,
                        self.lastUpdate,
                    )
                    new_data_found = True
                    break
                else:
                    _LOGGER.debug(
                        "Skipping non-'exp' quality data. Only 'exp' is processed."
                    )
            if not new_data_found:
                _LOGGER.debug("No new data with 'exp' quality found. Retaining last known data.")
                # Do not update self.time_past_start; retain the last known value
                # Optionally, you can log the time since the last update if needed
        else:
            _LOGGER.debug("Data did not change. Still in the same interval.")

        # Return self.data to comply with DataUpdateCoordinator requirements
        return self.data
