# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Repo

`koti` — a monorepo of headless home-automation services. One Python package `src/koti/`:
`koti.ha` + `koti.common` are shared; each service is a subpackage. Only service so far:
`koti.heating`. Platform (broker, HA, gateways, Caddy) is the separate `infra` repo.

## Heating controller — overview

Headless price-aware two-level heating controller. One control cycle every 15 minutes: read
electricity prices (Spot-Hinta API) + room temperatures (MQTT), control two independent
heating levels, actuate Shelly relays + TRVs over MQTT, publish computed values to HA over
MQTT discovery.

No web UI, no database. **The controller's only I/O channel is the MQTT broker** — it does
not talk to HA directly. HA is the display + history layer (and renders the setpoint
sliders). Deployed as a single Docker container on the Hetzner VM.

This is a v2 rewrite. The v1 code (Flask dashboard, JSONL log, hard-coded devices) is tagged
`v1-legacy`.

## Commands

```bash
uv run heating                              # run scheduler locally (foreground)
uv run pytest                               # tests
uv run ruff check . && uv run ruff format . # lint + format
uv run mypy                                 # type check (advisory)
docker compose up -d                        # production
```

## Architecture

**Two independent heating levels**, both configured in `zones.yaml` (mounted volume, re-read
every cycle):

1. `boiler` — electric boiler, on/off, price-rank blocking (`logic/boiler.py`).
2. `rooms[]` — per room, `control: onoff` or `control: trv`. A room with
   `requests_boiler_heat: true` forces the boiler on when it has heat demand.

**Control flow** (`control.py::run_cycle`): load zones → `sync_numbers` (declare base-setpoint
`number` entities) → `build_context` (price + temps from the MQTT bus) → run each room
strategy with per-room `try/except` → boiler decision (price rank + forced override) →
`bus.publish` (MQTT discovery) → healthcheck ping. `DRY_RUN=true` logs instead of actuating.

**MQTT migration** (`ARCHITECTURE.md` is the north star) — done. All sensor reads, all
actuation (Shelly relays via `<prefix>/command/switch:0`, TRVs via their ext-temp topic) and
all computed output go through the one `MqttBus`. `koti.ha.client` (HA REST) is no longer
used by the heating controller — kept as shared code for any future service.

**Strategies** (`strategies/`) are registered in a dict keyed by `RoomControl`. Add a control
type = new module + `register(...)` + import in `strategies/__init__.py`.

| Module | Responsibility |
|---|---|
| `koti.ha.client` | shared — HA REST (httpx). **Unused by heating** since the MQTT cutover; kept for future services |
| `koti.ha.price` | shared — Spot-Hinta `/JustNow` + `/TodayAndDayForward`, returns c/kWh incl. tax |
| `koti.common.{logging_setup,healthcheck}` | shared — structlog config; healthchecks.io ping |
| `koti.heating.settings` | env / `.env` via pydantic-settings |
| `koti.heating.models` | pydantic config models; frozen dataclasses for `ControlContext` / `RoomResult` / `BoilerDecision` |
| `koti.heating.zones` | parse + validate `zones.yaml`, merge `rooms.defaults` into each room |
| `koti.heating.publish` | `MqttBus` — the one paho client. Publishes `heating_*` discovery/state + LWT; subscribes for sensor topics (`get_float`) + `number` command topics; actuates (`set_switch` with a verify loop against the retained Shelly status, `publish_raw` for the TRV ext-temp topic) |
| `koti.heating.logic.*` | pure functions, ported verbatim from v1 `temperature_logic.py` / `background_tasks.py` |

## Conventions

- **Sensor reads come from the MQTT bus** (`bus.get_float(topic)`), not HA. `zones.yaml`
  `temp_topic` / `OUTDOOR_TEMP_TOPIC` are broker topics (ESPHome gateway publishes BLE
  sensors under `gateway-01/sensor/<slug>/state`). A value older than
  `SENSOR_MAX_AGE_MINUTES` counts as unavailable → that room does not actuate.
- **Base setpoints are controller-owned** MQTT `number` entities (`heating_<room>_base_temp`),
  declared from `zones.yaml` `base_temp:` every cycle. The controller holds the value
  (retained state topic recovers it across restarts); HA just renders a slider.
- **Actuation is MQTT.** `zones.yaml` `switch_topic` is a Shelly relay prefix — the bus
  publishes `on`/`off` to `<prefix>/command/<component>` and verifies against the retained
  `<prefix>/status/<component>` (`{"output": bool}`). `boiler.inverted: true` keeps the
  "relay ON = boiler blocked" wiring. TRV rooms get a price-adjusted fake temperature
  published to `trv_ext_temp_topic`.
- `logic/` stays pure and fully unit-tested. Thresholds are passed in as keyword args, never
  read from globals.
- Ruff-formatted, line length 100. `mypy --strict` should stay clean.

## Testing

`tests/` — ported price/boiler math (`test_price_adjust.py`, `test_boiler.py`), zone
validation, strategies, price + HA clients (`pytest-httpx`), `MqttBus` (payload shape,
`get_float` staleness, `number` round-trip, `set_switch` verify — `test_publish.py`), full
`run_cycle` with `FakeBus` (`tests/conftest.py`) + fake prices.
