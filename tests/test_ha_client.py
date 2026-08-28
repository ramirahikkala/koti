from __future__ import annotations

import httpx
import pytest

from heating.ha.client import HAClient
from heating.ha.price import PriceClient


@pytest.fixture
def ha() -> HAClient:
    return HAClient(
        "http://ha.test", "tok", retries=2, client=httpx.Client(base_url="http://ha.test")
    )


class TestHAClient:
    def test_get_state_float(self, ha, httpx_mock):
        httpx_mock.add_response(url="http://ha.test/api/states/sensor.t", json={"state": "21.4"})
        assert ha.get_state_float("sensor.t") == 21.4

    def test_unavailable_is_none(self, ha, httpx_mock):
        httpx_mock.add_response(
            url="http://ha.test/api/states/sensor.t", json={"state": "unavailable"}
        )
        assert ha.get_state("sensor.t") is None

    def test_get_retries_then_gives_up(self, ha, httpx_mock):
        httpx_mock.add_response(status_code=500)
        httpx_mock.add_response(status_code=500)
        assert ha.get_state("sensor.t") is None

    def test_call_service_payload(self, ha, httpx_mock):
        httpx_mock.add_response(url="http://ha.test/api/services/rest_command/x", json={})
        assert ha.call_service("rest_command", "x", {"temp": 20.5}) is True
        import json

        req = httpx_mock.get_requests()[0]
        assert json.loads(req.read()) == {"temp": 20.5}

    def test_set_switch_confirms_state(self, ha, httpx_mock):
        httpx_mock.add_response(url="http://ha.test/api/services/switch/turn_on", json={})
        httpx_mock.add_response(url="http://ha.test/api/states/switch.s", json={"state": "on"})
        assert ha.set_switch("switch.s", True) is True


class TestPriceClient:
    def test_current_price_cents(self, httpx_mock):
        httpx_mock.add_response(url="http://p.test/now", json={"PriceWithTax": 0.12483})
        pc = PriceClient("http://p.test/now", "http://p.test/fwd", client=httpx.Client())
        assert pc.current_price() == pytest.approx(12.483)

    def test_daily_prices_filtered_by_date(self, httpx_mock):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        today = datetime.now(ZoneInfo("Europe/Helsinki")).date()
        data = [
            {"DateTime": f"{today}T00:00:00+02:00", "PriceWithTax": 0.10},
            {"DateTime": f"{today}T00:15:00+02:00", "PriceWithTax": 0.20},
            {"DateTime": "2000-01-01T00:00:00+02:00", "PriceWithTax": 9.99},
        ]
        httpx_mock.add_response(url="http://p.test/fwd", json=data)
        pc = PriceClient("http://p.test/now", "http://p.test/fwd", client=httpx.Client())
        assert pc.daily_prices() == [10.0, 20.0]
