"""Coordinator for Localvolts integration."""

import datetime
import logging
from dateutil import parser, tz
from typing import Any, Dict

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession

import aiohttp

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = datetime.timedelta(seconds=10)  # Update every 10 seconds


class LocalvoltsDataUpdateCoordinator(DataUpdateCoordinator):
    """DataUpdateCoordinator to manage fetching data from Localvolts API."""

    # def __init__(self, hass: HomeAssistant, api_key, partner_id, nmi_id):
    def __init__(
        self,
        hass: HomeAssistant,
        api_key: str,
        partner_id: str,
        nmi_id: str,
    ) -> None:
        """Initialize the coordinator."""
        # self.api_key = api_key
        # self.partner_id = partner_id
        # self.nmi_id = nmi_id
        # self.intervalEnd = None
        # self.lastUpdate = None
        # self.time_past_start = datetime.timedelta(0)
        # self.data = {}
        self.api_key: str = api_key
        self.partner_id: str = partner_id
        self.nmi_id: str = nmi_id
        self.intervalEnd: Any = None
        self.lastUpdate: Any = None
        self.time_past_start: datetime.timedelta = datetime.timedelta(0)
        self.data: Dict[str, Any] = {}
        self.forecast_data: List[Dict[str, Any]] = []

        super().__init__(
            hass,
            _LOGGER,
            name="Localvolts Data",
            update_interval=SCAN_INTERVAL,
        )

    async def _async_update_data(self) -> Dict[str, Any]:
        """Fetch data from the API endpoint."""
        current_utc_time: datetime.datetime = datetime.datetime.now(
            datetime.timezone.utc)
        from_time: datetime.datetime = current_utc_time
        to_time: datetime.datetime = current_utc_time + \
            datetime.timedelta(minutes=5)

        _LOGGER.debug("intervalEnd = %s", self.intervalEnd)
        _LOGGER.debug("lastUpdate = %s", self.lastUpdate)
        _LOGGER.debug("from_time = %s", from_time)
        _LOGGER.debug("to_time = %s", to_time)

        # Determine if we need to fetch new data
        if (self.intervalEnd is None) or (current_utc_time > self.intervalEnd):
            _LOGGER.debug("New interval detected. Retrieving the latest data.")
            from_time_str: str = from_time.strftime("%Y-%m-%dT%H:%M:%SZ")
            to_time_str: str = to_time.strftime("%Y-%m-%dT%H:%M:%SZ")

            url: str = (
                f"https://api.localvolts.com/v1/customer/interval?"
                f"NMI={self.nmi_id}&from={from_time_str}&to={to_time_str}"
            )

            headers: Dict[str, str] = {
                "Authorization": f"apikey {self.api_key}",
                "partner": self.partner_id,
            }

            try:
                session = async_get_clientsession(self.hass)
                async with session.get(url, headers=headers) as response:
                    if response.status == 401:
                        _LOGGER.critical(
                            "Unauthorized access: Check your API key.")
                        raise UpdateFailed(
                            "Unauthorized access: Invalid API key.")
                    elif response.status == 403:
                        _LOGGER.critical("Forbidden: Check your Partner ID.")
                        raise UpdateFailed("Forbidden: Invalid Partner ID.")

                    response.raise_for_status()
                    data: Any = await response.json()

                # If the API returns an empty list, log a warning
                if isinstance(data, list) and not data:
                    _LOGGER.warning(
                        "No data received, check that your NMI, PartnerID and API Key are correct.")
                    raise UpdateFailed("No data received: Invalid NMI?")

            except aiohttp.ClientError as e:
                _LOGGER.error(
                    "Failed to fetch data from Localvolts API: %s", str(e))
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
                        last_update_time = last_update_time.replace(
                            tzinfo=tz.UTC)

                    # Update variables
                    self.intervalEnd = interval_end
                    self.lastUpdate = last_update_time
                    self.data = item

                    interval_start: datetime.datetime = interval_end - \
                        datetime.timedelta(minutes=5)
                    self.time_past_start = last_update_time - interval_start
                    _LOGGER.debug(
                        "Data updated: intervalEnd=%s, lastUpdate=%s",
                        self.intervalEnd,
                        self.lastUpdate,
                    )
                    new_data_found = True
                    break
                elif item.get("quality", "").lower() == "fcst":
                    # Store forecast data
                    self.forecast_data.append(item)
                    _LOGGER.debug(
                        "Stored forecast data: intervalEnd=%s", item["intervalEnd"])
                else:
                    _LOGGER.debug(
                        "Skipping non-'exp' and non-'fcst' quality data. Only 'exp' and 'fcst' are processed."
                    )
        else:
            _LOGGER.debug("Data did not change. Still in the same interval.")

        # Return both exp data and forecast data
        # The coordinator will make this available to sensors
        return {
            "exp": self.data,
            "fcst": self.forecast_data
        }
