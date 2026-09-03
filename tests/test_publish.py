from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from koti.heating.models import BoilerDecision, ControlContext, RoomControl, RoomResult
from koti.heating.publish import MqttBus
from koti.heating.settings import Settings


class _Info:
    rc = 0


class FakeMqtt:
    def __init__(self) -> None:
        self.published: list[tuple[str, str, bool]] = []
        self.subscribed: list[str] = []

    def username_pw_set(self, *a, **k): ...
    def will_set(self, *a, **k): ...
    def tls_set(self, *a, **k): ...

    def subscribe(self, topic, *a, **k):
        self.subscribed.append(topic)

    def publish(self, topic, payload=None, retain=False):
        self.published.append((topic, payload, retain))
        return _Info()

    def by_topic(self, needle: str):
        return [p for p in self.published if needle in p[0]]


class FakeMsg:
    def __init__(self, topic: str, payload: str) -> None:
        self.topic = topic
        self.payload = payload.encode()


def settings(**kw) -> Settings:
    return Settings(**kw)  # type: ignore[call-arg]


def _ctx() -> ControlContext:
    return ControlContext(datetime(2026, 1, 1), 12.0, [12.0] * 96, None, None)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("koti.heating.publish.time.sleep", lambda _: None)


def test_discovery_and_state_topics_retained():
    mq = FakeMqtt()
    bus = MqttBus(settings(), client=mq)
    rooms = [
        RoomResult("olo", RoomControl.ONOFF, True, 0.0, "d", setpoint=21.0, raw_temp=20.0),
        RoomResult("kylpy", RoomControl.TRV, False, -0.2, "d", trv_temp=20.8, raw_temp=21.0),
    ]
    decision = BoilerDecision(should_run=False, reason="peak", rank=3, forced=False, price=12.0)
    bus.publish(_ctx(), rooms, decision, price_avg=11.5, price_avg_ex_top=9.2)

    configs = mq.by_topic("/config")
    assert any(
        t == "homeassistant/sensor/heating_controller/heating_olo_setpoint/config"
        for t, _, _ in configs
    )
    assert all(retain for _, _, retain in configs)

    attr = mq.by_topic("heating_boiler_decision/attributes")
    assert attr and json.loads(attr[0][1])["rank"] == 3

    state = [p for p in mq.by_topic("heating_boiler_decision/state")]
    assert state[0][1] == "BLOCK"


def test_trv_room_has_no_setpoint_entity():
    mq = FakeMqtt()
    bus = MqttBus(settings(), client=mq)
    bus.publish(
        _ctx(),
        [RoomResult("kylpy", RoomControl.TRV, False, 0.0, "d", trv_temp=20.0)],
        None,
        price_avg=None,
        price_avg_ex_top=None,
    )
    assert not mq.by_topic("heating_kylpy_setpoint")
    assert mq.by_topic("heating_kylpy_trv_temp/config")


def test_get_float_fresh_stale_and_missing():
    bus = MqttBus(settings(sensor_max_age_minutes=20), client=FakeMqtt())
    assert bus.get_float("gw/a/state") is None  # never seen

    bus._on_message(None, None, FakeMsg("gw/a/state", "21.4"))
    assert bus.get_float("gw/a/state") == 21.4

    payload, _ = bus._received["gw/a/state"]
    bus._received["gw/a/state"] = (payload, datetime.now(bus._tz) - timedelta(minutes=30))
    assert bus.get_float("gw/a/state") is None

    bus._on_message(None, None, FakeMsg("gw/b/state", "nope"))
    assert bus.get_float("gw/b/state") is None  # non-numeric


def test_number_command_roundtrip():
    mq = FakeMqtt()
    bus = MqttBus(settings(), client=mq)
    bus.register_number(
        "heating_olo_base_temp", "olo base", default=21.0, min_value=15, max_value=25, step=0.5
    )
    assert bus.number_value("heating_olo_base_temp") == 21.0
    assert "heating_controller/heating_olo_base_temp/set" in mq.subscribed

    bus._on_message(None, None, FakeMsg("heating_controller/heating_olo_base_temp/set", "22.5"))
    assert bus.number_value("heating_olo_base_temp") == 22.5
    assert ("heating_controller/heating_olo_base_temp/state", 22.5, True) in mq.published

    bus.register_number(
        "heating_olo_base_temp", "olo base", default=21.0, min_value=15, max_value=25, step=0.5
    )
    assert bus.number_value("heating_olo_base_temp") == 22.5


def test_number_recovers_retained_state_on_connect():
    bus = MqttBus(settings(), client=FakeMqtt())
    bus.register_number(
        "heating_olo_base_temp", "olo base", default=21.0, min_value=15, max_value=25, step=0.5
    )
    bus._on_message(None, None, FakeMsg("heating_controller/heating_olo_base_temp/state", "19.5"))
    assert bus.number_value("heating_olo_base_temp") == 19.5


def test_publish_raw():
    mq = FakeMqtt()
    bus = MqttBus(settings(), client=mq)
    assert bus.publish_raw("shellies/trv/ext_t/0", "21.3") is True
    assert ("shellies/trv/ext_t/0", "21.3", False) in mq.published


def test_set_switch_confirmed():
    mq = FakeMqtt()
    bus = MqttBus(settings(), client=mq)
    # Shelly echoes the commanded state on its retained status topic
    bus._on_message(None, None, FakeMsg("shelly-x/status/switch:0", '{"output": true}'))
    assert bus.set_switch("shelly-x", True) is True
    assert ("shelly-x/command/switch:0", "on", False) in mq.published


def test_set_switch_unconfirmed_is_not_fatal():
    mq = FakeMqtt()
    bus = MqttBus(settings(), client=mq)
    bus._on_message(None, None, FakeMsg("shelly-x/online", "false"))
    # no status ever arrives -> loops the attempts (sleep is patched out) then gives up
    assert bus.set_switch("shelly-x", True) is True


def test_switch_output_parses_status_json():
    bus = MqttBus(settings(), client=FakeMqtt())
    assert bus.switch_output("shelly-x") is None
    bus._on_message(
        None, None, FakeMsg("shelly-x/status/switch:0", '{"output": false, "apower": 0}')
    )
    assert bus.switch_output("shelly-x") is False
