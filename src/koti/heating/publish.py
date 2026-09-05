"""The controller's MQTT bus client - the controller's whole world is this one connection.

One persistent MQTT connection for the life of the process. Three roles:

* **publish** - HA discovery config + retained state for the ``heating_*`` entities, plus an
  LWT on the availability topic so HA shows the controller offline if it dies.
* **subscribe** - room / outdoor temperatures from gateway state topics, and the command
  topics of the controller-owned ``number`` entities (the base setpoints).
* **actuate** - Shelly relays (``<prefix>/command/switch:0``, verified against the retained
  ``<prefix>/status/switch:0``) and the Shelly TRV external-temperature topic.
"""

from __future__ import annotations

import contextlib
import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import paho.mqtt.client as mqtt
import structlog

from koti.heating.models import BoilerDecision, ControlContext, RoomResult
from koti.heating.settings import Settings

log = structlog.get_logger(__name__)

_VERIFY_ATTEMPTS = 16  # x 0.5 s = up to 8 s waiting for a Shelly to echo a commanded state

_DEVICE = {
    "identifiers": ["heating_controller"],
    "name": "Heating controller",
    "manufacturer": "custom",
    "model": "price-aware heating v2",
}


@dataclass
class _Number:
    value: float
    set_topic: str
    state_topic: str
    config_topic: str
    config: dict[str, object]


class MqttBus:
    def __init__(self, settings: Settings, client: mqtt.Client | None = None) -> None:
        self._s = settings
        self._prefix = settings.mqtt_discovery_prefix
        self._node = settings.mqtt_node_id
        self._avail = f"{self._node}/status"
        self._tz = ZoneInfo(settings.timezone)
        self._max_age = timedelta(minutes=settings.sensor_max_age_minutes)

        self._lock = threading.Lock()
        self._received: dict[str, tuple[str, datetime]] = {}
        self._numbers: dict[str, _Number] = {}
        self._watched: set[str] = set()

        self._client = client or mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2, client_id=self._node, clean_session=True
        )
        if settings.mqtt_username:
            self._client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
        if settings.mqtt_tls:
            self._client.tls_set()
        self._client.will_set(self._avail, "offline", retain=True)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message

    # ------------------------------------------------------------- connection

    def connect(self) -> None:
        self._client.connect(self._s.mqtt_host, self._s.mqtt_port)
        self._client.loop_start()
        self._client.publish(self._avail, "online", retain=True)
        log.info("mqtt.connected", host=self._s.mqtt_host, port=self._s.mqtt_port)

    def close(self) -> None:
        self._client.publish(self._avail, "offline", retain=True)
        self._client.loop_stop()
        self._client.disconnect()

    def _on_connect(self, client: mqtt.Client, *_: object) -> None:
        topics = set(self._watched)
        for n in self._numbers.values():
            topics.add(n.set_topic)
            topics.add(n.state_topic)
        for t in topics:
            client.subscribe(t)
        if topics:
            log.info("mqtt.subscribed", count=len(topics))

    def _on_message(self, _client: mqtt.Client, _userdata: object, msg: mqtt.MQTTMessage) -> None:
        payload = msg.payload.decode(errors="replace").strip()
        now = datetime.now(self._tz)
        with self._lock:
            for oid, n in self._numbers.items():
                if msg.topic == n.set_topic:
                    self._set_number(oid, n, payload, source="command")
                    return
                if msg.topic == n.state_topic:
                    # retained value recovered on (re)connect - adopt without echoing back
                    with contextlib.suppress(ValueError):
                        n.value = float(payload)
                    return
            self._received[msg.topic] = (payload, now)

    # -------------------------------------------------------------- subscribe

    def watch(self, topic: str | None) -> None:
        if not topic:
            return
        self._watched.add(topic)
        self._client.subscribe(topic)

    def get_float(self, topic: str | None, *, max_age: timedelta | None = None) -> float | None:
        if not topic:
            return None
        with self._lock:
            entry = self._received.get(topic)
        if entry is None:
            log.warning("bus.no_value", topic=topic)
            return None
        payload, received_at = entry
        age = datetime.now(self._tz) - received_at
        if age > (max_age or self._max_age):
            log.warning("bus.stale", topic=topic, age_s=round(age.total_seconds()))
            return None
        try:
            return float(payload)
        except ValueError:
            log.warning("bus.not_numeric", topic=topic, payload=payload)
            return None

    def _raw(self, topic: str) -> str | None:
        with self._lock:
            entry = self._received.get(topic)
        return None if entry is None else entry[0]

    # --------------------------------------------------------------- actuate

    @staticmethod
    def _ok(info: object) -> bool:
        return getattr(info, "rc", 0) == 0

    def publish_raw(self, topic: str, payload: str | float, *, retain: bool = False) -> bool:
        return self._ok(self._client.publish(topic, payload, retain=retain))

    def _switch_topics(self, prefix: str, component: str) -> tuple[str, str, str]:
        return (
            f"{prefix}/command/{component}",
            f"{prefix}/status/{component}",
            f"{prefix}/online",
        )

    def watch_switch(self, prefix: str, component: str = "switch:0") -> None:
        _, status, online = self._switch_topics(prefix, component)
        self.watch(status)
        self.watch(online)

    def switch_output(self, prefix: str, component: str = "switch:0") -> bool | None:
        """Current relay state from the retained Shelly status topic, or None if unknown."""
        _, status, _ = self._switch_topics(prefix, component)
        raw = self._raw(status)
        if raw is None:
            return None
        try:
            return bool(json.loads(raw)["output"])
        except (ValueError, KeyError, TypeError):
            log.warning("switch.bad_status", prefix=prefix, payload=raw)
            return None

    def device_online(self, prefix: str) -> bool | None:
        raw = self._raw(f"{prefix}/online")
        if raw is None:
            return None
        return raw.strip().lower() == "true"

    def set_switch(self, prefix: str, on: bool, *, component: str = "switch:0") -> bool:
        """Command a Shelly relay and wait briefly for it to echo the new state.

        Returns True once the command is published (the 15-minute cycle is the real retry
        loop, so an unconfirmed command is logged but not treated as fatal).
        """
        command, _, _ = self._switch_topics(prefix, component)
        if not self.publish_raw(command, "on" if on else "off"):
            log.error("switch.publish_failed", prefix=prefix)
            return False

        if self.device_online(prefix) is False:
            log.warning("switch.device_offline", prefix=prefix)

        for _ in range(_VERIFY_ATTEMPTS):
            time.sleep(0.5)
            if self.switch_output(prefix, component) == on:
                log.info("switch.set", prefix=prefix, on=on)
                return True
        log.warning("switch.unconfirmed", prefix=prefix, wanted=on)
        return True

    # ----------------------------------------------------------- number entity

    def register_number(
        self,
        object_id: str,
        name: str,
        *,
        default: float,
        min_value: float,
        max_value: float,
        step: float,
        unit: str = "°C",
    ) -> None:
        set_topic = f"{self._node}/{object_id}/set"
        state_topic = f"{self._node}/{object_id}/state"
        config = {
            "name": name,
            "unique_id": object_id,
            "object_id": object_id,
            "state_topic": state_topic,
            "command_topic": set_topic,
            "availability_topic": self._avail,
            "min": min_value,
            "max": max_value,
            "step": step,
            "unit_of_measurement": unit,
            "mode": "box",
            "device": _DEVICE,
        }
        config_topic = f"{self._prefix}/number/{self._node}/{object_id}/config"
        with self._lock:
            existing = self._numbers.get(object_id)
            value = existing.value if existing is not None else default
            self._numbers[object_id] = _Number(value, set_topic, state_topic, config_topic, config)
            first_time = existing is None
        self._client.publish(config_topic, json.dumps(config), retain=True)
        if first_time:
            self._client.subscribe(set_topic)
            self._client.subscribe(state_topic)

    def number_value(self, object_id: str) -> float:
        with self._lock:
            return self._numbers[object_id].value

    def _set_number(self, object_id: str, n: _Number, payload: str, *, source: str) -> None:
        try:
            n.value = float(payload)
        except ValueError:
            log.warning("number.bad_command", object_id=object_id, payload=payload)
            return
        log.info("number.set", object_id=object_id, value=n.value, source=source)
        self._client.publish(n.state_topic, n.value, retain=True)

    def _republish_numbers(self) -> None:
        with self._lock:
            items = [(n.state_topic, n.value) for n in self._numbers.values()]
        for state_topic, value in items:
            self._client.publish(state_topic, value, retain=True)

    # ---------------------------------------------------------------- publish

    def _state_topic(self, object_id: str) -> str:
        return f"{self._node}/{object_id}/state"

    def _publish_entity(
        self,
        component: str,
        object_id: str,
        name: str,
        state: str | float,
        *,
        unit: str | None = None,
        device_class: str | None = None,
        attributes: dict[str, object] | None = None,
    ) -> None:
        state_topic = self._state_topic(object_id)
        config: dict[str, object] = {
            "name": name,
            "unique_id": object_id,
            "object_id": object_id,
            "state_topic": state_topic,
            "availability_topic": self._avail,
            "device": _DEVICE,
        }
        if unit:
            config["unit_of_measurement"] = unit
            config["state_class"] = "measurement"
        if device_class:
            config["device_class"] = device_class
        if attributes is not None:
            config["json_attributes_topic"] = f"{self._node}/{object_id}/attributes"

        self._client.publish(
            f"{self._prefix}/{component}/{self._node}/{object_id}/config",
            json.dumps(config),
            retain=True,
        )
        self._client.publish(state_topic, state, retain=True)
        if attributes is not None:
            self._client.publish(
                f"{self._node}/{object_id}/attributes",
                json.dumps(attributes, default=str),
                retain=True,
            )

    def publish(
        self,
        ctx: ControlContext,
        rooms: list[RoomResult],
        boiler: BoilerDecision | None,
        *,
        price_avg: float | None,
        price_avg_ex_top: float | None,
    ) -> None:
        self._republish_numbers()

        self._publish_entity(
            "sensor",
            "heating_current_price",
            "Current electricity price",
            round(ctx.current_price, 2),
            unit="c/kWh",
        )
        if price_avg is not None:
            self._publish_entity(
                "sensor", "heating_price_avg_today", "Price average today", price_avg, unit="c/kWh"
            )
        if price_avg_ex_top is not None:
            self._publish_entity(
                "sensor",
                "heating_price_avg_ex_top",
                "Price average excl. peak hours",
                price_avg_ex_top,
                unit="c/kWh",
            )

        for r in rooms:
            oid = f"heating_{r.zone_id}"
            self._publish_entity(
                "binary_sensor",
                f"{oid}_demand",
                f"{r.zone_id} heat demand",
                "ON" if r.heat_demand else "OFF",
                device_class="heat",
            )
            self._publish_entity(
                "sensor",
                f"{oid}_price_adjustment",
                f"{r.zone_id} price adjustment",
                r.adjustment,
                unit="°C",
            )
            if r.setpoint is not None:
                self._publish_entity(
                    "sensor",
                    f"{oid}_setpoint",
                    f"{r.zone_id} target setpoint",
                    r.setpoint,
                    unit="°C",
                    device_class="temperature",
                )
            if r.trv_temp is not None:
                self._publish_entity(
                    "sensor",
                    f"{oid}_trv_temp",
                    f"{r.zone_id} TRV reported temperature",
                    r.trv_temp,
                    unit="°C",
                    device_class="temperature",
                )
            # Human-readable one-liner, same text as the room.done log line. Its own state
            # history in HA is a de-facto log view of this room's decisions over time.
            self._publish_entity(
                "sensor",
                f"{oid}_status",
                f"{r.zone_id} status",
                r.detail,
            )

        if boiler is not None:
            self._publish_entity(
                "sensor",
                "heating_boiler_status",
                "Boiler status",
                boiler.reason,
            )
            self._publish_entity(
                "sensor",
                "heating_boiler_decision",
                "Boiler decision",
                "HEAT" if boiler.should_run else "BLOCK",
                attributes={
                    "reason": boiler.reason,
                    "rank": boiler.rank,
                    "forced": boiler.forced,
                    "price": round(boiler.price, 2),
                },
            )
            self._publish_entity(
                "binary_sensor",
                "heating_boiler_blocked",
                "Boiler blocked",
                "ON" if not boiler.should_run else "OFF",
            )
