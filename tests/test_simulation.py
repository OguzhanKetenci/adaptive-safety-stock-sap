import numpy as np
import pytest

from adaptive_ss import simulation as sim


def _run(ds, matnr, method, **cfg):
    row = ds.meta.set_index("MATNR").loc[matnr]
    return sim.simulate_material(ds.demand[matnr], ds.lt_hist[matnr], ds.lt_draws[matnr],
                                 row["service_level"], row["PLIFZ"], method,
                                 sim.SimConfig(**cfg), matnr=matnr)


@pytest.fixture(scope="module")
def sample_materials(ds):
    # one material of every demand pattern
    return ds.meta.groupby("pattern")["MATNR"].first().tolist()


@pytest.mark.parametrize("method", ["static", "rolling", "ewma", "empirical"])
def test_lost_sales_never_negative_and_flow_balance(ds, sample_materials, method):
    for m in sample_materials:
        d = _run(ds, m, method, lost_sales=True).daily
        assert (d["on_hand"] >= -1e-9).all()
        assert np.allclose(d["served"] + d["unmet"], d["demand"])
        # day by day: stock_t = stock_(t-1) + receipts_t - issues_t
        prev = d["on_hand"].shift(1).to_numpy()
        assert np.allclose((prev + d["receipt_qty"] - d["served"])[1:], d["on_hand"][1:])


def test_backorder_mode_balance(ds, sample_materials):
    for m in sample_materials:
        d = _run(ds, m, "static", lost_sales=False).daily
        prev = d["on_hand"].shift(1).to_numpy()
        assert np.allclose((prev + d["receipt_qty"] - d["demand"])[1:], d["on_hand"][1:])


def test_purchase_order_conservation(ds, sample_materials):
    for m in sample_materials:
        d = _run(ds, m, "rolling").daily
        # everything ordered is either received or still in the pipeline
        assert d["order_qty"].sum() == pytest.approx(d["receipt_qty"].sum() + d["pipeline"].iloc[-1])
        assert np.allclose(d["position"], d["on_hand"] + d["pipeline"])


def test_static_never_changes_and_adaptive_only_on_review_days(ds):
    m = ds.materials[7]
    st = _run(ds, m, "static").daily
    assert st["ss"].nunique() == 1
    ad = _run(ds, m, "rolling", review_every=14).daily
    change_days = ad.index[ad["ss"].diff().fillna(0) != 0]
    assert len(change_days) > 0
    assert all((t - 60) % 14 == 0 for t in change_days)


def test_identical_during_warmup(ds):
    m = ds.materials[3]
    a, b = _run(ds, m, "static").daily, _run(ds, m, "ewma").daily
    assert a.iloc[:60].equals(b.iloc[:60])


def test_deterministic_runs(ds):
    m = ds.materials[20]
    assert _run(ds, m, "empirical").daily.equals(_run(ds, m, "empirical").daily)


def test_no_lookahead(ds):
    """Parameters on day t must not depend on demand from day t onwards."""
    m = ds.materials[8]
    row = ds.meta.set_index("MATNR").loc[m]
    d = ds.demand[m].copy()
    cfg = sim.SimConfig()
    p1 = sim.estimate("rolling", d, ds.lt_hist[m], 200, row["service_level"], row["PLIFZ"], cfg)
    d[200:] *= 10
    p2 = sim.estimate("rolling", d, ds.lt_hist[m], 200, row["service_level"], row["PLIFZ"], cfg)
    assert p1 == p2


def test_growth_material_static_underperforms(ds):
    from adaptive_ss import costs
    m = ds.meta[ds.meta["pattern"] == "growth"]["MATNR"].iloc[0]
    res = {(m, k): _run(ds, m, k) for k in ["static", "rolling"]}
    k = costs.kpi_table(res, ds.meta[ds.meta["MATNR"] == m]).set_index("method")
    assert k.loc["rolling", "fill_rate"] > k.loc["static", "fill_rate"]
