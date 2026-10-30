# Details

Reference material for when the [README](../README.md) isn't enough.

## Entity IDs

Home Assistant 2026.9 changed how it generates IDs for new entities that belong to a device: the device name is prefixed. The effect for this integration:

- Installations that existed before the sensors were attached to a device (version 0.9.0) keep their original IDs - `sensor.costsflexup`, `sensor.earningsflexup`, `sensor.datalag`, `sensor.intervalend`, `sensor.forecasted_costs_flex_up`. IDs are stored, so they never change on upgrade.
- A fresh install on Home Assistant 2026.9 or later gets `sensor.localvolts_<nmi>_costsflexup` and so on.
- The sensors added in 0.10.0 - Demand flex up, Import tariff, Export tariff, Network, Site - are named the modern way and are `sensor.localvolts_<nmi>_demand_flex_up`, `..._import_tariff`, `..._export_tariff`, `..._network`, `..._site` on every version.

**Removing and re-adding.** Home Assistant remembers deleted entities for 30 days. Remove the integration and add it back within that time and every entity gets its original ID, name and history back. After 30 days it generates new IDs and the old history is left under the old ones; renaming an entity back to its original ID (Settings → Entities → the entity → Entity ID) reattaches it. The log will warn that it "cannot migrate history because the new entity_id is already in use" - that refers to the few rows recorded under the interim ID, which are dropped; the original history is live again.

The integration's three-dot menu offers **Recreate entity IDs**, which renames existing entities to the current rule. It does *not* update automations, scripts, scenes or dashboards that reference the old IDs - you edit those yourself - so there is no reason to use it unless you want the consistency.

## The forecast record

`sensor.forecasted_costs_flex_up`'s `forecast` attribute is a list of about 287 entries, one per 5-minute interval for the next 24 hours, each carrying every field the Localvolts API returns for that interval. One entry:

```yaml
forecast:
  - NMI: '4100000000'
    intervalDuration: '5'
    intervalDurationUnits: minutes
    intervalEnd: '2026-08-19T06:40:00Z'
    exportsAll: 0
    exportsAllUnits: kWh
    importsAll: 0.235
    importsAllUnits: kWh
    demandMain: 1.41
    demandMainUnits: kW
    demandPeriod: 30
    demandPeriodUnits: minutes
    demandInterval: 1
    earningsAll: 0
    earningsAllUnits: cents
    earningsAllVar: 0
    earningsAllVarUnits: cents
    earningsAllFixed: 0
    earningsAllFixedUnits: cents
    earningsAllVarRate: N/A
    earningsAllVarRateUnits: c/kWh
    earningsFlexUp: 7.48652
    earningsFlexDown: -7.48651605
    earningsFlexUnits: c/kWh
    costsAll: 3.54601201
    costsAllUnits: cents
    costsAllVar: 2.96613215
    costsAllVarUnits: cents
    costsAllFixed: 0.57987986
    costsAllFixedUnits: cents
    costsDemandMain: 39.485
    costsDemandMainUnits: c/kW/Day
    costsDemandRate: 39.485
    costsDemandRateUnits: c/kW/Day
    costsAllVarRate: '12.62183895'
    costsAllVarRateUnits: c/kWh
    costsFlexUp: 12.62184
    costsFlexDown: -12.62183895
    costsFlexUnits: c/kWh
    exportsAllEmissions: 0
    exportsAllEmissionsUnits: g-CO2e
    importsAllEmissions: 166.427
    importsAllEmissionsUnits: g-CO2e
    exportsAllZeroEE: 1
    exportsAllZeroEEUnits: '%'
    importsAllZeroEE: '0.21490000'
    importsAllZeroEEUnits: '%'
    quality: Fcst
    lastUpdate: '2026-08-19 06:31:44'
    duration: 5
    start_time: '2026-08-19T06:35:00+00:00'
    end_time: '2026-08-19T06:40:00+00:00'
  # ...286 more entries, same shape

  forecastcount: 287
```

`duration`, `start_time` and `end_time` are added by the integration for convenience; everything else is the API's. Values documented as `N/A` arrive as that string when there is nothing to price.

**The recorder.** That list is far over Home Assistant's size limit for stored attributes, so the integration tells the recorder to skip just that one attribute. The sensor's price still records and has statistics; only the rolling forecast list is not kept in history. If you have a `recorder: exclude:` entry for `sensor.forecasted_costs_flex_up` from a very old version, remove it - it now also blocks the price history.

## When prices stop arriving

The sensors report `unavailable` 90 seconds after the current interval ends without a fresh price. If that lasts more than five minutes, the integration logs a warning:

```
No fresh interval data for 18m12s (newest intervalEnd 2026-10-04T23:05:00+00:00);
last response 12s ago: 288 records (fcst=288), newest settled intervalEnd none
```

The second half distinguishes the two ways this can happen. A recent "last response" with only forecasts (`fcst=288`) and no settled interval means Localvolts are answering normally but have nothing settled to publish - usually an upstream problem, nothing at your end, and the integration will pick the prices up the moment they appear. A much older "last response" means requests aren't getting through, which is normally your own network or DNS. A second warning marks the recovery, with the length of the gap.

While unavailable, the integration polls every second for the first 45 seconds past each interval boundary, then eases off to every 30 seconds, with a little randomness so that every installation doesn't hit the API at once. Hard failures (timeouts, connection errors) back off from 5 to 30 seconds.

## Filling gaps in the statistics

Home Assistant builds an hourly statistic for each price sensor from the twelve 5-minute windows in the hour. When a price arrives late, the window is still written - from the previous interval's price, carried forward - so the hour looks complete and holds a value that was never published. Counting windows therefore can't find these hours; the integration instead counts the intervals that actually arrived, from `IntervalEnd`'s history.

On startup and once an hour, for the previous 71 hours (the API serves 72):

1. Find hours that received fewer than twelve intervals.
2. Fetch those hours from the API and keep only settled records (`Exp` or `Act`) - a forecast is never used, even when the API serves one for a past interval.
3. Where the API has more settled intervals for an hour than were received, rewrite that hour's mean, minimum and maximum from the published prices.
4. Remember every hour asked about, so it isn't fetched again. Hours still short of twelve are asked about again at the next startup, in case a late interval has since appeared.

Only `costsFlexUp` and `earningsFlexUp` are repaired: prices are authoritative within the 72-hour window, while consumption and cost figures aren't settled until the following day. Long-term statistics are repaired; the History graph is not, as Home Assistant has no way to import past states. Nothing is invented - if Localvolts never published an interval, the hour is left alone. A gap older than 72 hours when found is permanent; gaps are normally found within an hour.

A repaired hour's mean can move either way, depending on which way prices were moving across the gap. If the recorder is disabled, none of this runs.

The integration's diagnostics download (device page → three dots → Download diagnostics) shows what the repair has done and what the last sweep concluded. For a line per sweep in the log, add `custom_components.localvolts.backfill: debug` under `logger: logs:`.

## API usage

Per 5-minute interval: one request for the price (polling tightly only until it arrives), and one small request for demand flex after it has. Per day: one request for site metadata. Per hour: a history request only when a gap has been found. Interval prices come from Localvolts' v1 API; site metadata and demand flex from v2. Every request identifies itself with a `User-Agent` of `ha-localvolts/<version>`.
