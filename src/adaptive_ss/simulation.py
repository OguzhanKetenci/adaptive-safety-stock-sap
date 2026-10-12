"""Daily (s, Q) reorder-point simulation.

Daily sequence for every material and method:
  1. (adaptive methods, on review days) recalculate SS / ROP / Q from history before today
  2. goods receipts of purchase orders due today
  3. demand: served from stock; the rest is lost (lost-sales) or backordered
  4. reorder check: inventory position = on hand + open POs (- backorders);
     if IP <= ROP, order n*Q so that IP rises above ROP. Lead time is stochastic.

During the warm-up (first 60 days) every method runs with the same initial settings,
the ones derived from the baseline and stored in MARC. Every method sees the same
demand and the same sequence of supplier lead times (common random numbers), so the
differences in the KPIs come only from the safety stock logic.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import methods
from .data_gen import Dataset


@dataclass(frozen=True)
class SimConfig:
    window: int = 90             # days of demand history for rolling / empirical
    review_every: int = 7        # recalculation frequency in days (adaptive methods)
    ewma_alpha: float = 0.05     # smoothing factor for EWMA demand mean/variance
    lt_window: int = 180         # days of goods receipts used for lead-time statistics
    warmup: int = 60             # days excluded from KPIs; also the baseline period
    lost_sales: bool = True      # False -> backorder mode
    sl_override: float | None = None   # one service level for all materials
    sl_offset: float = 0.0       # added to every segment target (e.g. -0.02)


@dataclass
class SimResult:
    matnr: str
    method: str
    daily: pd.DataFrame
    cycles: np.ndarray = field(repr=False)   # rows: start_day, end_day, no_stockout(0/1)
    n_orders: int = 0


def _lt_obs(hist: pd.DataFrame | tuple[np.ndarray, np.ndarray], t: int, lt_window: int,
            min_obs: int = 3) -> np.ndarray:
    """Lead times of goods receipts posted before day t (most recent window).

    `hist` holds receipts sorted by gr_day (DataFrame or (gr_day, lt) arrays).
    """
    gr, lt = _as_arrays(hist)
    end = np.searchsorted(gr, t, side="left")              # receipts before day t
    start = np.searchsorted(gr, t - lt_window, side="left")
    if end - start < min_obs:
        start = max(0, end - max(min_obs, 5))
    return lt[start:end]


def _as_arrays(hist) -> tuple[np.ndarray, np.ndarray]:
    if isinstance(hist, pd.DataFrame):
        return hist["gr_day"].to_numpy(), hist["lt"].to_numpy()
    return hist


def estimate(method: str, demand_hist: np.ndarray, lt_hist, t: int,
             service_level: float, plifz: float, cfg: SimConfig) -> methods.Params:
    """Parameters a method would propose on day t using only data before day t."""
    lt = _lt_obs(lt_hist, t, cfg.lt_window)
    if method == "rolling":
        return methods.rolling_params(demand_hist[max(0, t - cfg.window):t], lt,
                                      service_level, plifz)
    if method == "ewma":
        return methods.ewma_params(demand_hist[max(0, t - 365):t], lt, service_level,
                                   plifz, alpha=cfg.ewma_alpha)
    if method == "empirical":
        win = max(cfg.window, 180)  # sparse demand needs a longer look-back
        return methods.empirical_params(demand_hist[max(0, t - win):t], lt,
                                        service_level, plifz)
    raise ValueError(f"unknown adaptive method {method!r}")


def service_level_for(row, cfg: SimConfig) -> float:
    sl = cfg.sl_override if cfg.sl_override is not None else row["service_level"] + cfg.sl_offset
    return float(np.clip(sl, 0.5, 0.999))


def baseline_params(demand: np.ndarray, lt_hist: pd.DataFrame, service_level: float,
                    plifz: float, warmup: int) -> methods.Params:
    """The 'static' SAP setting: computed once from the baseline period."""
    gr, lts = _as_arrays(lt_hist)
    lt = lts[gr < warmup]
    return methods.rolling_params(demand[:warmup], lt, service_level, plifz)


def simulate_material(demand: np.ndarray, lt_hist: pd.DataFrame, lt_draws: np.ndarray,
                      service_level: float, plifz: float, method: str,
                      cfg: SimConfig = SimConfig(), matnr: str = "") -> SimResult:
    demand = np.asarray(demand, dtype=float)
    n = demand.size
    params = baseline_params(demand, lt_hist, service_level, plifz, cfg.warmup)
    lt_arrays = _as_arrays(lt_hist)

    on_hand = float(np.ceil(params.ss + params.q))
    pipeline: list[list[float]] = []   # [arrival_day, qty, order_day]
    lt_idx = 0

    cols = {k: np.zeros(n) for k in ["on_hand", "position", "pipeline", "ss", "rop", "q",
                                     "served", "unmet", "order_qty", "receipt_qty",
                                     "d_mean_est"]}
    unmet = cols["unmet"]
    receipt_days: list[int] = []

    for t in range(n):
        if method != "static" and t >= cfg.warmup and (t - cfg.warmup) % cfg.review_every == 0:
            params = estimate(method, demand, lt_arrays, t, service_level, plifz, cfg)

        # 2. receipts
        arrived = 0.0
        if pipeline:
            keep = []
            for po in pipeline:
                if po[0] <= t:
                    arrived += po[1]
                else:
                    keep.append(po)
            pipeline = keep
        on_hand += arrived
        if arrived > 0:
            receipt_days.append(t)

        # 3. demand
        d = demand[t]
        served = min(max(on_hand, 0.0), d)
        if cfg.lost_sales:
            on_hand -= served
        else:
            on_hand -= d              # negative on hand = backorders
        unmet[t] = d - served

        # 4. reorder point check
        open_qty = sum(po[1] for po in pipeline)
        position = on_hand + open_qty
        order = 0.0
        if position <= params.rop:
            n_lots = int(np.floor((params.rop - position) / params.q)) + 1
            order = float(n_lots * params.q)
            lt = int(lt_draws[lt_idx % lt_draws.size])
            lt_idx += 1
            pipeline.append([t + lt, order, t])
            open_qty += order
            position += order

        cols["on_hand"][t] = on_hand
        cols["position"][t] = position
        cols["pipeline"][t] = open_qty
        cols["ss"][t] = params.ss
        cols["rop"][t] = params.rop
        cols["q"][t] = params.q
        cols["served"][t] = served
        cols["order_qty"][t] = order
        cols["receipt_qty"][t] = arrived
        cols["d_mean_est"][t] = params.d_mean

    daily = pd.DataFrame(cols)
    daily.insert(0, "demand", demand)
    daily.insert(0, "day", np.arange(n))

    # Cycle service level: a replenishment cycle runs from one goods receipt to the
    # next; it is "good" if no demand went unmet inside it (textbook definition).
    cyc = []
    for start, end in zip(receipt_days[:-1], receipt_days[1:]):
        if start >= cfg.warmup:
            cyc.append((start, end, 1 if unmet[start:end].sum() == 0 else 0))
    cyc_arr = np.array(cyc, dtype=float).reshape(-1, 3)
    n_orders = int((daily["order_qty"].to_numpy()[cfg.warmup:] > 0).sum())
    return SimResult(matnr=matnr, method=method, daily=daily, cycles=cyc_arr,
                     n_orders=n_orders)


def run_all(ds: Dataset, cfg: SimConfig = SimConfig(),
            method_list: list[str] | None = None) -> dict[tuple[str, str], SimResult]:
    """Simulate every material with every method."""
    method_list = method_list or methods.METHODS
    out = {}
    for _, row in ds.meta.iterrows():
        m = row["MATNR"]
        sl = service_level_for(row, cfg)
        for meth in method_list:
            out[(m, meth)] = simulate_material(ds.demand[m], ds.lt_hist[m], ds.lt_draws[m],
                                               sl, row["PLIFZ"], meth, cfg, matnr=m)
    return out
