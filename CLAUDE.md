# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Repo

`koti` — a monorepo of headless home-automation services. One Python package `src/koti/`:
`koti.ha` + `koti.common` are shared; each service is a subpackage. Only service so far:
`koti.heating`. Platform (broker, HA, gateways, Caddy) is the separate `infra` repo.

## Heating controller — overview

Headless price-aware two-level heating controller. One control cycle every 15 minutes: read
electricity prices (Spot-Hinta API) + room temperatures (HA REST), control two independent
heating levels, publish computed values back to HA over MQTT discovery.

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
| `koti.ha.client` | shared — HA REST (httpx): `get_state[_float]`, `call_service`, `set_switch` (verify loop) |
| `koti.ha.price` | shared — Spot-Hinta `/JustNow` + `/TodayAndDayForward`, returns c/kWh incl. tax |
| `koti.common.{logging_setup,healthcheck}` | shared — structlog config; healthchecks.io ping |
| `koti.heating.settings` | env / `.env` via pydantic-settings |
| `koti.heating.models` | pydantic config models; frozen dataclasses for `ControlContext` / `RoomResult` / `BoilerDecision` |
| `koti.heating.zones` | parse + validate `zones.yaml`, merge `rooms.defaults` into each room |
| `koti.heating.publish` | MQTT discovery config + retained state + availability/LWT (`heating_*` entities) |
| `koti.heating.shelly` | direct HTTP to a Shelly TRV's `ext_t` endpoint (TRV control only) |
| `koti.heating.logic.*` | pure functions, ported verbatim from v1 `temperature_logic.py` / `background_tasks.py` |

## Conventions

- Sensor reads and relay (`switch`) control go through Home Assistant (REST); computed values
  are published to HA over MQTT. The one exception: TRV control is a direct HTTP GET from the
  controller to the Shelly's `ext_t` endpoint (`koti.heating.shelly`), over the VM's Tailscale
  link — the controller runs where the LAN is reachable, so the HA round-trip buys nothing.
- `logic/` stays pure and fully unit-tested. Thresholds are passed in as keyword args, never
  read from globals.
- Ruff-formatted, line length 100. `mypy --strict` should stay clean.

## Testing

`tests/` — ported price/boiler math (`test_price_adjust.py`, `test_boiler.py`), zone
validation, strategies + HA/price clients (`pytest-httpx`), MQTT payload shape, full
`run_cycle` with `FakeHA` (`tests/conftest.py`) + fake price/publisher.
