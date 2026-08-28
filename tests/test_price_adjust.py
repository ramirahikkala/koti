"""Ported from v1 tests/test_temperature_control.py (adjustment + setpoint + linear + edges)."""

from heating.logic.price_adjust import setpoint_temperature, temperature_adjustment

LOW = 10.0
VARIATION = 0.5
BASE = 21.0


def adj(price: float) -> float:
    return temperature_adjustment(price, low_threshold=LOW, max_variation=VARIATION)


def setp(price: float, base: float = BASE) -> tuple[float, float]:
    return setpoint_temperature(price, base, low_threshold=LOW, max_variation=VARIATION)


class TestTemperatureAdjustment:
    def test_negative_price(self):
        assert adj(-5) == VARIATION == 0.5

    def test_zero_price(self):
        assert adj(0) == VARIATION == 0.5

    def test_baseline_price(self):
        assert adj(LOW) == 0.0

    def test_mid_range_price(self):
        assert adj(15) == -0.25

    def test_high_threshold_price(self):
        assert adj(20) == -VARIATION == -0.5

    def test_extreme_high_price(self):
        assert adj(60) == -VARIATION == -0.5

    def test_cheap_electricity_5_cents(self):
        assert adj(5) == 0.25

    def test_adjustment_within_bounds(self):
        for price in [-10, -5, 0, 2, 5, 8, 10, 12, 15, 18, 20, 30, 50, 100]:
            assert -VARIATION <= adj(price) <= VARIATION


class TestSetpointTemperature:
    def test_setpoint_at_zero_price(self):
        setpoint, adjustment = setp(0)
        assert setpoint == BASE + VARIATION == 21.5
        assert adjustment == 0.5

    def test_setpoint_at_baseline(self):
        setpoint, adjustment = setp(10)
        assert setpoint == BASE == 21.0
        assert adjustment == 0.0

    def test_setpoint_at_high_price(self):
        setpoint, adjustment = setp(20)
        assert setpoint == BASE - VARIATION == 20.5
        assert adjustment == -0.5

    def test_setpoint_returns_tuple(self):
        result = setp(10)
        assert isinstance(result, tuple) and len(result) == 2
        setpoint, adjustment = result
        assert isinstance(setpoint, float) and isinstance(adjustment, float)


class TestLinearFormula:
    def test_linear_progression_cheap_range(self):
        assert adj(0) > adj(5) > adj(10)
        assert (adj(0), adj(5), adj(10)) == (0.5, 0.25, 0.0)

    def test_linear_progression_expensive_range(self):
        assert adj(10) > adj(15) > adj(20)
        assert (adj(10), adj(15), adj(20)) == (0.0, -0.25, -0.5)

    def test_symmetry(self):
        assert adj(0) == -adj(20)
        assert abs(adj(0)) == abs(adj(20))


class TestEdgeCases:
    def test_very_negative_price(self):
        assert adj(-100) == 0.5

    def test_very_high_price(self):
        assert adj(1000) == -0.5

    def test_float_prices(self):
        a = adj(10.172)
        assert isinstance(a, float) and -0.5 <= a <= 0.5

    def test_rounding(self):
        a = adj(7.333)
        assert round(a, 2) == a
