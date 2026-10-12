import numpy as np
import pandas as pd

from adaptive_ss import methods


def test_abc_pareto_cut():
    v = pd.Series([80.0, 10.0, 5.0, 3.0, 2.0], index=list("abcde"))
    assert list(methods.abc_class(v)) == ["A", "B", "B", "C", "C"]


def test_abc_independent_of_input_order():
    v = pd.Series([2.0, 80.0, 5.0, 10.0, 3.0], index=list("edcba"))
    cls = methods.abc_class(v)
    assert cls["d"] == "A" and cls["e"] == "C"


def test_xyz_thresholds():
    cv = pd.Series([0.2, 0.5, 0.51, 1.0, 1.7])
    assert list(methods.xyz_class(cv)) == ["X", "X", "Y", "Y", "Z"]


def test_service_level_matrix_ordering():
    m = methods.SERVICE_LEVEL_MATRIX
    assert m["A"]["X"] == max(v for row in m.values() for v in row.values())
    assert m["C"]["Z"] == min(v for row in m.values() for v in row.values())
    for abc in "ABC":
        assert m[abc]["X"] >= m[abc]["Y"] >= m[abc]["Z"]


def test_segment_assigns_targets_and_method():
    stats = pd.DataFrame({"annual_value": [1000.0, 10.0], "cv": [0.3, 2.0],
                          "adi": [1.0, 4.0]}, index=["m1", "m2"])
    out = methods.segment(stats)
    assert out.loc["m1", "segment"] == "AX" and out.loc["m1", "service_level"] == 0.98
    assert out.loc["m2", "segment"] == "CZ" and out.loc["m2", "service_level"] == 0.90
    assert out.loc["m2", "adaptive_method"] == "empirical"
    assert out.loc["m1", "adaptive_method"] == "rolling"


def test_adi():
    assert methods.adi(np.array([0, 0, 5, 0])) == 4.0
    assert methods.adi(np.zeros(5)) == float("inf")


def test_dataset_segments(ds):
    assert set(ds.meta["ABC"]) == {"A", "B", "C"}
    assert set(ds.meta["XYZ"]) == {"X", "Y", "Z"}
    # every intermittent synthetic material must be recognised as Z / empirical
    inter = ds.meta[ds.meta["pattern"] == "intermittent"]
    assert (inter["XYZ"] == "Z").all() and (inter["adaptive_method"] == "empirical").all()
