import math

import numpy as np
import pytest

from adaptive_ss import methods


def test_z_value_known_points():
    assert methods.z_value(0.5) == pytest.approx(0.0, abs=1e-9)
    assert methods.z_value(0.95) == pytest.approx(1.6449, abs=1e-4)
    assert methods.z_value(0.98) == pytest.approx(2.0537, abs=1e-4)


def test_safety_stock_formula_hand_calculation():
    # z=2, d=10/day, sigma_d=3, LT=4 days, sigma_LT=1 day
    # var = 4*3^2 + 10^2*1^2 = 136
    assert methods.safety_stock_formula(2, 10, 3, 4, 1) == pytest.approx(2 * math.sqrt(136))


def test_formula_reduces_to_demand_only_case():
    # no lead-time variability -> z * sigma_d * sqrt(LT)
    assert methods.safety_stock_formula(1.645, 50, 10, 9, 0) == pytest.approx(1.645 * 10 * 3)


def test_formula_zero_when_no_uncertainty():
    assert methods.safety_stock_formula(2.0, 10, 0, 5, 0) == 0.0


def test_rolling_params_constant_history():
    p = methods.rolling_params(np.full(60, 10.0), np.array([5, 5, 5]), 0.95, plifz=7)
    assert p.ss == pytest.approx(0.0)
    assert p.rop == pytest.approx(50.0)
    assert p.q == 50


def test_rolling_params_falls_back_to_plifz_without_receipts():
    p = methods.rolling_params(np.full(30, 4.0), np.array([]), 0.95, plifz=12)
    assert p.lt_mean == 12 and p.lt_std == 0


def test_lot_size_at_least_one():
    assert methods.lot_size(0.01, 3) == 1


def test_ewma_constant_and_alpha_one():
    m, s = methods.ewma_stats(np.full(50, 7.0), 0.1)
    assert m == pytest.approx(7.0) and s == pytest.approx(0.0)
    m, _ = methods.ewma_stats(np.array([1.0, 2.0, 9.0]), 1.0)
    assert m == pytest.approx(9.0)


def test_ewma_reacts_faster_than_long_window_after_step():
    x = np.r_[np.full(80, 10.0), np.full(20, 20.0)]
    ewma_mean, _ = methods.ewma_stats(x, 0.1)
    assert ewma_mean > x.mean()
    assert ewma_mean > 18


def test_lead_time_demand_samples():
    d = np.array([1.0, 2.0, 3.0, 4.0])
    s = methods.lead_time_demand_samples(d, np.array([2]))
    assert list(s) == [3.0, 5.0, 7.0]


def test_empirical_percentile_simple_case():
    d = np.tile([0.0, 10.0], 50)            # mean 5/day
    p = methods.empirical_params(d, np.array([1, 1, 1]), 0.9, plifz=1)
    assert p.rop == pytest.approx(10.0)      # 90th percentile of 1-day demand
    assert p.ss == pytest.approx(5.0)        # ROP minus expected lead-time demand


def test_empirical_constant_demand_has_no_safety_stock():
    p = methods.empirical_params(np.full(100, 3.0), np.array([4, 4, 4]), 0.95, plifz=4)
    assert p.ss == pytest.approx(0.0)
