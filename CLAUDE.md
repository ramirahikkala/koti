# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project overview

Headless price-aware heating controller for Home Assistant. Runs one control cycle every 15
minutes: read electricity prices (Spot-Hinta API) + room temperatures (HA REST), control two
independent heating levels, publish computed values back to HA over MQTT discovery.

No web UI, no database. HA is the display + history layer. Deployed as a single Docker
container on the Hetzner VM (which holds the Tailscale link to the home HA instance).

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

**Control flow** (`control.py::run_cycle`): load zones → `build_context` (price + temps) →
run each room strategy with per-room `try/except` → boiler decision (price rank + forced
override) → `publish` to MQTT → healthcheck ping. `DRY_RUN=true` logs instead of actuating.

**Strategies** (`strategies/`) are registered in a dict keyed by `RoomControl`. Add a control
type = new module + `register(...)` + import in `strategies/__init__.py`.

| Module | Responsibility |
|---|---|
| `settings.py` | env / `.env` via pydantic-settings |
| `models.py` | pydantic config models; frozen dataclasses for `ControlContext` / `RoomResult` / `BoilerDecision` |
| `zones.py` | parse + validate `zones.yaml`, merge `rooms.defaults` into each room |
| `ha/client.py` | HA REST (httpx): `get_state[_float]`, `call_service`, `set_switch` (with verify loop) |
| `ha/price.py` | Spot-Hinta `/JustNow` + `/TodayAndDayForward`, returns c/kWh incl. tax |
| `ha/publish.py` | MQTT discovery config + retained state + availability/LWT |
| `shelly.py` | direct HTTP to a Shelly TRV's `ext_t` endpoint (TRV control only) |
| `logic/*` | pure functions, ported verbatim from v1 `temperature_logic.py` / `background_tasks.py` |

## Conventions

- Sensor reads and relay (`switch`) control go through Home Assistant (REST); computed values
  are published to HA over MQTT. The one exception: TRV control is a direct HTTP GET from the
  controller to the Shelly's `ext_t` endpoint (`heating/shelly.py`), over the VM's Tailscale
  link — the controller runs where the LAN is reachable, so the HA round-trip buys nothing.
- `logic/` stays pure and fully unit-tested. Thresholds are passed in as keyword args, never
  read from globals.
- Ruff-formatted, line length 100. `mypy --strict` should stay clean.

## Testing

`tests/` — ported price/boiler math (`test_price_adjust.py`, `test_boiler.py`), zone
validation, strategies + HA/price clients (`pytest-httpx`), MQTT payload shape, full
`run_cycle` with `FakeHA` (`tests/conftest.py`) + fake price/publisher.
