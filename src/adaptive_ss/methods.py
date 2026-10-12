"""Safety stock methods and ABC/XYZ segmentation.

All functions are pure: they take history up to "today" and return parameters.
The simulation decides *when* they are called (static = once, adaptive = every N days).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.special import ndtri

METHODS = ["quarterly", "static", "rolling", "ewma", "empirical"]
METHOD_LABELS = {
    "quarterly": "Quarterly refresh (baseline)",
    "static": "Never updated (reference)",
    "rolling": "Rolling window",
    "ewma": "EWMA",
    "empirical": "Empirical percentile",
    "adaptive": "Adaptive for all (weekly)",
    "segmented": "Segmented policy",
}

# Target cycle service level per ABC x XYZ segment.
# A items and stable (X) items get the highest protection; CZ the lowest.
SERVICE_LEVEL_MATRIX = {
    "A": {"X": 0.98, "Y": 0.97, "Z": 0.95},
    "B": {"X": 0.96, "Y": 0.95, "Z": 0.92},
    "C": {"X": 0.93, "Y": 0.92, "Z": 0.90},
}

# Average inter-demand interval above which demand is treated as intermittent
# (Syntetos-Boylan cut-off).
ADI_INTERMITTENT = 1.32

# Segmented policy: seasonality strength from which a material counts as seasonal.
# Fixed before any results were looked at (0.6 ~ "strong" seasonality in the
# Hyndman/Wang strength-of-seasonality scale).
SEASONALITY_THRESHOLD = 0.6
CV2_LUMPY = 0.49        # Syntetos-Boylan cut-off for the variability of demand sizes


# ---------------------------------------------------------------------------
# Core formulas
# ---------------------------------------------------------------------------
def z_value(service_level: float) -> float:
    """z-factor for a cycle service level (e.g. 0.95 -> 1.645)."""
    service_level = float(np.clip(service_level, 0.5, 0.9999))
    return float(ndtri(service_level))  # inverse standard normal CDF


def safety_stock_formula(z: float, d_mean: float, d_std: float,
                         lt_mean: float, lt_std: float) -> float:
    """Classic combined demand + lead-time uncertainty formula.

    SS = z * sqrt(LT_mean * sigma_d^2 + d_mean^2 * sigma_LT^2)
    All demand figures per day, lead time in days.
    """
    var = lt_mean * d_std ** 2 + d_mean ** 2 * lt_std ** 2
    return float(max(0.0, z * np.sqrt(max(var, 0.0))))


def reorder_point(d_mean: float, lt_mean: float, ss: float) -> float:
    return d_mean * lt_mean + ss


def lot_size(d_mean: float, lt_mean: float) -> int:
    """Q ~ expected lead-time demand, at least 1 unit (as specified)."""
    return int(max(1, np.ceil(d_mean * lt_mean)))


@dataclass
class Params:
    """Planning parameters valid from a given day."""
    ss: float
    rop: float
    q: int
    d_mean: float
    d_std: float
    lt_mean: float
    lt_std: float


def _lt_stats(lt_obs: np.ndarray, plifz: float) -> tuple[float, float]:
    """Lead-time mean/std from observed receipts; fall back to planned PLIFZ."""
    lt_obs = np.asarray(lt_obs, dtype=float)
    if lt_obs.size == 0:
        return float(plifz), 0.0
    if lt_obs.size == 1:
        return float(lt_obs[0]), 0.0
    return float(lt_obs.mean()), float(lt_obs.std(ddof=1))


def _finish(ss: float, d_mean: float, d_std: float, lt_mean: float, lt_std: float,
            rop: float | None = None) -> Params:
    rop = reorder_point(d_mean, lt_mean, ss) if rop is None else rop
    return Params(ss=ss, rop=rop, q=lot_size(d_mean, lt_mean), d_mean=d_mean,
                  d_std=d_std, lt_mean=lt_mean, lt_std=lt_std)


# ---------------------------------------------------------------------------
# Methods
# ---------------------------------------------------------------------------
def rolling_params(demand: np.ndarray, lt_obs: np.ndarray, service_level: float,
                   plifz: float) -> Params:
    """Formula-based SS on a window of recent history (also used for static)."""
    demand = np.asarray(demand, dtype=float)
    d_mean = float(demand.mean()) if demand.size else 0.0
    d_std = float(demand.std(ddof=1)) if demand.size > 1 else 0.0
    lt_mean, lt_std = _lt_stats(lt_obs, plifz)
    ss = safety_stock_formula(z_value(service_level), d_mean, d_std, lt_mean, lt_std)
    return _finish(ss, d_mean, d_std, lt_mean, lt_std)


def ewma_stats(x: np.ndarray, alpha: float) -> tuple[float, float]:
    """Exponentially weighted mean and standard deviation.

    The newest observation gets weight 1, the one before (1 - alpha), then
    (1 - alpha)^2, ... so recent demand dominates while old demand fades out.
    """
    x = np.asarray(x, dtype=float)
    if x.size == 0:
        return 0.0, 0.0
    w = (1.0 - alpha) ** np.arange(x.size - 1, -1, -1)
    w /= w.sum()
    mean = float(np.dot(w, x))
    var = float(np.dot(w, (x - mean) ** 2))
    return mean, float(np.sqrt(max(var, 0.0)))


def ewma_params(demand: np.ndarray, lt_obs: np.ndarray, service_level: float,
                plifz: float, alpha: float = 0.05, alpha_lt: float = 0.2) -> Params:
    """EWMA mean and variance of demand (and of lead times) plugged into the formula."""
    d_mean, d_std = ewma_stats(demand, alpha)
    lt_obs = np.asarray(lt_obs, dtype=float)
    if lt_obs.size >= 2:
        lt_mean, lt_std = ewma_stats(lt_obs, alpha_lt)
    else:
        lt_mean, lt_std = _lt_stats(lt_obs, plifz)
    ss = safety_stock_formula(z_value(service_level), d_mean, d_std, lt_mean, lt_std)
    return _finish(ss, d_mean, d_std, lt_mean, lt_std)


def lead_time_demand_samples(demand: np.ndarray, lt_obs: np.ndarray) -> np.ndarray:
    """All observed demand sums over windows whose length equals an observed lead time.

    Deterministic bootstrap: no random sampling, every (lead time, start day) pair is used.
    """
    demand = np.asarray(demand, dtype=float)
    cs = np.concatenate([[0.0], np.cumsum(demand)])
    out = []
    for lt in np.asarray(lt_obs, dtype=int):
        lt = max(1, int(lt))
        if lt < demand.size:
            out.append(cs[lt:] - cs[:-lt])
    return np.concatenate(out) if out else np.array([])


def empirical_params(demand: np.ndarray, lt_obs: np.ndarray, service_level: float,
                     plifz: float) -> Params:
    """Percentile of the empirical lead-time-demand distribution.

    Suited to intermittent / lumpy demand where the normal approximation breaks down.
    ROP = service-level percentile of lead-time demand, SS = ROP - expected LTD.
    """
    demand = np.asarray(demand, dtype=float)
    d_mean = float(demand.mean()) if demand.size else 0.0
    d_std = float(demand.std(ddof=1)) if demand.size > 1 else 0.0
    lt_mean, lt_std = _lt_stats(lt_obs, plifz)
    lt_list = np.asarray(lt_obs, dtype=int) if np.size(lt_obs) else np.array([int(round(plifz))])
    ltd = lead_time_demand_samples(demand, lt_list)
    if ltd.size < 10:  # not enough history -> formula fallback
        return rolling_params(demand, lt_obs, service_level, plifz)
    rop = float(np.quantile(ltd, service_level, method="higher"))
    ss = max(0.0, rop - d_mean * lt_mean)
    return _finish(ss, d_mean, d_std, lt_mean, lt_std, rop=d_mean * lt_mean + ss)


# ---------------------------------------------------------------------------
# Segmentation
# ---------------------------------------------------------------------------
def abc_class(values: pd.Series, a_cut: float = 0.80, b_cut: float = 0.95) -> pd.Series:
    """ABC by cumulative share of consumption value (Pareto)."""
    order = values.sort_values(ascending=False)
    total = order.sum()
    cum_before = order.cumsum().shift(fill_value=0.0) / (total if total else 1.0)
    cls = np.where(cum_before < a_cut, "A", np.where(cum_before < b_cut, "B", "C"))
    return pd.Series(cls, index=order.index).reindex(values.index)


def xyz_class(cv: pd.Series, x_cut: float = 0.5, y_cut: float = 1.0) -> pd.Series:
    """XYZ by coefficient of variation of daily demand."""
    return pd.Series(np.where(cv <= x_cut, "X", np.where(cv <= y_cut, "Y", "Z")),
                     index=cv.index)


def adi(demand: np.ndarray) -> float:
    """Average inter-demand interval in days (inf if no demand at all)."""
    nz = np.count_nonzero(np.asarray(demand))
    return float(len(demand) / nz) if nz else float("inf")


def segment(stats: pd.DataFrame) -> pd.DataFrame:
    """Add ABC, XYZ, segment and target service level.

    `stats` needs columns: annual_value, cv, adi.
    """
    out = stats.copy()
    out["ABC"] = abc_class(out["annual_value"])
    out["XYZ"] = xyz_class(out["cv"])
    out["segment"] = out["ABC"] + out["XYZ"]
    out["service_level"] = [SERVICE_LEVEL_MATRIX[a][x] for a, x in zip(out["ABC"], out["XYZ"])]
    out["intermittent"] = out["adi"] > ADI_INTERMITTENT
    out["adaptive_method"] = np.where(out["intermittent"], "empirical", "rolling")
    return out


# ---------------------------------------------------------------------------
# Demand classification for the segmented policy
# ---------------------------------------------------------------------------
def seasonality_strength(daily: np.ndarray, bucket: int = 7, period: int = 365) -> float:
    """Strength of yearly seasonality in [0, 1] from daily history.

    Weekly totals are regressed on level + linear trend + one yearly harmonic.
    Strength = max(0, 1 - Var(residual) / Var(seasonal + residual)), the
    Hyndman/Wang measure. A trend alone does not count as seasonality.
    """
    d = np.asarray(daily, dtype=float)
    w = d.size // bucket
    if w < 26:                        # need at least half a year of weekly buckets
        return 0.0
    y = d[-w * bucket:].reshape(w, bucket).sum(axis=1)
    t = np.arange(w)
    ang = 2 * np.pi * t * bucket / period
    X = np.column_stack([np.ones(w), t, np.sin(ang), np.cos(ang)])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    seasonal = X[:, 2:] @ beta[2:]
    resid = y - X @ beta
    denom = np.var(seasonal + resid)
    return float(max(0.0, 1 - np.var(resid) / denom)) if denom > 0 else 0.0


def sbc_class(daily: np.ndarray) -> tuple[str, float, float]:
    """Syntetos-Boylan class from ADI and CV^2 of the non-zero demand sizes."""
    d = np.asarray(daily, dtype=float)
    a = adi(d)
    nz = d[d > 0]
    cv2 = float((nz.std(ddof=1) / nz.mean()) ** 2) if nz.size > 1 else 0.0
    if a <= ADI_INTERMITTENT:
        cls = "smooth" if cv2 <= CV2_LUMPY else "erratic"
    else:
        cls = "intermittent" if cv2 <= CV2_LUMPY else "lumpy"
    return cls, a, cv2


def classify_policy(history: np.ndarray) -> dict:
    """Decide from consumption history whether weekly recalculation is worth it.

    Weekly review for seasonal demand (strength >= SEASONALITY_THRESHOLD) and for
    intermittent/lumpy demand (ADI > 1.32); quarterly refresh for everything else.
    """
    strength = seasonality_strength(history)
    cls, a, cv2 = sbc_class(history)
    seasonal = strength >= SEASONALITY_THRESHOLD
    intermittent = a > ADI_INTERMITTENT
    return {"seasonality_strength": strength, "adi_12m": a, "cv2_12m": cv2, "sbc_class": cls,
            "is_seasonal": bool(seasonal), "is_intermittent": bool(intermittent),
            "weekly_review": bool(seasonal or intermittent)}
