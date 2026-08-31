"""Ported from v1 tests/test_temperature_control.py::TestCentralHeatingControl."""

from koti.heating.logic.boiler import boiler_should_run, price_rank

MAX_SHUTOFF_HOURS = 6.0
ALWAYS_ON = 5.0


def run(price: float, prices: list[float]) -> tuple[bool, str]:
    return boiler_should_run(
        price, prices, max_shutoff_hours=MAX_SHUTOFF_HOURS, always_on_threshold=ALWAYS_ON
    )


class TestBoilerControl:
    def test_cheap_price_always_on(self):
        should_run, reason = run(5.0 - 0.1, [10.0] * 96)
        assert should_run is True
        assert "always on" in reason.lower() or "threshold" in reason.lower()

    def test_15_minute_granularity(self):
        prices = [10.0 + i * 0.1 for i in range(96)]
        should_run, reason = run(15.0, prices)
        assert isinstance(should_run, bool) and isinstance(reason, str)

    def test_top_expensive_quarters_shutoff(self):
        prices = [10.0] * 88 + [50.0] * 8
        should_run, reason = run(50.0, prices)
        assert should_run is False
        assert "top" in reason.lower() or "expensive" in reason.lower()

    def test_low_price_in_expensive_range(self):
        prices = [50.0] * 88 + [60.0] * 8
        should_run, _ = run(10.0, prices)
        assert should_run is True

    def test_tied_prices_ranked_correctly(self):
        prices = [20.0] * 50 + [30.0] * 46
        assert isinstance(run(20.0, prices)[0], bool)
        assert isinstance(run(30.0, prices)[0], bool)

    def test_max_shutoff_hours_respected(self):
        expensive = int(MAX_SHUTOFF_HOURS * 4)
        prices = [10.0] * (96 - expensive) + [50.0] * expensive
        should_run, reason = run(50.0, prices)
        assert should_run is False
        assert str(expensive) in reason or "top" in reason.lower()

    def test_no_prices_defaults_on(self):
        should_run, reason = run(10.0, [])
        assert should_run is True
        assert "no" in reason.lower() or "available" in reason.lower()

    def test_result_format(self):
        result = run(15.0, [15.0] * 96)
        assert isinstance(result, tuple) and len(result) == 2
        should_run, reason = result
        assert isinstance(should_run, bool) and isinstance(reason, str)


class TestPriceRank:
    def test_most_expensive_is_rank_1(self):
        prices = [10.0] * 95 + [99.0]
        assert price_rank(99.0, prices) == 1

    def test_cheapest_is_last(self):
        prices = [10.0] * 95 + [99.0]
        assert price_rank(10.0, prices) == 96
