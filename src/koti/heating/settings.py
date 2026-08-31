"""Environment / ``.env`` settings."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Home Assistant
    ha_url: str = "https://ha.ketunmetsa.fi"
    ha_api_token: str

    # MQTT (Home Assistant discovery)
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_username: str | None = None
    mqtt_password: str | None = None
    mqtt_discovery_prefix: str = "homeassistant"
    mqtt_node_id: str = "heating_controller"

    # Spot-Hinta price API
    spot_hinta_api_justnow: str = "https://api.spot-hinta.fi/JustNow"
    spot_hinta_api_url: str = "https://api.spot-hinta.fi/TodayAndDayForward"

    # Misc
    timezone: str = Field(default="Europe/Helsinki", alias="TZ")
    outdoor_temp_sensor: str | None = None
    healthcheck_url: str | None = None
    zones_file: str = "zones.yaml"
    dry_run: bool = False
    price_avg_exclude_top_hours: float = 6.0


def load_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
