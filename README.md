# koti

Headless home-automation services. Each is a small Python daemon that uses the MQTT broker
as its substrate — no web UI, no database of its own. Shared code (`koti.ha`, `koti.common`)
lives in the same package; each service is a subpackage.

Platform (broker, HA, gateways, proxy) lives in the separate `infra` repo.

| Service | |
|---|---|
| `koti.heating` | price-aware two-level heating controller (below) |

---

## Heating controller

Every 15 minutes it reads electricity prices (Spot-Hinta) and room temperatures (MQTT), then
controls two independent levels of heating — actuating Shelly relays and TRVs over MQTT — and
publishes everything it computes to HA over MQTT discovery. The broker is its only I/O
channel; HA is the display + history layer.

## The two levels

1. **Boiler (`boiler:` in `zones.yaml`)** — the electric boiler that heats the water.
   On/off. Blocked during the `max_shutoff_hours` most expensive quarters of the day; never
   blocked below `price_always_on_threshold`.
2. **Rooms (`rooms:` in `zones.yaml`)** — one entry per room. Two control types:
   - `onoff` — switch on while `temp < base setpoint + price shift` (shift is ±`temp_variation`,
     linear in price around `price_low_threshold`).
   - `trv` — Shelly TRV fed (over MQTT, to `trv_ext_temp_topic`) a fake "current temperature"
     (`raw + (price - 5) / 5`, capped ±1 °C) so it heats less when power is expensive.

The levels are independent, except a room with `requests_boiler_heat: true` forces the boiler
on whenever that room wants heat.

Adding a room = one entry in `zones.yaml`. The file is re-read every cycle — no restart.

## Setup

Everything is MQTT — the broker + its HA integration live in the `infra` repo; the ESP
gateways / device onboarding runbook in `koti-devices` (`DEVICES.md`). In `zones.yaml`:

- **`temp_topic`** / **`OUTDOOR_TEMP_TOPIC`** — the ESPHome gateway's sensor state topic
  (`gateway-01/sensor/<slug>/state`). Older than `SENSOR_MAX_AGE_MINUTES` → unavailable.
- **`switch_topic`** — a Shelly relay's MQTT prefix. The controller publishes `on`/`off` to
  `<prefix>/command/switch:0` and verifies against the retained `<prefix>/status/switch:0`.
- **`trv_ext_temp_topic`** — the topic the Shelly TRV reads as its external temperature.
- **`base_temp:`** — makes the room's base setpoint a controller-owned MQTT `number`
  (HA shows a slider; value is retained, survives restarts).

```bash
cp .env.example .env      # MQTT host / creds / TLS
$EDITOR zones.yaml        # describe the boiler and rooms

uv run heating            # run locally (foreground scheduler)
docker compose up -d      # production
```

Set `DRY_RUN=true` to log intended actions without actuating (used for the shadow period).

## Published entities (MQTT discovery)

Per room: `sensor.heating_<id>_setpoint`, `_price_adjustment`, `_trv_temp` (trv only),
`binary_sensor.heating_<id>_demand`, and `number.heating_<id>_base_temp` (the adjustable
base setpoint, when the room has `base_temp:`).
Boiler: `sensor.heating_boiler_decision` (state `HEAT`/`BLOCK` + reason/rank/forced/price
attributes), `binary_sensor.heating_boiler_blocked`.
Global: `sensor.heating_current_price`, `sensor.heating_price_avg_today`,
`sensor.heating_price_avg_ex_top`, `binary_sensor.heating_controller_online` (MQTT LWT).

The Shelly relays it commands appear as their own MQTT devices (declared in `infra`'s
`ha-cloud` config); the controller just drives their command topics.

## Development

```bash
uv run pytest             # unit tests
uv run ruff check . && uv run ruff format --check .
uv run mypy               # advisory
```

## Layout

```
src/koti/
  ha/              shared — Spot-Hinta price client (client.py: HA REST, unused by heating)
  common/          shared — structlog setup, healthcheck ping
  heating/
    settings.py    env / .env
    models.py      pydantic config models + runtime dataclasses
    zones.py       load + validate zones.yaml
    publish.py     MqttBus — the one MQTT connection: publish, subscribe, actuate
    logic/         pure functions: price_adjust, boiler, trv, price_stats
    strategies/    onoff, trv  (registry keyed by control type)
    control.py     run_cycle()
    scheduler.py   APScheduler entrypoint (`heating` script)
```
