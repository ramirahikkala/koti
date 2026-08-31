from __future__ import annotations

import json
from datetime import datetime

from koti.heating.models import BoilerDecision, ControlContext, RoomControl, RoomResult
from koti.heating.publish import Publisher
from koti.heating.settings import Settings


class FakeMqtt:
    def __init__(self) -> None:
        self.published: list[tuple[str, str, bool]] = []

    def username_pw_set(self, *a, **k): ...
    def will_set(self, *a, **k): ...

    def publish(self, topic, payload=None, retain=False):
        self.published.append((topic, payload, retain))

    def by_topic(self, needle: str):
        return [p for p in self.published if needle in p[0]]


def settings() -> Settings:
    return Settings(ha_api_token="x")  # type: ignore[call-arg]


def _ctx() -> ControlContext:
    return ControlContext(datetime(2026, 1, 1), 12.0, [12.0] * 96, None, None)


def test_discovery_and_state_topics_retained():
    mq = FakeMqtt()
    pub = Publisher(settings(), client=mq)
    rooms = [
        RoomResult("olo", RoomControl.ONOFF, True, 0.0, "d", setpoint=21.0, raw_temp=20.0),
        RoomResult("kylpy", RoomControl.TRV, False, -0.2, "d", trv_temp=20.8, raw_temp=21.0),
    ]
    decision = BoilerDecision(should_run=False, reason="peak", rank=3, forced=False, price=12.0)
    pub.publish(_ctx(), rooms, decision, price_avg=11.5, price_avg_ex_top=9.2)

    configs = mq.by_topic("/config")
    assert any(
        t == "homeassistant/sensor/heating_controller/heating_olo_setpoint/config"
        for t, _, _ in configs
    )
    assert all(retain for _, _, retain in configs)

    # boiler decision carries json attributes
    attr = mq.by_topic("heating_boiler_decision/attributes")
    assert attr and json.loads(attr[0][1])["rank"] == 3

    state = [p for p in mq.by_topic("heating_boiler_decision/state")]
    assert state[0][1] == "BLOCK"


def test_trv_room_has_no_setpoint_entity():
    mq = FakeMqtt()
    pub = Publisher(settings(), client=mq)
    pub.publish(
        _ctx(),
        [RoomResult("kylpy", RoomControl.TRV, False, 0.0, "d", trv_temp=20.0)],
        None,
        price_avg=None,
        price_avg_ex_top=None,
    )
    assert not mq.by_topic("heating_kylpy_setpoint")
    assert mq.by_topic("heating_kylpy_trv_temp/config")
