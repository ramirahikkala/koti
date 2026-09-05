# v1 → v2 cutover

Status: **live and merged to `main`** (2026-09-05 — 2026-09-06). Cloned to `/opt/koti` on the
VM (v1's old checkout, `/home/rami/nordpool-temperature-control`, is retired but not yet
deleted — v1 tagged `v1-legacy` regardless). Ran with no shadow period, `DRY_RUN=false` from
the first cycle — boiler + olohuone actuation confirmed working. `v2` fast-forwarded into
`main` cleanly (main had gained no commits since v2 branched, so this was a fast-forward, not
a real merge). Remaining: switch `/opt/koti` from `v2` to `main`; TRV bridge (prereq 4) still
pending gateway-01 reflash.

Plan: **no shadow period.** Turn v2 on live (`DRY_RUN=false`), watch the first cycle, keep v1
one `docker compose up` away as the rollback. The decision math is a faithful port of v1 and
the two actuated devices (boiler block relay, olohuone floor-heat) both have a mechanical
backstop, so a bad cycle is recoverable.

## Prerequisites — all on the MQTT bus (`infra` repo)

The controller talks only to the broker. No HA token, no LAN access needed.

1. Broker + MQTT integration in HA — `infra/mqtt/` (`mqtt.ketunmetsa.fi:8883` TLS, users
   incl. `heating`). Device onboarding runbook: `koti-devices/DEVICES.md`.
2. **Sensor topics.** `koti-devices/gateways/gateway-01.yaml` (flashed) publishes the whole
   heating loop under `topic_prefix: koti` — `koti/sensor/{sisa_alakerta,kylpyhuone,khh,ulko_kodari}/state`.
   These are already in `zones.yaml` / `OUTDOOR_TEMP_TOPIC`. Verify live with
   `mosquitto_sub -h mqtt.ketunmetsa.fi -p 8883 -u ha -P '<pw>' -t 'koti/#' -v`.
3. **Shelly relays** — boiler block (`shelly1minig3-5432045dd3f0`) and olohuone
   (`shelly1minig3-5432044efb74`) both on MQTT, "Generic status update over MQTT" ON so
   `<prefix>/status/switch:0` is retained. Done; prefixes are in `zones.yaml`. Also declared
   as `mqtt.switch` in `infra/ha-cloud/config/configuration.yaml`.
4. **Shelly TRVs** (kylpyhuone, khh) — the Gen1 TRVs can't do MQTT-over-TLS, so
   `gateway-01` bridges: the controller publishes a retained ext-temp to
   `koti/trv/<room>/ext_t`, gateway-01 forwards it to the TRV over LAN HTTP
   (`GET /ext_t?temp=X`) on new value + every 5 min. Needs: reserved DHCP for both TRVs
   (khh `192.168.86.31`, kylpyhuone `192.168.86.32`), the TRV's "external sensor" mode on,
   and gateway-01 reflashed with the bridge block. Until then these two rooms just publish
   to a topic nobody forwards yet (per-room `try/except`, harmless).

## Cut over (Hetzner VM)

1. **Stop v1 first** — `docker compose down` in the v1 stack (`ha-temperature-controller` +
   `ha-temperature-web`). Both v1 and v2 write `<prefix>/command/switch:0`; never run them
   together.
2. Fresh clone, don't reuse v1's checkout: `git clone --branch v2 git@github.com:ramirahikkala/koti.git /opt/koti`
   (note: this repo was renamed from `nordpool-temperature-control` to `koti` on GitHub —
   the old remote URL still redirects, but update `origin` when convenient).
3. `cp .env.example .env`, fill in:
   - `MQTT_HOST=mqtt.ketunmetsa.fi`, `MQTT_PORT=8883`, `MQTT_TLS=true`,
     `MQTT_USERNAME=heating` / `MQTT_PASSWORD`
   - `OUTDOOR_TEMP_TOPIC=koti/sensor/ulko_kodari/state`
   - `HEALTHCHECK_URL` (reuse v1's healthchecks.io UUID)
   - `DRY_RUN=false`
4. Check `zones.yaml` — `temp_topic` for every room, `base_temp:` for `olohuone`, and decide
   the TRV rooms (prereq 4). The base setpoint that was `input_number.sisalampoasetus` is now
   the controller-owned `number.heating_olohuone_base_temp` (HA slider); its starting value
   comes from `base_temp.default` (21.0) on the first run, then the retained state topic.
5. `docker compose up -d --build`.
6. **Watch the first cycle** (`docker compose logs -f`):
   - `mqtt.connected`, topic subscriptions, `cycle.start`
   - `room.done` lines with real temperatures — sanity-check against HA
   - boiler decision (HEAT/BLOCK) + `switch.set` → confirm on
     `shelly1minig3-5432045dd3f0/status/switch:0` and the olohuone relay
   - `number.heating_olohuone_base_temp` appears in HA
   - healthcheck ping; kill the container → every `heating_*` entity goes `unavailable` within
     the LWT interval (there's no separate "controller online" entity — each published
     entity carries the same `availability_topic`)
7. Rollback if it misbehaves: `docker compose down` here, `docker compose up -d` in the v1
   stack.
8. Once it's been happy for a day: merge `v2` → `main`.

## infra repo (`../infra`, separate git repo)

- `ha-proxy/Caddyfile` has a `temp.ketunmetsa.fi { reverse_proxy ha-temperature-web:5000 }`
  block — that is the **v1 dashboard**. After cutover: delete the block, reload Caddy
  (`docker exec caddy-proxy caddy reload --config /etc/caddy/Caddyfile`).
- `ha-cloud/config/configuration.yaml` declares the Shelly relays as `mqtt.switch` entities
  (Gen3 has no HA discovery). HA and the controller both publish to the same
  `<prefix>/command/switch:0` — harmless; the controller re-asserts every 15 min.

## Datastore / dashboards

- v2 has no application database. Everything it computes is published as MQTT entities that
  land in the cloud HA recorder (SQLite) — view + chart them in HA's own History/Logbook or
  the git-managed "Lämmitys" dashboard (`../infra/ha-cloud/config/dashboards/lammitys.yaml`,
  YAML-mode Lovelace alongside the default UI-managed Overview).
- Grafana + the Postgres recorder are **retired** (Grafana went unused; `../infra/ha_postgresql`
  stays only for other services). Cloud HA keeps its default SQLite recorder — tune
  `recorder:` (`purge_keep_days`, `exclude:` for noisy BLE attributes) instead.
- Entities to build panels from — note HA prefixes MQTT-discovered entities with the device
  slug (`heating_controller_...`), not the bare `object_id`; check
  `.storage/core.entity_registry` on the VM for the exact current IDs rather than guessing:
  - per room: `..._<id>_setpoint` (onoff only), `..._<id>_price_adjustment`,
    `..._<id>_trv_reported_temperature` (trv only), `..._<id>_heat_demand`,
    `number...._<id>_base_setpoint` (onoff only)
  - boiler: `..._boiler_decision` (+ `reason`/`rank`/`forced`/`price` attrs), `..._boiler_blocked`
  - global: `..._current_electricity_price`, `..._price_average_today`,
    `..._price_average_excl_peak_hours`; no dedicated "controller online" entity — watch any
    `heating_*` entity go unavailable instead

## Open decision

v1's price→setpoint formula never used `PRICE_HIGH_THRESHOLD`. v2 keeps the v1 behaviour
(linear ramp, slope `temp_variation / price_low_threshold`) and drops the setting. If you
want a real `price_low` → `price_high` interpolation instead, it's a small change in
`src/koti/heating/logic/price_adjust.py` + the config model.
