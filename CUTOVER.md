# v1 → v2 cutover

Status: v2 code is on branch `v2` (v1 tagged `v1-legacy`). Not yet deployed.

## Prerequisites on Home Assistant (rpi)

1. Install the **Mosquitto broker** add-on. Create an MQTT user for the controller.
2. Add a `rest_command` per `trv` room to `configuration.yaml`, then restart HA:
   ```yaml
   rest_command:
     kylpyhuone_trv_ext_temp:
       url: "http://192.168.86.32/ext_t?temp={{ temp }}"
       method: GET
     khh_trv_ext_temp:
       url: "http://192.168.86.31/ext_t?temp={{ temp }}"
       method: GET
   ```
   (Verify the TRV IPs — v1 had them in `.env`/compose, not tracked here.)
3. Long-lived access token → `HA_API_TOKEN`.

## Deploy (Hetzner VM)

1. `git pull` + `git checkout v2` in this repo on the VM.
2. `cp .env.example .env`, fill in:
   - `HA_API_TOKEN`
   - `MQTT_HOST` = the rpi's Tailscale address/name, `MQTT_USERNAME` / `MQTT_PASSWORD`
   - `OUTDOOR_TEMP_SENSOR`, `HEALTHCHECK_URL` (reuse v1's healthchecks.io UUID)
   - `DRY_RUN=true` for now
3. Check `zones.yaml` — entity IDs for the TRV rooms (`kylpyhuone`, `khh`) and their
   `temp_sensor`s. v1's real `.env` did **not** contain the bathroom/KHH sensor vars, so
   confirm these against HA before trusting them.
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
3. Watch one live cycle: HA switch states change, TRV `rest_command`s fire, MQTT entities
   update, healthcheck pings. Kill the container → `binary_sensor.heating_controller_online`
   goes `off` within the LWT interval.
4. Merge `v2` → `main` in this repo.

## infra repo (`../infra`, separate git repo)

- `ha-proxy/Caddyfile` has a `temp.ketunmetsa.fi { reverse_proxy ha-temperature-web:5000 }`
  block — that is the **v1 dashboard**. After cutover: delete the block, reload Caddy
  (`docker exec caddy-proxy caddy reload --config /etc/caddy/Caddyfile`).
- No other infra file references the heating controller. The v1 controller container reached
  HA via the public `https://ha.ketunmetsa.fi` URL, no special docker network — v2 default
  matches.

## Datastore / dashboards

- "Possu" = `../infra/ha_postgresql` — Postgres 16 (`home_assistant` DB) + **Grafana**,
  already running on HA's recorder database.
- v2 has no application database. Published MQTT entities land in the HA recorder → Postgres,
  so **Grafana can chart them directly**. Lovelace/ApexCharts is optional.
- Entities to build panels from:
  - per room: `sensor.heating_<id>_setpoint`, `_price_adjustment`, `_trv_temp` (trv only),
    `binary_sensor.heating_<id>_demand`
  - boiler: `sensor.heating_boiler_decision` (+ `reason`/`rank`/`forced`/`price` attrs),
    `binary_sensor.heating_boiler_blocked`
  - global: `sensor.heating_current_price`, `sensor.heating_price_avg_today`,
    `sensor.heating_price_avg_ex_top`, `binary_sensor.heating_controller_online`

## Open decision

v1's price→setpoint formula never used `PRICE_HIGH_THRESHOLD`. v2 keeps the v1 behaviour
(linear ramp, slope `temp_variation / price_low_threshold`) and drops the setting. If you
want a real `price_low` → `price_high` interpolation instead, it's a small change in
`src/heating/logic/price_adjust.py` + the config model.
