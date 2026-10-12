# Final report

Repository: https://github.com/OguzhanKetenci/adaptive-safety-stock-sap (branch `main`, all commits pushed).

## What was built

| Requirement | Status | Where |
|---|---|---|
| 1. Synthetic SAP-like data: MARA, MARC, MVER + daily consumption, EKKO/EKPO/EKBE. 30 materials, 2 plants, 6 demand patterns including a regime shift on day 180. Deterministic. | ✅ Done | `src/adaptive_ss/data_gen.py`, `data/sample/` |
| 2. ABC × XYZ segmentation → target service level; 3×3 matrix in the app | ✅ Done (matrix is editable in the sidebar) | `methods.py`, Overview page |
| 3. Static, rolling window, EWMA, empirical percentile (+ quarterly-refresh baseline) | ✅ Done | `methods.py`, `simulation.py` |
| 4. Daily (s,Q) simulation, stochastic lead times, inventory position, lost sales / backorder, 540 days, 60-day warm-up | ✅ Done | `simulation.py` |
| 5. Cost model and KPIs (fill rate, cycle service level, stockout days, average inventory, inventory value, total cost) | ✅ Done | `costs.py` |
| 6. SAP export: semicolon CSV, ±30% → planner approval | ✅ Done, plus a 5% dead band and a separate MM17 upload file | `sap_export.py`, SAP export page |
| 7. Streamlit app: overview, drill-down, replay (Play/Pause/Next day, speed, default 1 day/s), parameter sidebar, export with download | ✅ Done | `app/streamlit_app.py` |
| 8. SAP integration briefing | ✅ Done | `docs/sap_integration.md` |
| 9. README: problem → approach → results | ✅ Done (real screenshots; GIF is a placeholder) | `README.md` |
| 10. Tests | ✅ **57 passed**, including a headless Streamlit AppTest | `tests/` |

## Headline result (revision 2: honest baseline)

The headline now compares the weekly adaptive job with a **planner who refreshes EISBE every
quarter** using the same formula. The scenario uses mild demand changes (±10–25%) and a stockout
cost of 1.5 × a 25% margin, which is 37.5% of the unit value. The evaluation period is days 60–539.
Nothing was tuned towards a target number.

* **Quarterly refresh: about €292k total cost. Adaptive: about €264k. That is 9.4% lower (€27k).**
* **Fill rate rises from 98.1% to 98.6%.** Average inventory value is 1.1% lower.
* **Seasonal materials explain about 96% of the saving.** A quarterly value is always sized for the
  season that just ended, while the weekly job follows the season up and down. The largest single
  gain is the PCB control board (AY, about €14.6k): same stock, far fewer stockouts. Without the
  seasonal items, the saving is about 0.5%.
* **Intermittent items improve by about 11%**, partly through the weekly cycle and partly through
  the empirical percentile method. Growth, decline and regime-shift items are break-even.
* **Stable items get about 2.5% worse**, because weekly recalculation adds noise. The deep groove
  ball bearing (AY) loses about €5k. Adaptive is cheaper for 20 of the 30 materials.
* **Sensitivity:** 7.1% saving at 1× margin and 11.1% at 2× margin. 2–9% across different window
  lengths and review frequencies.
* **Reference only:** a never-updated setting would cost about €320k (96.9% fill rate). The first
  version used this as the headline baseline and reported 59%, which overstated the benefit. See
  DECISIONS.md, "Revision 2".

The result is slightly above the 2–8% you might expect. The reason is the 5 seasonal materials in
the portfolio. A portfolio with fewer seasonal items should expect close to break-even, with the
main benefit being planner time.

## What is unfinished

* **The README GIF is a placeholder.** No screen-recording tool was available, so static
  screenshots are included instead.
* EOQ-based lot sizing, MOQ and rounding values are not modelled. Q is expected lead-time demand,
  as specified.
* Segmentation is not re-run during the simulation.

## Known issues

* `CHANGE_PCT` uses a decimal point. If the file is opened in Excel with German locale settings it
  may be read as text. Quantities are integers, so the MM17 upload file itself is not affected.
* `data/sample/MARC.csv` holds the go-live values. The export's EISBE_OLD column is the value from
  the last quarterly review (day 510), so the two do not match by design.
* The seasonal amplitude (±30–50%) was not reduced in revision 2. It drives most of the saving. A
  sensitivity run with milder seasonality would be a useful addition.
* Replay speed depends on browser rendering. At 30 days/s the charts may skip days, though the
  timing itself stays correct.
* The git author on the commits is the machine's global git identity (`mathketenci-dotcom`). If
  the GitHub profile should show `OguzhanKetenci`, set `git config user.name/user.email` for
  future commits.
* Pytest shows two harmless protobuf deprecation warnings that come from inside Streamlit.

## Three next steps

1. **Run it on real data.** Read MSEG/MATDOC goods issues and EKKO/EKBE receipts for one plant in
   shadow mode (proposals only). Compare the proposals with planner judgement, and add back
   censored demand during stockouts.
2. **Add forecast-aware safety stock for seasonal items.** Seasonal items are where the value is.
   Computing σ from forecast error and anticipating the season, instead of following it, should
   beat both the weekly and the quarterly approach.
3. **Optimise the service-level matrix.** Instead of fixed targets, choose per-segment service
   levels that minimise total cost under a budget for inventory value, and re-run the ABC/XYZ
   segmentation quarterly.

## How to run

```bash
pip install -r requirements.txt
```

```bash
streamlit run app/streamlit_app.py
```

```bash
python -m pytest
```
