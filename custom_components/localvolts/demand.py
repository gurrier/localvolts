"""Demand flex: what another unit of demand right now would cost.

Many network tariffs charge for the month's peak average demand, measured
over 30-minute windows inside a demand period. Localvolts publish, per
interval, the expected cost of raising demand by one unit (`flexDemandUp`)
and the saving from lowering it (`flexDemandDown`). Outside a demand window,
or in a month the tariff doesn't track, both are 0 - which is not "unknown",
it is the answer: extra load now is free of demand charges.

The peak they are measured against is retrospective: meter data reaches
Localvolts from the metering provider the following morning, so `maxDemand`
is the month's peak as settled so far, not including today. It is the
running target to stay under, not a live position against it.

These fields exist only in the v2 API, where each interval is one record per
circuit. Demand charges apply to the main load, so the Import circuit's
record is the one that matters. This module parses only, so it can be tested
without Home Assistant.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any

from dateutil import parser as date_parser


@dataclass(frozen=True)
class DemandFlex:
    """The import circuit's demand position for one interval."""

    interval_end: datetime.datetime
    quality: str
    flex_up: float
    flex_down: float | None
    units: str | None
    max_demand: float | None
    demand_units: str | None


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_demand(payload: Any) -> DemandFlex | None:
    """The Import circuit's settled record from a v2 interval response.

    Returns None when there is no such record - the response is an error or
    the wrong shape, the site has no Import circuit, the record is still a
    forecast, or flexDemandUp is missing. A forecast is refused for the same
    reason prices refuse one: it isn't the number yet.
    """
    if not isinstance(payload, list):
        return None
    best: DemandFlex | None = None
    for item in payload:
        if not isinstance(item, dict):
            continue
        if str(item.get("circuit") or "").lower() != "import":
            continue
        if str(item.get("quality") or "").lower() not in ("exp", "act"):
            continue
        flex_up = _number(item.get("flexDemandUp"))
        end = item.get("intervalEnd")
        if flex_up is None or not end:
            continue
        try:
            interval_end = date_parser.isoparse(end)
        except (TypeError, ValueError):
            continue
        if interval_end.tzinfo is None:
            interval_end = interval_end.replace(tzinfo=datetime.UTC)
        candidate = DemandFlex(
            interval_end=interval_end,
            quality=str(item.get("quality")),
            flex_up=flex_up,
            flex_down=_number(item.get("flexDemandDown")),
            units=(str(item["flexDemandUnits"]) if item.get("flexDemandUnits") else None),
            max_demand=_number(item.get("maxDemand")),
            demand_units=(str(item["demandUnits"]) if item.get("demandUnits") else None),
        )
        # Nothing in the API promises an order; take the newest interval.
        if best is None or candidate.interval_end > best.interval_end:
            best = candidate
    return best
