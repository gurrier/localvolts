"""Diagnostics support for the Localvolts integration."""

from __future__ import annotations

import datetime
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_API_KEY, CONF_NMI_ID, CONF_PARTNER_ID

# The API key authenticates the account outright. The partner ID pairs with
# it, and the NMI identifies a physical connection point (and so, indirectly,
# an address) - diagnostics get pasted into public issue threads, so none of
# the three should travel with them. "NMI" is the API's own spelling of the
# same value inside interval records.
TO_REDACT = {CONF_API_KEY, CONF_PARTNER_ID, CONF_NMI_ID, "NMI"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry.

    Aimed at the questions that actually come up in support: is it polling,
    how fresh is the data, how far behind is Localvolts publishing, and does
    the payload look the shape we expect.
    """
    coordinator = config_entry.runtime_data
    now = datetime.datetime.now(datetime.timezone.utc)

    interval_end = coordinator.intervalEnd
    last_update = coordinator.lastUpdate
    update_interval = coordinator.update_interval

    return {
        "entry": {
            "version": config_entry.version,
            "data": async_redact_data(dict(config_entry.data), TO_REDACT),
        },
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "data_is_stale": coordinator.data_is_stale,
            # Where the adaptive poll schedule currently sits: a value near
            # the interval length means it's idling until the next boundary,
            # a small one means it's in catch-up.
            "update_interval_seconds": (
                update_interval.total_seconds() if update_interval else None
            ),
            "interval_end": interval_end.isoformat() if interval_end else None,
            "last_update": last_update.isoformat() if last_update else None,
            "seconds_since_interval_end": (
                (now - interval_end).total_seconds() if interval_end else None
            ),
            # Localvolts' own publish delay, not ours.
            "data_lag_seconds": coordinator.time_past_start.total_seconds(),
            "forecast_count": len(coordinator.forecast_data),
        },
        "current_interval": async_redact_data(
            dict(coordinator.interval_data), TO_REDACT
        ),
        # One entry is enough to confirm the shape and field names without
        # dumping ~287 of them into an issue.
        "forecast_sample": (
            async_redact_data(dict(coordinator.forecast_data[0]), TO_REDACT)
            if coordinator.forecast_data
            else None
        ),
    }
