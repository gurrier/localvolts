"""Tests for the Localvolts coordinator's scheduling and parsing logic.

Home Assistant isn't installed here - the handful of modules the coordinator
imports are stubbed below, which is enough to exercise everything that isn't
Home Assistant's own behaviour: when we poll, when the data counts as stale,
what gets logged when it stops arriving, and which record out of a response
we actually believe.

Run it either way:

    python tests/test_coordinator.py     # no pytest needed
    pytest tests/

Only aiohttp and python-dateutil are required, both of which the integration
already depends on.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import importlib.util
import statistics
import sys
import types
from pathlib import Path

UTC = dt.timezone.utc
td = dt.timedelta


# --- stand in for the Home Assistant modules coordinator.py imports ---------
def _install_stubs() -> None:
    ha = types.ModuleType("homeassistant")
    ha.__path__ = []
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    helpers = types.ModuleType("homeassistant.helpers")
    helpers.__path__ = []
    aiohttp_client = types.ModuleType("homeassistant.helpers.aiohttp_client")
    aiohttp_client.async_get_clientsession = lambda hass: None
    update_coordinator = types.ModuleType("homeassistant.helpers.update_coordinator")

    class UpdateFailed(Exception):
        pass

    class DataUpdateCoordinator:
        def __init__(self, hass, logger, config_entry=None, name="", update_interval=None):
            self.logger = logger
            self.name = name
            self.update_interval = update_interval
            self.last_update_success = True
            self.data = None
            self.notified = 0

        def async_update_listeners(self):
            self.notified += 1

    update_coordinator.UpdateFailed = UpdateFailed
    update_coordinator.DataUpdateCoordinator = DataUpdateCoordinator

    # The backfill module reaches into the recorder; none of it is exercised
    # by these tests, which cover the pure grouping and comparison logic.
    components = types.ModuleType("homeassistant.components")
    components.__path__ = []
    recorder = types.ModuleType("homeassistant.components.recorder")
    recorder.__path__ = []
    recorder.get_instance = lambda hass: None
    rec_models = types.ModuleType("homeassistant.components.recorder.models")
    rec_models.StatisticData = dict
    rec_history = types.ModuleType("homeassistant.components.recorder.history")
    rec_history.state_changes_during_period = lambda *a, **k: {}
    rec_stats = types.ModuleType("homeassistant.components.recorder.statistics")
    rec_stats.async_import_statistics = lambda *a, **k: None
    rec_stats.get_metadata = lambda *a, **k: {}
    rec_stats.statistics_during_period = lambda *a, **k: {}
    event = types.ModuleType("homeassistant.helpers.event")
    event.async_track_time_interval = lambda *a, **k: None
    entity_registry = types.ModuleType("homeassistant.helpers.entity_registry")
    entity_registry.async_get = lambda hass: None
    entity_registry.async_entries_for_config_entry = lambda reg, entry_id: []
    storage = types.ModuleType("homeassistant.helpers.storage")

    class Store:
        """An in-memory stand-in, shared between instances like the real files."""

        files: dict[str, dict] = {}

        def __init__(self, hass, version, key):
            self.key = key

        async def async_load(self):
            data = Store.files.get(self.key)
            return dict(data) if data is not None else None

        async def async_save(self, data):
            Store.files[self.key] = dict(data)

    storage.Store = Store
    util = types.ModuleType("homeassistant.util")
    util.__path__ = []
    util_dt = types.ModuleType("homeassistant.util.dt")
    util_dt.utcnow = lambda: dt.datetime.now(UTC)
    util_dt.utc_from_timestamp = lambda ts: dt.datetime.fromtimestamp(ts, UTC)

    for module in (ha, core, helpers, aiohttp_client, update_coordinator, components,
                   recorder, rec_history, rec_models, rec_stats, event, entity_registry,
                   storage, util, util_dt):
        sys.modules[module.__name__] = module


_install_stubs()

# Load the integration's modules as a package, so their relative imports work
# without Home Assistant having to be installed.
_PACKAGE = Path(__file__).resolve().parent.parent / "custom_components" / "localvolts"
_pkg = types.ModuleType("localvolts_under_test")
_pkg.__path__ = [str(_PACKAGE)]
sys.modules["localvolts_under_test"] = _pkg


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"localvolts_under_test.{name}", _PACKAGE / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


C = _load("coordinator")
B = _load("backfill")


def make() -> "C.LocalvoltsDataUpdateCoordinator":
    return C.LocalvoltsDataUpdateCoordinator(None, None, "k" * 32, "1234", "NMI1")


# --- a fake API, so the parsing half can be driven end to end --------------
class _Response:
    def __init__(self, payload):
        self.status = 200
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self):
        return self._payload

    async def text(self):
        return ""

    def raise_for_status(self):
        pass


class _Session:
    def __init__(self, payload):
        self._payload = payload

    def get(self, url, headers=None, timeout=None):
        return _Response(self._payload)


def serving(payload):
    """A coordinator whose next fetch returns `payload`."""
    c = make()
    C.async_get_clientsession = lambda hass: _Session(payload)
    return c


BASE = dt.datetime.now(UTC).replace(second=0, microsecond=0)


def record(end_offset_min: int, lag_s: int = 18, price: float = 0.2, quality: str = "Exp", **over):
    """One API record, `lag_s` seconds after its interval started."""
    end = BASE + td(minutes=end_offset_min)
    item = {
        "quality": quality,
        "intervalEnd": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lastUpdate": (end - td(minutes=5) + td(seconds=lag_s)).strftime("%Y-%m-%d %H:%M:%S"),
        "costsFlexUp": price,
        "intervalDuration": "5",
    }
    item.update(over)
    return item


# --- the schedule ----------------------------------------------------------
def test_flat_phase_is_exact_and_unjittered():
    """Normal operation must poll exactly as hard as it ever did."""
    for seconds in (0, 1, 20, 44, 45):
        got = C.LocalvoltsDataUpdateCoordinator._catchup_interval(td(seconds=seconds))
        assert got == C.CATCHUP_POLL_INTERVAL, f"{seconds}s -> {got}"


def test_ramp_reaches_the_cap_and_stays():
    """Jitter averages out; the mean should trace the ramp."""
    for seconds, expected in ((60, 2.7), (90, 6.1), (180, 16.4), (300, 30.0), (900, 30.0)):
        draws = [
            C.LocalvoltsDataUpdateCoordinator._catchup_interval(td(seconds=seconds)).total_seconds()
            for _ in range(400)
        ]
        assert abs(statistics.mean(draws) - expected) < 0.6, f"{seconds}s -> {statistics.mean(draws)}"


def test_jitter_stays_within_bounds():
    draws = [
        C.LocalvoltsDataUpdateCoordinator._catchup_interval(td(seconds=600)).total_seconds()
        for _ in range(2000)
    ]
    cap = C.CATCHUP_SLOWEST.total_seconds()
    assert min(draws) >= cap * (1 - C.CATCHUP_JITTER) - 0.01
    assert max(draws) <= cap * (1 + C.CATCHUP_JITTER) + 0.01
    assert len({round(d, 2) for d in draws}) > 100, "jitter should actually vary"


def test_normal_intervals_cost_the_same_as_flat_one_second_polling():
    """The ramp must not cost a single extra poll on a healthy interval."""
    def polls(schedule, arrival, dead=11):
        t, n = dead, 0
        while t <= arrival:
            n += 1
            t += schedule(t)
        return n

    flat = lambda t: 1.0  # noqa: E731
    ramped = lambda t: C.LocalvoltsDataUpdateCoordinator._catchup_interval(  # noqa: E731
        td(seconds=t)
    ).total_seconds()
    for arrival in (18, 29, 39, 45):  # p50, p95, p99, end of the flat phase
        assert polls(flat, arrival) == polls(ramped, arrival), arrival


def test_schedule_outside_the_catchup_window():
    c, now = make(), dt.datetime.now(UTC)
    c.intervalEnd = None
    assert c._next_update_interval(now) == C.SCAN_INTERVAL
    c.intervalEnd = now + td(seconds=200)
    assert c._next_update_interval(now) == td(seconds=200) + C.POST_BOUNDARY_DEAD_WINDOW


def test_hard_failures_take_precedence_and_back_off():
    c, now = make(), dt.datetime.now(UTC)
    c.intervalEnd = now - td(seconds=200)
    for failures, expected in ((1, 5), (2, 10), (3, 20), (4, 30), (9, 30)):
        c._consecutive_failures = failures
        assert c._next_update_interval(now).total_seconds() == expected, failures


# --- staleness and the outage announcement ---------------------------------
def test_staleness_boundary():
    c, now = make(), dt.datetime.now(UTC)
    assert c.data_is_stale, "no data yet must count as stale"
    c.intervalEnd = now + td(seconds=60)
    assert not c.data_is_stale
    c.intervalEnd = now - C.STALE_AFTER + td(seconds=1)
    assert not c.data_is_stale
    c.intervalEnd = now - C.STALE_AFTER - td(seconds=1)
    assert c.data_is_stale


def test_outage_is_announced_once_and_cleared_on_recovery():
    c = make()
    c._last_response_at = dt.datetime.now(UTC)
    c._last_record_count = 288
    c._last_quality_counts = {"fcst": 288}
    c.intervalEnd = dt.datetime.now(UTC) - C.OUTAGE_WARN_AFTER + td(seconds=30)
    c._announce_outage_state()
    assert c._outage_announced_end is None, "must stay quiet before the threshold"

    c.intervalEnd = dt.datetime.now(UTC) - td(minutes=18)
    c._announce_outage_state()
    announced = c._outage_announced_end
    assert announced is not None
    c._announce_outage_state()
    assert c._outage_announced_end is announced, "must announce only once"

    c.intervalEnd = dt.datetime.now(UTC) + td(minutes=4)
    c._announce_outage_state()
    assert c._outage_announced_end is None, "recovery must clear it"


def test_response_summary_names_what_arrived():
    c = make()
    c._last_response_at = dt.datetime.now(UTC)
    c._last_record_count = 288
    c._last_quality_counts = {"fcst": 288}
    c._last_settled_end = None
    summary = c._describe_last_response()
    assert "288 records" in summary and "fcst=288" in summary
    assert "newest settled intervalEnd none" in summary


# --- parsing ---------------------------------------------------------------
def test_newest_settled_record_wins_regardless_of_order():
    c = serving([record(0, price=0.10), record(10, price=0.30), record(5, price=0.20),
                 record(60, price=0.9, quality="Fcst")])
    asyncio.run(c._fetch_update_data())
    assert c.interval_data["costsFlexUp"] == 0.30
    assert c.intervalEnd == BASE + td(minutes=10)
    assert c._last_quality_counts == {"exp": 3, "fcst": 1}
    assert len(c.forecast_data) == 1


def test_an_older_record_cannot_drag_the_interval_backwards():
    c = serving([record(-20, price=0.99)])
    c.intervalEnd = BASE
    c.interval_data = {"costsFlexUp": 0.25}
    asyncio.run(c._fetch_update_data())
    assert c.intervalEnd == BASE
    assert c.interval_data["costsFlexUp"] == 0.25
    assert c._last_settled_end == BASE - td(minutes=20), "but it should still be counted"


def test_a_revised_record_for_the_same_interval_is_accepted():
    c = serving([record(-1, lag_s=120, price=0.44)])
    c.intervalEnd = BASE - td(minutes=1)
    c.interval_data = {"costsFlexUp": 0.25}
    asyncio.run(c._fetch_update_data())
    assert c.interval_data["costsFlexUp"] == 0.44
    assert c.intervalEnd == BASE - td(minutes=1), "a republish must not reset the staleness clock"


def test_no_request_is_made_mid_interval():
    c = serving([record(5, price=0.44)])
    c.intervalEnd = BASE + td(minutes=5)
    c.interval_data = {"costsFlexUp": 0.25}
    asyncio.run(c._fetch_update_data())
    assert c.interval_data["costsFlexUp"] == 0.25


def test_a_live_api_error_is_reported_rather_than_parsed():
    """The API answers a bad request with HTTP 200 and an error object, so it
    reaches the parser looking like one unusable record."""
    c = serving([{"error": "Invalid NMI"}])
    try:
        asyncio.run(c._fetch_update_data())
    except C.UpdateFailed as err:
        assert "Invalid NMI" in str(err), "the API's own complaint should survive"
    else:
        raise AssertionError("an error response must not pass as data")
    assert c.interval_data == {}, "and nothing should be believed from it"


def test_a_malformed_record_does_not_cost_a_good_one():
    bad = record(5, price=0.5)
    bad["intervalEnd"] = "not-a-date"
    c = serving([bad, record(10, price=0.31)])
    asyncio.run(c._fetch_update_data())
    assert c.interval_data["costsFlexUp"] == 0.31


def test_data_lag_is_measured_from_the_interval_start():
    c = serving([record(5, lag_s=18)])
    c.intervalEnd = BASE
    asyncio.run(c._fetch_update_data())
    assert int(c.time_past_start.total_seconds()) == 18


def test_an_unmeasured_lag_is_distinct_from_a_zero_one():
    c = serving([record(5, lag_s=18)])
    assert c.time_past_start is None, "nothing measured yet"
    asyncio.run(c._fetch_update_data())
    assert c.time_past_start is None, "the first fetch of a boot measures nothing"

    c = serving([record(5, lag_s=0)])
    c.intervalEnd = BASE
    asyncio.run(c._fetch_update_data())
    assert c.time_past_start == td(0), "a real zero-second lag is a reading, not a blank"


# --- statistics repair -----------------------------------------------------
def test_an_interval_belongs_to_the_hour_it_ends_within():
    """intervalEnd is the end of the interval, so 07:00 closes the 06:00 hour."""
    def at(h, m):
        return dt.datetime(2026, 10, 15, h, m, tzinfo=UTC)
    assert B.statistics_hour(at(6, 5)) == at(6, 0)
    assert B.statistics_hour(at(6, 55)) == at(6, 0)
    assert B.statistics_hour(at(7, 0)) == at(6, 0)   # the boundary case
    assert B.statistics_hour(at(7, 5)) == at(7, 0)


def test_summarise_matches_the_recorders_arithmetic():
    prices = [0.150, 0.156, 0.161, 0.160, 0.160, 0.158,
              0.156, 0.156, 0.170, 0.167, 0.165, 0.163]
    got = B.summarise(prices)
    assert round(got["mean"], 6) == 0.160167
    assert got["min"] == 0.150
    assert got["max"] == 0.170


def test_a_filled_window_does_not_mean_the_price_arrived():
    """13 Oct 2026: 11 intervals arrived, yet all 12 windows were written.

    A late price leaves the window populated with the previous interval's
    value carried forward, so counting windows reports the hour complete when
    it isn't. The repair compares intervals received, not windows recorded.
    """
    hour = dt.datetime(2026, 10, 12, 18, 0, tzinfo=UTC)
    windows_recorded = {hour: 12}
    intervals_received = {hour: 11}
    api_has = {hour: 12}
    assert B.hours_needing_repair(windows_recorded, api_has) == [], "window count hides it"
    assert B.hours_needing_repair(intervals_received, api_has) == [hour], "interval count finds it"


def test_an_api_error_is_not_mistaken_for_data():
    """The API answers a bad request with HTTP 200 and an error object.

    Nothing upstream notices, so the records just look malformed and the
    sweep concludes there is nothing to repair. It has to be checked for.
    """
    assert B.api_error([{"error": "'from' date cannot be more than 3 days in the past "}]) \
        == "'from' date cannot be more than 3 days in the past"
    assert B.api_error([{"intervalEnd": "2026-10-15T00:00:00Z", "costsFlexUp": 1.0}]) is None
    assert B.api_error([]) is None
    assert B.api_error({"unexpected": True}) is None


def test_the_fetch_window_stays_inside_the_apis_limits():
    """Verified against the live API: 72h back is refused, as is a 24h span."""
    assert B.LOOKBACK < dt.timedelta(hours=72)
    assert B.MAX_FETCH_SPAN < dt.timedelta(hours=24)


def test_only_hours_the_api_can_improve_are_repaired():
    hour = dt.datetime(2026, 10, 15, 5, 0, tzinfo=UTC)
    other = hour + td(hours=1)
    # recorded 11, API has 12 -> repair; both 12 -> leave alone
    assert B.hours_needing_repair({hour: 11, other: 12}, {hour: 12, other: 12}) == [hour]
    # home assistant never wrote the hour at all
    assert B.hours_needing_repair({}, {hour: 12}) == [hour]
    # Localvolts never published the interval either - nothing to add
    assert B.hours_needing_repair({hour: 11}, {hour: 11}) == []
    # the API knows less than we do; never make the record worse
    assert B.hours_needing_repair({hour: 12}, {hour: 9}) == []


def test_grouping_real_records_into_an_hour():
    """The 05:00 hour from 15 Oct 2026, the morning of a 10-minute stall."""
    prices = [14.97705076, 15.5825778, 16.13043559, 16.01048357, 16.00587003,
              15.77865322, 15.57335072, 15.57335072, 16.99662759, 16.67252646,
              16.51220597, 16.31613055]
    records = []
    for n, price in enumerate(prices, start=1):
        end = dt.datetime(2026, 10, 14, 18, 0, tzinfo=UTC) + td(minutes=5 * n)
        records.append({"intervalEnd": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "costsFlexUp": price, "quality": "Exp"})
    records.append({"intervalEnd": "not-a-date", "costsFlexUp": 99.0})
    records.append({"intervalEnd": "2026-10-14T18:05:00Z"})          # no price
    by_hour = B.group_by_hour(records, "costsFlexUp")
    hour = dt.datetime(2026, 10, 14, 18, 0, tzinfo=UTC)
    assert list(by_hour) == [hour], "all twelve belong to one hour"
    assert len(by_hour[hour]) == 12, "and the malformed records are dropped"
    assert by_hour[hour][0] == 0.150, "converted to $/kWh and rounded as the sensor does"
    assert round(B.summarise(by_hour[hour])["mean"], 6) == 0.160167


# --- a repair wired to fakes, to exercise a whole sweep --------------------
class _Executor:
    """Stands in for the recorder instance; runs the job inline."""

    async def async_add_executor_job(self, fn, *args):
        return fn(*args)


class _RegistryEntry:
    def __init__(self, unique_id, entity_id):
        self.unique_id = unique_id
        self.entity_id = entity_id


class _Coordinator:
    nmi_id = "NMI1"
    api_key = "k" * 32
    partner_id = "1234"
    user_agent = "ha-localvolts/test"


class _Hass:
    class config:
        components = {"recorder", "sensor"}


ENTITIES = {
    "NMI1_costsFlexUp": "sensor.localvolts_costsflexup",
    "NMI1_earningsFlexUp": "sensor.localvolts_earningsflexup",
    "NMI1_interval_end": "sensor.localvolts_intervalend",
}


def repair_window():
    """The window a sweep would choose right now."""
    end = (dt.datetime.now(UTC) - B.COMPILE_MARGIN).replace(
        minute=0, second=0, microsecond=0
    )
    return end - B.LOOKBACK, end


def make_repair(short_hours: dict, api_counts: dict):
    """A StatisticsRepair over a window that is complete but for short_hours.

    short_hours maps an hour to how many intervals were received; api_counts
    maps an hour to how many the API will offer. Every other hour in the
    window got all twelve, so it is never a candidate.
    """
    start, end = repair_window()
    received = {}
    hour = start
    while hour < end:
        received[hour] = short_hours.get(hour, B.INTERVALS_PER_HOUR)
        hour += td(hours=1)

    records = []
    for hour, count in api_counts.items():
        for n in range(1, count + 1):
            interval_end = hour + td(minutes=5 * n)
            records.append({
                "intervalEnd": interval_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "costsFlexUp": 10.0 + n,
                "earningsFlexUp": 8.0 + n,
                "quality": "Act",
            })

    B.Store.files.clear()
    repair = B.StatisticsRepair(_Hass(), _Coordinator(), types.SimpleNamespace(entry_id="e1"))
    log = types.SimpleNamespace(fetches=0, imports=[])

    B.er.async_entries_for_config_entry = lambda reg, entry_id: [
        _RegistryEntry(u, e) for u, e in ENTITIES.items()
    ]
    B.get_instance = lambda hass: _Executor()
    B.get_metadata = lambda hass, statistic_ids=None: {
        entity_id: (1, {"statistic_id": entity_id}) for entity_id in statistic_ids
    }
    B.async_import_statistics = lambda hass, meta, rows: log.imports.append(
        (meta["statistic_id"], [row["start"] for row in rows])
    )

    async def _fetch(fetch_start, fetch_end):
        log.fetches += 1
        return records

    repair._fetch = _fetch
    repair._intervals_received = lambda s, e: _done(received)
    return repair, log


async def _done(value):
    return value


def test_a_repaired_hour_is_not_fetched_again():
    """The whole point: the evidence of the gap outlives the gap."""
    _, end = repair_window()
    hour = end - td(hours=3)
    repair, log = make_repair({hour: 11}, {hour: 12})

    asyncio.run(repair.async_run(first_run=True))
    assert log.fetches == 1, "the short hour should be investigated"
    assert sorted(entity for entity, _ in log.imports) == [
        "sensor.localvolts_costsflexup", "sensor.localvolts_earningsflexup",
    ], "and both prices rewritten"
    assert log.imports[0][1] == [hour]

    asyncio.run(repair.async_run())
    assert log.fetches == 1, "a later sweep must not ask about it again"
    assert len(log.imports) == 2, "nor import the same hour twice"


def test_an_hour_the_api_cannot_improve_is_still_remembered():
    """An hour the API has nothing better for would otherwise be asked about
    on every sweep for 71 hours, forever answering the same way."""
    _, end = repair_window()
    hour = end - td(hours=3)
    repair, log = make_repair({hour: 11}, {hour: 11})

    asyncio.run(repair.async_run(first_run=True))
    assert log.fetches == 1
    assert log.imports == [], "nothing to add, so nothing written"

    asyncio.run(repair.async_run())
    assert log.fetches == 1, "the question has been asked and answered"


def test_a_restart_asks_again_about_an_incomplete_hour():
    """A late interval can still turn up, so a startup sweep re-checks."""
    _, end = repair_window()
    hour = end - td(hours=3)
    repair, log = make_repair({hour: 11}, {hour: 11})

    asyncio.run(repair.async_run(first_run=True))
    asyncio.run(repair.async_run())
    assert log.fetches == 1
    asyncio.run(repair.async_run(first_run=True))
    assert log.fetches == 2, "but an hour short of twelve is worth one more look"


def test_a_complete_window_costs_no_api_calls():
    repair, log = make_repair({}, {})
    asyncio.run(repair.async_run(first_run=True))
    assert log.fetches == 0
    assert log.imports == []


def test_nothing_is_remembered_before_the_statistics_exist():
    """Marking hours done while there is no series to repair would lose them."""
    _, end = repair_window()
    hour = end - td(hours=3)
    repair, log = make_repair({hour: 11}, {hour: 12})
    B.get_metadata = lambda hass, statistic_ids=None: {}

    asyncio.run(repair.async_run(first_run=True))
    assert log.imports == []
    assert B.Store.files.get("e1_statistics_repair") in (None, {})

    B.get_metadata = lambda hass, statistic_ids=None: {
        entity_id: (1, {"statistic_id": entity_id}) for entity_id in statistic_ids
    }
    asyncio.run(repair.async_run())
    assert len(log.imports) == 2, "once the series exists, the hour is repaired"


def test_repairs_outside_the_window_are_forgotten():
    start, end = repair_window()
    repair, _ = make_repair({}, {})
    stale = (start - td(hours=5)).isoformat()
    fresh = (end - td(hours=2)).isoformat()
    B.Store.files["e1_statistics_repair"] = {stale: 12, fresh: 12}

    remembered = asyncio.run(repair._load_done(start))
    assert stale not in remembered, "an hour the API no longer serves is dead weight"
    assert fresh in remembered


# --- runner, so this works without pytest ----------------------------------
def _main() -> int:
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
        except AssertionError as err:
            failed += 1
            print(f"FAIL  {name}: {err}")
        except Exception as err:  # noqa: BLE001 - a broken test is still a failure
            failed += 1
            print(f"ERROR {name}: {type(err).__name__}: {err}")
        else:
            print(f"pass  {name}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
