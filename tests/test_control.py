from __future__ import annotations

from heating.control import run_cycle
from heating.models import BoilerDecision, ControlContext, RoomResult
from heating.settings import Settings


class FakePrices:
    def __init__(self, current, daily, tomorrow=None):
        self._c, self._d, self._t = current, daily, tomorrow

    def current_price(self):
        return self._c

    def daily_prices(self):
        return self._d

    def tomorrow_prices(self):
        return self._t


class CapturePublisher:
    def __init__(self):
        self.calls = []

    def publish(self, ctx, rooms, boiler, *, price_avg, price_avg_ex_top):
        self.calls.append((ctx, rooms, boiler))


def settings(tmp_path, **kw) -> Settings:
    return Settings(ha_api_token="x", zones_file=str(tmp_path / "z.yaml"), **kw)  # type: ignore[call-arg]


ZONES = """
boiler:
  switch_entity: switch.boiler
  inverted: true
  price_always_on_threshold: 5.0
  max_shutoff_hours: 6.0
rooms:
  items:
    - id: olo
      control: onoff
      temp_sensor: sensor.olo
      switch_entity: switch.olo
      base_temp_fallback: 21.0
      requests_boiler_heat: true
    - id: kylpy
      control: trv
      temp_sensor: sensor.kylpy
      trv_ext_temp_service: rest_command.kylpy
"""


def test_full_cycle_actuates_and_publishes(tmp_path, fake_ha):
    (tmp_path / "z.yaml").write_text(ZONES)
    fake_ha.states.update({"sensor.olo": 19.0, "sensor.kylpy": 22.0})
    prices = FakePrices(8.0, [8.0] * 96)
    pub = CapturePublisher()

    run_cycle(settings(tmp_path), fake_ha, prices, pub)

    assert ("switch.olo", True) in fake_ha.switch_calls
    assert any(d == "rest_command" and s == "kylpy" for d, s, _ in fake_ha.service_calls)
    # boiler: price 8 >= always_on 5, not enough prices to be "top" -> would run anyway;
    # olo requests heat and is below setpoint -> boiler on -> inverted switch OFF
    assert ("switch.boiler", False) in fake_ha.switch_calls

    ctx, rooms, boiler = pub.calls[0]
    assert isinstance(ctx, ControlContext)
    assert {r.zone_id for r in rooms} == {"olo", "kylpy"}
    assert isinstance(boiler, BoilerDecision) and boiler.should_run is True


def test_forced_on_overrides_price_block(tmp_path, fake_ha):
    (tmp_path / "z.yaml").write_text(ZONES)
    fake_ha.states.update({"sensor.olo": 19.0, "sensor.kylpy": 22.0})
    # current price is the single most expensive quarter -> would block
    prices = FakePrices(50.0, [10.0] * 95 + [50.0])
    pub = CapturePublisher()

    run_cycle(settings(tmp_path), fake_ha, prices, pub)

    # olo below setpoint and requests heat -> boiler forced on -> inverted switch OFF
    assert ("switch.boiler", False) in fake_ha.switch_calls
    _, _, boiler = pub.calls[0]
    assert boiler.forced is True and boiler.should_run is True


def test_dry_run_no_actuation(tmp_path, fake_ha):
    (tmp_path / "z.yaml").write_text(ZONES)
    fake_ha.states.update({"sensor.olo": 19.0, "sensor.kylpy": 22.0})
    run_cycle(
        settings(tmp_path, dry_run=True), fake_ha, FakePrices(8.0, [8.0] * 96), CapturePublisher()
    )
    assert fake_ha.switch_calls == []
    assert fake_ha.service_calls == []


def test_no_price_aborts(tmp_path, fake_ha):
    (tmp_path / "z.yaml").write_text(ZONES)
    pub = CapturePublisher()
    run_cycle(settings(tmp_path), fake_ha, FakePrices(None, []), pub)
    assert pub.calls == []
    assert fake_ha.switch_calls == []


def test_bad_zones_aborts(tmp_path, fake_ha):
    (tmp_path / "z.yaml").write_text(
        "rooms:\n  items:\n    - id: x\n      control: onoff\n      temp_sensor: s\n"
    )
    pub = CapturePublisher()
    run_cycle(settings(tmp_path), fake_ha, FakePrices(8.0, [8.0] * 96), pub)
    assert pub.calls == []


def test_result_objects_shape():
    r = RoomResult("z", None, False, 0.0, "d")  # type: ignore[arg-type]
    assert r.setpoint is None and r.trv_temp is None and r.actuated is False
