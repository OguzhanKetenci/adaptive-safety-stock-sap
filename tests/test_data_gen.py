import pandas as pd

from adaptive_ss import data_gen


def test_shape_and_sap_fields(ds):
    assert len(ds.mara) == 30 and len(ds.marc) == 30
    assert set(ds.marc["WERKS"]) == {"1000", "2000"}
    assert {"MATNR", "MAKTX", "MEINS"} <= set(ds.mara.columns)
    assert {"MATNR", "WERKS", "EISBE", "PLIFZ", "DISMM", "MINBE", "BSTFE"} <= set(ds.marc.columns)
    assert set(ds.meta["pattern"]) == {"stable", "growth", "decline", "seasonal",
                                       "intermittent", "regime_shift"}


def test_deterministic():
    a, b = data_gen.generate(), data_gen.generate()
    pd.testing.assert_frame_equal(a.marc, b.marc)
    pd.testing.assert_frame_equal(a.ekbe, b.ekbe)
    for m in a.materials:
        assert (a.demand[m] == b.demand[m]).all()
        assert (a.lt_draws[m] == b.lt_draws[m]).all()


def test_lead_times_from_purchasing_tables(ds):
    po = ds.ekbe.merge(ds.ekko, on="EBELN").merge(ds.ekpo[["EBELN", "MATNR"]], on="EBELN")
    lt = (po["BUDAT"] - po["BEDAT"]).dt.days
    assert (lt >= 1).all()
    m = ds.materials[0]
    assert sorted(lt[po["MATNR"] == m]) == sorted(ds.lt_hist[m]["lt"])


def test_non_negative_demand_and_regime_shift(ds):
    for m in ds.materials:
        assert (ds.demand[m] >= 0).all()
    for m in ds.meta.loc[ds.meta["pattern"] == "regime_shift", "MATNR"]:
        d = ds.demand[m]
        before, after = d[:data_gen.SHIFT_DAY], d[data_gen.SHIFT_DAY:]
        cv_before, cv_after = before.std() / before.mean(), after.std() / after.mean()
        assert cv_after > 1.3 * cv_before                     # volatility regime changed (x1.5)
        assert 0.07 < abs(after.mean() / before.mean() - 1) < 0.30   # mild level step (10-25 %)


def test_trends_are_mild(ds):
    """Growth / decline change the level by roughly 10-25 % over the horizon."""
    for pat in ["growth", "decline"]:
        for m in ds.meta.loc[ds.meta["pattern"] == pat, "MATNR"]:
            d = ds.demand[m]
            ratio = d[-90:].mean() / d[:90].mean()
            assert 0.70 < ratio < 1.35
