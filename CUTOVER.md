# v1 → v2 cutover

Status: v2 code is on branch `v2` (v1 tagged `v1-legacy`). Not yet deployed.

## Prerequisites — all on the MQTT bus (`infra` repo)

The controller talks only to the broker. No HA token, no LAN access needed.

1. Broker + MQTT integration in HA — `infra/mqtt/` (`mqtt.ketunmetsa.fi:8883` TLS, users
   incl. `heating`). Device onboarding runbook: `koti-devices/DEVICES.md`.
2. **Sensor topics.** The ESPHome gateway (`koti-devices/gateways/gateway.yaml`) must publish
   each room + outdoor sensor; find its state topic with
   `mosquitto_sub -h mqtt.ketunmetsa.fi -p 8883 -u ha -P '<pw>' -t 'gateway-01/#' -v` and set
   it as `temp_topic` / `OUTDOOR_TEMP_TOPIC`. gateway.yaml still has placeholder MACs — fix
   those first.
3. **Shelly relays** (boiler block + olohuone) onboarded to MQTT per `koti-devices/DEVICES.md`
   ("Generic status update over MQTT" ON so `<prefix>/status/switch:0` is retained). Put the
   `<model>-<mac>` prefix in `zones.yaml` as `switch_topic`.
4. **Shelly TRVs** (kylpyhuone, khh): enable MQTT on each, point it at the broker, and set
   `trv_ext_temp_topic` in `zones.yaml` to the topic it reads as external temperature (depends
   on the TRV's MQTT device id — verify with `mosquitto_sub`).

## Deploy (Hetzner VM)

1. `git pull` + `git checkout v2` in this repo on the VM.
2. `cp .env.example .env`, fill in:
   - `MQTT_HOST=mqtt.ketunmetsa.fi`, `MQTT_PORT=8883`, `MQTT_TLS=true`,
     `MQTT_USERNAME=heating` / `MQTT_PASSWORD`
   - `OUTDOOR_TEMP_TOPIC`, `HEALTHCHECK_URL` (reuse v1's healthchecks.io UUID)
   - `DRY_RUN=true` for now
3. Check `zones.yaml` — `temp_topic` for every room and `base_temp:` for `olohuone`. The
   base setpoint that was `input_number.sisalampoasetus` is now the controller-owned
   `number.heating_olohuone_base_temp` (HA slider); set its starting value via `base_temp.default`.
4. `docker compose up -d --build` (runs as a 3rd stack alongside v1).

## Shadow period (3–5 days)

- v2 runs with `DRY_RUN=true`: it logs intended actions + publishes MQTT entities, but does
  not actuate.
- Compare v1's `data/heating_decisions.jsonl` (HEAT/BLOCK) against v2's
  `sensor.heating_boiler_decision` history in HA.
- Spot-check per-room: v1's published setpoint sensor vs `sensor.heating_<room>_setpoint`.

## Cut over

1. Stop v1: `docker compose down` in the v1 stack (`ha-temperature-controller` +
   `ha-temperature-web`).
2. Set `DRY_RUN=false` in v2's `.env`, `docker compose up -d`.
3. Watch one live cycle: Shelly relays flip (`<prefix>/command/switch:0`, confirmed by
   `switch.set` in the logs), TRV ext-temp published, MQTT entities update, healthcheck
   pings. Kill the container → `binary_sensor.heating_controller_online` goes `off` within
   the LWT interval.
4. Merge `v2` → `main` in this repo.

## infra repo (`../infra`, separate git repo)

- `ha-proxy/Caddyfile` has a `temp.ketunmetsa.fi { reverse_proxy ha-temperature-web:5000 }`
  block — that is the **v1 dashboard**. After cutover: delete the block, reload Caddy
  (`docker exec caddy-proxy caddy reload --config /etc/caddy/Caddyfile`).
- `ha-cloud/config/configuration.yaml` declares the Shelly relays as `mqtt.switch` entities
  (Gen3 has no HA discovery). HA and the controller both publish to the same
  `<prefix>/command/switch:0` — harmless; the controller re-asserts every 15 min.

## Datastore / dashboards

- v2 has no application database. Everything it computes is published as MQTT entities that
  land in the cloud HA recorder (SQLite) — view + chart them in HA's own History/Logbook or a
  Lovelace ApexCharts card.
- Grafana + the Postgres recorder are **retired** (Grafana went unused; `../infra/ha_postgresql`
  stays only for other services). Cloud HA keeps its default SQLite recorder — tune
  `recorder:` (`purge_keep_days`, `exclude:` for noisy BLE attributes) instead.
- Entities to build panels from:
  - per room: `sensor.heating_<id>_setpoint`, `_price_adjustment`, `_trv_temp` (trv only),
    `binary_sensor.heating_<id>_demand`, `number.heating_<id>_base_temp`
  - boiler: `sensor.heating_boiler_decision` (+ `reason`/`rank`/`forced`/`price` attrs),
    `binary_sensor.heating_boiler_blocked`
  - global: `sensor.heating_current_price`, `sensor.heating_price_avg_today`,
    `sensor.heating_price_avg_ex_top`, `binary_sensor.heating_controller_online`

## Open decision

v1's price→setpoint formula never used `PRICE_HIGH_THRESHOLD`. v2 keeps the v1 behaviour
(linear ramp, slope `temp_variation / price_low_threshold`) and drops the setting. If you
want a real `price_low` → `price_high` interpolation instead, it's a small change in
`src/koti/heating/logic/price_adjust.py` + the config model.
