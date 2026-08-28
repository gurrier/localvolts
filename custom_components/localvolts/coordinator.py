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


class LocalvoltsAuthError(Exception):
    """Raised when the API rejects the given API key or partner ID."""


async def async_validate_credentials(hass: HomeAssistant, api_key: str, partner_id: str, nmi_id: str) -> None:
    """Make a single, minimal real request to confirm these credentials actually work.

    Used by the config flow to catch bad credentials at setup time instead
    of only discovering them once the coordinator's first refresh fails.
    Deliberately kept separate from the coordinator's own fetch logic below
    - this only needs a tiny time window, not a full 24h forecast, and
    duplicating the few lines involved is safer than reshaping the
    coordinator's already-tuned fetch path just to share it.

    Raises LocalvoltsAuthError if the API rejects the key/partner, or
    ValueError if the NMI is accepted but returns no data. aiohttp.ClientError
    (network failures, bad HTTP status) propagates as-is.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    from_time_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    to_time_str = (now + datetime.timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    url = (
        f"https://api.localvolts.com/v1/customer/interval?"
        f"NMI={nmi_id}&from={from_time_str}&to={to_time_str}"
    )
    headers = {
        "Authorization": f"apikey {api_key}",
        "partner": partner_id,
        "User-Agent": "ha-localvolts/config-flow-validation (+https://github.com/gurrier/localvolts)",
    }

    session = async_get_clientsession(hass)
    async with session.get(url, headers=headers) as response:
        if response.status in (401, 403, 500):
            raise LocalvoltsAuthError((await response.text()).strip())
        response.raise_for_status()
        data = await response.json()

    if isinstance(data, list) and not data:
        raise ValueError("No data received: Invalid NMI?")


SCAN_INTERVAL = datetime.timedelta(seconds=10)  # Used only until the first successful fetch, before any interval boundary is known.

# Localvolts has never been observed publishing fresh data for a new interval
# faster than 11s after it starts (from a real dataLag sample spanning 200+
# intervals - 11s was the minimum ever seen), so there's nothing to gain by
# polling before this passes - instead of polling constantly, sleep through
# the rest of each interval and wake up right as this window ends.
POST_BOUNDARY_DEAD_WINDOW = datetime.timedelta(seconds=11)
# Once past the dead window, retry at this tighter cadence until fresh data
# for the new interval arrives. Localvolts' reported dataLag appears to
# reflect when it served the response rather than a fixed publish instant
# (observed dataLag values cluster on our own poll grid rather than varying
# independently of it), so tightening this should pull the effective delay
# the user sees down further, not just how fast we detect a fixed event.
CATCHUP_POLL_INTERVAL = datetime.timedelta(seconds=1)
# If fresh data still hasn't arrived this long after a boundary, treat it as
# a sign the backend is struggling rather than just running a bit slow -
# retrying every second won't help that, so back off to a gentler cadence.
# The slowest interval seen in a real sample was ~76s; 60s gives a margin
# over the normal range without hammering for as long as the old 120s did.
MAX_CATCHUP_WAIT = datetime.timedelta(seconds=60)
SLOW_RETRY_INTERVAL = datetime.timedelta(seconds=30)


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

        A poll that lands during the catch-up retries right after a
        boundary but finds no fresh data yet still counts as "no change" -
        without this, every entity re-writes state and pushes its (now
        large, for the forecast sensor) attributes on every such retry. Key
        includes last_update_success so failures/recoveries are still
        always reported immediately.
        """
        key = (self.intervalEnd, len(self.forecast_data), self.last_update_success)
        if key == self._last_notified_key:
            return
        self._last_notified_key = key
        super().async_update_listeners()

    def _next_update_interval(self, now: datetime.datetime) -> datetime.timedelta:
        """Work out how long to wait before the next poll.

        Sleeps through the bulk of each interval plus the known dead window
        right after each boundary, then polls tightly until fresh data for
        the new interval arrives, falling back to a slower cadence if that's
        taking unusually long. Runs from a `finally` block so it's based on
        the actual current state of self.intervalEnd/now regardless of
        whether this attempt succeeded, found no new data, or raised.
        """
        if self.intervalEnd is None:
            return SCAN_INTERVAL
        time_to_boundary = self.intervalEnd - now
        if time_to_boundary > datetime.timedelta(0):
            return time_to_boundary + POST_BOUNDARY_DEAD_WINDOW
        if -time_to_boundary > MAX_CATCHUP_WAIT:
            return SLOW_RETRY_INTERVAL
        return CATCHUP_POLL_INTERVAL

    async def _async_update_data(self) -> Dict[str, Any]:
        """Fetch data from the API endpoint."""
        try:
            return await self._fetch_update_data()
        finally:
            self.update_interval = self._next_update_interval(
                datetime.datetime.now(datetime.timezone.utc)
            )

    async def _fetch_update_data(self) -> Dict[str, Any]:
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
