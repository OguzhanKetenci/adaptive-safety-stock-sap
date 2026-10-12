import numpy as np
import pytest

from adaptive_ss import costs, data_gen, methods, simulation


def test_seasonality_strength_detects_yearly_wave():
    t = np.arange(365)
    rng = np.random.default_rng([1, 2])
    seasonal = 50 * (1 + 0.4 * np.sin(2 * np.pi * t / 365)) + rng.normal(0, 3, 365)
    assert methods.seasonality_strength(seasonal) > 0.8


def test_trend_and_noise_are_not_seasonal():
    t = np.arange(365)
    rng = np.random.default_rng([3, 4])
    trend = 50 + 0.05 * t + rng.normal(0, 5, 365)
    noise = 50 + rng.normal(0, 10, 365)
    # one year of weekly buckets is noisy: pure noise can score ~0.4, but must stay
    # below the classification threshold
    assert methods.seasonality_strength(trend) < methods.SEASONALITY_THRESHOLD
    assert methods.seasonality_strength(noise) < methods.SEASONALITY_THRESHOLD


def test_seasonality_needs_enough_history():
    assert methods.seasonality_strength(np.ones(100)) == 0.0


@pytest.mark.parametrize("series,expected", [
    (np.full(100, 10.0), "smooth"),
    (np.tile([1.0, 30.0], 50), "erratic"),
    (np.tile([0, 0, 0, 10.0], 25), "intermittent"),
    (np.tile([0, 0, 0, 1.0, 0, 0, 0, 40.0], 12), "lumpy"),
])
def test_sbc_classes(series, expected):
    assert methods.sbc_class(series)[0] == expected


def test_classify_policy_flags():
    t = np.arange(365)
    seasonal = 50 * (1 + 0.5 * np.sin(2 * np.pi * t / 365))
    assert methods.classify_policy(seasonal)["weekly_review"]
    assert not methods.classify_policy(np.full(365, 20.0))["weekly_review"]
    assert methods.classify_policy(np.tile([0, 0, 0, 0, 8.0], 73))["is_intermittent"]


def test_classification_uses_only_pre_golive_history(ds):
    assert all(len(h) == data_gen.HISTORY_DAYS for h in ds.history.values())
    m = ds.materials[15]
    row = ds.meta.set_index("MATNR").loc[m]
    assert row["seasonality_strength"] == pytest.approx(
        methods.seasonality_strength(ds.history[m]))


def test_history_does_not_change_horizon(ds):
    """The history uses its own random stream: horizon demand is reproducible on its own."""
    d, _, h = data_gen._demand_series("seasonal", 15, data_gen.N_DAYS, hist_days=100)
    assert np.array_equal(d, ds.demand[ds.materials[15]])
    assert len(h) == 100


def test_segmented_composite_picks_right_method(ds):
    res = simulation.run_all(ds, method_list=["quarterly", "rolling", "empirical"])
    k = costs.kpi_table(res, ds.meta).set_index(["MATNR", "method"])["total_cost"]
    for _, row in ds.meta.iterrows():
        src = row["adaptive_method"] if row["weekly_review"] else "quarterly"
        assert k[(row["MATNR"], "segmented")] == pytest.approx(k[(row["MATNR"], src)])


def test_intermittent_materials_go_weekly(ds):
    inter = ds.meta[ds.meta["pattern"] == "intermittent"]
    assert inter["weekly_review"].all()
