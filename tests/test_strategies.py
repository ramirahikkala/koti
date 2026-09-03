from __future__ import annotations

from datetime import datetime

from koti.heating.models import ControlContext, RoomConfig, RoomControl
from koti.heating.strategies import strategy_for


def ctx(price: float) -> ControlContext:
    return ControlContext(
        now=datetime(2026, 1, 1, 12, 0),
        current_price=price,
        daily_prices=[price] * 96,
        tomorrow_prices=None,
        outdoor_temp=None,
    )


def onoff_room(**kw) -> RoomConfig:
    base = dict(
        id="olo",
        control=RoomControl.ONOFF,
        temp_topic="gw/olo/state",
        switch_topic="shelly-olo",
        base_temp={"default": 21.0},
        price_low_threshold=10.0,
        temp_variation=0.5,
    )
    return RoomConfig.model_validate(base | kw)


def trv_room(**kw) -> RoomConfig:
    base = dict(
        id="kylpy",
        control=RoomControl.TRV,
        temp_topic="gw/kylpy/state",
        trv_ext_temp_topic="shellies/trv-kylpy/ext_t/0",
    )
    return RoomConfig.model_validate(base | kw)


def _apply(control, room, price, bus, *, dry_run=False):
    if room.base_temp is not None:
        bus.numbers.setdefault(f"heating_{room.id}_base_temp", room.base_temp.default)
    return strategy_for(control).apply(room, ctx(price), bus, dry_run=dry_run)


class TestOnOff:
    def test_heats_when_below_setpoint(self, fake_bus):
        fake_bus.values["gw/olo/state"] = 20.0
        r = _apply(RoomControl.ONOFF, onoff_room(), 10.0, fake_bus)
        assert r.heat_demand is True
        assert r.setpoint == 21.0
        assert fake_bus.switch_calls == [("shelly-olo", True, "switch:0")]

    def test_idle_when_above_setpoint(self, fake_bus):
        fake_bus.values["gw/olo/state"] = 22.0
        r = _apply(RoomControl.ONOFF, onoff_room(), 30.0, fake_bus)
        assert r.heat_demand is False
        assert fake_bus.switch_calls == [("shelly-olo", False, "switch:0")]

    def test_uses_base_temp_number(self, fake_bus):
        fake_bus.values["gw/olo/state"] = 19.0
        fake_bus.numbers["heating_olo_base_temp"] = 20.0
        r = _apply(RoomControl.ONOFF, onoff_room(), 10.0, fake_bus)
        assert r.setpoint == 20.0

    def test_custom_switch_component(self, fake_bus):
        fake_bus.values["gw/olo/state"] = 20.0
        _apply(RoomControl.ONOFF, onoff_room(switch_component="switch:1"), 10.0, fake_bus)
        assert fake_bus.switch_calls == [("shelly-olo", True, "switch:1")]

    def test_dry_run_does_not_actuate(self, fake_bus):
        fake_bus.values["gw/olo/state"] = 20.0
        _apply(RoomControl.ONOFF, onoff_room(), 10.0, fake_bus, dry_run=True)
        assert fake_bus.switch_calls == []

    def test_missing_sensor_no_actuation(self, fake_bus):
        r = _apply(RoomControl.ONOFF, onoff_room(), 10.0, fake_bus)
        assert r.heat_demand is False
        assert fake_bus.switch_calls == []


class TestTrv:
    def test_expensive_reports_warmer(self, fake_bus):
        fake_bus.values["gw/kylpy/state"] = 20.0
        r = _apply(RoomControl.TRV, trv_room(), 15.0, fake_bus)
        assert r.trv_temp == 21.0  # 20 + (15-5)/5 = +2.0, capped to +1.0
        assert r.heat_demand is False
        assert r.actuated is True
        assert fake_bus.raw_publishes == [("shellies/trv-kylpy/ext_t/0", "21.0")]

    def test_cheap_reports_colder(self, fake_bus):
        fake_bus.values["gw/kylpy/state"] = 20.0
        r = _apply(RoomControl.TRV, trv_room(), 0.0, fake_bus)
        assert r.trv_temp == 19.0  # (0-5)/5 = -1.0
        assert r.heat_demand is True
        assert fake_bus.raw_publishes == [("shellies/trv-kylpy/ext_t/0", "19.0")]

    def test_publish_failure_is_not_fatal(self, fake_bus):
        fake_bus.publish_raw_ok = False
        fake_bus.values["gw/kylpy/state"] = 20.0
        r = _apply(RoomControl.TRV, trv_room(), 7.5, fake_bus)
        assert r.actuated is False

    def test_dry_run(self, fake_bus):
        fake_bus.values["gw/kylpy/state"] = 20.0
        r = _apply(RoomControl.TRV, trv_room(), 10.0, fake_bus, dry_run=True)
        assert r.actuated is False
        assert fake_bus.raw_publishes == []

    def test_missing_sensor_no_actuation(self, fake_bus):
        r = _apply(RoomControl.TRV, trv_room(), 10.0, fake_bus)
        assert r.heat_demand is False
        assert fake_bus.raw_publishes == []
