"""Cost model and KPIs (computed after the warm-up period only)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .simulation import SimResult


@dataclass(frozen=True)
class CostParams:
    holding_rate: float = 0.20        # share of unit value per year (capital, storage, risk)
    margin_rate: float = 0.25         # unit margin as share of unit value
    stockout_margin_multiple: float = 1.5  # stockout cost per unit = multiple x unit margin
    ordering_cost: float = 50.0       # EUR per purchase order

    @property
    def stockout_factor(self) -> float:
        """Stockout cost per unit as a share of unit value (default 1.5 x 25 % = 37.5 %)."""
        return self.margin_rate * self.stockout_margin_multiple


def material_kpis(res: SimResult, price: float, costs: CostParams, warmup: int) -> dict:
    d = res.daily.iloc[warmup:]
    days = len(d)
    demand = d["demand"].sum()
    served = d["served"].sum()
    unmet = d["unmet"].sum()
    avg_inv = d["on_hand"].clip(lower=0).mean()
    holding = avg_inv * price * costs.holding_rate * days / 365
    stockout = unmet * price * costs.stockout_factor
    ordering = res.n_orders * costs.ordering_cost
    csl = res.cycles[:, 2].mean() if res.cycles.size else np.nan
    return {
        "MATNR": res.matnr,
        "method": res.method,
        "demand": demand,
        "fill_rate": served / demand if demand > 0 else 1.0,
        "cycle_service_level": csl,
        "stockout_days": int((d["unmet"] > 0).sum()),
        "unmet_units": unmet,
        "avg_inventory": avg_inv,
        "inventory_value": avg_inv * price,
        "orders": res.n_orders,
        "holding_cost": holding,
        "stockout_cost": stockout,
        "ordering_cost": ordering,
        "total_cost": holding + stockout + ordering,
        "final_ss": res.daily["ss"].iloc[-1],
    }


def kpi_table(results: dict[tuple[str, str], SimResult], meta: pd.DataFrame,
              costs: CostParams = CostParams(), warmup: int = 60) -> pd.DataFrame:
    """KPIs for every material x method plus the 'adaptive' recommended mix.

    'adaptive' = rolling window for regular demand, empirical percentile for
    intermittent demand (choice made from the baseline period, no hindsight).
    'segmented' = the adaptive method only for materials classified as seasonal or
    intermittent from the 12-month history before go-live, quarterly refresh otherwise.
    """
    price = meta.set_index("MATNR")["price"]
    rows = [material_kpis(r, price[m], costs, warmup) for (m, _), r in results.items()]
    kpis = pd.DataFrame(rows)
    composites = [kpis]
    for name, col in [("adaptive", "adaptive_method"), ("segmented", "segmented_method")]:
        if col not in meta:
            continue
        choice = meta.set_index("MATNR")[col]
        mix = kpis[kpis["method"] == kpis["MATNR"].map(choice)].copy()
        mix["method"] = name
        composites.append(mix)
    kpis = pd.concat(composites, ignore_index=True)
    return kpis.merge(meta[["MATNR", "WERKS", "pattern", "segment", "price"]], on="MATNR")


def summary_by_method(kpis: pd.DataFrame) -> pd.DataFrame:
    """Portfolio totals per method (fill rate demand-weighted)."""
    g = kpis.assign(served=kpis["fill_rate"] * kpis["demand"]).groupby("method")
    out = pd.DataFrame({
        "total_cost": g["total_cost"].sum(),
        "holding_cost": g["holding_cost"].sum(),
        "stockout_cost": g["stockout_cost"].sum(),
        "ordering_cost": g["ordering_cost"].sum(),
        "inventory_value": g["inventory_value"].sum(),
        "fill_rate": g["served"].sum() / g["demand"].sum(),
        "cycle_service_level": g["cycle_service_level"].mean(),
        "stockout_days": g["stockout_days"].sum(),
        "orders": g["orders"].sum(),
    })
    return out


BASELINE = "quarterly"   # headline comparison: planner refreshes EISBE every 90 days


def headline(kpis: pd.DataFrame, baseline: str = BASELINE) -> dict:
    """Adaptive vs. the baseline; the never-updated static setting is kept as a reference."""
    s = summary_by_method(kpis)
    base, adaptive = s.loc[baseline, "total_cost"], s.loc["adaptive", "total_cost"]
    return {
        "baseline_cost": base,
        "adaptive_cost": adaptive,
        "savings": base - adaptive,
        "savings_pct": (base - adaptive) / base if base else 0.0,
        "baseline_fill": s.loc[baseline, "fill_rate"],
        "adaptive_fill": s.loc["adaptive", "fill_rate"],
        "baseline_inv": s.loc[baseline, "inventory_value"],
        "adaptive_inv": s.loc["adaptive", "inventory_value"],
        "static_cost": s.loc["static", "total_cost"],
        "static_fill": s.loc["static", "fill_rate"],
    }


def impact_by_material(kpis: pd.DataFrame, baseline: str = BASELINE) -> pd.DataFrame:
    """Cost difference baseline - adaptive per material (positive = adaptive saves)."""
    p = kpis.pivot_table(index="MATNR", columns="method", values="total_cost")
    info = kpis.drop_duplicates("MATNR").set_index("MATNR")[["WERKS", "pattern", "segment"]]
    out = info.join(p[[baseline, "adaptive"]].rename(columns={baseline: "baseline"}))
    out["savings"] = out["baseline"] - out["adaptive"]
    return out.sort_values("savings", ascending=False)
