# Target architecture (north star)

This is the **end-state** we're aiming for: Home Assistant in the cloud, a minimal home
footprint, MQTT as the integration bus. It deliberately ignores how things are wired today —
`CUTOVER.md` covers the migration path from the current setup.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                             EXTERNAL SERVICES                                 │
│     api.spot-hinta.fi  (sähköhinnat)              hc-ping.com  (watchdog)     │
└──────────▲───────────────────────────────────────────────▲───────────────────┘
           │ HTTPS pull, 15 min                            │ HTTPS ping
           │                                               │
╔══════════╪═══════════════ CLOUD  —  Hetzner VM ══════════╪═══════════════════╗
║          │                                               │                   ║
║  ┌───────┴───────────────────────────────────────────────┴───────────────┐   ║
║  │                       heating-controller  (v2)                         │   ║
║  │   APScheduler :00/:15/:30/:45 → run_cycle():                           │   ║
║  │     • lue huone- & ulkolämmöt          ┐                               │   ║
║  │     • lue perus-setpointit             │  MQTT sub                     │   ║
║  │     • päätä: kattila on/off,           │                               │   ║
║  │       per-huone setpoint / TRV-lämpö   ┘                               │   ║
║  │     • komenna releet + TRV:t           ┐  MQTT pub                     │   ║
║  │     • julkaise lasketut arvot          ┘  (HA discovery)               │   ║
║  │   zones.yaml  (kattila + huoneet, luetaan joka sykli)                  │   ║
║  └───────────────────────────┬──────────────────────────────────────────┘   ║
║                              │ MQTT  (localhost:1883)                        ║
║   ┌──────────────────────────┴───────┐         ┌──────────────────────────┐  ║
║   │        Mosquitto  (broker)       │◄───────►│     Home Assistant       │  ║
║   │   :1883  cloud-local             │  MQTT   │  • entity registry       │  ║
║   │   :8883  TLS, WAN (vain tämä     │  disc.  │  • automaatiot           │  ║
║   │          auki kotiverkolle)      │         │  • dashboard / mobiili   │  ║
║   └──────────────▲───────────────────┘         │  • number-helperit =     │  ║
║                  │                             │    perus-setpointit      │  ║
║                  │                             │  • recorder (SQLite)     │  ║
║                  │                             └──────────────────────────┘  ║
║                  │                                                           ║
║                  │             ┌─────────────────┐                           ║
║                  │             │      Caddy      │◄── HA UI                  ║
║                  │             │  reverse proxy  │                           ║
║                  │             │  TLS            │                           ║
║                  │             └────────▲────────┘                           ║
╚══════════════════╪═══════════════════════╪═══════════════════════════════════╝
                   │ MQTT / TLS :8883      │ HTTPS
                   │ (outbound only)       │ ha.ketunmetsa.fi
        ═══════════╪═══════════════════════╪═══════════ INTERNET ══════════════
                   │                       │
╔══════════════════╪═══════ HOME ══════════╪═══ suljettu verkko, vain ulos ════╗
║                  │                       │                                   ║
║  ┌───────────────┴────────┐        ┌─────┴──────┐                            ║
║  │  ESP32 (ESPHome)      │        │  selain /   │                            ║
║  │  BLE → MQTT -silta      │        │  puhelin    │                          ║
║  │  1–3 nodea kattavuuteen│        └────────────┘                            ║
║  │  eksplisiittiset yamlit│                                                  ║
║  └───▲───────────▲────────┘                                                  ║
║  BLE │           │ BLE                                                       ║
║ ┌────┴─────┐ ┌───┴──────────┐                                                ║
║ │RuuviTagit│ │Shelly H&T BLU│   paristokäyttöiset BLE-beaconit               ║
║ └──────────┘ └──────────────┘                                                ║
║                                                                             ║
║  ┌──────────────────────────────────────────────┐                           ║
║  │  Shelly-releet  +  Shelly-TRV:t              │  WiFi, natiivi MQTT-client ║
║  │  kattila / huonelämmittimet / patteriventtiilit ──► Mosquitto :8883 (ulos)║
║  └──────────────────────────────────────────────┘                           ║
║                                                                             ║
║   Ei palvelinta. Ei HA:ta. Ei SSD:tä. Vain ESP32:t + Shellyt seinälaturissa.║
╚═════════════════════════════════════════════════════════════════════════════╝
```

## Idea

- **MQTT-broker on väylä.** HA ja lämmitysohjain ovat molemmat vain sen asiakkaita. Ohjain ei
  tarvitse HA:ta ohjaukseen — se lukee sensorit ja perus-setpointit brokerista ja julkaisee
  komennot + lasketut arvot brokeriin. HA näkee kaiken discoveryn kautta ja hoitaa näytön +
  historian.

- **Kotona nolla palvelinta.** ESP32(t) hoitaa BLE→MQTT (RuuviTag, Shelly BLU). WiFi-Shellyt
  puhuvat MQTT:tä suoraan pilveen. Kaikki **ulospäin, TLS :8883** — kotiverkkoon ei avata
  mitään sisään.

- **Tailscale poistuu datapolusta.** Ei enää hyppykonetta laitteiden ja ohjaimen väliin.
  (Voit pitää sen VM:n SSH:hon / hätäyhteytenä kotiin, mutta se ei ole arkkitehtuurissa.)

- **Perus-setpointit = ohjaimen omistamat MQTT `number`-entiteetit** (discovery), joiden arvon
  ohjain pitää (retained state-topic). HA renderöi liukusäätimen; säätö menee väylän kautta.

- **Historia = HA:n oma recorder (SQLite)** cloud-VM:llä. Lasketut arvot (`heating_boiler_decision`,
  per-huone setpointit, hinnat) näkyvät HA:n History/Logbookissa ja ApexCharts-kortissa.
  (Grafana + erillinen Postgres-recorder poistettiin — jäivät käyttämättä.)

- **Vikatilanteet:** nettikatko kotona → Shellyt jäävät viimeiseen tilaan, sensoridata
  katkeaa kunnes yhteys palaa; mitään ei tarvitse konffata uusiksi. VM alas → koko homma
  seisoo (hyväksytty kompromissi tässä mittakaavassa; `hc-ping` hälyttää).

## Miksi MQTT ei vaadi kotiverkon avaamista

MQTT ei ole pollaava, mutta lopputulos on se: **laite avaa yhteyden ulospäin, komennot tulevat
takaisin samaa putkea.**

1. Shelly avaa **ulospäin TCP-yhteyden** brokeriin (`mqtt.hetzner:8883`) ja **pitää sen auki**
   (keepalive-ping ~30–60 s välein pitää NAT/palomuuritilan elossa).
2. Sen yhden auki olevan yhteyden yli viestit kulkevat **molempiin suuntiin**:
   - Shelly → broker: julkaisee tilansa (`shelly-boiler/status/switch:0`)
   - broker → Shelly: työntää komennot topiceihin joihin Shelly on subscribannut
3. Kun ohjain haluaa kytkeä kattilan, se julkaisee komennon brokeriin → broker työntää sen
   **heti** alas Shellyn jo auki olevaa yhteyttä. Ei pollausväliä, ei viivettä.

Kotiverkon tarvitsee sallia vain **outbound** portti 8883 VM:n IP:hen (yleensä oletuksena
sallittu). Ei port forwardia, ei VPN:ää, ei sisääntulevaa mitään.

Vertailu nykyiseen: HA:n Shelly-integraatio avaa WebSocketin *Shellyyn päin*
(`ws://192.168.86.x/rpc`) → sisääntuleva → vaatii tunnelin. MQTT kääntää suunnan.

Retained-viestit + QoS hoitavat "laite oli hetken offline" -tilanteen: kun Shelly yhdistää
takaisin, se saa viimeisimmän komennon/tilan jonka se missasi.

**Varauma:** Gen2/Gen3-Shellyissä (esim. `shelly1minig3`) MQTT on vankka. Gen1-laitteissa
(mahdollisesti vanhat TRV:t) MQTT on rajallisempi — siksi TRV voi jäädä suoraksi HTTP:ksi
tai vaihtua Gen2:een.

## Koti-gateway (ESP32): mikä firmware

BLE-laitteet (RuuviTag, Shelly BLU) tarvitsevat jonkin kuuntelemaan paikan päällä. Kolme
vaihtoehtoa, jotka eroavat juuri sen suhteen tarvitseeko uusi laite ESP:n uudelleenkonffausta:

| Firmware | Uusi BLE-laite | Toimii pilvi-HA + suljettu verkko |
|---|---|---|
| ESPHome **Bluetooth Proxy** | nolla konffia (ESP = tyhmä rele, HA parsii) | **ei** — vaatii ESPHome natiivi-API:n (HA → ESP sisään); ei toimi MQTT:n yli |
| ESPHome **eksplisiittiset sensorit** | ESP:n yaml-editointi + OTA per laite, per ESP | kyllä (outbound MQTT) |
| **OpenMQTTGateway** | **nolla konffia** tuetuille tyypeille (ESP dekoodaa + HA-discovery) | **kyllä** (outbound MQTT) |

**Valinta (POC:ssa todistettu): ESPHome + eksplisiittiset sensorit.** Config
`koti-devices`-repossa: `gateways/gateway.yaml`. Syyt:
- OpenMQTTGateway:lla ei ole T-Display-S3 -buildia (vain geneerinen `esp32s3-dev-c1-ble`).
- Laiteroster on vakaa → "auto-discovery vs yaml-editti" -ero on pieni.
- Eksplisiittinen yaml = sinä päätät mikä entiteetti syntyy ja millä nimellä — ei
  "ilmestyi 40 entiteettiä joista käytän kahta".

Toteutus: `esp32-s3-devkitc-1`, esp-idf-framework (MQTT-TLS), inline `certificate_authority`
(ISRG-juuret; `!include` ei parsiudu laitteen mbedtls:llä). RuuviTagit `platform: ruuvitag`,
Shelly BLU `platform: bthome_receiver` (`dz0ny/esphome-bthome` external component). Uusi
BLE-laite = yaml-editti + OTA. Useampi node kattavuuteen: kopioi + vaihda `topic_prefix`.

ESPHome BT-proxy (täysi nollakonffi) hylättiin: se vaatii ESPHome natiivi-API:n eli tunnelin
kotiin (HA ottaa yhteyden ESP:hen) — tappaa "ei mitään kotona" -idean.
