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
    for module in (ha, core, helpers, aiohttp_client, update_coordinator):
        sys.modules[module.__name__] = module


_install_stubs()
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "custom_components" / "localvolts"))
import coordinator as C  # noqa: E402


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
