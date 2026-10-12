"""Proposed MARC-EISBE changes in an MM17 / LSMW friendly flat-file layout.

Design point: the job never pushes large changes blindly.
  |change| <  DEAD_BAND      -> NO_CHANGE   (avoid nervous master data)
  |change| <= APPROVAL_LIMIT -> AUTO_UPDATE (goes into the MM17 upload file)
  |change| >  APPROVAL_LIMIT -> NEEDS_PLANNER_APPROVAL (MRP controller DISPO decides)

The status uses the larger of the EISBE and MINBE changes: with DISMM = VB the
reorder point MINBE is what actually triggers MRP, so a big MINBE move must not
slip through just because EISBE barely changed.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import simulation
from .data_gen import Dataset

SEP = ";"
DEAD_BAND = 0.05
APPROVAL_LIMIT = 0.30

STATUS_NO_CHANGE = "NO_CHANGE"
STATUS_AUTO = "AUTO_UPDATE"
STATUS_APPROVAL = "NEEDS_PLANNER_APPROVAL"
STATUS_ORDER = [STATUS_NO_CHANGE, STATUS_AUTO, STATUS_APPROVAL]   # increasing severity

EXPORT_COLUMNS = ["MATNR", "WERKS", "DISPO", "EISBE_OLD", "EISBE_NEW", "CHANGE_PCT",
                  "MINBE_OLD", "MINBE_NEW", "METHOD", "REASON", "STATUS"]


def classify_change(old: float, new: float, dead_band: float = DEAD_BAND,
                    approval_limit: float = APPROVAL_LIMIT) -> tuple[float, str]:
    """Return (change as a fraction, status)."""
    if old == 0:
        if new == 0:
            return 0.0, STATUS_NO_CHANGE
        return float("inf"), STATUS_APPROVAL
    change = (new - old) / old
    if abs(change) < dead_band:
        return change, STATUS_NO_CHANGE
    if abs(change) <= approval_limit:
        return change, STATUS_AUTO
    return change, STATUS_APPROVAL


def _pct(new: float, old: float) -> float:
    return (new - old) / old if old else 0.0


def _reason(base, new) -> str:
    """Plain-language driver of the change, written for the MRP controller."""
    drivers = []
    for label, b, n in [("demand mean", base.d_mean, new.d_mean),
                        ("demand variability", base.d_std, new.d_std),
                        ("supplier lead time", base.lt_mean, new.lt_mean),
                        ("lead-time variability", base.lt_std, new.lt_std)]:
        ch = _pct(n, b)
        if abs(ch) >= 0.10:
            drivers.append((abs(ch), f"{label} {ch:+.0%}"))
    if not drivers:
        return "Minor statistical update"
    drivers.sort(reverse=True)
    return ", ".join(text for _, text in drivers[:3]) + " vs. current setting"


def build_proposals(ds: Dataset, cfg: simulation.SimConfig = simulation.SimConfig(),
                    as_of_day: int | None = None) -> pd.DataFrame:
    """What the scheduled job would propose on `as_of_day` (default: end of data)."""
    t = ds.n_days if as_of_day is None else as_of_day
    marc = ds.marc.set_index("MATNR")
    rows = []
    for _, m in ds.meta.iterrows():
        matnr = m["MATNR"]
        sl = simulation.service_level_for(m, cfg)
        base = simulation.baseline_params(ds.demand[matnr], ds.lt_hist[matnr], sl,
                                          m["PLIFZ"], cfg.warmup)
        new = simulation.estimate(m["adaptive_method"], ds.demand[matnr], ds.lt_hist[matnr],
                                  t, sl, m["PLIFZ"], cfg)
        old_eisbe = int(marc.loc[matnr, "EISBE"])
        new_eisbe = int(np.ceil(new.ss))
        old_minbe, new_minbe = int(marc.loc[matnr, "MINBE"]), int(np.ceil(new.rop))
        change, status_ss = classify_change(old_eisbe, new_eisbe)
        _, status_rop = classify_change(old_minbe, new_minbe)
        status = max(status_ss, status_rop, key=STATUS_ORDER.index)
        rows.append({
            "MATNR": matnr,
            "WERKS": m["WERKS"],
            "DISPO": marc.loc[matnr, "DISPO"],
            "EISBE_OLD": old_eisbe,
            "EISBE_NEW": new_eisbe,
            "CHANGE_PCT": round(change * 100, 1) if np.isfinite(change) else np.nan,
            "MINBE_OLD": old_minbe,
            "MINBE_NEW": new_minbe,
            "METHOD": m["adaptive_method"],
            "REASON": _reason(base, new),
            "STATUS": status,
        })
    return pd.DataFrame(rows, columns=EXPORT_COLUMNS)


def to_csv(df: pd.DataFrame) -> str:
    """Full proposal list for the planner (semicolon separated, UTF-8)."""
    return df.to_csv(sep=SEP, index=False, lineterminator="\n")


def mm17_upload(df: pd.DataFrame) -> pd.DataFrame:
    """Only auto-approved rows, with the MARC fields MM17/LSMW needs.

    For reorder point planning with manual reorder point (DISMM = VB) MINBE must be
    maintained together with EISBE, otherwise MRP keeps triggering at the old level.
    """
    auto = df[df["STATUS"] == STATUS_AUTO]
    return auto[["MATNR", "WERKS", "EISBE_NEW", "MINBE_NEW"]].rename(
        columns={"EISBE_NEW": "EISBE", "MINBE_NEW": "MINBE"}).reset_index(drop=True)


def mm17_csv(df: pd.DataFrame) -> str:
    return to_csv(mm17_upload(df))
