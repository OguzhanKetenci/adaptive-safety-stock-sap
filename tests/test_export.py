import io

import pandas as pd
import pytest

from adaptive_ss import sap_export as ex


@pytest.mark.parametrize("old,new,status", [
    (100, 104, ex.STATUS_NO_CHANGE),
    (100, 120, ex.STATUS_AUTO),
    (100, 130, ex.STATUS_AUTO),
    (100, 131, ex.STATUS_APPROVAL),
    (100, 69, ex.STATUS_APPROVAL),
    (100, 75, ex.STATUS_AUTO),
    (0, 0, ex.STATUS_NO_CHANGE),
    (0, 10, ex.STATUS_APPROVAL),
])
def test_classify_change(old, new, status):
    assert ex.classify_change(old, new)[1] == status


@pytest.fixture(scope="module")
def proposals(ds):
    return ex.build_proposals(ds)


def test_export_layout(proposals):
    text = ex.to_csv(proposals)
    header = text.splitlines()[0]
    assert header.split(";")[:6] == ["MATNR", "WERKS", "DISPO", "EISBE_OLD", "EISBE_NEW", "CHANGE_PCT"]
    back = pd.read_csv(io.StringIO(text), sep=";", dtype={"MATNR": str, "WERKS": str})
    assert len(back) == 30
    assert {"REASON", "STATUS"} <= set(back.columns)
    assert back["STATUS"].isin([ex.STATUS_NO_CHANGE, ex.STATUS_AUTO, ex.STATUS_APPROVAL]).all()
    assert back["EISBE_NEW"].dtype.kind == "i"


def test_big_changes_require_approval(proposals):
    big = proposals["CHANGE_PCT"].abs() > 30
    assert big.any()
    assert (proposals.loc[big, "STATUS"] == ex.STATUS_APPROVAL).all()


def test_mm17_file_only_contains_auto_updates(proposals):
    up = ex.mm17_upload(proposals)
    assert list(up.columns) == ["MATNR", "WERKS", "EISBE", "MINBE"]
    auto = proposals[proposals["STATUS"] == ex.STATUS_AUTO]
    assert set(up["MATNR"]) == set(auto["MATNR"])
    assert ex.mm17_csv(proposals).splitlines()[0] == "MATNR;WERKS;EISBE;MINBE"
