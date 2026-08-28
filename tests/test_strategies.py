from __future__ import annotations

from datetime import datetime

from heating.models import ControlContext, RoomConfig, RoomControl
from heating.strategies import strategy_for


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
        temp_sensor="sensor.t",
        switch_entity="switch.s",
        base_temp_fallback=21.0,
        price_low_threshold=10.0,
        temp_variation=0.5,
    )
    return RoomConfig.model_validate(base | kw)


def trv_room(**kw) -> RoomConfig:
    base = dict(
        id="kylpy",
        control=RoomControl.TRV,
        temp_sensor="sensor.t",
        trv_ext_temp_service="rest_command.kylpy_ext",
    )
    return RoomConfig.model_validate(base | kw)


class TestOnOff:
    def test_heats_when_below_setpoint(self, fake_ha):
        fake_ha.states["sensor.t"] = 20.0
        r = strategy_for(RoomControl.ONOFF).apply(onoff_room(), ctx(10.0), fake_ha, dry_run=False)
        assert r.heat_demand is True
        assert r.setpoint == 21.0
        assert fake_ha.switch_calls == [("switch.s", True)]

    def test_idle_when_above_setpoint(self, fake_ha):
        fake_ha.states["sensor.t"] = 22.0
        r = strategy_for(RoomControl.ONOFF).apply(onoff_room(), ctx(30.0), fake_ha, dry_run=False)
        assert r.heat_demand is False
        assert fake_ha.switch_calls == [("switch.s", False)]

    def test_reads_base_from_entity(self, fake_ha):
        fake_ha.states.update({"sensor.t": 19.0, "input_number.base": 20.0})
        r = strategy_for(RoomControl.ONOFF).apply(
            onoff_room(base_temp_entity="input_number.base"), ctx(10.0), fake_ha, dry_run=False
        )
        assert r.setpoint == 20.0

    def test_dry_run_does_not_actuate(self, fake_ha):
        fake_ha.states["sensor.t"] = 20.0
        strategy_for(RoomControl.ONOFF).apply(onoff_room(), ctx(10.0), fake_ha, dry_run=True)
        assert fake_ha.switch_calls == []

    def test_missing_sensor_no_actuation(self, fake_ha):
        r = strategy_for(RoomControl.ONOFF).apply(onoff_room(), ctx(10.0), fake_ha, dry_run=False)
        assert r.heat_demand is False
        assert fake_ha.switch_calls == []


class TestTrv:
    def test_expensive_reports_warmer(self, fake_ha):
        fake_ha.states["sensor.t"] = 20.0
        r = strategy_for(RoomControl.TRV).apply(trv_room(), ctx(15.0), fake_ha, dry_run=False)
        assert r.trv_temp == 21.0  # 20 + (15-5)/5 = +2.0, capped to +1.0
        assert r.heat_demand is False
        assert fake_ha.service_calls == [("rest_command", "kylpy_ext", {"temp": 21.0})]

    def test_cheap_reports_colder(self, fake_ha):
        fake_ha.states["sensor.t"] = 20.0
        r = strategy_for(RoomControl.TRV).apply(trv_room(), ctx(0.0), fake_ha, dry_run=False)
        assert r.trv_temp == 19.0  # (0-5)/5 = -1.0
        assert r.heat_demand is True

    def test_dry_run(self, fake_ha):
        fake_ha.states["sensor.t"] = 20.0
        strategy_for(RoomControl.TRV).apply(trv_room(), ctx(10.0), fake_ha, dry_run=True)
        assert fake_ha.service_calls == []
