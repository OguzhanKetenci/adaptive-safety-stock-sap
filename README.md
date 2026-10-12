# Adaptive Safety Stock for SAP MM

**A planner-controlled way to keep `MARC-EISBE` up to date, with the numbers to show why it matters.**

![Overview page](docs/img/overview.jpg)

---

## The problem

In most SAP MM systems the safety stock (`MARC-EISBE`) and, for reorder-point items, the reorder
point (`MARC-MINBE`) are set when the material is created. After that, almost nobody touches them.
Demand does not stand still, though. A product line grows, a customer leaves, a supplier gets
less reliable, or the market simply becomes more volatile. A safety stock that was right a year ago
quietly turns into one of two problems:

* **Too low** for materials whose demand grew or became more volatile. The result is stockouts,
  expediting, and production stops.
* **Too high** for materials whose demand declined. The result is capital tied up in stock nobody needs.

Planners rarely have time to review hundreds of materials by hand, so the static value survives.

## The approach

This project simulates what happens when a scheduled job **recalculates the safety stock every
week** from data that SAP already holds:

1. **Demand** is read from consumption history (goods issues in MSEG, monthly totals in MVER).
2. **Real supplier lead times** come from purchasing history: PO date (`EKKO-BEDAT`) to goods receipt
   (`EKBE-BUDAT`, movement type 101). The planned delivery time `PLIFZ` is not used for this,
   because it is often out of date.
3. **Segmentation** uses ABC (consumption value) × XYZ (demand variability). Each segment gets a target
   service level, from 98% for AX items down to 90% for CZ items.
4. The job computes a **new safety stock** with the method that fits the demand type:
   * regular demand: `SS = z · √(LT_mean · σ_d² + d_mean² · σ_LT²)` on a rolling 90-day window
   * intermittent / lumpy demand: an empirical percentile of observed lead-time demand
   * EWMA is also simulated as an alternative.
5. **Planner control** decides what gets posted. Changes under 5% are ignored, so the master data
   does not flicker. Changes up to ±30% are posted automatically through an MM17/LSMW file. Anything
   larger goes to the responsible MRP controller for approval, together with a plain-language
   reason, for example *"demand mean +93%, demand variability +86% vs. current setting"*.

To test this, 30 materials are simulated over 540 days (18 months) with a daily reorder-point
(s, Q) policy. The simulation includes stochastic lead times and either lost sales or backorders.
Every method sees exactly the same demand and the same supplier delays, so any difference in the
results comes from the safety stock logic alone.

## Results

**Over the 16-month evaluation period, the adaptive approach cuts total cost by 59%
(from about €827k to €339k).** It raises the fill rate from 90.7% to 98.3% and needs only about 5%
more average inventory value. Total cost here means holding, stockout and ordering cost combined.

The headline compares the static setting with a method mix that was **fixed before the
simulation**: rolling window for regular items, empirical percentile for intermittent items.
EWMA did slightly better in this data set, but choosing it afterwards would be hindsight, so it is
reported and not used for the headline.

The benefit is not spread evenly, and the details are the useful part:

* **Growth and regime-shift materials account for almost all of the savings.** Under the static
  setting these items run out again and again, because their safety stock was sized for the demand of
  the first two months. The adaptive job sees the trend within a few weeks and raises EISBE and MINBE.
* **Declining materials** move the other way. Adaptive cuts their average inventory by about a third,
  at nearly the same service level.
* **Seasonal materials** benefit too, because the safety stock follows the yearly cycle. It does so
  with a lag, so a forecast-based method would do better here.
* **Stable and intermittent materials see no benefit, and sometimes a small loss.** With nothing to
  adapt to, recalculation mostly adds estimation noise. Adaptive is cheaper for 17 of the 30
  materials, not all of them. This is exactly why the export has a dead band and an approval step:
  the goal is to catch real changes in demand, not to chase noise.

The result does not hinge on one cost assumption. The headline values a lost unit at 50% of its
price. Even if a stockout cost only 5% of the unit value, adaptive would still be 17% cheaper. In
backorder mode the saving rises to about 72%. Changing the window length (60–180 days) or the
review frequency (daily to monthly) moves the saving only between 53% and 59%.

| Drill-down: inventory per method | Step-by-step replay |
|---|---|
| ![Drill-down](docs/img/drilldown.jpg) | ![Replay](docs/img/replay.jpg) |

> 🎬 *GIF placeholder: a short recording of the replay mode (Play at 1 day/s through the regime shift
> on day 180) would go here: `docs/img/replay.gif`.*

## The app

| Page | What it shows |
|---|---|
| **Overview** | Headline savings, cost by method, the ABC × XYZ segment matrix with savings per cell, results by demand pattern, top materials by impact (including where adaptive does worse) |
| **Material drill-down** | Demand, on-hand inventory per method, safety stock over time, and KPIs for one material |
| **Step-by-step replay** | Day-by-day playback with ▶ Play / ⏸ Pause / ⏭ Next day / ⏮ Reset and a speed control (default slow: 1 day per second). Shows receipts, issues, POs placed and EISBE recalculations as they happen |
| **SAP export** | Proposed EISBE/MINBE changes with reason and status. Planners can approve or reject the large changes in the table, then download the proposal list and the MM17 upload file |
| **About & SAP fields** | Tables and fields used, plus the current MARC settings |

The sidebar holds all the parameters: service-level overrides per segment (an editable 3×3
matrix), window length, review frequency, EWMA α, lost sales vs. backorder, holding cost %,
stockout cost and ordering cost.

### Run it

You need Python 3.11+.

```bash
pip install -r requirements.txt
```

```bash
streamlit run app/streamlit_app.py
```

```bash
python -m pytest
```

The synthetic SAP tables in `data/sample/` can be regenerated with
`python -m adaptive_ss.data_gen` (run from `src/`, or with `PYTHONPATH=src`). The data is fully
deterministic.

## SAP fields used

| Table | Fields | Role |
|---|---|---|
| **MARA** | MATNR, MAKTX, MEINS | Material master |
| **MARC** | MATNR, WERKS, **EISBE**, **MINBE**, BSTFE, PLIFZ, DISMM, DISPO | Current planning settings, which are also the update target. DISPO routes approvals to the right MRP controller |
| **MSEG / MVER** | goods issues (daily) / GSVBR (monthly) | Demand mean and variability |
| **EKKO / EKPO / EKBE** | BEDAT / MATNR, WERKS, MENGE / BUDAT, BWART 101 | Actual lead time and its variability |

The export file is semicolon separated: `MATNR;WERKS;DISPO;EISBE_OLD;EISBE_NEW;CHANGE_PCT;MINBE_OLD;MINBE_NEW;METHOD;REASON;STATUS`.
The MM17 upload file contains only the auto-approved rows: `MATNR;WERKS;EISBE;MINBE`.
For reorder-point planning with DISMM = VB, MINBE has to be updated together with EISBE, otherwise
MRP keeps triggering at the old level.

How this would run in a real SAP system (scheduled job, MD04/MD07 monitoring, the approval workflow)
is described in [docs/sap_integration.md](docs/sap_integration.md).

## Repository layout

```
src/adaptive_ss/
  data_gen.py     deterministic SAP-like tables (MARA, MARC, MVER, EKKO, EKPO, EKBE)
  methods.py      safety stock formulas, EWMA, empirical method, ABC/XYZ segmentation
  simulation.py   daily (s,Q) simulation, lost sales / backorder
  costs.py        cost model and KPIs (fill rate, cycle service level, stockout days, ...)
  sap_export.py   proposal list + MM17/LSMW upload file with approval logic
app/streamlit_app.py
data/sample/      generated CSVs (semicolon separated)
docs/             SAP integration briefing, screenshots
tests/            pytest: formulas, inventory balance, segmentation, export format, app smoke test
DECISIONS.md      every modelling choice and why
```

## Limitations

* **Synthetic data.** The demand patterns are deliberately clear-cut. Real data has more noise,
  more outliers, and master data errors.
* **Consumption = demand.** In a real system, consumption under-reports demand during stockouts
  (censored demand). A real implementation should add back unfulfilled sales orders or
  production shortages.
* **Single echelon.** One plant, one supplier per material. No distribution network and no
  stock transfers between plants.
* **No capacity or order constraints.** No minimum order quantities, rounding values, supplier
  capacity or storage limits. Lot size is simply expected lead-time demand.
* **No forecast.** All methods look backwards. Seasonal items would benefit from forecast-based
  safety stock (SAP forecast models or IBP).
* **Segmentation is fixed** from the baseline period and is not re-run over time.

## Author's note

I built this as a supply chain specialist rather than a software developer. The point is to show
how I would frame the problem, design the logic, and brief an SAP team on implementing it. Every
modelling decision is documented in [DECISIONS.md](DECISIONS.md).
