"""Publish computed values to Home Assistant via MQTT discovery.

One persistent MQTT connection for the life of the process. An LWT on the availability
topic lets HA show the controller as offline if it dies.
"""

from __future__ import annotations

import json

import paho.mqtt.client as mqtt
import structlog

from koti.heating.models import BoilerDecision, ControlContext, RoomResult
from koti.heating.settings import Settings

log = structlog.get_logger(__name__)

_DEVICE = {
    "identifiers": ["heating_controller"],
    "name": "Heating controller",
    "manufacturer": "custom",
    "model": "price-aware heating v2",
}


class Publisher:
    def __init__(self, settings: Settings, client: mqtt.Client | None = None) -> None:
        self._s = settings
        self._prefix = settings.mqtt_discovery_prefix
        self._node = settings.mqtt_node_id
        self._avail = f"{self._node}/status"
        self._client = client or mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2, client_id=self._node, clean_session=True
        )
        if settings.mqtt_username:
            self._client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
        self._client.will_set(self._avail, "offline", retain=True)

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

    # ---------------------------------------------------------------- helpers

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
        config = {
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

    # ------------------------------------------------------------------ cycle

    def publish(
        self,
        ctx: ControlContext,
        rooms: list[RoomResult],
        boiler: BoilerDecision | None,
        *,
        price_avg: float | None,
        price_avg_ex_top: float | None,
    ) -> None:
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

        if boiler is not None:
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
