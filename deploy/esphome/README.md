# esphome — BLE→MQTT gateway nodes

ESPHome firmware for the home BLE gateway(s). Reads **explicitly listed** RuuviTag / BTHome
devices and publishes them to the cloud MQTT broker (`mqtt.ketunmetsa.fi:8883`, TLS,
user `gateway`) with HA MQTT discovery.

Chosen over OpenMQTTGateway on purpose: the device roster is stable, and explicit config
means you decide exactly which entities land in HA and what they're called.

## One-time setup (laptop)

```bash
cd deploy/esphome
cp secrets.yaml.example secrets.yaml     # fill in wifi + mqtt + ota
cat /opt/infra/mqtt/certs/ca.crt > mqtt-ca.pem   # copy from the VM (scp / paste)
```

## Flash

```bash
# first time: USB
uvx esphome run gateway.yaml
# after that, from a machine on the home LAN: OTA (same command, pick the network target)
```

## Adding a RuuviTag (two steps)

1. Flash `gateway.yaml` as-is (no `sensor:` block yet). It logs every BLE advertisement:
   ```
   [scan] AA:BB:CC:DD:EE:FF  rssi=-70  name='Ruuvi 1A2B'
   ```
   `uvx esphome logs gateway.yaml` to watch.
2. Add a `sensor:` block per tag (uncomment the template at the bottom of `gateway.yaml`),
   fill the MAC, keep only the measurements you want, name them. `uvx esphome run` again.
3. Comment out the `on_ble_advertise` logging block once you're done — it's noisy.

## More gateway nodes (BLE coverage)

Copy `gateway.yaml` → `gateway-02.yaml`, change `name:`/`topic_prefix:`, and either repeat
the sensor list or share it via an ESPHome `packages:` include.
