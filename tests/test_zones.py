import pytest

from heating.models import RoomControl
from heating.zones import ZonesError, load_zones

VALID = """
boiler:
  switch_entity: switch.boiler
rooms:
  defaults:
    price_low_threshold: 8.0
    temp_variation: 0.4
  items:
    - id: olohuone
      control: onoff
      temp_sensor: sensor.a
      switch_entity: switch.a
      requests_boiler_heat: true
    - id: kylpy
      control: trv
      temp_sensor: sensor.b
      trv_ext_temp_url: "http://trv-b/t?temp="
      temp_variation: 1.0
"""


def write(tmp_path, text):
    p = tmp_path / "zones.yaml"
    p.write_text(text)
    return p


def test_valid_config(tmp_path):
    cfg = load_zones(write(tmp_path, VALID))
    assert cfg.boiler is not None and cfg.boiler.switch_entity == "switch.boiler"
    assert [r.id for r in cfg.rooms] == ["olohuone", "kylpy"]
    olo, kylpy = cfg.rooms
    assert olo.control is RoomControl.ONOFF
    assert olo.price_low_threshold == 8.0 and olo.temp_variation == 0.4  # from defaults
    assert kylpy.temp_variation == 1.0  # explicit override wins
    assert kylpy.price_low_threshold == 8.0


def test_missing_file(tmp_path):
    with pytest.raises(ZonesError, match="not found"):
        load_zones(tmp_path / "nope.yaml")


def test_onoff_requires_switch(tmp_path):
    text = """
rooms:
  items:
    - id: x
      control: onoff
      temp_sensor: sensor.a
"""
    with pytest.raises(ZonesError, match="switch_entity"):
        load_zones(write(tmp_path, text))


def test_trv_requires_service(tmp_path):
    text = """
rooms:
  items:
    - id: x
      control: trv
      temp_sensor: sensor.a
"""
    with pytest.raises(ZonesError, match="trv_ext_temp_url"):
        load_zones(write(tmp_path, text))


def test_duplicate_room_id(tmp_path):
    text = """
rooms:
  items:
    - {id: x, control: trv, temp_sensor: s, trv_ext_temp_url: "http://trv-x/t?temp="}
    - {id: x, control: trv, temp_sensor: s, trv_ext_temp_url: "http://trv-x/t?temp="}
"""
    with pytest.raises(ZonesError, match="duplicate"):
        load_zones(write(tmp_path, text))


def test_unknown_key_rejected(tmp_path):
    text = """
rooms:
  items:
    - id: x
      control: trv
      temp_sensor: s
      trv_ext_temp_url: "http://trv-x/t?temp="
      typo_field: 1
"""
    with pytest.raises(ZonesError):
        load_zones(write(tmp_path, text))
