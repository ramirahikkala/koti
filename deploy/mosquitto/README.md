# Mosquitto broker (rpi)

Copy this directory to the rpi (e.g. `~/homeassistant_docker-compose/mosquitto/`).

## 1. Create the password file

One `mqtt` user is enough for both Home Assistant and the heating controller:

```bash
cd mosquitto
docker run --rm -v "$PWD/config:/mosquitto/config" eclipse-mosquitto:2 \
  mosquitto_passwd -c -b /mosquitto/config/passwd mqtt 'CHOOSE_A_PASSWORD'
```

(Drop `-c` to add more users later.)

## 2. Start

```bash
docker compose up -d
docker compose logs -f    # expect "mosquitto version 2.x starting" and no errors
```

## 3. Point Home Assistant at it

HA runs as a container with `network_mode: host`, so it reaches the broker on localhost.
Settings -> Devices & Services -> Add Integration -> **MQTT**:

- Broker: `127.0.0.1`
- Port: `1883`
- Username / Password: `mqtt` / the password from step 1
- Leave "Enable discovery" on.

## 4. Controller side (Hetzner VM `.env`)

```
MQTT_HOST=<rpi Tailscale IP or MagicDNS name>
MQTT_PORT=1883
MQTT_USERNAME=mqtt
MQTT_PASSWORD=CHOOSE_A_PASSWORD
```

## Optional hardening

Port 1883 is published on all interfaces (incl. Tailscale). It has password auth and the
tailnet is private, so this is usually fine. To restrict it, replace the `ports:` mapping
with two explicit binds:

```yaml
    ports:
      - "127.0.0.1:1883:1883"
      - "<rpi-tailscale-ip>:1883:1883"
```
