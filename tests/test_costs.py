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
    k = costs.material_kpis(res, price=100.0, costs=costs.CostParams(0.2, 0.5, 50.0), warmup=0)
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
    assert h["savings"] == pytest.approx(h["static_cost"] - h["adaptive_cost"])
    assert h["adaptive_fill"] > h["static_fill"]
