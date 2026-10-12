# Final report

Repository: https://github.com/OguzhanKetenci/adaptive-safety-stock-sap (branch `main`, all commits pushed).

## What was built

| Requirement | Status | Where |
|---|---|---|
| 1. Synthetic SAP-like data: MARA, MARC, MVER + daily consumption, EKKO/EKPO/EKBE. 30 materials, 2 plants, 6 demand patterns including a regime shift on day 180. Deterministic. | ✅ Done | `src/adaptive_ss/data_gen.py`, `data/sample/` |
| 2. ABC × XYZ segmentation → target service level; 3×3 matrix in the app | ✅ Done (matrix is editable in the sidebar) | `methods.py`, Overview page |
| 3. Static, rolling window, EWMA, empirical percentile | ✅ Done | `methods.py` |
| 4. Daily (s,Q) simulation, stochastic lead times, inventory position, lost sales / backorder, 540 days, 60-day warm-up | ✅ Done | `simulation.py` |
| 5. Cost model and KPIs (fill rate, cycle service level, stockout days, average inventory, inventory value, total cost) | ✅ Done | `costs.py` |
| 6. SAP export: semicolon CSV, ±30% → planner approval | ✅ Done, plus a 5% dead band and a separate MM17 upload file | `sap_export.py`, SAP export page |
| 7. Streamlit app: overview, drill-down, replay (Play/Pause/Next day, speed, default 1 day/s), parameter sidebar, export with download | ✅ Done | `app/streamlit_app.py` |
| 8. SAP integration briefing | ✅ Done | `docs/sap_integration.md` |
| 9. README: problem → approach → results | ✅ Done (real screenshots; GIF is a placeholder) | `README.md` |
| 10. Tests | ✅ **53 passed**, including a headless Streamlit AppTest | `tests/` |

## Headline result

With the default settings (90-day window, weekly review, lost sales, holding 20%/yr, stockout
cost 50% of unit value, €50 per PO), the evaluation period is days 60–539:

* **Static (SAP as-is): about €827k total cost. Adaptive: about €339k. That is €488k or 59% less.**
* Fill rate rises from **90.7% to 98.3%**. Average inventory value rises about **5%**, from €530k to €559k.
* The savings come from growth, regime-shift and seasonal materials, where static settings cause
  repeated stockouts. Declining items lose about a third of their inventory.
* Stable and intermittent items do slightly *worse* with adaptive, because recalculation adds
  noise. Adaptive is cheaper for 17 of the 30 materials. This is reported openly and is the
  reason for the dead band and the approval step.
* The result holds up under other assumptions: 17% saving even if a stockout costs only 5% of the
  unit value, 72% in backorder mode, and 53–59% across window and review-frequency settings.

## What is unfinished

* **The README GIF is a placeholder.** No screen-recording tool was available, so static
  screenshots are included instead.
* EOQ-based lot sizing, MOQ and rounding values are not modelled. Q is expected lead-time demand,
  as specified.
* Segmentation is not re-run during the simulation.

## Known issues

* `CHANGE_PCT` uses a decimal point. If the file is opened in Excel with German locale settings it
  may be read as text. Quantities are integers, so the MM17 upload file itself is not affected.
* The first export compares 16-month-old static values with today's estimate, so 24 of 30 items
  need approval. That is realistic for a first run but not for steady weekly operation. The app
  says this on the export page.
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
2. **Add forecast-aware safety stock for seasonal items.** Compute σ from forecast error
   instead of from raw demand variability. This removes the lag the rolling window shows on
   seasonal materials.
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
