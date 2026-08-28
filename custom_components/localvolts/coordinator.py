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

    def __init__(
        self,
        hass,
        api_key: str,
        partner_id: str,
        nmi_id: str,
        version: str = "unknown",
    ) -> None:
        """Initialize the coordinator."""
        self.hass = hass
        self.api_key: str = api_key
        self.partner_id: str = partner_id
        self.nmi_id: str = nmi_id
        self.user_agent: str = f"ha-localvolts/{version} (+https://github.com/gurrier/localvolts)"
        self.intervalEnd: Any = None
        self.lastUpdate: Any = None
        self.time_past_start: datetime.timedelta = datetime.timedelta(0)
        # NOTE: deliberately not named `self.data` - the DataUpdateCoordinator
        # base class overwrites `self.data` with whatever _async_update_data()
        # returns after every poll. Since we return {"exp": ..., "fcst": ...},
        # reusing `self.data` for the raw current-interval item here would
        # self-collide: the wrapped dict from the last poll would get wrapped
        # again on the next one, nesting deeper every poll where no fresh
        # interval data arrives.
        self.interval_data: Dict[str, Any] = {}
        self.forecast_data: List[Dict[str, Any]] = []
        self._last_notified_key: Any = None

        super().__init__(
            hass,
            _LOGGER,
            name="Localvolts Data",
            update_interval=SCAN_INTERVAL,
        )

    def async_update_listeners(self) -> None:
        """Notify entities only when something actually changed.

        Polling runs every 10s so a new interval's price data is picked up
        with minimal delay, but the API is only actually queried once per
        5-minute interval - the other ~29 polls out of 30 return unchanged
        data. Without this, every entity re-writes state and pushes its
        (now large, for the forecast sensor) attributes on every single
        poll. Key includes last_update_success so failures/recoveries are
        still always reported immediately.
        """
        key = (self.intervalEnd, len(self.forecast_data), self.last_update_success)
        if key == self._last_notified_key:
            return
        self._last_notified_key = key
        super().async_update_listeners()

    async def _async_update_data(self) -> Dict[str, Any]:
        """Fetch data from the API endpoint."""
        current_utc_time: datetime.datetime = datetime.datetime.now(
            datetime.timezone.utc)
        from_time: datetime.datetime = current_utc_time
        to_time: datetime.datetime = current_utc_time + datetime.timedelta(hours=24) - datetime.timedelta(minutes=5)

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
                "User-Agent": self.user_agent,
            }

            try:
                session = async_get_clientsession(self.hass)
                async with session.get(url, headers=headers) as response:
                    # The Localvolts API returns auth failures (missing/invalid
                    # API key or partner id) as HTTP 500 with the specific
                    # reason as plain text in the body, e.g. "Invalid API Key
                    # (partner: 1234)" or "Unregistered partner: 1234". 401/403
                    # are kept as a defensive fallback in case that ever
                    # changes, but per the API docs 500 is what's actually
                    # sent.
                    if response.status in (401, 403, 500):
                        error_text = (await response.text()).strip()
                        _LOGGER.critical(
                            "Localvolts API authentication error (HTTP %s): %s",
                            response.status, error_text,
                        )
                        raise UpdateFailed(
                            f"Localvolts API authentication error: {error_text or response.status}"
                        )

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
            # Clear existing forecast data to prevent duplicates
            self.forecast_data.clear()
            for item in data:
                quality = item.get("quality", "").lower()
                try:
                    if quality == "exp":
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
                        self.interval_data = item

                        duration = int(item.get("intervalDuration", 5))
                        interval_start: datetime.datetime = interval_end - \
                            datetime.timedelta(minutes=duration)
                        self.time_past_start = last_update_time - interval_start
                        _LOGGER.debug(
                            "Data updated: intervalEnd=%s, lastUpdate=%s",
                            self.intervalEnd,
                            self.lastUpdate,
                        )
                    elif quality == "fcst":
                        # Store forecast data
                        self.forecast_data.append(item)
                        _LOGGER.debug(
                            "Stored forecast data: intervalEnd=%s", item["intervalEnd"])
                    else:
                        _LOGGER.debug(
                            "Skipping non-'exp' and non-'fcst' quality data. Only 'exp' and 'fcst' are processed."
                        )
                except (KeyError, ValueError, TypeError) as err:
                    _LOGGER.warning(
                        "Skipping malformed interval record %s: %s", item, err)
                    continue
        else:
            _LOGGER.debug("Data did not change. Still in the same interval.")

        # Return both exp data and forecast data. This becomes `self.data`
        # (the base class assigns it), so it must never read `self.data`
        # itself - see the note on self.interval_data in __init__.
        return {
            "exp": self.interval_data,
            "fcst": self.forecast_data
        }
