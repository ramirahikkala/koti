"""Load and validate ``zones.yaml`` into a :class:`ZonesConfig`."""

from __future__ import annotations

from pathlib import Path

import yaml

from koti.heating.models import RoomConfig, ZonesConfig, ZonesFile


class ZonesError(ValueError):
    """Raised when zones.yaml is missing or invalid."""


def load_zones(path: str | Path) -> ZonesConfig:
    p = Path(path)
    if not p.is_file():
        raise ZonesError(f"zones file not found: {p}")

    try:
        raw = yaml.safe_load(p.read_text()) or {}
    except yaml.YAMLError as exc:
        raise ZonesError(f"zones file is not valid YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise ZonesError("zones file must be a mapping at the top level")

    try:
        parsed = ZonesFile.model_validate(raw)
    except ValueError as exc:
        raise ZonesError(str(exc)) from exc

    defaults = parsed.rooms.defaults
    merged: list[RoomConfig] = []
    seen: set[str] = set()
    for item in parsed.rooms.items:
        if item.id in seen:
            raise ZonesError(f"duplicate room id: {item.id!r}")
        seen.add(item.id)
        fields = item.model_dump()
        if "price_low_threshold" not in item.model_fields_set:
            fields["price_low_threshold"] = defaults.price_low_threshold
        if "temp_variation" not in item.model_fields_set:
            fields["temp_variation"] = defaults.temp_variation
        merged.append(RoomConfig.model_validate(fields))

    return ZonesConfig(boiler=parsed.boiler, rooms=merged)
