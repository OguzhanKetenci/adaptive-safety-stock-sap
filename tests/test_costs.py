import numpy as np
import pandas as pd
import pytest

from adaptive_ss import costs
from adaptive_ss.simulation import SimResult


def _fake(on_hand, demand, served, n_orders):
    n = len(on_hand)
    daily = pd.DataFrame({"day": np.arange(n), "demand": demand, "on_hand": on_hand,
                          "served": served, "unmet": np.array(demand) - np.array(served),
                          "ss": np.zeros(n)})
    return SimResult("M1", "static", daily, np.array([[0, 5, 1], [5, 9, 0]], float), n_orders)


def test_cost_components():
    res = _fake([10.0] * 365, [2.0] * 365, [2.0] * 364 + [1.0], n_orders=4)
    cp = costs.CostParams(holding_rate=0.2, margin_rate=0.25, stockout_margin_multiple=2.0,
                          ordering_cost=50.0)
    assert cp.stockout_factor == pytest.approx(0.5)
    k = costs.material_kpis(res, price=100.0, costs=cp, warmup=0)
    assert k["holding_cost"] == pytest.approx(10 * 100 * 0.2)
    assert k["stockout_cost"] == pytest.approx(1 * 100 * 0.5)
    assert k["ordering_cost"] == 200
    assert k["total_cost"] == pytest.approx(200 + 50 + 200)
    assert k["stockout_days"] == 1
    assert k["cycle_service_level"] == 0.5
    assert k["fill_rate"] == pytest.approx(729 / 730)


def test_headline_sign(ds):
    from adaptive_ss import simulation
    res = simulation.run_all(ds)
    h = costs.headline(costs.kpi_table(res, ds.meta))
    # headline compares against the quarterly refresh, not the never-updated setting
    assert h["savings"] == pytest.approx(h["baseline_cost"] - h["adaptive_cost"])
    assert {"static_cost", "static_fill", "baseline_fill", "adaptive_fill"} <= set(h)


def test_default_stockout_cost_is_margin_based():
    assert costs.CostParams().stockout_factor == pytest.approx(0.25 * 1.5)
