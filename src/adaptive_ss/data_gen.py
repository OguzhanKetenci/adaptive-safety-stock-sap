"""Deterministic synthetic SAP-like data.

Tables produced (SAP names, simplified field sets):
  MARA   material master          MATNR, MAKTX, MEINS
  MARC   plant data               MATNR, WERKS, DISMM, DISPO, EISBE, MINBE, BSTFE, PLIFZ
  consumption  daily goods issues (MSEG 261/201 aggregated)  MATNR, WERKS, BUDAT, MENGE
  MVER   monthly consumption      MATNR, WERKS, GJAHR, MONAT, GSVBR
  EKKO   PO header                EBELN, BUKRS, BSART, LIFNR, BEDAT
  EKPO   PO item                  EBELN, EBELP, MATNR, WERKS, MENGE, MEINS
  EKBE   PO history (GR)          EBELN, EBELP, VGABE, BWART, BUDAT, MENGE

Actual lead time = EKBE.BUDAT (goods receipt) - EKKO.BEDAT (PO date).
Every random draw uses numpy Generators seeded with fixed integer tuples, so the
data is identical on every machine and every run (no use of Python's hash()).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from . import methods

SEED = 42
N_DAYS = 540            # simulation horizon (~18 months)
BASELINE_DAYS = 60      # history used for the initial ("static") SAP settings
SHIFT_DAY = 180         # regime shift day
PO_HISTORY_START = -150 # PO history starts before day 0 so lead times are known at go-live
START_DATE = pd.Timestamp("2025-01-06")  # a Monday -> day % 7 == 0 is Monday

PATTERNS = (["stable"] * 6 + ["growth"] * 5 + ["decline"] * 4 + ["seasonal"] * 5
            + ["intermittent"] * 5 + ["regime_shift"] * 5)

MATERIAL_NAMES = [
    ("Hex bolt M8x40 DIN933", "ST"), ("Hydraulic oil HLP46", "L"),
    ("Deep groove ball bearing 6204", "ST"), ("Steel sheet DC01 1.5mm", "KG"),
    ("O-ring 25x3 NBR70", "ST"), ("Cable tie 300x4.8 black", "ST"),
    ("Pallet EUR 1200x800", "ST"), ("Cardboard box 400x300x200", "ST"),
    ("Stretch film 23my 500mm", "ST"), ("Aluminium profile 40x40", "ST"),
    ("Proximity sensor M12 PNP", "ST"), ("Gear motor 0.37kW", "ST"),
    ("Paint RAL7035 powder", "KG"), ("Hex nut M8 DIN934", "ST"),
    ("Washer 8.4 DIN125", "ST"), ("PCB control board v3", "ST"),
    ("Thermal paste 100g", "ST"), ("Pneumatic cylinder D32", "ST"),
    ("Hose clamp 20-32mm", "ST"), ("Safety gloves size 9", "ST"),
    ("Label roll 100x50", "ST"), ("Adhesive 2K epoxy 50ml", "ST"),
    ("Spare drive belt XPZ1000", "ST"), ("Solenoid valve 24VDC", "ST"),
    ("Linear guide rail 500mm", "ST"), ("Coolant concentrate", "L"),
    ("Filter cartridge 10um", "ST"), ("Copper wire 2.5mm2", "KG"),
    ("Servo drive 1.5kW", "ST"), ("Gasket kit pump P200", "ST"),
]


def _rng(*keys: int) -> np.random.Generator:
    """Generator seeded from a fixed integer tuple (deterministic everywhere)."""
    return np.random.default_rng([SEED, *keys])


@dataclass
class Dataset:
    mara: pd.DataFrame
    marc: pd.DataFrame
    consumption: pd.DataFrame
    mver: pd.DataFrame
    ekko: pd.DataFrame
    ekpo: pd.DataFrame
    ekbe: pd.DataFrame
    meta: pd.DataFrame          # synthetic ground truth + segmentation (not an SAP table)
    demand: dict[str, np.ndarray] = field(repr=False)        # MATNR -> daily demand
    lt_hist: dict[str, pd.DataFrame] = field(repr=False)     # MATNR -> (gr_day, lt)
    lt_draws: dict[str, np.ndarray] = field(repr=False)      # MATNR -> future LTs for sim
    n_days: int = N_DAYS
    baseline_days: int = BASELINE_DAYS

    @property
    def materials(self) -> list[str]:
        return list(self.marc["MATNR"])


# ---------------------------------------------------------------------------
# Demand
# ---------------------------------------------------------------------------
def _demand_series(pattern: str, i: int, n_days: int) -> tuple[np.ndarray, dict]:
    r = _rng(i, 0)
    t = np.arange(n_days)
    base = r.uniform(5, 80)
    cv = r.uniform(0.2, 0.9)
    info: dict = {"base_true": base, "cv_true": cv}

    if pattern == "intermittent":
        p = r.uniform(0.08, 0.25)
        size = r.uniform(5, 25)
        occurs = r.random(n_days) < p
        sizes = np.maximum(1, np.round(r.lognormal(np.log(size), 0.6, n_days)))
        info.update(p_demand=p, mean_size=size, base_true=p * size, cv_true=np.nan)
        return np.where(occurs, sizes, 0).astype(float), info

    mu = np.full(n_days, base)
    sigma_mult = np.ones(n_days)
    if pattern == "growth":
        g = r.uniform(0.10, 0.25)            # +10-25 % over 18 months
        mu = base * (1 + g * t / n_days)
        info["growth_total"] = g
    elif pattern == "decline":
        d = r.uniform(0.10, 0.25)            # -10-25 % over 18 months
        mu = base * (1 - d * t / n_days)
        info["decline_total"] = d
    elif pattern == "seasonal":
        amp = r.uniform(0.3, 0.5)
        phase = r.uniform(0, 365)
        weekly = np.array([1.15, 1.10, 1.05, 1.10, 1.00, 0.40, 0.20])
        weekly = weekly / weekly.mean()
        mu = base * (1 + amp * np.sin(2 * np.pi * (t + phase) / 365)) * weekly[t % 7]
        info.update(yearly_amplitude=amp)
    elif pattern == "regime_shift":
        cv = r.uniform(0.15, 0.35)   # calm before the shift so the volatility jump is visible
        info["cv_true"] = cv
        # level step of +10-25 % (even i) or -10-25 % (odd i), volatility x1.5
        step = r.uniform(0.10, 0.25)
        factor = 1 + step if i % 2 == 0 else 1 - step
        after = t >= SHIFT_DAY
        mu = np.where(after, base * factor, base)
        sigma_mult = np.where(after, 1.5, 1.0)
        info.update(shift_mean_factor=factor, shift_cv_factor=1.5, shift_day=SHIFT_DAY)

    noise = r.normal(0.0, 1.0, n_days)
    qty = np.maximum(0, np.round(mu + noise * mu * cv * sigma_mult))
    return qty.astype(float), info


def _lt_sampler(r: np.random.Generator, mean: float, cv: float, n: int) -> np.ndarray:
    """Gamma-distributed lead times in whole days (>= 1)."""
    shape = 1.0 / cv ** 2
    return np.maximum(1, np.round(r.gamma(shape, mean / shape, n))).astype(int)


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
def generate(n_days: int = N_DAYS) -> Dataset:
    rows_mara, rows_meta = [], []
    demand, lt_hist, lt_draws = {}, {}, {}
    po_rows = []

    for i, pattern in enumerate(PATTERNS):
        matnr = str(40001001 + i)
        werks = "2000" if i % 5 in (1, 3) else "1000"
        name, meins = MATERIAL_NAMES[i]
        r = _rng(i, 1)
        price = float(np.round(r.lognormal(np.log(30), 1.1), 2))
        plifz = int(r.integers(5, 21))
        lt_mean_true = plifz * r.uniform(0.95, 1.25)    # suppliers tend to be late vs PLIFZ
        lt_cv_true = r.uniform(0.1, 0.35)

        d, info = _demand_series(pattern, i, n_days)
        demand[matnr] = d

        # PO history: regular ordering cadence starting before go-live
        r_po = _rng(i, 2)
        interval = max(7, int(round(plifz * 0.8)))
        order_days = np.arange(PO_HISTORY_START + int(r_po.integers(0, interval)), n_days, interval)
        lts = _lt_sampler(r_po, lt_mean_true, lt_cv_true, order_days.size)
        avg_d = max(1.0, float(d[:BASELINE_DAYS].mean()))
        for od, lt in zip(order_days, lts):
            po_rows.append((matnr, werks, meins, int(od), int(od + lt),
                            float(np.ceil(avg_d * interval)), f"V{1000 + i % 7}"))
        # Independent future lead-time draws used by the simulation (same for every method)
        lt_draws[matnr] = _lt_sampler(_rng(i, 3), lt_mean_true, lt_cv_true, 2000)

        rows_mara.append((matnr, name, meins))
        rows_meta.append(dict(MATNR=matnr, WERKS=werks, pattern=pattern, price=price,
                              PLIFZ=plifz, lt_mean_true=lt_mean_true, lt_cv_true=lt_cv_true,
                              **{k: v for k, v in info.items()}))

    mara = pd.DataFrame(rows_mara, columns=["MATNR", "MAKTX", "MEINS"])
    meta = pd.DataFrame(rows_meta)

    # --- purchasing tables ---------------------------------------------------
    po = pd.DataFrame(po_rows, columns=["MATNR", "WERKS", "MEINS", "order_day", "gr_day",
                                        "MENGE", "LIFNR"])
    po = po.sort_values(["order_day", "MATNR"]).reset_index(drop=True)
    po["EBELN"] = [str(4500000001 + k) for k in range(len(po))]
    po["EBELP"] = 10
    po["BEDAT"] = START_DATE + pd.to_timedelta(po["order_day"], unit="D")
    ekko = po[["EBELN", "LIFNR", "BEDAT"]].assign(BUKRS="1000", BSART="NB")[
        ["EBELN", "BUKRS", "BSART", "LIFNR", "BEDAT"]]
    ekpo = po[["EBELN", "EBELP", "MATNR", "WERKS", "MENGE", "MEINS"]].copy()
    received = po[po["gr_day"] < n_days]
    ekbe = received[["EBELN", "EBELP", "MENGE"]].assign(
        VGABE="1", BWART="101",
        BUDAT=START_DATE + pd.to_timedelta(received["gr_day"], unit="D"))[
        ["EBELN", "EBELP", "VGABE", "BWART", "BUDAT", "MENGE"]]
    for matnr, g in received.groupby("MATNR"):
        lt_hist[matnr] = pd.DataFrame({"gr_day": g["gr_day"].to_numpy(),
                                       "lt": (g["gr_day"] - g["order_day"]).to_numpy()}
                                      ).sort_values("gr_day").reset_index(drop=True)

    # --- consumption tables --------------------------------------------------
    dates = START_DATE + pd.to_timedelta(np.arange(n_days), unit="D")
    cons = pd.concat([pd.DataFrame({"MATNR": m, "WERKS": w, "day": np.arange(n_days),
                                    "BUDAT": dates, "MENGE": demand[m]})
                      for m, w in zip(meta["MATNR"], meta["WERKS"])], ignore_index=True)
    mver = (cons.assign(GJAHR=cons["BUDAT"].dt.year, MONAT=cons["BUDAT"].dt.month)
            .groupby(["MATNR", "WERKS", "GJAHR", "MONAT"], as_index=False)["MENGE"].sum()
            .rename(columns={"MENGE": "GSVBR"}))

    # --- segmentation + current ("static") SAP settings from the baseline ----
    seg_rows, marc_rows = [], []
    for row in meta.itertuples():
        base_d = demand[row.MATNR][:BASELINE_DAYS]
        mean = base_d.mean()
        seg_rows.append(dict(MATNR=row.MATNR,
                             annual_value=mean * 365 * row.price,
                             cv=(base_d.std(ddof=1) / mean) if mean > 0 else np.inf,
                             adi=methods.adi(base_d)))
    seg = methods.segment(pd.DataFrame(seg_rows).set_index("MATNR")).reset_index()
    meta = meta.merge(seg, on="MATNR")

    for row in meta.itertuples():
        h = lt_hist[row.MATNR]
        lt_obs = h.loc[h["gr_day"] < BASELINE_DAYS, "lt"].to_numpy()
        p = methods.rolling_params(demand[row.MATNR][:BASELINE_DAYS], lt_obs,
                                   row.service_level, row.PLIFZ)
        marc_rows.append(dict(MATNR=row.MATNR, WERKS=row.WERKS, DISMM="VB",
                              DISPO="P01" if row.WERKS == "1000" else "P02",
                              EISBE=int(np.ceil(p.ss)), MINBE=int(np.ceil(p.rop)),
                              BSTFE=p.q, PLIFZ=row.PLIFZ))
    marc = pd.DataFrame(marc_rows)

    return Dataset(mara=mara, marc=marc, consumption=cons.drop(columns="day"), mver=mver,
                   ekko=ekko, ekpo=ekpo, ekbe=ekbe, meta=meta, demand=demand,
                   lt_hist=lt_hist, lt_draws=lt_draws, n_days=n_days)


def save_sample(ds: Dataset, folder: str | Path) -> None:
    """Write the SAP-like tables as CSV (semicolon separated, like SE16N downloads)."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    tables = {"MARA": ds.mara, "MARC": ds.marc, "MVER": ds.mver, "EKKO": ds.ekko,
              "EKPO": ds.ekpo, "EKBE": ds.ekbe, "consumption_daily": ds.consumption,
              "material_meta_synthetic": ds.meta}
    for name, df in tables.items():
        df.to_csv(folder / f"{name}.csv", sep=";", index=False, date_format="%Y-%m-%d",
                  float_format="%.4f")


if __name__ == "__main__":
    from . import sap_export   # local import: sap_export depends on this module

    out = Path(__file__).resolve().parents[2] / "data" / "sample"
    data = generate()
    save_sample(data, out)
    proposals = sap_export.build_proposals(data)
    (out / "eisbe_proposals.csv").write_text(sap_export.to_csv(proposals), encoding="utf-8")
    (out / "mm17_eisbe_upload.csv").write_text(sap_export.mm17_csv(proposals), encoding="utf-8")
    print(f"Sample data and export files written to {out}")
