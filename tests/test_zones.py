import pytest

from koti.heating.models import RoomControl
from koti.heating.zones import ZonesError, load_zones

VALID = """
boiler:
  switch_topic: shelly-boiler
rooms:
  defaults:
    price_low_threshold: 8.0
    temp_variation: 0.4
  items:
    - id: olohuone
      control: onoff
      temp_topic: gw/a/state
      switch_topic: shelly-a
      base_temp: {default: 21.0}
      requests_boiler_heat: true
    - id: kylpy
      control: trv
      temp_topic: gw/b/state
      trv_ext_temp_topic: shellies/trv-b/ext_t/0
      temp_variation: 1.0
"""


def write(tmp_path, text):
    p = tmp_path / "zones.yaml"
    p.write_text(text)
    return p


def test_valid_config(tmp_path):
    cfg = load_zones(write(tmp_path, VALID))
    assert cfg.boiler is not None and cfg.boiler.switch_topic == "shelly-boiler"
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
      temp_topic: gw/a/state
"""
    with pytest.raises(ZonesError, match="switch_topic"):
        load_zones(write(tmp_path, text))


def test_onoff_requires_base_temp(tmp_path):
    text = """
rooms:
  items:
    - id: x
      control: onoff
      temp_topic: gw/a/state
      switch_topic: shelly-x
"""
    with pytest.raises(ZonesError, match="base_temp"):
        load_zones(write(tmp_path, text))


def test_trv_requires_service(tmp_path):
    text = """
rooms:
  items:
    - id: x
      control: trv
      temp_topic: gw/a/state
"""
    with pytest.raises(ZonesError, match="trv_ext_temp_topic"):
        load_zones(write(tmp_path, text))


def test_duplicate_room_id(tmp_path):
    text = """
rooms:
  items:
    - {id: x, control: trv, temp_topic: s, trv_ext_temp_topic: t}
    - {id: x, control: trv, temp_topic: s, trv_ext_temp_topic: t}
"""
    with pytest.raises(ZonesError, match="duplicate"):
        load_zones(write(tmp_path, text))


def test_unknown_key_rejected(tmp_path):
    text = """
rooms:
  items:
    - id: x
      control: trv
      temp_topic: s
      trv_ext_temp_topic: t
      typo_field: 1
"""
    with pytest.raises(ZonesError):
        load_zones(write(tmp_path, text))
