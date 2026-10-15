"""Repair hours of price statistics that Home Assistant never recorded.

Home Assistant compiles an hourly statistic from the twelve 5-minute windows
in each hour. If the integration was unavailable for part of an hour - because
Home Assistant was off, or because Localvolts published late and the sensors
went stale - the hour is still written, but computed from however many windows
happened to exist. It looks exactly like a complete hour and isn't one.

The Localvolts API serves the previous 72 hours on request, and those records
usually turn up eventually even when they were late enough to be missed live.
So the gap is recoverable: fetch the window, recompute the hour from the real
interval prices, and import it over the top.

Counting the recorder's own 5-minute windows is not enough to find those
hours. When a price arrives late, the window is still written - from the
*previous* interval's price, carried forward - so the hour looks complete and
holds a wrong value. On 13 and 14 October 2026 exactly that happened: eleven
of twelve intervals arrived, yet all twelve windows were recorded. What gives
an honest count is the intervalEnd sensor, which records one state per record
actually received.

Three rules keep this honest:

* Only hours where the API genuinely has more intervals than were received are
  touched. If Localvolts never published an interval either, the existing row
  is already the best that exists and is left alone.
* Only hours that Home Assistant has already compiled are considered, so this
  never races the recorder's own hourly compile.
* Every hour the API is asked about is remembered, answer or not. Fixing an
  hour doesn't change the evidence that it needed fixing - the intervals were
  never received and never will be - so without that record the same hours
  would be re-fetched on every sweep for as long as they stayed in the API's
  window. A startup sweep asks again about any hour still short of twelve
  intervals, in case a late one has since appeared.

Nothing here can invent a price. Every value written came from the API.

One deliberate difference worth knowing: Home Assistant averages twelve
wall-clock windows, and because a price arrives ~18s after its interval
starts, each window blends a sliver of the previous price. A repaired hour
averages the twelve interval prices instead. The two differ in the fourth
decimal place. That is not a bug.
"""

from __future__ import annotations

import datetime
import logging
from functools import partial
from typing import Any

import aiohttp
from dateutil import parser as date_parser

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.history import state_changes_during_period
from homeassistant.components.recorder.models import StatisticData
from homeassistant.components.recorder.statistics import (
    async_import_statistics,
    get_metadata,
    statistics_during_period,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .coordinator import (
    REQUEST_TIMEOUT,
    LocalvoltsDataUpdateCoordinator,
    _build_request,
    api_error,
)

_LOGGER = logging.getLogger(__name__)

# The API refuses a `from` more than three days old. Asking for exactly 72
# hours gets rejected once the sweep's own arithmetic rounds down to the hour,
# so stay an hour inside the limit.
LOOKBACK = datetime.timedelta(hours=71)
# "'to' date cannot be more than 24 hours after 'from' date" - and it means
# strictly less than, so a span of exactly 24h is refused. Verified against
# the live API: 24h rejected, 23.9h accepted.
MAX_FETCH_SPAN = datetime.timedelta(hours=23)
# Leave the most recent hour alone until the recorder has compiled it, so an
# import can't be overwritten moments later by Home Assistant's own summary.
COMPILE_MARGIN = datetime.timedelta(minutes=10)
INTERVALS_PER_HOUR = 12
STORAGE_VERSION = 1

# unique_id suffix -> the API field that feeds it. Both are prices in c/kWh
# that the sensors publish in $/kWh, rounded the same way the sensors round.
REPAIRABLE = {
    "costsFlexUp": "costsFlexUp",
    "earningsFlexUp": "earningsFlexUp",
}
MONETARY_CONVERSION_FACTOR = 100


def store_key(entry_id: str) -> str:
    """Where an entry's record of repaired hours lives."""
    return f"{entry_id}_statistics_repair"


async def async_forget_repairs(hass: HomeAssistant, entry_id: str) -> None:
    """Drop that record, for an entry being removed."""
    await Store(hass, STORAGE_VERSION, store_key(entry_id)).async_remove()


def statistics_hour(interval_end: datetime.datetime) -> datetime.datetime:
    """Return the hour an interval belongs to.

    intervalEnd is the *end* of the interval, so the 06:00 hour is made of the
    intervals ending 06:05 through 07:00 - one ending exactly on the hour
    belongs to the hour before it, not the one it starts.
    """
    floored = interval_end.replace(minute=0, second=0, microsecond=0)
    if floored == interval_end:
        return floored - datetime.timedelta(hours=1)
    return floored


def summarise(prices: list[float]) -> dict[str, float]:
    """Summarise an hour the way the recorder would have."""
    return {"mean": sum(prices) / len(prices), "min": min(prices), "max": max(prices)}


def group_by_hour(
    records: list[dict[str, Any]], field: str
) -> dict[datetime.datetime, list[float]]:
    """Collect each hour's interval prices, in $/kWh as the sensors publish them."""
    by_hour: dict[datetime.datetime, list[float]] = {}
    for item in records:
        raw = item.get(field)
        end = item.get("intervalEnd")
        if raw is None or not end:
            continue
        try:
            price = round(float(raw) / MONETARY_CONVERSION_FACTOR, 3)
            interval_end = date_parser.isoparse(end)
        except (TypeError, ValueError):
            continue
        if interval_end.tzinfo is None:
            interval_end = interval_end.replace(tzinfo=datetime.UTC)
        by_hour.setdefault(statistics_hour(interval_end), []).append(price)
    return by_hour


def hours_needing_repair(
    recorded: dict[datetime.datetime, int],
    available: dict[datetime.datetime, int],
) -> list[datetime.datetime]:
    """Hours where the API can do better than what was recorded."""
    return sorted(
        hour
        for hour, count in available.items()
        if count > recorded.get(hour, 0)
    )


class StatisticsRepair:
    """Fills gaps in the hourly price statistics from the API's 72-hour window."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: LocalvoltsDataUpdateCoordinator,
        config_entry: Any,
    ) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self.config_entry = config_entry
        # Repairing an hour doesn't change the evidence that it needed
        # repairing: the intervals were never received and never will be, so
        # the detector would find the same hours every hour until they aged
        # out of the window. What we have already done has to be remembered
        # separately - hour -> how many intervals it was rebuilt from.
        self._store: Store = Store(
            hass, STORAGE_VERSION, store_key(config_entry.entry_id)
        )
        self._done: dict[str, int] | None = None

    async def _load_done(self, cutoff: datetime.datetime) -> dict[str, int]:
        """What we have already repaired, forgetting anything out of range.

        Keys are UTC hour boundaries written by isoformat(), so they all carry
        the same offset and sort lexically in time order - which is what makes
        comparing them as strings sound.
        """
        if self._done is None:
            self._done = await self._store.async_load() or {}
        kept = {
            hour: count
            for hour, count in self._done.items()
            if hour >= cutoff.isoformat()
        }
        if len(kept) != len(self._done):
            self._done = kept
            await self._store.async_save(kept)
        return self._done

    def _entity_ids(self) -> dict[str, str]:
        """Map each repairable API field to the entity that holds it."""
        registry = er.async_get(self.hass)
        by_unique_id = {
            entry.unique_id: entry.entity_id
            for entry in er.async_entries_for_config_entry(
                registry, self.config_entry.entry_id
            )
        }
        found = {}
        for suffix, field in REPAIRABLE.items():
            entity_id = by_unique_id.get(f"{self.coordinator.nmi_id}_{suffix}")
            if entity_id:
                found[field] = entity_id
        return found

    async def _intervals_received(
        self, start: datetime.datetime, end: datetime.datetime
    ) -> dict[datetime.datetime, int] | None:
        """How many distinct intervals actually reached us, per hour.

        The intervalEnd sensor publishes the end of every record received, so
        its history is a precise account of what arrived - unlike the 5-minute
        windows, which get filled with a carried-forward price when one is
        late. Returns None if that history isn't available (the entity is
        missing, or someone has excluded it from the recorder), so the caller
        can fall back to the coarser count rather than assume the worst and
        rewrite every hour.
        """
        registry = er.async_get(self.hass)
        entity_id = None
        for entry in er.async_entries_for_config_entry(
            registry, self.config_entry.entry_id
        ):
            if entry.unique_id == f"{self.coordinator.nmi_id}_interval_end":
                entity_id = entry.entity_id
                break
        if entity_id is None:
            return None

        history = await get_instance(self.hass).async_add_executor_job(
            partial(
                state_changes_during_period,
                self.hass,
                start - datetime.timedelta(minutes=10),
                end + datetime.timedelta(minutes=10),
                entity_id,
            )
        )
        states = history.get(entity_id) or []
        if not states:
            return None

        seen: dict[datetime.datetime, set[datetime.datetime]] = {}
        for state in states:
            try:
                interval_end = date_parser.isoparse(state.state)
            except (TypeError, ValueError):
                continue
            if interval_end.tzinfo is None:
                interval_end = interval_end.replace(tzinfo=datetime.UTC)
            seen.setdefault(statistics_hour(interval_end), set()).add(interval_end)
        return {hour: len(ends) for hour, ends in seen.items()}

    async def _recorded_counts(
        self, entity_ids: set[str], start: datetime.datetime, end: datetime.datetime
    ) -> dict[str, dict[datetime.datetime, int]]:
        """How many 5-minute windows the recorder has for each hour."""
        rows = await get_instance(self.hass).async_add_executor_job(
            partial(
                statistics_during_period,
                self.hass,
                start,
                end,
                entity_ids,
                "5minute",
                None,
                {"mean"},
            )
        )
        counts: dict[str, dict[datetime.datetime, int]] = {}
        for entity_id, entries in rows.items():
            per_hour: dict[datetime.datetime, int] = {}
            for entry in entries:
                when = dt_util.utc_from_timestamp(entry["start"])
                hour = when.replace(minute=0, second=0, microsecond=0)
                per_hour[hour] = per_hour.get(hour, 0) + 1
            counts[entity_id] = per_hour
        return counts

    async def _fetch(
        self, start: datetime.datetime, end: datetime.datetime
    ) -> list[dict[str, Any]]:
        """Fetch raw records, in chunks the API will accept."""
        session = async_get_clientsession(self.hass)
        records: list[dict[str, Any]] = []
        chunk_start = start
        while chunk_start < end:
            chunk_end = min(chunk_start + MAX_FETCH_SPAN, end)
            url, headers = _build_request(
                self.coordinator.nmi_id,
                self.coordinator.api_key,
                self.coordinator.partner_id,
                self.coordinator.user_agent,
                chunk_start,
                chunk_end,
            )
            async with session.get(url, headers=headers, timeout=REQUEST_TIMEOUT) as response:
                response.raise_for_status()
                payload = await response.json()
            if (error := api_error(payload)) is not None:
                # The API reports a bad request as HTTP 200 with an error
                # object, so raise_for_status sees nothing wrong and the
                # records simply look malformed. Say so instead of quietly
                # concluding there is nothing to repair.
                _LOGGER.warning(
                    "Localvolts refused a history request for %s - %s: %s",
                    chunk_start, chunk_end, error,
                )
                return []
            if isinstance(payload, list):
                records.extend(item for item in payload if isinstance(item, dict))
            chunk_start = chunk_end
        return records

    async def async_run(self, first_run: bool = False) -> None:
        """Look for gaps and, if there are any, fill them."""
        # Declared as an after_dependency rather than a dependency: prices work
        # perfectly well without the recorder, and someone who has turned it
        # off should not lose the integration along with it.
        if "recorder" not in self.hass.config.components:
            _LOGGER.debug("Recorder isn't loaded; nothing to repair")
            return

        entities = self._entity_ids()
        if not entities:
            return

        now = dt_util.utcnow()
        end = (now - COMPILE_MARGIN).replace(minute=0, second=0, microsecond=0)
        start = end - LOOKBACK

        received = await self._intervals_received(start, end)
        if received is None:
            # No record of what arrived, so fall back to counting windows. That
            # misses hours whose windows were filled with a carried-forward
            # price, but it cannot produce a false positive.
            windows = await self._recorded_counts(set(entities.values()), start, end)
            received = {}
            for per_hour in windows.values():
                for hour, count in per_hour.items():
                    received[hour] = max(received.get(hour, 0), count)

        done = await self._load_done(start)
        # An hour that was never recorded doesn't appear at all, so consider
        # every hour in the window rather than only the ones present. An hour
        # already rebuilt from a full set of intervals can never be improved
        # on, so it is settled; one rebuilt from fewer is retried only on a
        # startup sweep, in case the missing intervals have since appeared.
        best_known: dict[datetime.datetime, int] = {}
        hour = start
        while hour < end:
            best_known[hour] = max(
                received.get(hour, 0), done.get(hour.isoformat(), 0)
            )
            hour += datetime.timedelta(hours=1)
        candidates = {
            hour
            for hour, count in best_known.items()
            if count < INTERVALS_PER_HOUR
            and (first_run or hour.isoformat() not in done)
        }
        if not candidates:
            _LOGGER.debug(
                "Nothing left to repair in the last %s; no history fetched", LOOKBACK
            )
            return

        try:
            records = await self._fetch(start, end)
        except (TimeoutError, aiohttp.ClientError) as err:
            _LOGGER.debug("Couldn't fetch history to repair statistics: %s", err)
            return
        if not records:
            return

        metadata = await get_instance(self.hass).async_add_executor_job(
            partial(get_metadata, self.hass, statistic_ids=set(entities.values()))
        )
        usable = {
            field: entity_id
            for field, entity_id in entities.items()
            if entity_id in metadata
        }
        if not usable:
            # No sensor has produced statistics yet, so there is no series to
            # repair and no metadata to reuse. Record nothing: the hours are
            # still open questions once the series exists.
            _LOGGER.debug("No price statistics exist yet; nothing to repair")
            return

        settled: dict[datetime.datetime, int] = {}
        for field, entity_id in usable.items():
            by_hour = group_by_hour(records, field)
            available = {h: len(v) for h, v in by_hour.items() if h in candidates}
            for hour, count in available.items():
                settled[hour] = max(settled.get(hour, 0), count)
            repairs = hours_needing_repair(best_known, available)
            if not repairs:
                continue
            rows: list[StatisticData] = [
                StatisticData(start=hour, **summarise(by_hour[hour])) for hour in repairs
            ]
            _, existing_metadata = metadata[entity_id]
            async_import_statistics(self.hass, existing_metadata, rows)
            _LOGGER.info(
                "Repaired %d hour(s) of statistics for %s (%s)",
                len(rows),
                entity_id,
                ", ".join(
                    f"{h:%Y-%m-%d %H:00} {best_known[h]}->{available[h]}"
                    for h in repairs[:6]
                )
                + (" ..." if len(repairs) > 6 else ""),
            )

        # Every candidate hour has now been put to the API, so remember the
        # answer for all of them - including the ones it had nothing better
        # for, such as hours predating the install. Those are exactly the ones
        # that would otherwise provoke a fetch on every sweep, since no amount
        # of asking will improve them.
        for hour in candidates:
            key = hour.isoformat()
            self._done[key] = max(
                self._done.get(key, 0), best_known[hour], settled.get(hour, 0)
            )
        await self._store.async_save(self._done)
