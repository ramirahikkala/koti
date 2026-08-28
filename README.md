# Heating controller (v2)

Price-aware, headless heating controller for Home Assistant. Every 15 minutes it reads
electricity prices (Spot-Hinta) and room temperatures (HA), then controls two independent
levels of heating and publishes everything it computes back to HA over MQTT.

There is **no web UI** and **no database** — Home Assistant is the display layer and the
history store.

## The two levels

1. **Boiler (`boiler:` in `zones.yaml`)** — the electric boiler that heats the water.
   On/off. Blocked during the `max_shutoff_hours` most expensive quarters of the day; never
   blocked below `price_always_on_threshold`.
2. **Rooms (`rooms:` in `zones.yaml`)** — one entry per room. Two control types:
   - `onoff` — switch on while `temp < base setpoint + price shift` (shift is ±`temp_variation`,
     linear in price around `price_low_threshold`).
   - `trv` — Shelly TRV fed a fake "current temperature" (`raw + (price - 5) / 5`, capped ±1 °C)
     so it heats less when power is expensive.

The levels are independent, except a room with `requests_boiler_heat: true` forces the boiler
on whenever that room wants heat.

Adding a room = one entry in `zones.yaml`. The file is re-read every cycle — no restart.

## Setup

### Home Assistant

1. Install the **Mosquitto broker** add-on and create an MQTT user for the controller.
2. For each `trv` room, add a `rest_command` to `configuration.yaml` (HA makes the LAN call):
   ```yaml
   rest_command:
     kylpyhuone_trv_ext_temp:
       url: "http://192.168.86.32/ext_t?temp={{ temp }}"
       method: GET
   ```
3. Create a long-lived access token for `HA_API_TOKEN`.

### Controller

```bash
cp .env.example .env      # fill HA_API_TOKEN + MQTT creds
$EDITOR zones.yaml        # describe the boiler and rooms

uv run heating            # run locally (foreground scheduler)
docker compose up -d      # production
```

Set `DRY_RUN=true` to log intended actions without touching HA (used for the shadow period).

## Published entities (MQTT discovery)

Per room: `sensor.heating_<id>_setpoint`, `_price_adjustment`, `_trv_temp` (trv only),
`binary_sensor.heating_<id>_demand`.
Boiler: `sensor.heating_boiler_decision` (state `HEAT`/`BLOCK` + reason/rank/forced/price
attributes), `binary_sensor.heating_boiler_blocked`.
Global: `sensor.heating_current_price`, `sensor.heating_price_avg_today`,
`sensor.heating_price_avg_ex_top`, `binary_sensor.heating_controller_online` (MQTT LWT).

Build the dashboard from these in Lovelace (ApexCharts card for the price/temperature graphs;
the sun/daylight panel is HA-native).

## Development

```bash
uv run pytest             # unit tests
uv run ruff check . && uv run ruff format --check .
uv run mypy               # advisory
```

## Layout

```
src/heating/
  settings.py      env / .env
  models.py        pydantic config models + runtime dataclasses
  zones.py         load + validate zones.yaml
  ha/client.py     HA REST client (httpx)
  ha/price.py      Spot-Hinta price client
  ha/publish.py    MQTT discovery publisher
  logic/           pure functions: price_adjust, boiler, trv, price_stats
  strategies/      onoff, trv  (registry keyed by control type)
  control.py       run_cycle()
  scheduler.py     APScheduler entrypoint (`heating`)
```
