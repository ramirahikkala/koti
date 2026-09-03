from __future__ import annotations

from koti.heating.control import run_cycle
from koti.heating.models import BoilerDecision, ControlContext, RoomResult
from koti.heating.settings import Settings
from tests.conftest import FakeBus


class FakePrices:
    def __init__(self, current, daily, tomorrow=None):
        self._c, self._d, self._t = current, daily, tomorrow

    def current_price(self):
        return self._c

    def daily_prices(self):
        return self._d

    def tomorrow_prices(self):
        return self._t


def settings(tmp_path, **kw) -> Settings:
    return Settings(zones_file=str(tmp_path / "z.yaml"), **kw)  # type: ignore[call-arg]


ZONES = """
boiler:
  switch_topic: shelly-boiler
  inverted: true
  price_always_on_threshold: 5.0
  max_shutoff_hours: 6.0
rooms:
  items:
    - id: olo
      control: onoff
      temp_topic: gw/olo/state
      switch_topic: shelly-olo
      base_temp: {default: 21.0}
      requests_boiler_heat: true
    - id: kylpy
      control: trv
      temp_topic: gw/kylpy/state
      trv_ext_temp_topic: shellies/trv-kylpy/ext_t/0
"""


def _bus(**temps) -> FakeBus:
    return FakeBus(values=dict(temps))


def test_full_cycle_actuates_and_publishes(tmp_path):
    (tmp_path / "z.yaml").write_text(ZONES)
    bus = _bus(**{"gw/olo/state": 19.0, "gw/kylpy/state": 22.0})
    prices = FakePrices(8.0, [8.0] * 96)

    run_cycle(settings(tmp_path), prices, bus)

    assert ("shelly-olo", True, "switch:0") in bus.switch_calls
    # kylpy 22.0 + (8-5)/5 = 22.6
    assert bus.raw_publishes == [("shellies/trv-kylpy/ext_t/0", "22.6")]
    # boiler: price 8 >= always_on 5 -> runs; inverted -> switch OFF
    assert ("shelly-boiler", False, "switch:0") in bus.switch_calls

    ctx, rooms, boiler = bus.publish_calls[0]
    assert isinstance(ctx, ControlContext)
    assert {r.zone_id for r in rooms} == {"olo", "kylpy"}
    assert isinstance(boiler, BoilerDecision) and boiler.should_run is True
    assert "heating_olo_base_temp" in bus.registered_numbers


def test_forced_on_overrides_price_block(tmp_path):
    (tmp_path / "z.yaml").write_text(ZONES)
    bus = _bus(**{"gw/olo/state": 19.0, "gw/kylpy/state": 22.0})
    # current price is the single most expensive quarter -> would block
    prices = FakePrices(50.0, [10.0] * 95 + [50.0])

    run_cycle(settings(tmp_path), prices, bus)

    # olo below setpoint and requests heat -> boiler forced on -> inverted switch OFF
    assert ("shelly-boiler", False, "switch:0") in bus.switch_calls
    _, _, boiler = bus.publish_calls[0]
    assert boiler.forced is True and boiler.should_run is True


def test_dry_run_no_actuation(tmp_path):
    (tmp_path / "z.yaml").write_text(ZONES)
    bus = _bus(**{"gw/olo/state": 19.0, "gw/kylpy/state": 22.0})
    run_cycle(settings(tmp_path, dry_run=True), FakePrices(8.0, [8.0] * 96), bus)
    assert bus.switch_calls == []
    assert bus.raw_publishes == []


def test_no_price_aborts(tmp_path):
    (tmp_path / "z.yaml").write_text(ZONES)
    bus = _bus()
    run_cycle(settings(tmp_path), FakePrices(None, []), bus)
    assert bus.publish_calls == []
    assert bus.switch_calls == []


def test_bad_zones_aborts(tmp_path):
    (tmp_path / "z.yaml").write_text(
        "rooms:\n  items:\n    - id: x\n      control: onoff\n      temp_topic: s\n"
    )
    bus = _bus()
    run_cycle(settings(tmp_path), FakePrices(8.0, [8.0] * 96), bus)
    assert bus.publish_calls == []


def test_result_objects_shape():
    r = RoomResult("z", None, False, 0.0, "d")  # type: ignore[arg-type]
    assert r.setpoint is None and r.trv_temp is None and r.actuated is False
